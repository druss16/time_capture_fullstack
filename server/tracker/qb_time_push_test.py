"""
TimeTracker → QuickBooks Time timesheet push.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.qb_time_push_test --noinput < /dev/null

QuickBooks Time is faked at the client's paginated/post/put/delete seam, with
payloads shaped like the published reference — no network.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from tracker.integrations.qb_time import push as push_mod
from tracker.integrations.qb_time.client import (
    QBTimeAuthError, QBTimeError, row_error, row_ok, row_results,
)
from tracker.integrations.qb_time.push import build_push_plan, decide_entry, execute_push
from tracker.models import (
    Block, Client, Integration, Organization, OrganizationMembership, Project, Timesheet,
)
from tracker.models_task_type_sets import (
    ExternalClientMapping, ExternalMatterMapping, ExternalStaffMapping, QbtPushedTimesheet,
    QbtPushSettings, QbtTimesheetPush,
)

User = get_user_model()
DAY = date(2026, 9, 29)
T0 = datetime(2026, 9, 29, 14, 0, tzinfo=dt_timezone.utc)


class FakeAPI:
    """Holds QuickBooks Time's timesheets in memory and answers like the API."""

    def __init__(self, jobcodes=None, timesheets=None, reject=None):
        self.jobcodes = jobcodes or {}
        self.timesheets = {str(t['id']): dict(t) for t in (timesheets or [])}
        self.reject = reject or {}           # jobcode_id -> rejection message
        self.next_id = 9000
        self.calls = []

    def paginated(self, endpoint, **params):
        self.calls.append(('GET', endpoint, params))
        if endpoint == 'jobcodes':
            ids = params['ids'].split(',')
            return iter([self.jobcodes[i] for i in ids if i in self.jobcodes])
        if endpoint == 'timesheets':
            users = set(params['user_ids'].split(','))
            return iter([t for t in self.timesheets.values()
                         if str(t['user_id']) in users
                         and params['start_date'] <= t['date'] <= params['end_date']])
        raise AssertionError(endpoint)

    def post(self, endpoint, data):
        self.calls.append(('POST', endpoint, data))
        out = {}
        for n, row in enumerate(data, start=1):
            msg = self.reject.get(str(row['jobcode_id']))
            if msg:
                out[str(n)] = {'_status_code': 417, '_status_message': 'Expectation Failed',
                               '_status_extra': msg}
                continue
            self.next_id += 1
            self.timesheets[str(self.next_id)] = {**row, 'id': self.next_id}
            out[str(n)] = {'_status_code': 200, '_status_message': 'Created', 'id': self.next_id}
        return {'results': {'timesheets': out}}

    def put(self, endpoint, data):
        self.calls.append(('PUT', endpoint, data))
        for row in data:
            self.timesheets[str(row['id'])]['duration'] = row['duration']
        return {'results': {'timesheets': {'1': {'_status_code': 200, 'id': data[0]['id']}}}}

    def delete(self, endpoint, ids):
        self.calls.append(('DELETE', endpoint, ids))
        for i in ids:
            self.timesheets.pop(str(i), None)
        return {'results': {'timesheets': {'1': {'_status_code': 200, 'id': int(ids[0])}}}}

    def total(self, user_id, jobcode_id, day=DAY):
        return sum(int(t['duration']) // 60 for t in self.timesheets.values()
                   if str(t['user_id']) == str(user_id) and str(t['jobcode_id']) == str(jobcode_id)
                   and t['date'] == str(day))


def jc(id, name, active=True, has_children=False):
    return {'id': id, 'name': name, 'active': active, 'has_children': has_children}


