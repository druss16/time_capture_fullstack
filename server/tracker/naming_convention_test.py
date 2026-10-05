"""
Agency file-naming convention → client + project (CLIENTCODE_ClientName_Project_...).

Real database for the attribution cases: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.naming_convention_test --noinput < /dev/null
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from tracker.models import Block, Client, Organization, OrganizationMembership, Project
from tracker.services.matter_attribution import attribute_matters_for_org
from tracker.services.naming_convention import build_index, compact, resolve_text, tokens

User = get_user_model()
T0 = datetime(2026, 10, 1, 14, 0, tzinfo=dt_timezone.utc)

INDEX = build_index(
    clients=[(1, 'Acme Motors', 'ACM', []), (2, 'Bayside Auto Group', 'BAG', ['Bayside']),
             (3, 'Coastal Trucks', '', []), (4, 'Acme Holdings', 'ACM', [])],   # ACM shared by 1 and 4
    codes_extra=[(3, 'CST')],
    projects=[(11, 1, 'Spring Launch'), (12, 1, 'Website Refresh'), (13, 1, 'Social'),
              (21, 2, 'Website Refresh'), (31, 3, 'Truck Month')],
)


def r(text):
    return resolve_text([('title', text)], INDEX)


class ParseTests(SimpleTestCase):
    def test_compact(self):
        self.assertEqual(compact('Spring-Launch'), compact('spring launch'))
        self.assertEqual(compact('SpringLaunch'), 'springlaunch')

    def test_tokens(self):
        self.assertEqual(tokens('BAG_Bayside_WebsiteRefresh_sitemap.fig'),
                         [['BAG', 'Bayside', 'WebsiteRefresh', 'sitemap']])
        self.assertEqual(tokens('notes.docx'), [])
        self.assertEqual(tokens('a_b.psd'), [])        # two segments is not the convention

    def test_shared_code_falls_back_to_the_name(self):
        # ACM belongs to two clients, so it identifies neither; the name decides.
        self.assertEqual(r('ACM_AcmeMotors_SpringLaunch_v3.psd @ 66% (RGB/8)')[:2], (1, 11))

    def test_title_with_spaces_inside_names(self):
        self.assertEqual(r('BAG_Bayside Auto Group_Website Refresh_hero.ai')[:2], (2, 21))

    def test_project_is_scoped_to_the_named_client(self):
        # Both Acme and Bayside have a "Website Refresh" — the file's client decides.
        self.assertEqual(r('BAG_Bayside_Website-Refresh_x.psd')[:2], (2, 21))

    def test_integration_short_code(self):
        self.assertEqual(r('CST_Coastal_TruckMonth_spot30.mov')[:2], (3, 31))

    def test_split_project_name(self):
        self.assertEqual(r('CST_Coastal_Truck_Month_spot.mov')[:2], (3, 31))

    def test_unknown_project_still_names_the_client(self):
        self.assertEqual(r('BAG_Bayside_HolidaySale_banner.psd')[:2], (2, None))

    def test_code_and_name_disagree_abstains(self):
        self.assertIsNone(r('CST_Bayside_TruckMonth.psd'))

    def test_unknown_client_abstains(self):
        self.assertIsNone(r('XYZ_Nobody_Thing_v1.psd'))

    def test_two_fields_naming_different_clients_abstain(self):
        self.assertIsNone(resolve_text([('file_path', '/x/CST_Coastal_TruckMonth.mov'),
                                        ('title', 'BAG_Bayside_WebsiteRefresh.fig')], INDEX))


# More Than Cars' real Dropbox layout (photographed 2026-10-05): a client folder
# CODE_Name, and inside it one folder per deliverable CODE_date_ShortName_Deliverable.
# The client's QuickBooks Time projects are billing buckets, not deliverables.
MTC = build_index(
    clients=[(7, 'Easterns Automotive Group', 'EASTERNSAU', []),
             (8, 'Eastern Shore Dental', 'EASTERNSHO', []),
             (9, 'Tom Gill Chevrolet', 'TOMGILLCHE', [])],
    codes_extra=[],
    projects=[(71, 7, 'Easterns KONETIQ Campaigns'), (72, 7, 'Konetiq Launch Ads'),
              (91, 9, 'Truck Month')],
)
ROOT = '/Users/alannah/Library/CloudStorage/Dropbox-MoreThanCars/Congruent Team Folder 2018 +/_ServerRefresh_052021/Client-Work_2026'


def mtc(path):
    return resolve_text([('file_path', path)], MTC)


class DatedShortNameTests(SimpleTestCase):
    """CODE_2026-09_ShortName_Deliverable, with the code unknown to us."""

    def test_date_segment_is_skipped_and_short_name_names_the_client(self):
        p = f'{ROOT}/0074_Easterns-Auto-Group/0074_2026-09_Easterns-Auto_General-Collision-Center-Flyer-CDJR/hero.psd'
        self.assertEqual(mtc(p)[:2], (7, None))       # client yes; a deliverable is not a project

    def test_year_only_and_full_short_name(self):
        self.assertEqual(mtc(f'{ROOT}/0074_2026_Easterns-Auto_Monthly-Nissan-New-Cars-Offer-Email/a.html')[:2], (7, None))
        self.assertEqual(mtc(f'{ROOT}/0074_2026-01_Easterns-Auto-Group_VDP-Overlays/b.psd')[:2], (7, None))

    def test_deliverable_equal_to_a_project_files_it(self):
        self.assertEqual(mtc(f'{ROOT}/0074_2026-08_Easterns-Auto_Konetiq-Launch-Ads/c.psd')[:2], (7, 72))

    def test_client_folder_alone(self):
        self.assertEqual(mtc(f'{ROOT}/0074_Easterns-Auto-Group/contract.pdf')[:2], (7, None))
        self.assertEqual(mtc(f'{ROOT}/0019_Tom-Gill-Chevrolet/logo.ai')[:2], (9, None))

    def test_first_word_must_match_whole(self):
        # "Eastern" is not "Easterns": Eastern Shore Dental, never Easterns Automotive.
        self.assertEqual(mtc(f'{ROOT}/0031_2026-02_Eastern-Shore_Cleaning-Promo/x.psd')[:2], (8, None))

    def test_short_name_fitting_two_clients_abstains(self):
        idx = build_index([(7, 'Easterns Automotive Group', '', []), (10, 'Easterns Auto Body', '', [])], [], [])
        self.assertIsNone(resolve_text([('file_path', '/d/0074_2026-09_Easterns-Auto_Flyer/x.psd')], idx))

    def test_short_name_needs_a_client_number_in_front(self):
        # Without a code-shaped first segment, only an exact name counts.
        self.assertIsNone(mtc('/d/Notes_Easterns-Auto_Flyer/x.psd'))
        self.assertIsNone(mtc('/d/Report_Easterns-Auto.docx'))

    def test_two_part_names_need_more_than_one_word(self):
        self.assertIsNone(mtc('/d/0074_Easterns/x.psd'))
        self.assertIsNone(mtc('/d/12_Intro.mp4'))

    def test_dates_are_not_mistaken_for_client_numbers(self):
        self.assertIsNone(mtc('/d/2026_09_Recap/x.psd'))
        self.assertIsNone(mtc('/d/2026_Easterns-Auto_Flyer/x.psd'))   # a year is not a client number


class AttributionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-nc', industry_type='marketing')
        self.user = User.objects.create_user('nc', email='nc@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.acme = Client.objects.create(org=self.org, name='Acme Motors', code='ACM')
        self.bay = Client.objects.create(org=self.org, name='Bayside Auto Group', code='BAG')
        self.spring = Project.objects.create(org=self.org, client=self.acme, name='Spring Launch')
        self.web = Project.objects.create(org=self.org, client=self.acme, name='Website Refresh')
        self.radio = Project.objects.create(org=self.org, client=self.bay, name='Radio')
        self.social = Project.objects.create(org=self.org, client=self.bay, name='Social')
        self._n = 0

    def block(self, title, client=None, categorized_by='ai', app='Adobe Photoshop', gap=30):
        self._n += 1
        s = T0 + timedelta(minutes=gap * self._n)
        return Block.objects.create(
            org=self.org, user=self.user, hostname='mac', device_id='d', start=s,
            end=s + timedelta(minutes=20), minutes=20, app_name=app, window_title=title, title=title,
            classification_state='committed', is_categorized=True, client=client,
            categorized_by=categorized_by, category_hours={'Design': 0.3})

    def run_(self):
        stats = attribute_matters_for_org(self.org, days=3650)
        return stats

    def test_names_client_and_project(self):
        b = self.block('ACM_AcmeMotors_SpringLaunch_storyboard_v3.psd')
        stats = self.run_()
        b.refresh_from_db()
        self.assertEqual((b.client_id, b.project_id), (self.acme.id, self.spring.id))
        self.assertEqual(stats['by_convention'], 1)

    def test_corrects_a_machine_guess_but_never_a_person(self):
        guessed = self.block('BAG_Bayside_Radio_script.docx', client=self.acme, categorized_by='ai')
        chosen = self.block('BAG_Bayside_Radio_script.docx', client=self.acme, categorized_by='manual')
        self.run_()
        guessed.refresh_from_db(); chosen.refresh_from_db()
        self.assertEqual((guessed.client_id, guessed.project_id), (self.bay.id, self.radio.id))
        self.assertEqual((chosen.client_id, chosen.project_id), (self.acme.id, None))

    def test_gap_is_filled_only_within_the_same_client(self):
        self.block('ACM_AcmeMotors_SpringLaunch_a.psd')
        slack = self.block('Slack - #acme', client=self.acme, app='Slack')
        youtube = self.block('YouTube', client=None, app='Google Chrome')
        self.block('ACM_AcmeMotors_SpringLaunch_b.psd')
        # First pass files the two named blocks; the second uses them as neighbours.
        self.run_(); self.run_()
        slack.refresh_from_db(); youtube.refresh_from_db()
        self.assertEqual(slack.project_id, self.spring.id)
        self.assertIsNone(youtube.project_id)
        self.assertIsNone(youtube.client_id)

    def test_cpa_firm_ignores_conventions(self):
        self.org.industry_type = 'cpa'
        self.org.save()
        b = self.block('ACM_AcmeMotors_SpringLaunch_v3.psd')
        self.run_()
        b.refresh_from_db()
        self.assertIsNone(b.client_id)
