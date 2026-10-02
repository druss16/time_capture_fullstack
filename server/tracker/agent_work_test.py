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
        call_command('agent_presence_summary', '--days', '1', stdout=StringIO())
