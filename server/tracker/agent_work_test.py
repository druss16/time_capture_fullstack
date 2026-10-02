"""
AI agent work — report-in endpoint and its separate totals.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.agent_work_test --noinput < /dev/null
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.models import (
    AgentDevice, AgentWorkSession, AuthToken, Block, Client, Organization,
    OrganizationMembership,
)

User = get_user_model()


def snap(session_id='s1', start='2026-10-02T14:00:00Z', last='2026-10-02T14:30:00Z', **kw):
    body = {
        'agent_kind': 'claude_code', 'session_id': session_id, 'model': 'claude-opus-5-5',
        'started_at': start, 'last_activity_at': last, 'active_seconds': 900, 'turns': 3,
        'tokens': {'input': 10, 'output': 2000, 'cache_read': 50000, 'cache_write': 3000},
        'project_path': '/work/acme',
    }
    body.update(kw)
    return body


class AgentWorkTest(TestCase):
    def setUp(self):
        # plan='none' makes AgentKeyAuthentication refuse every agent call.
        self.org = Organization.objects.create(name='MavOps', slug='mavops', plan='professional')
        self.owner = User.objects.create_user('dan', email='dan@mavops.ai', password='x')
        self.member = User.objects.create_user('amy', email='amy@mavops.ai', password='x')
        OrganizationMembership.objects.create(user=self.owner, organization=self.org, role='owner')
        OrganizationMembership.objects.create(user=self.member, organization=self.org, role='member')
        self.acme = Client.objects.create(org=self.org, name='Acme Widgets', code='ACME')
        self.dev = AgentDevice.objects.create(
            user=self.member, device_id='d1', api_key='k-member', is_active=True)
        self.agent = APIClient()
        self.agent.credentials(HTTP_X_AGENT_KEY='k-member')

    def post(self, body):
        return self.agent.post('/api/agent-work/report/', body, format='json')

    def web(self, user):
        c = APIClient()
        tok = AuthToken.objects.create(
            user=user, token=f't-{user.username}',
            expires_at=timezone.now() + timezone.timedelta(days=1))
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok.token}')
        return c

    def test_snapshot_creates_then_updates_without_double_counting(self):
        self.assertEqual(self.post(snap()).status_code, 201)
        r = self.post(snap(last='2026-10-02T14:45:00Z', active_seconds=1200, turns=4))
        self.assertEqual(r.status_code, 200)
        s = AgentWorkSession.objects.get()
        self.assertEqual((s.active_seconds, s.turns, s.user, s.org), (1200, 4, self.member, self.org))

    def test_out_of_order_snapshot_cannot_roll_totals_back(self):
        self.post(snap(last='2026-10-02T14:45:00Z', active_seconds=1200))
        r = self.post(snap(last='2026-10-02T14:30:00Z', active_seconds=900))
        self.assertEqual(r.data['status'], 'stale_snapshot_ignored')
        self.assertEqual(AgentWorkSession.objects.get().active_seconds, 1200)

    def test_active_time_capped_at_wall_clock(self):
        self.post(snap(active_seconds=99999))
        self.assertEqual(AgentWorkSession.objects.get().active_seconds, 1800)

    def test_client_resolves_by_exact_name_or_code_only(self):
        self.post(snap('a', client='acme widgets'))
        self.post(snap('b', client='ACME'))
        self.post(snap('c', client='Acme Widget'))  # near-miss: kept as a hint, not guessed
        got = {s.external_session_id: (s.client_id, s.client_hint)
               for s in AgentWorkSession.objects.all()}
        self.assertEqual(got['a'][0], self.acme.id)
        self.assertEqual(got['b'][0], self.acme.id)
        self.assertEqual(got['c'], (None, 'Acme Widget'))

    def test_rejects_missing_fields_and_bad_keys(self):
        self.assertEqual(self.post({'session_id': 'x'}).status_code, 400)
        bad = APIClient()
        bad.credentials(HTTP_X_AGENT_KEY='nope')
        self.assertIn(bad.post('/api/agent-work/report/', snap(), format='json').status_code, (401, 403))

    def test_agent_work_never_becomes_human_time(self):
        self.post(snap(client='Acme Widgets'))
        self.assertEqual(Block.objects.count(), 0)

    def test_list_totals_and_role_scope(self):
        self.post(snap('a', client='ACME', start='2026-10-02T14:00:00Z'))
        AgentWorkSession.objects.create(
            org=self.org, user=self.owner, agent_kind='codex', external_session_id='o1',
            started_at='2026-10-02T15:00:00Z', last_activity_at='2026-10-02T15:10:00Z',
            active_seconds=300)

        r = self.web(self.owner).get('/api/agent-work/?start=2026-10-01&end=2026-10-03')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['scope'], 'firm')
        self.assertEqual(r.data['totals']['sessions'], 2)
        self.assertEqual(r.data['totals']['active_seconds'], 1200)
        by_client = {c['client_name']: c['active_seconds'] for c in r.data['by_client']}
        self.assertEqual(by_client, {'Acme Widgets': 900, 'Unassigned': 300})

        r = self.web(self.member).get('/api/agent-work/?start=2026-10-01&end=2026-10-03')
        self.assertEqual(r.data['scope'], 'self')
        self.assertEqual(r.data['totals']['active_seconds'], 900)


class AgentPresenceTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MavOps', slug='mavops', plan='professional')
        self.user = User.objects.create_user('amy', email='amy@mavops.ai', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='member')
        self.dev = AgentDevice.objects.create(
            user=self.user, device_id='d1', api_key='k-presence', is_active=True)
        self.agent = APIClient()
        self.agent.credentials(HTTP_X_AGENT_KEY='k-presence')

    def bucket(self, **kw):
        b = {'bucket_start': '2026-10-02T14:00:00+00:00', 'seconds_observed': 3600,
             'idle_seconds': 1200, 'remote_session': False, 'input_monitor': 'ok',
             'clicks_real': 300, 'clicks_synthetic': 40, 'synthetic_by': {'pad.robot': 40},
             'idle_changes': 12, 'idle_changes_by_app': {'chrome': 12},
             'unattended_active_seconds': 900, 'unattended_active_by_app': {'safari': 900},
             'unattended_by_cause': {'remote_control': 540, 'agent_busy': 180, 'unexplained': 180},
             'processes': {'power_automate': {'seen_min': 60, 'busy_min': 45, 'cpu_s': 300.5}},
             'local_sessions': {'claude_code': 2}}
        b.update(kw)
        return b

    def test_hour_is_idempotent_and_sanitised(self):
        from tracker.models import AgentPresenceSample
        r = self.agent.post('/api/agent-presence/', {'buckets': [self.bucket()]}, format='json')
        self.assertEqual(r.data, {'saved': 1})
        self.agent.post('/api/agent-presence/', {'buckets': [
            self.bucket(clicks_synthetic=50, seconds_observed=99999, clicks_real=-5,
                        synthetic_by={f'a{i}': 1 for i in range(80)}),
            {'bucket_start': 'garbage'}, 'not-a-dict']}, format='json')
        s = AgentPresenceSample.objects.get()
        self.assertEqual((s.clicks_synthetic, s.seconds_observed, s.clicks_real), (50, 3600, 0))
        self.assertEqual(len(s.synthetic_by), 50)
        self.assertEqual((s.org, s.user), (self.org, self.user))

    def test_rejects_non_list(self):
        r = self.agent.post('/api/agent-presence/', {'buckets': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_summary_command_runs(self):
        from io import StringIO
        from django.core.management import call_command
        from django.utils import timezone as tz
        self.agent.post('/api/agent-presence/', {'buckets': [
            self.bucket(bucket_start=(tz.now() - tz.timedelta(hours=2)).replace(
                minute=0, second=0, microsecond=0).isoformat())]}, format='json')
        out = StringIO()
        call_command('agent_presence_summary', '--days', '1', '--json', stdout=out)
        fleet = json.loads(out.getvalue())['fleet']
        self.assertEqual(fleet['clicks']['driven_device_hours'], 1)
        self.assertEqual(fleet['agent_processes']['power_automate']['busy_hours'], 0.8)
        self.assertEqual(fleet['unattended_active']['hours'], 0.2)
        self.assertEqual(fleet['unattended_active']['top_apps'], [['safari', 0.2]])
        # Remote control is a person, not an agent: only agent_busy + unexplained count.
        self.assertEqual(fleet['unattended_active']['candidate_agent_hours'], 0.1)
        self.assertEqual(fleet['unattended_active']['by_cause_hours']['remote_control'], 0.1)
        call_command('agent_presence_summary', '--days', '1', stdout=StringIO())


class AgentPresenceSwitchTest(TestCase):
    def setUp(self):
        from tracker.services.agent_presence_switch import clear_cache
        clear_cache()
        self.org = Organization.objects.create(name='MavOps', slug='mavops', plan='professional')
        self.other = Organization.objects.create(name='Other', slug='other', plan='professional')
        self.user = User.objects.create_user('amy', email='amy@mavops.ai', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='member')
        self.dev = AgentDevice.objects.create(
            user=self.user, device_id='d1', hostname='AMY-PC', api_key='k-switch', is_active=True)

    def control(self):
        from tracker.services.agent_presence_switch import clear_cache
        clear_cache()
        c = APIClient()
        c.credentials(HTTP_X_AGENT_KEY='k-switch')
        r = c.get('/api/agent/control/?host=AMY-PC')
        self.assertEqual(r.status_code, 200)
        return r.data['agent_presence']

    def switch(self, *args):
        from io import StringIO
        from django.core.management import call_command
        call_command('agent_presence_switch', *args, stdout=StringIO())

    def test_default_on(self):
        self.assertTrue(self.control())

    def test_precedence_device_then_firm_then_everyone(self):
        self.switch('off', '--all')
        self.assertFalse(self.control())
        self.switch('on', '--org', str(self.org.pk))
        self.assertTrue(self.control())                  # firm beats everyone
        self.switch('off', '--device', 'AMY-PC')
        self.assertFalse(self.control())                 # device beats firm
        self.switch('clear', '--device', str(self.dev.pk))
        self.assertTrue(self.control())
        self.switch('off', '--org', str(self.other.pk))  # someone else's firm
        self.switch('clear', '--org', str(self.org.pk))
        self.assertFalse(self.control())                 # back to everyone=off

    def test_env_var_beats_everything(self):
        import os
        from unittest import mock
        self.switch('on', '--device', 'AMY-PC')
        with mock.patch.dict(os.environ, {'AGENT_PRESENCE_DISABLED': '1'}):
            self.assertFalse(self.control())

    def test_broken_table_defaults_on(self):
        from unittest import mock
        with mock.patch('tracker.services.agent_presence_switch._rows', side_effect=RuntimeError('no table')):
            self.assertTrue(self.control())


class MavOpsAgentPresenceTest(TestCase):
    def setUp(self):
        from tracker.services.agent_presence_switch import clear_cache
        clear_cache()
        self.org = Organization.objects.create(name='MavOps', slug='mavops', plan='professional')
        self.staff = User.objects.create_user('ops', email='ops@mavops.ai', password='x', is_staff=True)
        self.member = User.objects.create_user('amy', email='amy@mavops.ai', password='x')
        OrganizationMembership.objects.create(user=self.member, organization=self.org, role='owner')
        self.dev = AgentDevice.objects.create(
            user=self.member, device_id='d1', hostname='AMY-PC', api_key='k-mv', is_active=True)

    def client_for(self, user):
        c = APIClient()
        tok = AuthToken.objects.create(user=user, token=f't-{user.username}',
                                       expires_at=timezone.now() + timezone.timedelta(days=1))
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok.token}')
        return c

    def test_staff_only(self):
        c = self.client_for(self.member)   # a firm OWNER is still not MavOps staff
        self.assertEqual(c.get('/api/mavops/agent-presence/switch/').status_code, 403)
        self.assertEqual(c.post('/api/mavops/agent-presence/switch/',
                                {'action': 'off', 'scope': 'all'}, format='json').status_code, 403)
        self.assertEqual(c.get('/api/mavops/agent-presence/summary/').status_code, 403)

    def test_switch_round_trip_reaches_agents(self):
        c = self.client_for(self.staff)
        r = c.get('/api/mavops/agent-presence/switch/')
        self.assertEqual((r.data['rows'], r.data['everyone_enabled']), ([], True))

        r = c.post('/api/mavops/agent-presence/switch/',
                   {'action': 'off', 'scope': 'device', 'device_pk': self.dev.pk, 'note': 'cpu'},
                   format='json')
        [row] = r.data['rows']
        self.assertEqual((row['scope'], row['enabled'], row['note']), ('device', False, 'cpu'))
        self.assertIn('AMY-PC', row['device_label'])

        agent = APIClient()
        agent.credentials(HTTP_X_AGENT_KEY='k-mv')
        self.assertFalse(agent.get('/api/agent/control/?host=AMY-PC').data['agent_presence'])

        c.post('/api/mavops/agent-presence/switch/',
               {'action': 'clear', 'scope': 'device', 'device_pk': self.dev.pk}, format='json')
        self.assertTrue(agent.get('/api/agent/control/?host=AMY-PC').data['agent_presence'])

    def test_bad_input(self):
        c = self.client_for(self.staff)
        self.assertEqual(c.post('/api/mavops/agent-presence/switch/',
                                {'action': 'off', 'scope': 'org', 'org_id': 'x'}, format='json').status_code, 400)
        self.assertEqual(c.post('/api/mavops/agent-presence/switch/',
                                {'action': 'off', 'scope': 'org', 'org_id': 999999}, format='json').status_code, 404)
        self.assertEqual(c.post('/api/mavops/agent-presence/switch/',
                                {'action': 'nuke', 'scope': 'all'}, format='json').status_code, 400)

    def test_summary(self):
        r = self.client_for(self.staff).get('/api/mavops/agent-presence/summary/?days=7')
        self.assertEqual(r.status_code, 200)
        self.assertIn('fleet', r.data)


class AIAgentReportTest(TestCase):
    def setUp(self):
        from tracker.models import AgentPresenceSample
        self.org = Organization.objects.create(name='More Than Cars', slug='mtc', plan='professional')
        self.owner = User.objects.create_user('own', email='own@mtc.com', password='x')
        self.manager = User.objects.create_user('mgr', email='mgr@mtc.com', password='x')
        self.jordan = User.objects.create_user('jordan', email='jordan@mtc.com', password='x',
                                               first_name='Jordan', last_name='Lee')
        for u, role in ((self.owner, 'owner'), (self.manager, 'manager'), (self.jordan, 'member')):
            OrganizationMembership.objects.create(user=u, organization=self.org, role=role)
        dev = AgentDevice.objects.create(user=self.jordan, device_id='j1', api_key='k-j', is_active=True)
        hour = (timezone.now() - timezone.timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
        mk = lambda **kw: AgentPresenceSample.objects.create(
            org=self.org, user=self.jordan, device=dev, input_monitor='ok', **kw)
        # Mac hour: agent working while nobody touched the Mac
        self.mac = mk(bucket_start=hour, unattended_active_seconds=1800,
                      unattended_active_by_app={'excel': 1500, 'chrome': 300},
                      unattended_by_cause={'agent_busy': 900, 'unexplained': 300, 'remote_control': 600},
                      processes={'power_automate': {'seen_min': 60, 'busy_min': 40, 'cpu_s': 90},
                                 'claude_desktop': {'seen_min': 60, 'busy_min': 60, 'cpu_s': 300},
                                 'remote_teamviewer': {'seen_min': 60, 'busy_min': 0, 'cpu_s': 0}})
        # Windows hour: simulated clicks
        self.win = mk(bucket_start=hour - timezone.timedelta(hours=1), clicks_synthetic=25,
                      synthetic_by={'excel': 25}, processes={})
        # Remote session hour: never listed, whatever the clicks
        mk(bucket_start=hour - timezone.timedelta(hours=2), clicks_synthetic=99, remote_session=True)
        # Small Mac hour: under the 5-minute bar
        mk(bucket_start=hour - timezone.timedelta(hours=3), unattended_by_cause={'unexplained': 120})

    def as_user(self, user):
        c = APIClient()
        tok = AuthToken.objects.create(user=user, token=f'r-{user.username}',
                                       expires_at=timezone.now() + timezone.timedelta(days=1))
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok.token}')
        return c

    def enable(self):
        from tracker.services.ai_agent_report import set_report_enabled
        set_report_enabled(self.org.pk, True)

    def test_hidden_until_enabled(self):
        c = self.as_user(self.owner)
        self.assertEqual(c.get('/api/reports/ai-agents/').status_code, 404)
        self.assertFalse(c.get('/api/reports/ai-agents/status/').data['available'])
        self.enable()
        self.assertTrue(c.get('/api/reports/ai-agents/status/').data['available'])

    def test_owners_only(self):
        self.enable()
        for u in (self.manager, self.jordan):
            c = self.as_user(u)
            self.assertEqual(c.get('/api/reports/ai-agents/').status_code, 403)
            self.assertFalse(c.get('/api/reports/ai-agents/status/').data['available'])
            self.assertEqual(c.post('/api/reports/ai-agents/review/',
                                    {'sample_id': self.mac.pk, 'verdict': 'human'},
                                    format='json').status_code, 403)

    def test_report_content(self):
        self.enable()
        r = self.as_user(self.owner).get('/api/reports/ai-agents/?days=7').data
        self.assertEqual([x['sample_id'] for x in r['review']], [self.mac.pk, self.win.pk])
        mac, win = r['review']
        self.assertEqual((mac['minutes'], mac['app'], mac['person']), (20, 'excel', 'Jordan Lee'))
        self.assertEqual(mac['evidence'], 'Power Automate was working')
        self.assertEqual((win['clicks'], win['app']), (25, 'excel'))
        tools = {t['tool']: t for t in r['tools']}
        self.assertEqual(tools['power_automate']['working_hours'], 0.7)
        self.assertIsNone(tools['claude_desktop']['working_hours'])   # open, not evidence
        self.assertNotIn('remote_teamviewer', tools)                  # a person's tool, not an agent
        self.assertEqual(r['tiles']['to_review'], 2)
        self.assertEqual(r['explained_hours'], 0.2)
        self.assertEqual((r['tiles']['people_using'], r['tiles']['people_total']), (1, 3))

    def test_review_is_record_only(self):
        from tracker.models import Block
        self.enable()
        c = self.as_user(self.owner)
        blocks_before = Block.objects.count()
        r = c.post('/api/reports/ai-agents/review/', {'sample_id': self.mac.pk, 'verdict': 'agent'},
                   format='json')
        self.assertEqual(r.data['verdict'], 'agent')
        rep = c.get('/api/reports/ai-agents/').data
        self.assertEqual(rep['tiles']['to_review'], 1)
        self.assertEqual(rep['review'][0]['verdict'], 'agent')
        self.assertEqual(Block.objects.count(), blocks_before)
        c.post('/api/reports/ai-agents/review/', {'sample_id': self.mac.pk, 'verdict': 'clear'},
               format='json')
        self.assertEqual(c.get('/api/reports/ai-agents/').data['tiles']['to_review'], 2)

    def test_cannot_review_another_firms_sample(self):
        self.enable()
        other = Organization.objects.create(name='Other', slug='o', plan='professional')
        boss = User.objects.create_user('boss', email='b@o.com', password='x')
        OrganizationMembership.objects.create(user=boss, organization=other, role='owner')
        from tracker.services.ai_agent_report import set_report_enabled
        set_report_enabled(other.pk, True)
        r = self.as_user(boss).post('/api/reports/ai-agents/review/',
                                    {'sample_id': self.mac.pk, 'verdict': 'human'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_mavops_flag_endpoint(self):
        staff = User.objects.create_user('ops', email='ops@mavops.ai', password='x', is_staff=True)
        c = self.as_user(staff)
        self.assertEqual(c.get('/api/mavops/ai-agent-report/').data['orgs'], [])
        r = c.post('/api/mavops/ai-agent-report/', {'org_id': self.org.pk, 'enabled': True}, format='json')
        self.assertEqual(r.data['orgs'], [{'id': self.org.pk, 'name': 'More Than Cars'}])
        self.assertEqual(self.as_user(self.owner).get('/api/mavops/ai-agent-report/').status_code, 403)
