"""
The flexible reader: a client named however the firm writes it.

Real database for the attribution cases: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.flexible_naming_test --noinput < /dev/null

Titles are More Than Cars' own (org 44, October 2026). None of them fit the
CODE_ClientName_Project grammar, so the strict reader returned nothing for
every one, and each block waited on a person.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from tracker.models import Block, Client, Organization, OrganizationMembership, Project
from tracker.services.classification_service import ClassificationService
from tracker.services.matter_attribution import attribute_matters_for_org
from tracker.services.naming_convention import build_index, flex_words, resolve_flexible, resolve_text

User = get_user_model()
T0 = datetime(2026, 10, 6, 14, 0, tzinfo=dt_timezone.utc)

TGBGMC, TGC, EASTERNS, SHORE, DIRECT, PODIUM, MAIN = 1537, 1538, 1124, 8, 1110, 1473, 99
INDEX = build_index(
    clients=[(TGBGMC, 'Tom Gill Buick GMC', '', []),
             (TGC, 'Tom Gill Chevrolet', '', []),
             (EASTERNS, 'Easterns Automotive Group', '', ['Easterns']),
             (SHORE, 'Eastern Shore Dental', '', []),
             (DIRECT, 'Direct Exteriors', '', []),
             (PODIUM, 'Podium', '', []),
             (MAIN, 'Main', '', []),
             (70, 'Internal', '', [])],
    is_safe=ClassificationService._alias_is_safe,
)


def flex(text):
    r = resolve_flexible([('title', text)], INDEX)
    return r[:2] if r else None


class FlexibleReaderTests(SimpleTestCase):
    def test_words_split_on_separators_and_case(self):
        self.assertEqual([w for _o, w in flex_words('TomGill_Buick-GMC DealerCONNECT.png')],
                         ['tom', 'gill', 'buick', 'gmc', 'dealer', 'connect', 'png'])

    def test_name_split_across_segments(self):
        self.assertEqual(flex('TomGill_Buick_GMC_Offers_October_2026_2026 Enclave.png'), (TGBGMC, 'name'))

    def test_full_name_in_a_docs_title(self):
        self.assertEqual(flex('Easterns Automotive Group Scope Addendum 6-1 - Google Docs'), (EASTERNS, 'name'))

    def test_alias_in_capitals(self):
        self.assertEqual(flex('61099 - EASTERNS CHRYSLER DODGE JEEP RAM DealerCONNECT'), (EASTERNS, 'name'))

    def test_firms_own_abbreviation_in_capitals(self):
        self.assertEqual(flex('TGBGMC Website Reskin'), (TGBGMC, 'abbreviation'))
        self.assertEqual(flex('TGC Q4 Production - hero.psd'), (TGC, 'abbreviation'))
        self.assertIsNone(flex('tgbgmc website reskin'))          # lowercase is not the abbreviation

    def test_shortened_name(self):
        self.assertEqual(flex('Notes_Easterns-Auto_Flyer.psd'), (EASTERNS, 'name'))   # alias "Easterns" wins
        idx = build_index([(EASTERNS, 'Easterns Automotive Group', '', [])])
        self.assertEqual(resolve_flexible([('t', 'Easterns-Auto-Grp_Flyer.psd')], idx)[:2], (EASTERNS, 'short'))

    def test_shortening_that_fits_two_clients_names_neither(self):
        self.assertIsNone(flex('Tom Gill October Offers for Creative - Google Docs'))

    def test_longer_name_absorbs_the_shorter(self):
        # "Tom Gill" fits both Tom Gills; "Tom Gill Chevrolet" names one.
        self.assertEqual(flex('Tom Gill Chevrolet Q4 Production'), (TGC, 'name'))

    def test_two_clients_abstain(self):
        self.assertIsNone(flex('Easterns vs Tom Gill Chevrolet - recap'))

    def test_first_word_must_be_whole(self):
        self.assertEqual(flex('Easterns DealerCONNECT'), (EASTERNS, 'name'))   # never Eastern Shore

    def test_unsafe_and_internal_names_never_match(self):
        self.assertIsNone(flex('Main'))
        self.assertIsNone(flex('Internal - Calendar'))
        self.assertEqual(flex('Podium - Reviews dashboard'), (PODIUM, 'name'))

    def test_strict_reader_is_unchanged(self):
        self.assertIsNone(resolve_text([('title', 'TomGill_Buick_GMC_Offers.png')], INDEX))


class FlexibleAttributionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-flex', industry_type='marketing')
        self.user = User.objects.create_user('al', email='al@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.tgbgmc = Client.objects.create(org=self.org, name='Tom Gill Buick GMC')
        self.easterns = Client.objects.create(org=self.org, name='Easterns Automotive Group', aliases=['Easterns'])
        self.direct = Client.objects.create(org=self.org, name='Direct Exteriors')
        self.reskin = Project.objects.create(org=self.org, client=self.tgbgmc, name='TGBGMC Website Reskin')
        Project.objects.create(org=self.org, client=self.easterns, name='Easterns Cares Campaign')
        Project.objects.create(org=self.org, client=self.direct, name='Direct Fall Mailer')
        self._n = 0

    def block(self, title, client=None, categorized_by='ai'):
        self._n += 1
        s = T0 + timedelta(minutes=30 * self._n)
        return Block.objects.create(
            org=self.org, user=self.user, hostname='mac', device_id='d', start=s,
            end=s + timedelta(minutes=20), minutes=20, app_name='Google Chrome',
            window_title=title, title=title, classification_state='committed',
            is_categorized=True, client=client, categorized_by=categorized_by,
            category_hours={'Design': 0.3})

    def test_fills_client_then_project_tier_finds_the_project(self):
        b = self.block('TomGill_Buick_GMC_Website_Reskin_homepage.png')
        stats = attribute_matters_for_org(self.org, days=3650)
        b.refresh_from_db()
        self.assertEqual((b.client_id, b.project_id), (self.tgbgmc.id, self.reskin.id))
        self.assertEqual(stats['by_flexible_name'], 1)

    def test_full_name_corrects_a_machine_guess_but_never_a_person(self):
        guessed = self.block('Easterns Automotive Group Scope Addendum 6-1 - Google Docs', client=self.direct)
        chosen = self.block('Easterns Automotive Group Scope Addendum 6-1 - Google Docs',
                            client=self.direct, categorized_by='manual')
        attribute_matters_for_org(self.org, days=3650)
        guessed.refresh_from_db(); chosen.refresh_from_db()
        self.assertEqual(guessed.client_id, self.easterns.id)
        self.assertEqual(chosen.client_id, self.direct.id)

    def test_abbreviation_fills_but_does_not_correct(self):
        empty = self.block('TGBGMC Website Reskin - Figma')
        other = self.block('TGBGMC Website Reskin - Figma', client=self.direct)
        attribute_matters_for_org(self.org, days=3650)
        empty.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(empty.client_id, self.tgbgmc.id)
        self.assertEqual(other.client_id, self.direct.id)

    def test_cpa_firm_ignores_it(self):
        Organization.objects.filter(pk=self.org.pk).update(industry_type='cpa')
        self.org.refresh_from_db()
        b = self.block('TomGill_Buick_GMC_Offers.png')
        attribute_matters_for_org(self.org, days=3650)
        b.refresh_from_db()
        self.assertIsNone(b.client_id)
