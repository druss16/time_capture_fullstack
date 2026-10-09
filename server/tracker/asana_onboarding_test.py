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


class SpeedTests(Base):
    def test_unchanged_projects_are_not_rewritten_and_archived_are_not_rematched(self):
        rows = [{'gid': 'g1', 'name': 'DeNooyer: Logo Emblem'},
                {'gid': 'g2', 'name': 'Old Thing', 'archived': True}]
        stats = lambda: {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0}
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            s._sync_projects(self.integ, FakeApi({'projects': rows}), 'ws1', stats())
        stamp = AsanaProjectLink.objects.get(asana_gid='g1').updated_at
        with mock.patch.object(s, '_redis', return_value=FakeRedis()), \
                mock.patch.object(s, '_apply', wraps=s._apply) as applied:
            s._sync_projects(self.integ, FakeApi({'projects': rows}), 'ws1', stats())
        self.assertEqual(AsanaProjectLink.objects.get(asana_gid='g1').updated_at, stamp)   # not rewritten
        self.assertIsNotNone(AsanaProjectLink.objects.get(asana_gid='g1').last_seen_in_source)
        self.assertEqual(applied.call_count, 2)       # called, but the archived one returns at once


class QbtFieldTests(Base):
    """A "QB Time Project" custom field in Asana is the shared key: names are
    typed twice by hand and drift; the field makes the link exact."""
    def setUp(self):
        super().setUp()
        from tracker.models_task_type_sets import ExternalMatterMapping
        qbt = Integration.objects.create(organization=self.org, provider='qb_time', is_connected=True)
        self.deal = Project.objects.create(org=self.org, client=self.tgb, name='Tom Gill Buick GMC Showroom Deal Maker')
        ExternalMatterMapping.objects.create(integration=qbt, project=self.deal, external_id='8812345')

    def sync(self, *rows):
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            s._sync_projects(self.integ, FakeApi({'projects': list(rows)}), 'ws1',
                             {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0})
        return {l.asana_gid: (l.project_id, l.client_id, l.link_source) for l in AsanaProjectLink.objects.all()}

    def field(self, name, value):
        return [{'name': name, 'display_value': value}]

    def test_qbt_id_links_exactly_whatever_the_name_says(self):
        got = self.sync({'gid': 'g1', 'name': 'Totally different name',
                         'custom_fields': self.field('QB Time Project', '8812345')})
        self.assertEqual(got['g1'], (self.deal.id, self.tgb.id, 'field'))

    def test_qbt_name_and_field_name_variants(self):
        got = self.sync({'gid': 'g1', 'name': 'x', 'custom_fields': self.field('QBT Project', 'Robert DeNooyer Logo Emblem')},
                        {'gid': 'g2', 'name': 'y', 'custom_fields': self.field('QuickBooks-Time Project',
                                                                            'Tom Gill Buick GMC Showroom Dealmaker')})
        self.assertEqual(got['g1'][0], self.emblem.id)
        self.assertEqual(got['g2'][0], self.deal.id)       # close match, still exact enough

    def test_field_naming_nothing_falls_back_to_the_name(self):
        got = self.sync({'gid': 'g1', 'name': 'Robert DeNooyer: Logo Emblem',
                         'custom_fields': self.field('QB Time Project', 'no such thing 999')})
        self.assertEqual(got['g1'][:2], (self.emblem.id, self.denooyer.id))
        self.assertEqual(got['g1'][2], 'name')

    def test_hand_link_still_wins(self):
        AsanaProjectLink.objects.create(integration=self.integ, asana_gid='g1', asana_name='x',
                                        project=self.emblem, link_source='manual')
        got = self.sync({'gid': 'g1', 'name': 'x', 'custom_fields': self.field('QB Time Project', '8812345')})
        self.assertEqual(got['g1'][0], self.emblem.id)


class HeartbeatTests(Base):
    def test_lock_is_short_and_renewed_while_running(self):
        import time
        renewed = []

        class R(FakeRedis):
            def expire(self, key, ttl):
                renewed.append((key, ttl))
        fake = R()
        with mock.patch.object(s, '_redis', return_value=fake):
            with s._Heartbeat(self.integ.id, interval=0.05):
                time.sleep(0.2)
        self.assertLessEqual(s.LOCK_TTL, 5 * 60)
        self.assertIn((f'asana:sync-lock:{self.integ.id}', s.LOCK_TTL), renewed)

    def test_heartbeat_stops_with_the_sync(self):
        import time
        calls = []

        class R(FakeRedis):
            def expire(self, key, ttl):
                calls.append(key)
        with mock.patch.object(s, '_redis', return_value=R()):
            with s._Heartbeat(self.integ.id, interval=0.05):
                time.sleep(0.12)
            n = len(calls)
            time.sleep(0.2)
        self.assertEqual(len(calls), n)


