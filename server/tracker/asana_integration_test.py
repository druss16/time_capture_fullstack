"""
Asana integration: client, sync, and the attribution tier.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.asana_integration_test --noinput < /dev/null

Asana is faked: FakeApi answers `paginated(path, **params)` from a dict, and
FakeHttp answers the client's raw requests. Nothing leaves the machine.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.integrations.asana import attribution
from tracker.integrations.asana.client import AsanaClient, AsanaNotAvailable
from tracker.integrations.asana.sync import _sync_projects, _sync_staff, sync_activity
from tracker.models import Block, Client, Integration, Organization, OrganizationMembership, Project
from tracker.models_asana import AsanaActivity, AsanaProjectLink
from tracker.models_task_type_sets import ExternalStaffMapping
from tracker.services.matter_attribution import attribute_matters_for_org

User = get_user_model()
ASANA = dict(ASANA_CLIENT_ID='cid', ASANA_CLIENT_SECRET='secret',
             ASANA_REDIRECT_URI='https://api.test/api/integrations/asana/callback/',
             ASANA_SCOPES='projects:read tasks:read stories:read users:read workspaces:read')


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.text = str(body)

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, responses):
        self.responses, self.calls, self.posts = list(responses), [], []

    def request(self, method, url, params=None, **kw):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)

    def post(self, url, data=None, **kw):
        self.posts.append(data)
        return FakeResp(200, {'access_token': 'new', 'expires_in': 3600})


class FakeApi:
    def __init__(self, data):
        self.data, self.calls = data, []

    def paginated(self, path, **params):
        self.calls.append((path, params))
        value = self.data.get(path, [])
        if isinstance(value, Exception):
            raise value
        return iter(value(params) if callable(value) else value)


@override_settings(**ASANA)
class ClientTests(TestCase):
    def setUp(self):
        org = Organization.objects.create(name='MTC', slug='mtc-asana-client')
        self.integ = Integration.objects.create(
            organization=org, provider='asana', is_connected=True, access_token='tok',
            refresh_token='ref', token_expires_at=timezone.now() + timedelta(hours=1))

    def test_pages_by_offset(self):
        http = FakeHttp([FakeResp(200, {'data': [{'gid': '1'}], 'next_page': {'offset': 'abc'}}),
                         FakeResp(200, {'data': [{'gid': '2'}], 'next_page': None})])
        rows = list(AsanaClient(self.integ, session=http, sleep=lambda s: None)
                    .paginated('projects', workspace='9'))
        self.assertEqual([r['gid'] for r in rows], ['1', '2'])
        self.assertEqual(http.calls[1][1]['offset'], 'abc')

    def test_waits_out_429_then_refreshes_on_401(self):
        waits = []
        http = FakeHttp([FakeResp(429, headers={'Retry-After': '7'}),
                         FakeResp(401),
                         FakeResp(200, {'data': []})])
        AsanaClient(self.integ, session=http, sleep=waits.append).get('workspaces')
        self.assertEqual(waits, [7])
        self.assertEqual(http.posts[0]['grant_type'], 'refresh_token')
        self.integ.refresh_from_db()
        self.assertEqual(self.integ.access_token, 'new')

    def test_forbidden_is_not_available(self):
        http = FakeHttp([FakeResp(403)])
        with self.assertRaises(AsanaNotAvailable):
            AsanaClient(self.integ, session=http, sleep=lambda s: None).get('projects/1')


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-asana', industry_type='marketing')
        self.al = User.objects.create_user('al', email='alannah@morethancars.com', password='x',
                                           first_name='Alannah', last_name='Gallagher')
        OrganizationMembership.objects.create(user=self.al, organization=self.org, role='owner')
        self.tom = Client.objects.create(org=self.org, name='Tom Gill Buick GMC')
        self.ford = Client.objects.create(org=self.org, name='Ford Dealers')
        self.reskin = Project.objects.create(org=self.org, client=self.tom, name='TGBGMC Website Reskin')
        self.donut = Project.objects.create(org=self.org, client=self.tom, name='TGBGMC Monthly Donut Videos')
        self.social_t = Project.objects.create(org=self.org, client=self.tom, name='Social')
        self.social_f = Project.objects.create(org=self.org, client=self.ford, name='Social')
        self.integ = Integration.objects.create(organization=self.org, provider='asana',
                                                is_connected=True, tenant_id='ws1')


class SyncTests(Base):
    def test_projects_link_by_name_never_create(self):
        before = Project.objects.count()
        api = FakeApi({'projects': [
            {'gid': '111111', 'name': 'TGBGMC Website Reskin', 'archived': False},
            {'gid': '222222', 'name': 'tgbgmc  monthly donut-videos', 'archived': False},
            {'gid': '333333', 'name': 'Social', 'archived': False},          # two clients have it
            {'gid': '444444', 'name': 'Something Asana-only', 'archived': True},
        ]})
        stats = {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0}
        _sync_projects(self.integ, api, 'ws1', stats)
        links = dict(AsanaProjectLink.objects.values_list('asana_gid', 'project_id'))
        self.assertEqual(links['111111'], self.reskin.id)
        self.assertEqual(links['222222'], self.donut.id)
        self.assertIsNone(links['333333'])          # "Social" is two clients' project
        self.assertIsNone(links['444444'])
        self.assertEqual(Project.objects.count(), before)

    def test_hand_made_link_survives_sync(self):
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='333333',
                                        project=self.social_f, link_source='manual')
        _sync_projects(self.integ, FakeApi({'projects': [{'gid': '333333', 'name': 'Social'}]}),
                       'ws1', {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0})
        self.assertEqual(AsanaProjectLink.objects.get(asana_gid='333333').project_id, self.social_f.id)

    def test_people_by_email_then_unique_name(self):
        bo = User.objects.create_user('bo', email='bo@mtc.test', password='x',
                                      first_name='Bo', last_name='Lee')
        OrganizationMembership.objects.create(user=bo, organization=self.org, role='member')
        stats = _sync_staff(self.integ, FakeApi({'users': [
            {'gid': 'u1', 'name': 'Alannah G', 'email': 'Alannah@MoreThanCars.com'},
            {'gid': 'u2', 'name': 'Bo Lee', 'email': 'bo.personal@gmail.com'},
            {'gid': 'u3', 'name': 'Stranger', 'email': 'x@else.com'},
        ]}), 'ws1')
        self.assertEqual(stats, {'matched': 2, 'unmatched': 1})
        self.assertEqual(dict(ExternalStaffMapping.objects.filter(integration=self.integ)
                              .values_list('external_id', 'user_id')),
                         {'u1': self.al.id, 'u2': bo.id})

    def test_activity_recorded_for_linked_people_on_linked_projects(self):
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='111111',
                                        project=self.reskin, link_source='name')
        ExternalStaffMapping.objects.create(integration=self.integ, external_id='u1', user=self.al)
        now = timezone.now()
        api = FakeApi({
            'tasks': [{'gid': 't1', 'name': 'Homepage wireframe'}],
            'tasks/t1/stories': [
                {'gid': 's1', 'created_at': (now - timedelta(minutes=10)).isoformat(),
                 'created_by': {'gid': 'u1'}, 'resource_subtype': 'comment_added'},
                {'gid': 's2', 'created_at': (now - timedelta(minutes=9)).isoformat(),
                 'created_by': {'gid': 'someone-else'}, 'resource_subtype': 'comment_added'},
                {'gid': 's3', 'created_at': (now - timedelta(days=9)).isoformat(),
                 'created_by': {'gid': 'u1'}, 'resource_subtype': 'marked_complete'},
            ],
        })
        stats = sync_activity(self.integ, api=api)
        self.assertEqual(stats['recorded'], 1)
        a = AsanaActivity.objects.get()
        self.assertEqual((a.user_id, a.project_id, a.task_name, a.kind),
                         (self.al.id, self.reskin.id, 'Homepage wireframe', 'comment_added'))
        # Twice is once: stories are unique per integration.
        sync_activity(self.integ, api=api)
        self.assertEqual(AsanaActivity.objects.count(), 1)
        self.assertIsNotNone(AsanaProjectLink.objects.get(asana_gid='111111').activity_cursor)


class UrlTests(SimpleTestCase):
    def test_both_address_styles(self):
        self.assertEqual(attribution.project_gid_in_url(
            'https://app.asana.com/0/1205551234567/1206667654321/f'), '1205551234567')
        self.assertEqual(attribution.project_gid_in_url(
            'https://app.asana.com/1/1199990000000/project/1205551234567/task/1206667654321'),
            '1205551234567')
        self.assertEqual(attribution.project_gid_in_url('https://app.asana.com/0/0/1206667654321/f'), '')
        self.assertEqual(attribution.project_gid_in_url('https://app.asana.com/0/inbox/123'), '')


class AttributionTests(Base):
    T0 = datetime(2026, 10, 7, 20, 9, tzinfo=dt_timezone.utc)

    def block(self, **kw):
        defaults = dict(org=self.org, user=self.al, hostname='mac', device_id='d1',
                        start=self.T0, end=self.T0 + timedelta(minutes=46), minutes=12,
                        app_name='Asana', title='Asana', window_title='Asana',
                        classification_state='committed', is_categorized=True, is_billable=True,
                        client=self.tom, category_hours={'Project Management': 0.2})
        defaults.update(kw)
        return Block.objects.create(**defaults)

    def did(self, project, minutes_in):
        AsanaActivity.objects.create(integration=self.integ, story_gid=f's{project.id}{minutes_in}',
                                     user=self.al, at=self.T0 + timedelta(minutes=minutes_in),
                                     project=project, task_name='x', kind='comment_added')

    def run_sweep(self):
        with mock.patch('tracker.services.matter_attribution.timezone.now',
                        return_value=self.T0 + timedelta(hours=1)):
            return attribute_matters_for_org(self.org, days=2)

    def test_desktop_app_filed_by_what_was_done(self):
        b = self.block()
        self.did(self.reskin, 5)
        self.did(self.reskin, 30)
        stats = self.run_sweep()
        b.refresh_from_db()
        self.assertEqual(b.project_id, self.reskin.id)
        self.assertEqual(stats['by_asana_activity'], 1)

    def test_two_projects_touched_abstains(self):
        b = self.block()
        self.did(self.reskin, 5)
        self.did(self.donut, 30)
        self.run_sweep()
        b.refresh_from_db()
        self.assertIsNone(b.project_id)

    def test_browser_tab_named_by_its_address_and_client_fixed(self):
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='1205551234567',
                                        project=self.reskin, link_source='name')
        b = self.block(app_name='Google Chrome', title='Google Chrome',
                       window_title='Homepage wireframe - TGBGMC Website Reskin - Asana',
                       url='https://app.asana.com/0/1205551234567/1206667654321/f',
                       client=self.ford, categorized_by='ai')
        stats = self.run_sweep()
        b.refresh_from_db()
        self.assertEqual((b.project_id, b.client_id), (self.reskin.id, self.tom.id))
        self.assertEqual(stats['by_asana_url'], 1)

    def test_never_overrules_a_person(self):
        self.did(self.reskin, 5)
        b = self.block(client=self.ford, categorized_by='manual')
        self.run_sweep()
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.ford.id)
        self.assertIsNone(b.project_id)

    def test_other_apps_untouched(self):
        self.did(self.reskin, 5)
        b = self.block(app_name='Slack', title='Slack', window_title='Slack')
        self.run_sweep()
        b.refresh_from_db()
        self.assertNotEqual(b.project_id, self.reskin.id)


@override_settings(**ASANA)
class ViewTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.al)

    def test_connect_asks_for_read_scopes(self):
        r = self.api.post('/api/integrations/asana/connect/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('app.asana.com/-/oauth_authorize', r.data['auth_url'])
        self.assertIn('stories%3Aread', r.data['auth_url'])

    def test_callback_stores_grant_and_starts_sync(self):
        self.integ.oauth_state, self.integ.is_connected = 'st', False
        self.integ.save()
        with mock.patch('tracker.integrations.asana.views.exchange_code',
                        return_value={'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600}), \
                mock.patch('tracker.integrations.asana.views._start_sync') as started:
            r = self.api.get('/api/integrations/asana/callback/', {'code': 'c', 'state': 'st'})
        self.assertEqual(r.status_code, 200)
        self.integ.refresh_from_db()
        self.assertTrue(self.integ.is_connected)
        self.assertEqual((self.integ.access_token, self.integ.tenant_id), ('a', ''))
        started.assert_called_once()

    def test_link_by_hand(self):
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='333333', asana_name='Social')
        r = self.api.post('/api/integrations/asana/projects/',
                          {'asana_gid': '333333', 'project_id': self.social_t.id}, format='json')
        self.assertEqual(r.status_code, 200)
        link = AsanaProjectLink.objects.get(asana_gid='333333')
        self.assertEqual((link.project_id, link.link_source), (self.social_t.id, 'manual'))
        rows = self.api.get('/api/integrations/asana/projects/').data['projects']
        self.assertEqual(rows[0]['client_name'], 'Tom Gill Buick GMC')

    def test_status_card_counts(self):
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='1', project=self.reskin)
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='2')
        data = self.api.get('/api/integrations/status/').data['integrations']['asana']
        self.assertEqual((data['connected'], data['projects'], data['projects_linked']), (True, 2, 1))


class ClientPrefixMatchingTests(Base):
    """More Than Cars names Asana projects "Client: Project" with the client in
    its spoken short form. Real names from their workspace (2026-10-08)."""
    def setUp(self):
        super().setUp()
        self.eastern = Client.objects.create(org=self.org, name='Easterns Automotive Group')
        self.btoy = Client.objects.create(org=self.org, name='Beaver Toyota')
        self.bmaz = Client.objects.create(org=self.org, name='Beaver Mazda')
        self.cdp = Project.objects.create(org=self.org, client=self.tom,
                                          name='Tom Gill Buick GMC CDP Planning and Execution')
        self.guide = Project.objects.create(org=self.org, client=self.btoy, name='Beaver Toyota Brand Guide')

    def sync(self, *names):
        rows = [{'gid': str(100000 + i), 'name': n} for i, n in enumerate(names)]
        _sync_projects(self.integ, FakeApi({'projects': rows}), 'ws1',
                       {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0})
        return {l.asana_name: (l.project_id, l.client_id, l.link_source)
                for l in AsanaProjectLink.objects.all()}

    def test_short_client_then_project(self):
        got = self.sync('Tom Gill: CDP Planning & Execution', 'Beaver Toyota: Brand Guide',
                        'Tom Gill: Website Reskin')
        self.assertEqual(got['Tom Gill: CDP Planning & Execution'], (self.cdp.id, self.tom.id, 'name'))
        self.assertEqual(got['Beaver Toyota: Brand Guide'], (self.guide.id, self.btoy.id, 'name'))
        # TGBGMC Website Reskin, via the client-abbreviation strip
        self.assertEqual(got['Tom Gill: Website Reskin'], (self.reskin.id, self.tom.id, 'name'))

    def test_client_only_when_no_project_fits(self):
        got = self.sync('Tom Gill: Mirror Hang Tag and Reorder- October 2023',
                        'Easterns Auto: Monthly Nissan New Cars Offer Ads',
                        'Beaver Toyota:Ameris Step and Repeat')
        self.assertEqual(got['Tom Gill: Mirror Hang Tag and Reorder- October 2023'],
                         (None, self.tom.id, 'client'))
        self.assertEqual(got['Easterns Auto: Monthly Nissan New Cars Offer Ads'],
                         (None, self.eastern.id, 'client'))
        self.assertEqual(got['Beaver Toyota:Ameris Step and Repeat'], (None, self.btoy.id, 'client'))

    def test_ambiguous_or_unknown_client_links_nothing(self):
        got = self.sync('Beaver: Flags', 'ASOTU CON 2025', 'Frank Leta- Ukraine Fundraiser Graphics')
        for name in got:
            self.assertEqual(got[name], (None, None, ''), name)

    def test_desktop_time_gets_the_client_and_still_asks_the_project(self):
        self.sync('Tom Gill: Mirror Hang Tag and Reorder- October 2023')
        link = AsanaProjectLink.objects.get()
        ExternalStaffMapping.objects.create(integration=self.integ, external_id='u1', user=self.al)
        t0 = AttributionTests.T0
        AsanaActivity.objects.create(integration=self.integ, story_gid='s1', user=self.al,
                                     at=t0 + timedelta(minutes=5), client=self.tom,
                                     asana_project_gid=link.asana_gid, kind='comment_added')
        b = Block.objects.create(org=self.org, user=self.al, hostname='mac', device_id='d1',
                                 start=t0, end=t0 + timedelta(minutes=20), minutes=12,
                                 app_name='Asana', title='Asana', window_title='Asana',
                                 classification_state='committed', is_categorized=True,
                                 is_billable=True, client=self.ford, categorized_by='ai',
                                 category_hours={'Project Management': 0.2})
        with mock.patch('tracker.services.matter_attribution.timezone.now',
                        return_value=t0 + timedelta(hours=1)):
            stats = attribute_matters_for_org(self.org, days=2)
        b.refresh_from_db()
        self.assertEqual((b.client_id, b.project_id), (self.tom.id, None))
        self.assertEqual(stats['by_asana_activity_client'], 1)


class FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return False
        self.data[key] = value.encode() if isinstance(value, str) else value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


class LockAndPeopleTests(Base):
    """The 2026-10-08 stall: a Postgres advisory lock leaked through Neon's
    pooler and every sync after the first said "already running"."""
    def test_lock_is_exclusive_and_released_only_by_its_holder(self):
        from tracker.integrations.asana import sync as s
        fake = FakeRedis()
        with mock.patch.object(s, '_redis', return_value=fake):
            first = s._try_lock(self.integ.id)
            self.assertTrue(first)
            self.assertIsNone(s._try_lock(self.integ.id))          # held
            s._unlock(self.integ.id, 'not-the-holder')
            self.assertIsNone(s._try_lock(self.integ.id))          # still held
            s._unlock(self.integ.id, first)
            self.assertTrue(s._try_lock(self.integ.id))            # free again

    def test_lock_expires_so_a_lost_release_cannot_stall_syncing(self):
        from tracker.integrations.asana import sync as s
        fake = mock.Mock()
        fake.set.return_value = True
        with mock.patch.object(s, '_redis', return_value=fake):
            s._try_lock(self.integ.id)
        self.assertEqual(fake.set.call_args.kwargs['ex'], s.LOCK_TTL)

    def test_no_redis_still_syncs(self):
        from tracker.integrations.asana import sync as s
        with mock.patch.object(s, '_redis', return_value=None):
            self.assertTrue(s._try_lock(self.integ.id))

    def test_five_minute_pass_asks_per_person_not_per_project(self):
        from tracker.integrations.asana import sync as s
        for i in range(50):
            AsanaProjectLink.objects.create(integration=self.integ, asana_gid=f'p{i}', project=self.donut)
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='111111', project=self.reskin)
        ExternalStaffMapping.objects.create(integration=self.integ, external_id='u1', user=self.al)
        now = timezone.now()
        api = FakeApi({
            'tasks': [{'gid': 't1', 'name': 'Homepage wireframe',
                       'memberships': [{'project': {'gid': '111111'}}]}],
            'tasks/t1/stories': [{'gid': 's1', 'created_at': (now - timedelta(minutes=3)).isoformat(),
                                  'created_by': {'gid': 'u1'}, 'resource_subtype': 'comment_added'}],
        })
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            stats = s.sync_people_activity(self.integ, api=api)
        task_calls = [p for path, p in api.calls if path == 'tasks']
        self.assertEqual(len(task_calls), 1)                         # one person, one call
        self.assertEqual((task_calls[0]['assignee'], task_calls[0]['workspace']), ('u1', 'ws1'))
        self.assertEqual(stats['recorded'], 1)
        self.assertEqual(AsanaActivity.objects.get().project_id, self.reskin.id)

    def test_inactive_people_are_not_asked_about(self):
        from tracker.integrations.asana import sync as s
        ExternalStaffMapping.objects.create(integration=self.integ, external_id='u1', user=self.al)
        self.al.is_active = False
        self.al.save()
        api = FakeApi({})
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            stats = s.sync_people_activity(self.integ, api=api)
        self.assertEqual((stats['people'], api.calls), (0, []))


class CardStateTests(Base):
    """The card has to say what the sync is doing: More Than Cars' first
    big sync looked 'stopped' because the card only knew the last finish."""
    def state(self):
        from tracker.integrations.asana.sync import sync_state
        self.integ.refresh_from_db()
        return sync_state(self.integ)

    def test_running_full_sync_shows_syncing(self):
        from tracker.integrations.asana import sync as s
        fake = FakeRedis()
        with mock.patch.object(s, '_redis', return_value=fake):
            s._try_lock(self.integ.id, 'full')
            self.integ.last_sync_status = 'running'
            self.integ.save()
            st = self.state()
        self.assertEqual((st['syncing'], st['last_sync_status']), (True, 'running'))

    def test_dead_sync_reads_as_failed(self):
        from tracker.integrations.asana import sync as s
        self.integ.last_sync_status = 'running'
        self.integ.save()
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):    # nobody holds the lock
            st = self.state()
        self.assertFalse(st['syncing'])
        self.assertEqual(st['last_sync_status'], 'failed')
        self.assertIn('stopped before it finished', st['last_sync_error'])

    def test_five_minute_pass_is_not_a_full_sync(self):
        from tracker.integrations.asana import sync as s
        fake = FakeRedis()
        with mock.patch.object(s, '_redis', return_value=fake):
            s._try_lock(self.integ.id, 'activity')
            self.assertFalse(self.state()['syncing'])

    def test_full_sync_marks_running_then_success(self):
        from tracker.integrations.asana import sync as s
        seen = []
        real = s._sync_projects

        def spy(integration, *a, **k):
            seen.append(Integration.objects.get(id=integration.id).last_sync_status)
            return real(integration, *a, **k)
        with mock.patch.object(s, '_sync_projects', side_effect=spy), \
                mock.patch.object(s, '_redis', return_value=FakeRedis()):
            s.full_sync(self.integ, api=FakeApi({}))
        self.integ.refresh_from_db()
        self.assertEqual((seen, self.integ.last_sync_status), (['running'], 'success'))

    @override_settings(**ASANA)
    def test_status_endpoint_and_second_press(self):
        from tracker.integrations.asana import sync as s
        api = APIClient()
        api.force_authenticate(self.al)
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='9', client=self.tom)
        fake = FakeRedis()
        with mock.patch.object(s, '_redis', return_value=fake):
            s._try_lock(self.integ.id, 'full')
            data = api.get('/api/integrations/status/').data['integrations']['asana']
            self.assertEqual((data['syncing'], data['clients_linked']), (True, 1))
            with mock.patch('tracker.integrations.asana.views._start_sync') as started:
                r = api.post('/api/integrations/asana/sync/')
            self.assertEqual(r.data.get('running'), True)
            started.assert_not_called()


class RealPairsMatcherTests(SimpleTestCase):
    """More Than Cars' QuickBooks Time and Asana lists are 'identical' the
    way people mean it. Pairs from their data, 2026-10-08."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from types import SimpleNamespace as NS
        from tracker.integrations.asana.matching import Matcher
        names = ['CarNow, Inc.', 'Robert DeNooyer Chevrolet', 'More Than Cars Media', 'More Than Cars',
                 'Easterns Automotive Group', 'Fredericktown Chevrolet', 'Tom Gill Chevrolet',
                 'Tom Gill Buick GMC', 'Beaver Mazda', 'Bob Weaver Chevrolet', 'Auto Acquire, Inc.']
        cls.c = {n: NS(id=i + 1, name=n, aliases=[], email='', alias_sources={})
                 for i, n in enumerate(names)}
        rows = [
            ('CarNow Showroom Deal Maker UX Video', 'CarNow, Inc.'),
            ('CarNow NADA Booth Design', 'CarNow, Inc.'),
            ('CarNow 2026 Positioning Video', 'CarNow, Inc.'),
            ('DeNooyer 250th Email', 'Robert DeNooyer Chevrolet'),
            ('DeNooyer Website & Asset Color Revisions', 'Robert DeNooyer Chevrolet'),
            ('DeNooyer Logo Emblem', 'Robert DeNooyer Chevrolet'),
            ('MTCM NY Auto Forum Event Coverage', 'More Than Cars Media'),
            ('MTCM Podcast Production', 'More Than Cars Media'),
            ('Easterns Nissan White Marsh Website Updates', 'Easterns Automotive Group'),
            ('Easterns Monthly Offers', 'Easterns Automotive Group'),
            ('Fredy Chevy Q4 Production', 'Fredericktown Chevrolet'),
            ('Fredy Chevy Q3 Production', 'Fredericktown Chevrolet'),
            ('Fredy Chevy Used Cars Brand Campaign', 'Fredericktown Chevrolet'),
            ('Tom Gill Auto Group Onboarding Video', 'Tom Gill Chevrolet'),
            ('TGBGMC Website Reskin', 'Tom Gill Buick GMC'),
            ('Beaver Mazda CX5 Event Emails', 'Beaver Mazda'),
            ('Beaver Mazda CX5 Event Logo', 'Beaver Mazda'),
            ('Bob Weaver Billboard Designs', 'Bob Weaver Chevrolet'),
            ('AutoAcquire Social Media Videos', 'Auto Acquire, Inc.'),
            ('AutoAcquire Banners', 'Auto Acquire, Inc.'),
        ]
        cls.p = {n: NS(id=100 + i, name=n, client_id=cls.c[cl].id, is_active=True)
                 for i, (n, cl) in enumerate(rows)}
        cls.m = Matcher(list(cls.c.values()), list(cls.p.values()))

    def project(self, asana_name):
        p, _c, _how = self.m.match(asana_name)
        return p.name if p else None

    def test_wording_differences_still_link(self):
        for asana, tt in [
            ('CarNow: Showroom Dealmaker UX Video', 'CarNow Showroom Deal Maker UX Video'),
            ('DeNooyer: 250 Email', 'DeNooyer 250th Email'),
            ('DeNooyer: Website and Asset Color Revision', 'DeNooyer Website & Asset Color Revisions'),
            ('Beaver Mazda: CX5 Event Email', 'Beaver Mazda CX5 Event Emails'),
        ]:
            self.assertEqual(self.project(asana), tt, asana)

    def test_client_short_forms(self):
        self.assertEqual(self.project('MTC Media - NY Auto Forum Event Coverage'),
                         'MTCM NY Auto Forum Event Coverage')
        self.assertEqual(self.project('Easterns Auto Group: Nissan of White Marsh Website Update'),
                         'Easterns Nissan White Marsh Website Updates')
        self.assertEqual(self.project('Fredy Chevy: Q4 Production'), 'Fredy Chevy Q4 Production')
        self.assertEqual(self.project('AutoAcquire: Banners'), 'AutoAcquire Banners')

    def test_ambiguous_client_resolved_by_its_project(self):
        self.assertEqual(self.project('Tom Gill: Auto Group Onboarding Video'),
                         'Tom Gill Auto Group Onboarding Video')
        self.assertEqual(self.project('Tom Gill: Website Reskin'), 'TGBGMC Website Reskin')
        # Two Tom Gill clients and no project fits: nothing, not a guessed client.
        self.assertEqual(self.m.match('Tom Gill: Mirror Hang Tag and Reorder'), (None, None, ''))

    def test_numbers_must_agree(self):
        p, c, how = self.m.match('Fredy Chevy: Q2 Production')
        self.assertEqual((p, c.name, how), (None, 'Fredericktown Chevrolet', 'client'))

    def test_near_miss_stays_client_only(self):
        p, c, how = self.m.match('Bob Weaver: Billboards')
        self.assertEqual((p, c.name, how), (None, 'Bob Weaver Chevrolet', 'client'))
        self.assertEqual(self.m.match('ASOTU CON 2025'), (None, None, ''))
