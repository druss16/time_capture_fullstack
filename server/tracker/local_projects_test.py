"""
Client → Project for firms that keep their own projects (agencies).

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.local_projects_test --noinput < /dev/null

What is being pinned:
  - a marketing firm's own projects are selectable; a CPA firm's legacy
    "(General)" Project rows are not, so nothing changes for it
  - the attribution sweep files time by project name / sole project, and
    never lets a guess put one client's project on another client's block
  - Daily Review's queue, picker, inline create and client cards
  - CSV import matches clients by name and never invents one
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tracker.models import Block, Client, Organization, OrganizationMembership, Project
from tracker.services.matter_attribution import attribute_matters_for_org
from tracker.services.projects import org_uses_projects, selectable_projects

User = get_user_model()

DAY = date(2026, 9, 29)
T0 = datetime(2026, 9, 29, 14, 0, tzinfo=dt_timezone.utc)


class Base(TestCase):
    industry = 'marketing'

    def setUp(self):
        self.org = Organization.objects.create(
            name='MTC', slug=f'mtc-{self.industry}', industry_type=self.industry)
        self.user = User.objects.create_user('ae', email='ae@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.ford = Client.objects.create(org=self.org, name='Ford Dealers')
        self.chevy = Client.objects.create(org=self.org, name='Chevy')
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self._n = 0

    def block(self, client, title='Untitled', file_path='', **kw):
        self._n += 1
        start = T0 + timedelta(minutes=30 * self._n)
        defaults = dict(
            org=self.org, user=self.user, hostname='mac', device_id='d1',
            start=start, end=start + timedelta(minutes=20), minutes=20, day=DAY,
            app_name='Adobe Photoshop', window_title=title, title=title, file_path=file_path,
            classification_state='committed', is_categorized=True, is_billable=True,
            client=client, category_hours={'Design': 0.33},
        )
        defaults.update(kw)
        return Block.objects.create(**defaults)


class SelectionTests(Base):
    def test_marketing_projects_are_selectable(self):
        Project.objects.create(org=self.org, client=self.ford, name='Spring Launch')
        Project.objects.create(org=self.org, client=self.ford, name='Old', is_active=False)
        opts = selectable_projects(self.org)
        self.assertEqual([o.name for o in opts[self.ford.id]], ['Spring Launch'])
        self.assertTrue(org_uses_projects(self.org))

    def test_archived_current_project_stays_visible(self):
        old = Project.objects.create(org=self.org, client=self.ford, name='Old', is_active=False)
        opts = selectable_projects(self.org, include_ids=[old.id])
        self.assertEqual([o.project_id for o in opts[self.ford.id]], [old.id])


class CpaUnchangedTests(Base):
    industry = 'cpa'

    def test_legacy_project_rows_are_ignored(self):
        Project.objects.create(org=self.org, client=self.ford, name='(General)')
        self.assertEqual(selectable_projects(self.org), {})
        self.assertFalse(org_uses_projects(self.org))
        b = self.block(self.ford, title='(General) workpapers')
        stats = attribute_matters_for_org(self.org, days=3650)
        self.assertEqual(stats['scanned'], 0)
        b.refresh_from_db()
        self.assertIsNone(b.project_id)

    def test_queue_and_cards_unchanged(self):
        Project.objects.create(org=self.org, client=self.ford, name='(General)')
        self.block(self.ford)
        r = self.api.get('/api/blocks/needs-matter/', {'date': str(DAY)})
        self.assertEqual(r.data['blocks'], [])
        from tracker.services.billing_totals import compute_client_cards
        cards = compute_client_cards(self.org, T0 - timedelta(days=1), T0 + timedelta(days=1),
                                     user_id=self.user.id)
        self.assertNotIn('projects', cards[0])


class AttributionTests(Base):
    def setUp(self):
        super().setUp()
        self.spring = Project.objects.create(org=self.org, client=self.ford, name='Ford - Spring Launch')
        self.web = Project.objects.create(org=self.org, client=self.ford, name='Website Refresh')
        self.chevy_only = Project.objects.create(org=self.org, client=self.chevy, name='Truck Month')

    def test_name_and_sole_project(self):
        a = self.block(self.ford, title='Spring Launch storyboard.psd - Photoshop')
        b = self.block(self.chevy, title='random.psd')
        c = self.block(self.ford, title='untitled.psd')   # two Ford projects -> abstain
        stats = attribute_matters_for_org(self.org, days=3650)
        for x in (a, b, c):
            x.refresh_from_db()
        self.assertEqual(a.project_id, self.spring.id)
        self.assertEqual(b.project_id, self.chevy_only.id)
        self.assertIsNone(c.project_id)
        self.assertEqual(stats['by_name'], 1)
        self.assertEqual(stats['by_sole_matter'], 1)

    def test_learned_folder_never_crosses_clients(self):
        # A Ford folder learned from a filed block...
        self.block(self.ford, title='a.psd', file_path='/Dropbox/Shared/a.psd', project=self.web)
        # ...must not put a Chevy block in that folder onto Ford's project.
        x = self.block(self.chevy, title='b.psd', file_path='/Dropbox/Shared/b.psd')
        Project.objects.create(org=self.org, client=self.chevy, name='Second')  # no sole fallback
        stats = attribute_matters_for_org(self.org, days=3650)
        x.refresh_from_db()
        self.assertIsNone(x.project_id)
        self.assertEqual(stats['off_client'], 1)


class EndpointTests(Base):
    def test_queue_lists_unfiled_time_even_without_projects(self):
        b = self.block(self.ford)
        r = self.api.get('/api/blocks/needs-matter/', {'date': str(DAY)})
        self.assertTrue(r.data['can_create'])
        self.assertEqual([x['id'] for x in r.data['blocks']], [b.id])

    def test_queue_range_and_internal_client_excluded(self):
        # Every org is seeded with its own Internal client.
        internal = (Client.objects.filter(org=self.org, code='INTERNAL').first()
                    or Client.objects.create(org=self.org, name='Internal'))
        self.block(internal)
        # Block.save derives `day` from `start`, so move the time, not the label.
        b = self.block(self.ford, start=T0 - timedelta(days=2), end=T0 - timedelta(days=2) + timedelta(minutes=20))
        r = self.api.get('/api/blocks/needs-matter/', {'date': str(DAY)})
        self.assertEqual(r.data['blocks'], [])
        r = self.api.get('/api/blocks/needs-matter/',
                         {'start': str(DAY - timedelta(days=6)), 'end': str(DAY)})
        self.assertEqual([x['id'] for x in r.data['blocks']], [b.id])

    def test_create_inline_then_assign(self):
        b = self.block(self.ford)
        opts = self.api.get(f'/api/blocks/{b.id}/matter-options/').data
        self.assertTrue(opts['can_create'])
        self.assertEqual(opts['options'], [])
        r = self.api.post('/api/projects/create/', {'client_id': self.ford.id, 'name': 'Spring Launch'},
                          format='json')
        self.assertEqual(r.status_code, 201)
        pid = r.data['project']['id']
        # same name, other case -> the same project back, not a twin
        r2 = self.api.post('/api/projects/create/', {'client_id': self.ford.id, 'name': 'spring launch'},
                           format='json')
        self.assertEqual((r2.status_code, r2.data['project']['id']), (200, pid))
        r = self.api.post(f'/api/blocks/{b.id}/set-matter/', {'project_id': pid}, format='json')
        self.assertEqual(r.status_code, 200)
        opts = self.api.get(f'/api/blocks/{b.id}/matter-options/').data
        self.assertEqual([o['display_number'] for o in opts['options']], ['Spring Launch'])

    def test_client_cards_group_by_project(self):
        p = Project.objects.create(org=self.org, client=self.ford, name='Spring Launch')
        self.block(self.ford, title='brief.docx', project=p)
        self.block(self.ford, title='brief.docx')
        r = self.api.get('/api/today-time/', {'date': str(DAY)})
        self.assertEqual(r.status_code, 200)
        card = next(c for c in r.data['clients'] if c['client_id'] == self.ford.id)
        by = {x['project_id']: x for x in card['projects']}
        self.assertEqual(set(by), {p.id, None})
        acts = [a for cat in card['categories'] for a in cat['activities']]
        self.assertEqual({a['project_id'] for a in acts}, {p.id, None})
        self.assertEqual(len(acts), 2)  # same title, two projects -> two lines

    def test_whoami_flag(self):
        r = self.api.get('/api/whoami/')
        self.assertTrue(r.data.get('local_projects'))
        self.assertEqual(r.data['terminology']['project'], 'Project')

    def test_import(self):
        text = 'Client,Project\nford dealers,Spring Launch\nFord Dealers,Spring Launch\nNobody Inc,X\nChevy,Truck Month'
        r = self.api.post('/api/projects/import/', {'text': text, 'dry_run': True}, format='json')
        self.assertEqual(len(r.data['created']), 2)
        self.assertEqual(r.data['unmatched_clients'][0]['client'], 'Nobody Inc')
        self.assertEqual(Project.objects.filter(org=self.org).count(), 0)
        self.api.post('/api/projects/import/', {'text': text}, format='json')
        self.assertEqual(Project.objects.filter(org=self.org).count(), 2)
        r = self.api.post('/api/projects/import/', {'text': text}, format='json')
        self.assertEqual((len(r.data['created']), len(r.data['unchanged'])), (0, 2))
        self.assertFalse(Client.objects.filter(name='Nobody Inc').exists())

    def test_import_admin_only(self):
        m = OrganizationMembership.objects.get(user=self.user)
        m.role = 'member'
        m.save()
        r = self.api.post('/api/projects/import/', {'text': 'Chevy,X'}, format='json')
        self.assertEqual(r.status_code, 403)
