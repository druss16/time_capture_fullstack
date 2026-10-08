"""
Asana onboarding: the link report, one choice per client name, Asana's own
team / Client field, and a first sync that survives being killed.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.asana_onboarding_test --noinput < /dev/null
"""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from tracker.asana_integration_test import FakeApi, FakeRedis
from tracker.integrations.asana import sync as s
from tracker.models import Client, Integration, Project
from tracker.models_asana import AsanaNameMap, AsanaProjectLink
from tracker.models_task_type_sets import ExternalStaffMapping
from tracker.tests_onboarding_console import ConsoleBase


class Base(ConsoleBase):
    def setUp(self):
        super().setUp()
        self.p = self.make_project()
        self.org = self.p.organization
        self.integ = Integration.objects.create(organization=self.org, provider='asana',
                                                is_connected=True, tenant_id='ws1')
        self.denooyer = Client.objects.create(org=self.org, name='Robert DeNooyer Chevrolet')
        self.tgc = Client.objects.create(org=self.org, name='Tom Gill Chevrolet')
        self.tgb = Client.objects.create(org=self.org, name='Tom Gill Buick GMC')
        self.emblem = Project.objects.create(org=self.org, client=self.denooyer, name='Robert DeNooyer Logo Emblem')

    def link(self, name, **kw):
        return AsanaProjectLink.objects.create(integration=self.integ, asana_gid=name[:60], asana_name=name, **kw)


class OneChoiceTests(Base):
    def test_report_groups_unmatched_by_client_name(self):
        for n in ('DeNooyer: Used Car Sticker', 'DeNooyer: May Banner', 'Tom Gill: Mirror Hang Tag'):
            self.link(n)
        s.relink(self.integ)
        r = self.api.get(f'/api/onboard/projects/{self.p.id}/asana-links/').json()
        g = {x['label']: x for x in r['groups']}
        self.assertEqual(g['DeNooyer']['count'], 2)
        self.assertEqual(g['Tom Gill']['count'], 1)
        self.assertIn('Robert DeNooyer Chevrolet', [c['name'] for c in g['DeNooyer']['suggestions']])

    def test_one_choice_relinks_the_whole_group_and_finds_projects(self):
        a = self.link('DeNooyer: Used Car Sticker')
        b = self.link('DeNooyer: Logo Emblem')
        r = self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                          {'prefix': 'DeNooyer', 'client_id': self.denooyer.id}, format='json').json()
        self.assertEqual(r['changed'], 2)
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.client_id, a.project_id, a.link_source), (self.denooyer.id, None, 'client'))
        self.assertEqual((b.project_id, b.link_source), (self.emblem.id, 'name'))
        # Not a classifier alias.
        self.denooyer.refresh_from_db()
        self.assertNotIn('denooyer', [x.lower() for x in (self.denooyer.aliases or [])])

    def test_ambiguous_name_decided_once(self):
        t = self.link('Tom Gill: Mirror Hang Tag')
        self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                      {'prefix': 'Tom Gill', 'client_id': self.tgb.id}, format='json')
        t.refresh_from_db()
        self.assertEqual(t.client_id, self.tgb.id)

    def test_not_a_client_and_undo(self):
        x = self.link('ASOTU CON: Slides')
        self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                      {'prefix': 'ASOTU CON', 'ignore': True}, format='json')
        x.refresh_from_db()
        self.assertEqual(x.link_source, 'ignored')
        r = self.api.get(f'/api/onboard/projects/{self.p.id}/asana-links/').json()
        self.assertEqual(r['ignored'], 1)
        self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                      {'prefix': 'ASOTU CON', 'clear': True}, format='json')
        x.refresh_from_db()
        self.assertEqual(x.link_source, '')
        self.assertFalse(AsanaNameMap.objects.exists())

    def test_a_choice_survives_the_next_sync(self):
        self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                      {'prefix': 'DeNooyer', 'client_id': self.denooyer.id}, format='json')
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            s._sync_projects(self.integ, FakeApi({'projects': [{'gid': 'g1', 'name': 'DeNooyer: New Thing'}]}),
                             'ws1', {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0})
        self.assertEqual(AsanaProjectLink.objects.get(asana_gid='g1').client_id, self.denooyer.id)

    def test_only_operators(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(f'/api/onboard/projects/{self.p.id}/asana-links/').status_code,
                      (401, 403))

    def test_playbook_step_reports_progress(self):
        from tracker.onboarding_playbook import evaluate
        self.link('DeNooyer: Used Car Sticker')
        s.relink(self.integ)
        steps = {st['key']: st for ph in evaluate(self.p)['phases'] for st in ph['steps']}
        self.assertIn('asana_linked', steps)
        self.assertIn('unmatched', steps['asana_linked']['detail'])


