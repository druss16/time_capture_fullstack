"""
A client's email at a platform domain must never become an alias.

More Than Cars, 2026-10-07: "Laura Murphy" came in from QuickBooks with
lamurphy@google.com. Derivation made "google.com" and "google" aliases, and
every Gmail, Google Calendar and Merchant Center window was booked to her.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.alias_platform_domain_test --noinput < /dev/null
"""
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from tracker.models import Client, Organization
from types import SimpleNamespace

from tracker.services.alias_derivation import (
    _email_candidates, is_platform_domain, platform_email_aliases, usable_aliases,
)


class PlatformDomainTests(SimpleTestCase):
    def test_platform_email_yields_nothing(self):
        for email in ('lamurphy@google.com', 'x@mail.google.com', 'a@microsoft.com',
                      'b@gmail.com', 'c@asana.com', 'd@WWW.Apple.com'):
            self.assertEqual(_email_candidates(email), [], email)

    def test_client_domain_still_derives(self):
        self.assertEqual([a for a, _ in _email_candidates('billing@fullypromoted.com')],
                         ['fullypromoted.com', 'fullypromoted'])

    def test_lookalike_is_not_a_platform(self):
        self.assertFalse(is_platform_domain('notgoogle.com'))
        self.assertFalse(is_platform_domain('googleplex-motors.com'))

    def test_what_a_platform_email_would_have_made(self):
        self.assertEqual(platform_email_aliases('lamurphy@google.com'), {'google.com', 'google'})
        self.assertEqual(platform_email_aliases('billing@fullypromoted.com'), set())


class UsableAliasTests(SimpleTestCase):
    def test_unhealed_platform_aliases_ignored(self):
        c = SimpleNamespace(email='lamurphy@google.com', aliases=['google.com', 'Google', 'laura murphy'],
                            alias_sources={'google.com': 'derived', 'google': 'derived'})
        self.assertEqual(usable_aliases(c), ['laura murphy'])

    def test_manual_kept_and_normal_client_untouched(self):
        c = SimpleNamespace(email='ap@google.com', aliases=['google'], alias_sources={'google': 'manual'})
        self.assertEqual(usable_aliases(c), ['google'])
        d = SimpleNamespace(email='x@fullypromoted.com', aliases=['fullypromoted'], alias_sources={})
        self.assertEqual(usable_aliases(d), ['fullypromoted'])


class ClassifierTests(TestCase):
    """The live path: a Google Doc must not be booked to a client whose
    QuickBooks email happens to be at google.com, even before the heal."""
    def test_google_doc_not_booked_to_google_email_client(self):
        from datetime import datetime, timedelta, timezone as tz
        from django.contrib.auth import get_user_model
        from tracker.models import Block, OrganizationMembership
        from tracker.services.classification_service import ClassificationService
        org = Organization.objects.create(name='MTC', slug='mtc-cls', industry_type='marketing')
        user = get_user_model().objects.create_user('al', email='al@mtc.test', password='x')
        OrganizationMembership.objects.create(user=user, organization=org, role='owner')
        laura = Client.objects.create(
            org=org, name='Laura Murphy', email='lamurphy@google.com',
            aliases=['google.com', 'google'], alias_sources={'google.com': 'derived', 'google': 'derived'})
        t0 = datetime(2026, 10, 7, 20, 0, tzinfo=tz.utc)
        b = Block.objects.create(
            org=org, user=user, hostname='mac', device_id='d1', start=t0, end=t0 + timedelta(minutes=11),
            minutes=11, app_name='Google Chrome', title='Google Chrome',
            window_title='Tom Gill October Offers for Creative - Google Docs',
            url='https://docs.google.com/document/d/1xQ7bW9q/edit')
        decision = ClassificationService(org=org, user=user).classify(b, skip_ai=True)
        self.assertNotEqual(getattr(decision, 'client_id', None), laura.id)


class HealTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-heal')

    def heal(self):
        call_command('heal_ambiguous_aliases', org_id=self.org.id, stdout=StringIO())

    def test_derived_platform_aliases_removed(self):
        c = Client.objects.create(
            org=self.org, name='Laura Murphy', email='lamurphy@google.com',
            aliases=['google.com', 'google', 'laura murphy'],
            alias_sources={'google.com': 'derived', 'google': 'derived', 'laura murphy': 'manual'})
        self.heal()
        c.refresh_from_db()
        self.assertEqual(c.aliases, ['laura murphy'])
        self.assertEqual(c.alias_sources, {'laura murphy': 'manual'})

    def test_manual_platform_alias_kept(self):
        c = Client.objects.create(
            org=self.org, name='Google LLC', email='ap@google.com',
            aliases=['google'], alias_sources={'google': 'manual'})
        self.heal()
        c.refresh_from_db()
        self.assertEqual(c.aliases, ['google'])

    def test_derive_then_heal_leaves_no_google(self):
        c = Client.objects.create(org=self.org, name='Laura Murphy', email='lamurphy@google.com')
        call_command('derive_aliases', org_id=self.org.id, stdout=StringIO())
        self.heal()
        c.refresh_from_db()
        self.assertFalse({'google', 'google.com'} & {a.lower() for a in (c.aliases or [])})