class ProjectPickTests(Base):
    def setUp(self):
        super().setUp()
        self.eastern = Client.objects.create(org=self.org, name='Easterns Automotive Group')
        self.white = Project.objects.create(org=self.org, client=self.eastern,
                                            name='Easterns Nissan White Marsh Website Updates')
        self.bm = Client.objects.create(org=self.org, name='Beaver Mazda')
        self.logo = Project.objects.create(org=self.org, client=self.bm, name='Beaver Mazda CX5 Event Logo')
        self.refresh = Project.objects.create(org=self.org, client=self.tgb, name='Tom Gill Buick GMC Website Refresh')

    def sync(self, *names):
        rows = [{'gid': f'g{i}', 'name': n} for i, n in enumerate(names)]
        with mock.patch.object(s, '_redis', return_value=FakeRedis()):
            s._sync_projects(self.integ, FakeApi({'projects': rows}), 'ws1',
                             {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0})
        return {l.asana_name: l for l in AsanaProjectLink.objects.all()}

    def test_client_words_set_aside_on_both_sides(self):
        got = self.sync('Easterns Auto Group: Nissan of White Marsh Website Update')
        self.assertEqual(got['Easterns Auto Group: Nissan of White Marsh Website Update'].project_id, self.white.id)

    def test_a_different_deliverable_is_not_linked(self):
        got = self.sync('Beaver Mazda: CX5 Event Email')
        link = got['Beaver Mazda: CX5 Event Email']
        self.assertEqual((link.project_id, link.client_id), (None, self.bm.id))

    def test_report_suggests_and_one_click_accept_sticks(self):
        self.sync('Beaver Mazda: CX5 Event Email', 'Tom Gill Buick GMC: Website Changes')
        url = f'/api/onboard/projects/{self.p.id}/asana-links/'
        r = self.api.get(url).json()
        picks = {x['asana_name']: x for x in r['project_picks']}
        self.assertEqual(picks['Tom Gill Buick GMC: Website Changes']['candidates'][0]['project_id'],
                         self.refresh.id)
        gid = picks['Tom Gill Buick GMC: Website Changes']['asana_gid']
        r = self.api.post(url, {'accept': gid, 'project_id': self.refresh.id}, format='json').json()
        self.assertNotIn('Tom Gill Buick GMC: Website Changes', [x['asana_name'] for x in r['project_picks']])
        link = AsanaProjectLink.objects.get(asana_gid=gid)
        self.assertEqual((link.project_id, link.link_source), (self.refresh.id, 'manual'))
        # A later sync keeps it.
        self.sync('Beaver Mazda: CX5 Event Email', 'Tom Gill Buick GMC: Website Changes')
        link.refresh_from_db()
        self.assertEqual(link.project_id, self.refresh.id)

    def test_accept_refuses_another_firms_project(self):
        from tracker.models import Organization
        other = Organization.objects.create(name='Other', slug='other-firm')
        foreign = Project.objects.create(org=other, name='Theirs',
                                         client=Client.objects.create(org=other, name='Their Client'))
        self.sync('Beaver Mazda: CX5 Event Email')
        gid = AsanaProjectLink.objects.get().asana_gid
        r = self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                          {'accept': gid, 'project_id': foreign.id}, format='json')
        self.assertEqual(r.status_code, 400)


class CarryToActivityTests(ProjectPickTests):
    def test_accepting_a_pick_moves_activity_already_read(self):
        from tracker.models_asana import AsanaActivity
        self.sync('Tom Gill Buick GMC: Website Changes')
        link = AsanaProjectLink.objects.get()
        act = AsanaActivity.objects.create(integration=self.integ, story_gid='s1', user=self.operator,
                                           at=timezone.now(), asana_project_gid=link.asana_gid,
                                           client=self.tgb, kind='comment_added')
        self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                      {'accept': link.asana_gid, 'project_id': self.refresh.id}, format='json')
        act.refresh_from_db()
        self.assertEqual((act.project_id, act.client_id), (self.refresh.id, self.tgb.id))

    def test_a_group_choice_moves_activity_too(self):
        from tracker.models_asana import AsanaActivity
        link = AsanaProjectLink.objects.create(integration=self.integ, asana_gid='gx',
                                               asana_name='DeNooyer: Used Car Sticker')
        act = AsanaActivity.objects.create(integration=self.integ, story_gid='s2', user=self.operator,
                                           at=timezone.now(), asana_project_gid='gx', kind='comment_added')
        self.api.post(f'/api/onboard/projects/{self.p.id}/asana-links/',
                      {'prefix': 'DeNooyer', 'client_id': self.denooyer.id}, format='json')
        act.refresh_from_db()
        self.assertEqual(act.client_id, self.denooyer.id)


class PicksByActivityTests(ProjectPickTests):
    def test_busiest_first_and_no_match_still_listed(self):
        from tracker.models_asana import AsanaActivity
        self.sync('Tom Gill Buick GMC: Website Changes', 'Beaver Mazda: Totally Unrelated Thing')
        quiet = AsanaProjectLink.objects.get(asana_name='Tom Gill Buick GMC: Website Changes')
        busy = AsanaProjectLink.objects.get(asana_name='Beaver Mazda: Totally Unrelated Thing')
        for i in range(3):
            AsanaActivity.objects.create(integration=self.integ, story_gid=f'b{i}', user=self.operator,
                                         at=timezone.now(), asana_project_gid=busy.asana_gid,
                                         client=self.bm, kind='comment_added')
        r = self.api.get(f'/api/onboard/projects/{self.p.id}/asana-links/').json()
        names = [x['asana_name'] for x in r['project_picks']]
        self.assertEqual(names[0], busy.asana_name)              # 3 actions, no close match
        self.assertIn(quiet.asana_name, names)
        top = r['project_picks'][0]
        self.assertEqual(top['activity_7d'], 3)
        self.assertIn(self.logo.id, [o['id'] for o in top['others']])
        self.assertEqual(r['project_picks_activity_7d'], 3)
