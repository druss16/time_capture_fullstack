"""
One pick per deliverable folder, for the whole team.

Real database for the TestCase classes: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.folder_learning_test --noinput < /dev/null

What is pinned:
  - the folder key is the same on every machine (home directory and sync root
    dropped), and a deliverable's subfolders roll up into the deliverable
  - a person's pick files the rest of that folder at once — anyone's, same
    client — and never spreads into a folder already split between projects
  - the sweep then files later work in that folder for everyone else
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from tracker.models import Block, Client, Organization, OrganizationMembership, Project
from tracker.services.matter_attribution import attribute_matters_for_org, folder_key

User = get_user_model()
T0 = datetime(2026, 9, 21, 14, 0, tzinfo=dt_timezone.utc)
DELIV = 'Client-Work_2026/0074_Easterns-Auto-Group/0074_2026-08_Easterns-Auto_Konetiq-Launch-Ads'


class FolderKeyTests(SimpleTestCase):
    def test_same_folder_on_every_machine(self):
        keys = {
            folder_key(f'/Users/alannah/Dropbox/{DELIV}/a.psd'),
            folder_key(f'/Users/bob/Library/CloudStorage/Dropbox-MoreThanCars/{DELIV}/b.psd'),
            folder_key(f'C:\\Users\\bob\\Dropbox (More Than Cars)\\{DELIV.replace("/", chr(92))}\\c.psd'),
        }
        self.assertEqual(len(keys), 1)
        self.assertNotIn('alannah', keys.pop())

    def test_subfolders_roll_up_into_the_deliverable(self):
        self.assertEqual(folder_key(f'/Users/a/Dropbox/{DELIV}/Exports/Final/x.png'),
                         folder_key(f'/Users/a/Dropbox/{DELIV}/y.psd'))

    def test_deepest_convention_folder_wins(self):
        # A top folder that merely looks like a convention must not swallow every project.
        a = folder_key('/Users/a/Dropbox/Clients_All_2026/0074_2026-08_Easterns-Auto_Ads/x.psd')
        b = folder_key('/Users/a/Dropbox/Clients_All_2026/0074_2026-09_Easterns-Auto_Flyer/x.psd')
        self.assertNotEqual(a, b)

    def test_sync_root_itself_has_no_key(self):
        self.assertEqual(folder_key('/Users/a/Dropbox/loose.psd'), '')

    def test_project_named_like_a_sync_client_is_kept(self):
        k = folder_key('/Users/a/Dropbox/Clients/Acme/Dropbox Ads Campaign/x.psd')
        self.assertIn('dropbox ads campaign', k)

    def test_law_firm_paths_unchanged(self):
        self.assertEqual(folder_key(r'S:\Clients\Ridgeline\Estate Planning\motion.docx'),
                         's clients ridgeline estate planning')


class SiblingFilingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-fl', industry_type='marketing')
        self.alannah = User.objects.create_user('alannah', email='a@mtc.test', password='x')
        self.bob = User.objects.create_user('bob', email='b@mtc.test', password='x')
        for u in (self.alannah, self.bob):
            OrganizationMembership.objects.create(user=u, organization=self.org, role='member')
        self.easterns = Client.objects.create(org=self.org, name='Easterns Automotive Group')
        self.tomgill = Client.objects.create(org=self.org, name='Tom Gill Chevrolet')
        self.konetiq = Project.objects.create(org=self.org, client=self.easterns, name='Easterns KONETIQ Campaigns')
        self.social = Project.objects.create(org=self.org, client=self.easterns, name='Easterns CDJR Social Ads')
        self.api = APIClient()
        self.api.force_authenticate(self.alannah)
        self._n = 0

    def block(self, user, path, client=None, project=None, days_ago=0):
        self._n += 1
        s = T0 - timedelta(days=days_ago) + timedelta(minutes=30 * self._n)
        return Block.objects.create(
            org=self.org, user=user, hostname='mac', device_id=f'd{user.id}', start=s,
            end=s + timedelta(minutes=20), minutes=20, app_name='Adobe Photoshop',
            window_title=path.rsplit('/', 1)[-1], title=path.rsplit('/', 1)[-1], file_path=path,
            classification_state='committed', is_categorized=True, is_billable=True,
            client=client or self.easterns, project=project, categorized_by='ai',
            category_hours={'Design': 0.3})

    def pick(self, block, project):
        return self.api.post(f'/api/blocks/{block.id}/set-matter/', {'project_id': project.id}, format='json')

    def test_one_pick_files_the_deliverable_for_the_whole_team(self):
        mine = self.block(self.alannah, f'/Users/alannah/Dropbox/{DELIV}/hero.psd')
        older = self.block(self.alannah, f'/Users/alannah/Dropbox/{DELIV}/Links/bg.psd', days_ago=9)
        bobs = self.block(self.bob, f'C:/Users/bob/Dropbox (More Than Cars)/{DELIV}/Exports/hero.png', days_ago=4)
        other_folder = self.block(self.alannah, f'/Users/alannah/Dropbox/{DELIV}-v2/x.psd')
        other_client = self.block(self.alannah, f'/Users/alannah/Dropbox/{DELIV}/stray.psd', client=self.tomgill)
        r = self.pick(mine, self.konetiq)
        self.assertEqual((r.status_code, r.data['folder_filed']), (200, 2))
        for b in (older, bobs, other_folder, other_client):
            b.refresh_from_db()
        self.assertEqual((older.project_id, bobs.project_id), (self.konetiq.id, self.konetiq.id))
        self.assertIsNone(other_folder.project_id)
        self.assertIsNone(other_client.project_id)

    def test_a_split_folder_is_not_spread(self):
        self.block(self.bob, f'/Users/bob/Dropbox/{DELIV}/a.psd', project=self.social)
        mine = self.block(self.alannah, f'/Users/alannah/Dropbox/{DELIV}/b.psd')
        waiting = self.block(self.alannah, f'/Users/alannah/Dropbox/{DELIV}/c.psd')
        r = self.pick(mine, self.konetiq)
        self.assertEqual(r.data['folder_filed'], 0)
        waiting.refresh_from_db()
        self.assertIsNone(waiting.project_id)

    def test_sweep_files_a_teammates_later_work_in_that_folder(self):
        mine = self.block(self.alannah, f'/Users/alannah/Dropbox/{DELIV}/hero.psd', days_ago=1)
        self.pick(mine, self.konetiq)
        later = self.block(self.bob, f'C:/Users/bob/Dropbox/{DELIV}/Exports/banner.png')
        stats = attribute_matters_for_org(self.org, days=3650)
        later.refresh_from_db()
        self.assertEqual(later.project_id, self.konetiq.id)
        self.assertEqual(stats['by_folder'], 1)