class PureTests(SimpleTestCase):
    def test_delta(self):
        self.assertEqual(decide_entry(90, 0), ('push', 90, ''))
        self.assertEqual(decide_entry(90, 60), ('push', 30, ''))
        self.assertEqual(decide_entry(90, 90, ours_minutes=90), ('skip', 90, 'already_in_qbt'))

    def test_hand_entered_extra_is_never_reduced(self):
        # We pushed 60 and they logged 60 more by hand: total exceeds captured,
        # but our 60 is still right.
        self.assertEqual(decide_entry(60, 120, ours_minutes=60)[0], 'skip')

    def test_moved_time_reduces_only_ours(self):
        self.assertEqual(decide_entry(30, 90, ours_minutes=90), ('reduce', 60, 'attribution_moved'))

    def test_row_results_in_request_order(self):
        payload = {'results': {'timesheets': {'10': {'id': 'j'}, '2': {'id': 'b'}, '1': {'id': 'a'}}}}
        self.assertEqual([r['id'] for r in row_results(payload, 'timesheets')], ['a', 'b', 'j'])
        self.assertTrue(row_ok({'_status_code': 200}))
        self.assertFalse(row_ok({'_status_code': 417}))
        self.assertEqual(row_error({'_status_code': 417, '_status_message': 'Expectation Failed',
                                    '_status_extra': 'not assigned'}),
                         'Expectation Failed — not assigned')


class PushTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-push', industry_type='marketing')
        self.user = User.objects.create_user('ann', email='ann@mtc.test', password='x',
                                             first_name='Ann', last_name='Lee')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.integration = Integration.objects.create(
            organization=self.org, provider='qb_time', is_connected=True, access_token='t')

        self.ford = Client.objects.create(org=self.org, name='Ford Dealers')
        self.launch = Project.objects.create(org=self.org, client=self.ford, name='Spring Launch')
        self.chevy = Client.objects.create(org=self.org, name='Chevy')
        self.local = Client.objects.create(org=self.org, name='Local Only')
        ExternalClientMapping.objects.create(integration=self.integration, client=self.ford, external_id='1')
        ExternalClientMapping.objects.create(integration=self.integration, client=self.chevy, external_id='2')
        ExternalMatterMapping.objects.create(integration=self.integration, project=self.launch, external_id='11')
        ExternalStaffMapping.objects.create(integration=self.integration, user=self.user, external_id='55')

        self.api = FakeAPI(jobcodes={
            '1': jc(1, 'Ford Dealers', has_children=True),
            '11': jc(11, 'Spring Launch'),
            '2': jc(2, 'Chevy'),
        })

    def block(self, minutes, client, project=None, at=T0, user=None, notes=''):
        return Block.objects.create(
            org=self.org, user=user or self.user, hostname='mac', device_id='d', start=at,
            end=at + timedelta(minutes=minutes), minutes=minutes, app_name='Photoshop',
            window_title='Hero v2.psd', title='Hero v2.psd', notes=notes,
            classification_state='committed', is_categorized=True, client=client, project=project)

    def plan(self):
        return build_push_plan(self.integration, DAY, DAY, api=self.api)

    def push(self):
        return execute_push(self.integration, self.plan(), api=self.api)

    def test_project_wins_over_client_and_days_are_summed(self):
        self.block(30, self.ford, self.launch)
        self.block(45, self.ford, self.launch, at=T0 + timedelta(hours=1))
        self.block(20, self.chevy)
        plan = self.plan()
        got = {(e['jobcode_id'], e['push_minutes']) for e in plan['entries']}
        self.assertEqual(got, {('11', 75), ('2', 20)})
        self.assertEqual(plan['totals']['minutes'], 95)

        result = execute_push(self.integration, plan, api=self.api)
        self.assertEqual(result['totals'], {'entries': 2, 'minutes': 95, 'hours': 1.58, 'errors': 0})
        self.assertEqual(self.api.total(55, 11), 75)
        posted = [c for c in self.api.calls if c[0] == 'POST']
        self.assertEqual(len(posted), 1, 'one batched write, not one per entry')
        row = posted[0][2][0]
        self.assertEqual((row['type'], row['date'], row['user_id']), ('manual', '2026-09-29', 55))
        self.assertEqual(QbtPushedTimesheet.objects.filter(integration=self.integration).count(), 2)

    def test_rerun_never_double_counts(self):
        self.block(60, self.chevy)
        self.push()
        self.assertEqual(self.push()['totals']['entries'], 0)
        self.assertEqual(self.api.total(55, 2), 60)

        self.block(15, self.chevy, at=T0 + timedelta(hours=2))
        self.assertEqual(self.push()['pushed'][0]['minutes'], 15)
        self.assertEqual(self.api.total(55, 2), 75)

    def test_time_already_clocked_by_hand_is_netted(self):
        self.api.timesheets['500'] = {'id': 500, 'user_id': 55, 'jobcode_id': 2, 'date': '2026-09-29',
                                      'duration': 40 * 60, 'type': 'regular', 'notes': 'clocked'}
        self.block(60, self.chevy)
        plan = self.plan()
        self.assertEqual(plan['entries'][0]['push_minutes'], 20)

        self.api.timesheets['500']['duration'] = 90 * 60
        skip = self.plan()['skipped'][0]
        self.assertEqual(skip['reason'], 'already_in_qbt')
        self.assertEqual(skip['existing'][0]['timesheet_id'], '500')

    def test_recategorised_block_moves_our_time_not_theirs(self):
        b = self.block(60, self.chevy)
        self.push()
        # Someone also clocked 30m on Chevy by hand.
        self.api.timesheets['600'] = {'id': 600, 'user_id': 55, 'jobcode_id': 2, 'date': '2026-09-29',
                                      'duration': 30 * 60, 'type': 'regular', 'notes': ''}
        Block.objects.filter(id=b.id).update(client=self.ford, project=self.launch)

        result = self.push()
        self.assertEqual(len(result['reduced']), 1)
        self.assertEqual(result['reduced'][0]['to_minutes'], 0)
        self.assertIn('600', self.api.timesheets, 'hand-entered time untouched')
        self.assertEqual(self.api.total(55, 2), 30)
        self.assertEqual(self.api.total(55, 11), 60)
        self.assertEqual(QbtPushedTimesheet.objects.filter(
            integration=self.integration, deleted_at__isnull=False).count(), 1)

    def test_partial_reduction_edits_duration(self):
        b = self.block(60, self.chevy)
        self.push()
        Block.objects.filter(id=b.id).update(minutes=40, end=b.start + timedelta(minutes=40))
        result = self.push()
        self.assertEqual(result['reduced'][0]['to_minutes'], 40)
        self.assertEqual(self.api.total(55, 2), 40)
        self.assertTrue(any(c[0] == 'PUT' for c in self.api.calls))

    def test_skips_say_why(self):
        self.block(10, self.local)
        self.block(10, None)
        other = User.objects.create_user('bob', email='bob@mtc.test', password='x')
        OrganizationMembership.objects.create(user=other, organization=self.org, role='member')
        self.block(10, self.chevy, user=other)
        self.api.jobcodes['2'] = jc(2, 'Chevy', active=False)
        self.block(10, self.chevy)

        plan = self.plan()
        self.assertEqual(plan['entries'], [])
        self.assertEqual(sorted(s['reason'] for s in plan['skipped']),
                         ['jobcode_inactive', 'jobcode_not_synced', 'no_client', 'user_not_mapped'])

    def test_rejected_row_is_reported_and_others_land(self):
        self.api.reject['2'] = 'jobcode not assigned to user'
        self.block(30, self.ford, self.launch)
        self.block(20, self.chevy)
        result = self.push()
        self.assertEqual(result['totals']['entries'], 1)
        self.assertEqual(result['errors'][0]['error'], 'rejected_by_qbt')
        self.assertIn('not assigned', result['errors'][0]['detail'])
        self.assertEqual(QbtPushedTimesheet.objects.filter(integration=self.integration).count(), 1)

    def test_parent_jobcode_is_flagged(self):
        self.block(30, self.ford)  # no project -> customer jobcode, which has children
        self.assertTrue(self.plan()['entries'][0]['parent_jobcode'])

    def test_write_failure_reports_every_row(self):
        self.block(30, self.chevy)
        with mock.patch.object(self.api, 'post', side_effect=QBTimeError('boom')):
            result = self.push()
        self.assertEqual(result['totals']['errors'], 1)
        self.assertFalse(QbtPushedTimesheet.objects.exists())


class PushEndpointTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-push-ep', industry_type='marketing')
        self.owner = User.objects.create_user('own', email='own@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.owner, organization=self.org, role='owner')
        Integration.objects.create(organization=self.org, provider='qb_time', is_connected=True,
                                   access_token='t')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_dry_run_writes_nothing(self):
        plan = {'window': {}, 'entries': [], 'skipped': [], 'totals': {'entries': 0}}
        with mock.patch('tracker.integrations.qb_time.push.build_push_plan', return_value=plan), \
             mock.patch('tracker.integrations.qb_time.push.execute_push') as ex:
            r = self.api.post('/api/integrations/qb_time/push/',
                              {'start_date': '2026-09-28', 'end_date': '2026-10-04', 'dry_run': True},
                              format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['dry_run'])
        ex.assert_not_called()

    def test_window_is_validated(self):
        url = '/api/integrations/qb_time/push/'
        self.assertEqual(self.api.post(url, {'start_date': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.api.post(url, {'start_date': '2026-09-01', 'end_date': '2026-12-01'},
                                       format='json').status_code, 400)

    def test_member_cannot_push(self):
        member = User.objects.create_user('mem', email='mem@mtc.test', password='x')
        OrganizationMembership.objects.create(user=member, organization=self.org, role='member')
        c = APIClient()
        c.force_authenticate(member)
        r = c.post('/api/integrations/qb_time/push/',
                   {'start_date': '2026-09-28', 'end_date': '2026-10-04'}, format='json')
        self.assertEqual(r.status_code, 403)


WEEK = date(2026, 9, 28)  # Monday of DAY's week


class ApprovalPushTests(TestCase):
    """Approving a timesheet sends that person's week, when the firm has opted in."""

    block = PushTests.block

    def setUp(self):
        PushTests.setUp(self)
        self.manager = User.objects.create_user('mgr', email='mgr@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.manager, organization=self.org, role='manager')
        self.ts = Timesheet.objects.create(org=self.org, user=self.user, week_start=WEEK,
                                           status='submitted')
        # Neither neighbour on the transition is under test, and both reach a broker.
        for name in ('_queue_notify', '_queue_clio_push'):
            p = mock.patch.object(Timesheet, name)
            p.start()
            self.addCleanup(p.stop)
        # QuickBooks Time is the fake; the worker runs inline.
        p = mock.patch.object(push_mod, 'QBTimeClient', return_value=self.api)
        p.start()
        self.addCleanup(p.stop)
        self.delay = mock.patch.object(
            push_mod.push_timesheet_to_qb_time_task, 'delay',
            side_effect=lambda tid: push_mod.push_timesheet_to_qb_time_task(tid)).start()
        self.addCleanup(mock.patch.stopall)

    def turn_on(self):
        QbtPushSettings.objects.create(integration=self.integration, push_trigger='approve')

    def test_off_by_default_so_connecting_never_writes(self):
        self.block(60, self.chevy)
        self.ts.approve(approved_by=self.manager)
        self.delay.assert_not_called()
        self.assertFalse(QbtTimesheetPush.objects.exists())
        self.assertEqual(self.api.timesheets, {})

    def test_approve_sends_the_week(self):
        self.turn_on()
        self.block(60, self.chevy)
        self.block(30, self.ford, self.launch)
        self.ts.approve(approved_by=self.manager)

        self.assertEqual(self.api.total(55, 2), 60)
        self.assertEqual(self.api.total(55, 11), 30)
        row = QbtTimesheetPush.objects.get(timesheet_id=self.ts.id)
        self.assertEqual(row.status, 'done')
        self.assertEqual((row.result['entries'], row.result['minutes']), (2, 90))

    def test_only_this_person_and_week(self):
        self.turn_on()
        other = User.objects.create_user('bob', email='bob@mtc.test', password='x')
        OrganizationMembership.objects.create(user=other, organization=self.org, role='member')
        ExternalStaffMapping.objects.create(integration=self.integration, user=other, external_id='66')
        self.block(60, self.chevy)
        self.block(45, self.chevy, user=other)
        self.block(20, self.chevy, at=T0 + timedelta(days=7))  # next week
        self.ts.approve(approved_by=self.manager)

        self.assertEqual(self.api.total(55, 2), 60)
        self.assertEqual(self.api.total(66, 2), 0)
        self.assertEqual(self.api.total(55, 2, day=DAY + timedelta(days=7)), 0)

    def test_rerun_after_approval_adds_nothing(self):
        self.turn_on()
        self.block(60, self.chevy)
        self.ts.approve(approved_by=self.manager)
        result = push_mod.push_timesheet_to_qb_time_task(self.ts.id)
        self.assertEqual(result['entries'], 0)
        self.assertEqual(self.api.total(55, 2), 60)

    def test_owner_auto_approve_sends_too(self):
        self.turn_on()
        self.block(60, self.chevy)
        self.ts.status = 'draft'
        self.ts.save()
        with mock.patch.object(Timesheet, '_holds_misfiled_time', return_value=False):
            self.ts.submit()
        self.ts.refresh_from_db()
        self.assertEqual(self.ts.status, 'approved')
        self.assertEqual(self.api.total(55, 2), 60)

    def test_qb_time_failure_never_undoes_the_approval(self):
        self.turn_on()
        self.block(60, self.chevy)
        with mock.patch.object(self.api, 'paginated', side_effect=QBTimeAuthError('token revoked')):
            self.ts.approve(approved_by=self.manager)
        self.ts.refresh_from_db()
        self.assertEqual(self.ts.status, 'approved')
        row = QbtTimesheetPush.objects.get(timesheet_id=self.ts.id)
        self.assertEqual(row.status, 'failed')
        self.assertIn('reconnect', row.result['error'])

    def test_queue_failure_never_undoes_the_approval(self):
        self.turn_on()
        self.delay.side_effect = RuntimeError('broker down')
        self.ts.approve(approved_by=self.manager)
        self.ts.refresh_from_db()
        self.assertEqual(self.ts.status, 'approved')
        self.assertEqual(QbtTimesheetPush.objects.get(timesheet_id=self.ts.id).status, 'failed')

    def test_disconnected_is_not_a_failure(self):
        self.turn_on()
        Integration.objects.filter(id=self.integration.id).update(is_connected=False)
        self.ts.approve(approved_by=self.manager)
        self.delay.assert_not_called()

    def test_approve_endpoint_reports_the_push(self):
        self.turn_on()
        self.block(60, self.chevy)
        c = APIClient()
        c.force_authenticate(self.manager)
        r = c.post(f'/api/billing/timesheets/{self.ts.id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['qb_time']['status'], 'done')
        self.assertEqual(r.data['qb_time']['minutes'], 60)


class PushTriggerEndpointTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-trig', industry_type='marketing')
        self.owner = User.objects.create_user('own', email='own@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.owner, organization=self.org, role='owner')
        self.integration = Integration.objects.create(
            organization=self.org, provider='qb_time', is_connected=True, access_token='t')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_admin_turns_it_on_and_off(self):
        self.assertEqual(push_mod.push_trigger_for(self.integration), 'off')
        url = '/api/integrations/qb_time/push-trigger/'
        r = self.api.post(url, {'push_trigger': 'approve'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(push_mod.push_trigger_for(self.integration), 'approve')
        self.api.post(url, {'push_trigger': 'off'}, format='json')
        self.assertEqual(push_mod.push_trigger_for(self.integration), 'off')
        self.assertEqual(self.api.post(url, {'push_trigger': 'submit'}, format='json').status_code, 400)

    def test_member_cannot_change_it(self):
        member = User.objects.create_user('mem', email='mem@mtc.test', password='x')
        OrganizationMembership.objects.create(user=member, organization=self.org, role='member')
        c = APIClient()
        c.force_authenticate(member)
        r = c.post('/api/integrations/qb_time/push-trigger/', {'push_trigger': 'approve'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(push_mod.push_trigger_for(self.integration), 'off')
