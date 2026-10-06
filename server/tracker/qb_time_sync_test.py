"""
QuickBooks Time → Client / Project sync.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.qb_time_sync_test --noinput < /dev/null

The QuickBooks Time API is faked at the `paginated()` seam with payloads shaped
like the published reference — no network.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from tracker.integrations.qb_time import sync as sync_mod
from tracker.integrations.qb_time.client import QBTimeError, QBTimeNotAvailable, records
from tracker.integrations.qb_time.sync import (
    estimate_hours_by_project, full_sync, plan_tree, remote_changed_since,
)
from tracker.models import Block, Client, Integration, Organization, OrganizationMembership, Project
from tracker.models_task_type_sets import ExternalMatterMapping, ExternalStaffMapping
from tracker.services.projects import selectable_projects

User = get_user_model()
T0 = datetime(2026, 9, 29, 14, 0, tzinfo=dt_timezone.utc)


def jc(id, name, parent=0, active=True, type='regular', qbo=False):
    return {'id': id, 'name': name, 'parent_id': parent, 'active': active, 'type': type,
            'connect_with_quickbooks': qbo, 'short_code': ''}


JOBCODES = [
    jc(1, 'Ford Dealers'),
    jc(11, 'Spring Launch', 1),
    jc(111, 'Storyboards', 11),            # task under a project -> ignored
    jc(12, 'Website Refresh', 1),
    jc(2, 'Chevy'),
    jc(21, 'Truck Month', 2),
    jc(3, 'Admin'),                         # overhead code, no projects -> no client
    jc(4, 'Lincoln', qbo=True),             # linked to QBO, no projects yet -> client
    jc(9, 'PTO', type='pto'),
]


class FakeAPI:
    def __init__(self, data, unavailable=()):
        self.data, self.unavailable = data, set(unavailable)

    def paginated(self, endpoint, **params):
        if endpoint in self.unavailable:
            raise QBTimeNotAvailable(endpoint)
        return iter(self.data.get(endpoint, []))


class PureTests(SimpleTestCase):
    def test_records_shapes(self):
        self.assertEqual(records({'results': {'jobcodes': {'1': {'id': 1}}}}, 'jobcodes'), [{'id': 1}])
        self.assertEqual(records({'results': {'jobcodes': [{'id': 1}]}}, 'jobcodes'), [{'id': 1}])
        self.assertEqual(records({}, 'jobcodes'), [])

    def test_tree(self):
        plan = plan_tree(JOBCODES, [])
        self.assertEqual(set(plan['customers']), {'1', '2', '3', '4'})
        self.assertEqual({k: v[0] for k, v in plan['projects'].items()},
                         {'11': '1', '12': '1', '21': '2'})
        self.assertEqual(plan['skipped_tasks'], 1)

    def test_project_record_promotes_a_deeper_jobcode(self):
        plan = plan_tree(JOBCODES, [{'id': 500, 'jobcode_id': 111, 'parent_jobcode_id': 1}])
        self.assertEqual(plan['projects']['111'][0], '1')
        self.assertEqual(plan['skipped_tasks'], 0)

    def test_estimates_sum_active_items(self):
        hours = estimate_hours_by_project(
            [{'id': 7, 'project_id': 500, 'active': True}, {'id': 8, 'project_id': 501, 'active': False}],
            [{'estimate_id': 7, 'estimated_seconds': 36000, 'active': True},
             {'estimate_id': 7, 'estimated_seconds': 36000, 'active': True},
             {'estimate_id': 7, 'estimated_seconds': 99999, 'active': False},
             {'estimate_id': 8, 'estimated_seconds': 3600, 'active': True}])
        self.assertEqual(hours, {'500': Decimal('20.00')})


class SyncTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc', industry_type='marketing')
        self.owner = User.objects.create_user('owner', email='owner@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.owner, organization=self.org, role='owner')
        self.existing = Client.objects.create(org=self.org, name='Chevy', imported_from='quickbooks')
        self.integration = Integration.objects.create(
            organization=self.org, provider='qb_time', is_connected=True, access_token='t')

    def data(self, **over):
        d = {
            'jobcodes': JOBCODES,
            'projects': [{'id': 500, 'jobcode_id': 11, 'parent_jobcode_id': 1, 'name': 'Spring Launch',
                          'status': 'in_progress', 'start_date': '2026-09-01', 'due_date': '2026-10-31',
                          'active': True},
                         {'id': 501, 'jobcode_id': 21, 'parent_jobcode_id': 2, 'name': 'Truck Month',
                          'status': 'complete', 'active': True}],
            'estimates': [{'id': 7, 'project_id': 500, 'active': True}],
            'estimate_items': [{'estimate_id': 7, 'estimated_seconds': 72000, 'active': True}],
            'users': [{'id': 55, 'email': 'OWNER@mtc.test', 'first_name': 'O', 'last_name': 'Wner'},
                      {'id': 56, 'email': 'freelancer@else.test'}],
        }
        d.update(over)
        return d

    def sync(self, **kw):
        unavailable = kw.pop('unavailable', ())
        return full_sync(self.integration, api=FakeAPI(self.data(**kw), unavailable))

    def test_first_sync(self):
        stats = self.sync()
        self.assertEqual(stats['errors'], [])
        names = set(Client.objects.filter(org=self.org).values_list('name', flat=True))
        self.assertIn('Ford Dealers', names)
        self.assertIn('Lincoln', names)        # QBO-linked customer
        self.assertNotIn('Admin', names)       # overhead code
        self.assertEqual(Client.objects.filter(org=self.org, name='Chevy').count(), 1)  # matched, not duplicated
        self.assertEqual(stats['clients']['skipped'], 1)

        spring = ExternalMatterMapping.objects.get(integration=self.integration, external_id='11')
        self.assertEqual(spring.estimated_hours, Decimal('20.00'))
        self.assertEqual(str(spring.due_date), '2026-10-31')
        self.assertEqual(spring.display_number, '')
        # MTC's estimates are monthly hours: the estimate becomes the budget.
        from tracker.models import ProjectBudget
        budget = ProjectBudget.objects.get(project=spring.project)
        self.assertEqual((budget.monthly_hours, budget.source), (Decimal('20.00'), 'qb_time'))
        self.assertEqual(stats['estimates'].get('applied'), 1)
        truck = ExternalMatterMapping.objects.get(integration=self.integration, external_id='21')
        self.assertFalse(truck.project.is_active)   # completed project takes no new time
        self.assertEqual(truck.project.client_id, self.existing.id)

        live = selectable_projects(self.org)
        ford = Client.objects.get(org=self.org, name='Ford Dealers')
        self.assertEqual(sorted(o.name for o in live[ford.id]), ['Spring Launch', 'Website Refresh'])
        self.assertNotIn(self.existing.id, live)

        self.assertEqual(ExternalStaffMapping.objects.get(integration=self.integration).user, self.owner)
        self.assertEqual(stats['staff'], {'matched': 1, 'unmatched': 1})
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.last_sync_status, 'success')

    def test_idempotent_and_adopts_local_project(self):
        ford = Client.objects.create(org=self.org, name='Ford Dealers')
        local = Project.objects.create(org=self.org, client=ford, name='spring launch')
        self.sync()
        self.sync()
        self.assertEqual(Project.objects.filter(org=self.org, client=ford).count(), 2)
        self.assertEqual(ExternalMatterMapping.objects.get(external_id='11').project_id, local.id)

    def test_removed_jobcode_closes_project(self):
        self.sync()
        self.sync(jobcodes=[j for j in JOBCODES if j['id'] != 12])
        web = ExternalMatterMapping.objects.get(external_id='12')
        self.assertEqual(web.external_status, 'closed')
        self.assertFalse(web.project.is_active)

    def test_account_without_projects_feature(self):
        stats = self.sync(unavailable={'projects'})
        self.assertFalse(stats['estimates']['available'])
        self.assertEqual(stats['errors'], [])
        self.assertTrue(ExternalMatterMapping.objects.filter(external_id='21', project__is_active=True).exists())

    def test_synced_project_name_attributes_time(self):
        self.sync()
        ford = Client.objects.get(org=self.org, name='Ford Dealers')
        b = Block.objects.create(
            org=self.org, user=self.owner, hostname='mac', device_id='d', start=T0,
            end=T0 + timedelta(minutes=20), minutes=20, app_name='Photoshop',
            window_title='Website Refresh hero v2.psd', title='Website Refresh hero v2.psd',
            classification_state='committed', is_categorized=True, client=ford,
            category_hours={'Design': 0.3})
        from tracker.services.matter_attribution import attribute_matters_for_org
        stats = attribute_matters_for_org(self.org, days=3650)
        b.refresh_from_db()
        self.assertEqual(b.project.name, 'Website Refresh')
        self.assertEqual(stats['by_name'], 1)

    def test_failure_is_recorded(self):
        class Boom(FakeAPI):
            def paginated(self, endpoint, **params):
                raise RuntimeError('down')
        stats = full_sync(self.integration, api=Boom({}))
        self.assertTrue(stats['errors'])
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.last_sync_status, 'failed')


@override_settings(QBTIME_CLIENT_ID='cid', QBTIME_CLIENT_SECRET='sec',
                   QBTIME_REDIRECT_URI='https://api.test/api/integrations/qb_time/callback/',
                   FRONTEND_URL='https://app.test')
class EndpointTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc2', industry_type='marketing')
        self.user = User.objects.create_user('o2', email='o2@mtc.test', password='x')
        self.m = OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_connect_and_callback(self):
        r = self.api.post('/api/integrations/qb_time/connect/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('rest.tsheets.com/api/v1/authorize', r.data['auth_url'])
        state = Integration.objects.get(organization=self.org, provider='qb_time').oauth_state

        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'access_token': 'a', 'refresh_token': 'r', 'expires_in': 864000,
                                  'company_id': 4242}
        with mock.patch('tracker.integrations.qb_time.views.requests.post', return_value=resp), \
             mock.patch('tracker.integrations.qb_time.sync.sync_qb_time_full.delay') as delay:
            r = APIClient().get('/api/integrations/qb_time/callback/', {'code': 'c', 'state': state})
        self.assertEqual(r.status_code, 200)
        i = Integration.objects.get(organization=self.org, provider='qb_time')
        self.assertTrue(i.is_connected)
        self.assertEqual((i.realm_id, i.access_token, i.last_sync_status), ('4242', 'a', 'pending'))
        delay.assert_called_once_with(i.id)

        status = self.api.get('/api/integrations/status/').data
        self.assertTrue(status['integrations']['qb_time']['connected'])
        self.assertEqual(status['integrations']['qb_time']['realm_id'], '4242')

        self.assertEqual(self.api.post('/api/integrations/qb_time/disconnect/').status_code, 200)
        i.refresh_from_db()
        self.assertFalse(i.is_connected)

    def test_bad_state_rejected(self):
        r = APIClient().get('/api/integrations/qb_time/callback/', {'code': 'c', 'state': 'nope'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('invalid_state', r['Location'])

    def test_member_cannot_connect(self):
        self.m.role = 'member'
        self.m.save()
        self.assertEqual(self.api.post('/api/integrations/qb_time/connect/').status_code, 403)

    @override_settings(QBTIME_CLIENT_ID='')
    def test_not_configured(self):
        self.assertEqual(self.api.post('/api/integrations/qb_time/connect/').status_code, 503)


class StampAPI:
    """Answers last_modified_timestamps like the published reference."""

    def __init__(self, stamps):
        self.stamps = stamps
        self.calls = []

    def get(self, endpoint, **params):
        self.calls.append((endpoint, params))
        assert endpoint == 'last_modified_timestamps'
        return {'results': {'last_modified_timestamps': dict(self.stamps)}}


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S+00:00')


class ChangeDetectionTests(SimpleTestCase):
    def test_unchanged_since_last_sync(self):
        api = StampAPI({'jobcodes': iso(T0 - timedelta(hours=2)), 'users': iso(T0 - timedelta(days=3))})
        self.assertFalse(remote_changed_since(api, T0))
        self.assertEqual(api.calls, [('last_modified_timestamps', {'endpoints': 'jobcodes,users'})])

    def test_new_project_moves_jobcodes(self):
        api = StampAPI({'jobcodes': iso(T0 + timedelta(minutes=1)), 'users': iso(T0 - timedelta(days=3))})
        self.assertTrue(remote_changed_since(api, T0))

    def test_new_user_counts(self):
        api = StampAPI({'jobcodes': iso(T0 - timedelta(days=1)), 'users': iso(T0 + timedelta(seconds=5))})
        self.assertTrue(remote_changed_since(api, T0))

    def test_change_just_before_our_sync_is_not_trusted(self):
        # Their clock may run behind ours; a change stamped 30s "before" our
        # sync started may have landed after it.
        api = StampAPI({'jobcodes': iso(T0 - timedelta(seconds=30)), 'users': iso(T0 - timedelta(days=1))})
        self.assertTrue(remote_changed_since(api, T0))

    def test_missing_stamp_syncs_rather_than_guesses(self):
        self.assertTrue(remote_changed_since(StampAPI({'users': iso(T0 - timedelta(days=1))}), T0))

    def test_never_synced_needs_no_request(self):
        api = StampAPI({})
        self.assertTrue(remote_changed_since(api, None))
        self.assertEqual(api.calls, [])


class ChangeCheckTaskTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-cc', industry_type='marketing')
        self.integration = Integration.objects.create(
            organization=self.org, provider='qb_time', is_connected=True, access_token='t',
            last_synced_at=T0, last_sync_status='success')
        self.stamps = {'jobcodes': iso(T0 - timedelta(hours=1)), 'users': iso(T0 - timedelta(hours=1))}
        p = mock.patch.object(sync_mod, 'QBTimeClient', side_effect=lambda i: StampAPI(self.stamps))
        p.start()
        self.addCleanup(p.stop)
        self.queued = mock.patch.object(sync_mod.sync_qb_time_full, 'delay').start()
        self.addCleanup(mock.patch.stopall)

    def test_quiet_firm_is_left_alone(self):
        out = sync_mod.check_qb_time_changes()
        self.assertEqual(out['unchanged'], 1)
        self.queued.assert_not_called()

    def test_changed_firm_is_synced(self):
        self.stamps['jobcodes'] = iso(T0 + timedelta(minutes=2))
        out = sync_mod.check_qb_time_changes()
        self.assertEqual(out['synced'], 1)
        self.queued.assert_called_once_with(self.integration.id)

    def test_disconnected_firm_is_not_asked(self):
        Integration.objects.filter(id=self.integration.id).update(is_connected=False)
        self.assertEqual(sync_mod.check_qb_time_changes()['unchanged'], 0)
        self.queued.assert_not_called()

    def test_failing_firm_backs_off(self):
        # A failed sync leaves last_synced_at behind; without backing off every
        # check would re-run a sync that is about to fail again.
        self.stamps['jobcodes'] = iso(T0 + timedelta(minutes=2))
        Integration.objects.filter(id=self.integration.id).update(last_sync_status='failed')
        out = sync_mod.check_qb_time_changes()
        self.assertEqual(out['backing_off'], 1)
        self.queued.assert_not_called()

    def test_check_error_skips_that_firm_only(self):
        other_org = Organization.objects.create(name='B', slug='b-cc', industry_type='marketing')
        Integration.objects.create(organization=other_org, provider='qb_time', is_connected=True,
                                   access_token='t', last_synced_at=T0)
        self.stamps['jobcodes'] = iso(T0 + timedelta(minutes=2))
        calls = {'n': 0}

        def client(integration):
            calls['n'] += 1
            if integration.id == self.integration.id:
                raise QBTimeError('token expired')
            return StampAPI(self.stamps)

        with mock.patch.object(sync_mod, 'QBTimeClient', side_effect=client):
            out = sync_mod.check_qb_time_changes()
        self.assertEqual((out['errors'], out['synced']), (1, 1))

    def test_sync_stamps_its_start_not_its_end(self):
        # A jobcode created while the sync is fetching must still look newer
        # than last_synced_at, so the stamp is the moment the sync began.
        clock = {'now': T0 + timedelta(minutes=10)}

        class SlowAPI(FakeAPI):
            def paginated(self, endpoint, **params):
                clock['now'] = T0 + timedelta(minutes=20)
                return super().paginated(endpoint, **params)

        with mock.patch('django.utils.timezone.now', side_effect=lambda: clock['now']):
            full_sync(self.integration, api=SlowAPI({'jobcodes': [], 'users': []},
                                                     unavailable=('projects',)))
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.last_sync_status, 'success')
        self.assertEqual(self.integration.last_synced_at, T0 + timedelta(minutes=10))

    def test_second_concurrent_sync_stands_down(self):
        with mock.patch.object(sync_mod, '_try_sync_lock', return_value=False), \
             mock.patch.object(sync_mod, 'full_sync') as full:
            self.assertEqual(sync_mod.sync_qb_time_full(self.integration.id), {'skipped': 'already_running'})
        full.assert_not_called()
