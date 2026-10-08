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
from tracker.services.alias_derivation import (
    _email_candidates, is_platform_domain, platform_email_aliases,
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
