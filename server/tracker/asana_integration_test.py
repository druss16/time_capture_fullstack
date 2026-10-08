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
        self.assertIsNone(links['333333'])
        self.assertIsNone(links['444444'])
        self.assertEqual(stats['ambiguous'], 1)
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