class AsanaSaysTests(Base):
    def test_team_and_client_field_name_the_client(self):
        rows = [
            {'gid': 'g1', 'name': 'October Offers', 'team': {'name': 'Tom Gill Buick GMC'}},
            {'gid': 'g2', 'name': 'Hang Tags', 'custom_fields': [
                {'name': 'Client', 'display_value': 'Tom Gill Chevrolet'}]},
        ]
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            s._sync_projects(self.integ, FakeApi({'projects': rows}), 'ws1',
                             {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0})
        got = dict(AsanaProjectLink.objects.values_list('asana_gid', 'client_id'))
        self.assertEqual(got, {'g1': self.tgb.id, 'g2': self.tgc.id})

    def test_without_team_scope_names_still_link(self):
        from tracker.integrations.asana.client import AsanaNotAvailable
        calls = []

        class Api(FakeApi):
            def paginated(self, path, **params):
                calls.append(params.get('opt_fields'))
                if 'team.name' in (params.get('opt_fields') or ''):
                    raise AsanaNotAvailable('403')
                return iter([{'gid': 'g1', 'name': 'Robert DeNooyer: Logo Emblem'}])
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            s._sync_projects(self.integ, Api({}), 'ws1', {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0})
        self.assertEqual(len(calls), 2)
        self.assertEqual(AsanaProjectLink.objects.get().project_id, self.emblem.id)


class ResumableSyncTests(Base):
    def test_activity_is_time_boxed_and_resumes_oldest_first(self):
        for i in range(5):
            self.link(f'DeNooyer: P{i}', client=self.denooyer)
        ExternalStaffMapping.objects.create(integration=self.integ, external_id='u1', user=self.operator)
        fake = FakeRedis()
        ticks = iter([0, 0, 0, 0, 1000, 1000, 1000, 1000, 1000, 1000, 1000])
        with mock.patch.object(s, '_redis', return_value=fake), \
                mock.patch('time.monotonic', side_effect=lambda: next(ticks)):
            first = s.sync_activity(self.integ, api=FakeApi({'tasks': []}), budget=10)
        self.assertGreater(first['remaining'], 0)
        self.assertTrue(fake.get(f'asana:backlog:{self.integ.id}'))
        with mock.patch.object(s, '_redis', return_value=fake):
            second = s.sync_activity(self.integ, api=FakeApi({'tasks': []}), budget=None)
        self.assertEqual(second['remaining'], 0)
        self.assertEqual(second['projects'], 5)        # oldest first: the unread ones led
        self.assertIsNone(fake.get(f'asana:backlog:{self.integ.id}'))

    def test_a_sync_that_died_runs_again_on_the_next_tick(self):
        self.integ.last_sync_status = 'running'
        self.integ.last_synced_at = timezone.now()
        self.integ.save()
        with mock.patch.object(s, '_redis', return_value=FakeRedis()), \
                mock.patch.object(s, 'full_sync', return_value={'ok': 1}) as full:
            s.run_sync(self.integ.id)
        full.assert_called_once()

    def test_progress_shown_while_syncing(self):
        fake = FakeRedis()
        with mock.patch.object(s, '_redis', return_value=fake):
            s._try_lock(self.integ.id, 'full')
            s._progress(self.integ.id, 'activity', 120, 379)
            st = s.sync_state(self.integ)
        self.assertEqual(st['progress'], {'phase': 'activity', 'done': 120, 'total': 379})
