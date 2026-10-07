"""
seed_google_reviewer — the login Google's verification reviewer signs in with.

Real database (TestCase): run against a THROWAWAY Postgres, never the default
settings (the local docker DB is production):

    python manage.py test tracker.seed_google_reviewer_test --noinput < /dev/null
"""
from io import StringIO
from unittest import mock

from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from tracker.management.commands import seed_google_reviewer as seed
from tracker.models import Block, Organization, OrganizationMembership
from tracker.models_calendar_rules import OrgCalendarRule
from tracker.services.mail_compose import is_gmail_block
from tracker.views_reports import is_pending_review_block

User = get_user_model()


def run(*args):
    out = StringIO()
    call_command("seed_google_reviewer", *args, stdout=out)
    return out.getvalue()


class SeedGoogleReviewerTest(TestCase):
    def test_reviewer_can_sign_in_as_owner_of_a_calendar_enabled_org(self):
        run("--password", "pw-for-test-only", "--days", "3")
        org = Organization.objects.get(slug=seed.ORG_SLUG)
        self.assertTrue(org.calendar_classification_enabled)
        self.assertTrue(org.is_demo)
        self.assertFalse(org.disable_mail_integration)
        user = authenticate(username=seed.DEFAULT_EMAIL, password="pw-for-test-only")
        self.assertIsNotNone(user)
        self.assertEqual(OrganizationMembership.objects.get(user=user).role, "owner")

    def test_client_domains_are_mapped_including_extras(self):
        run("--password", "x", "--days", "1", "--domain", "Acme Co=acme-demo.com")
        org = Organization.objects.get(slug=seed.ORG_SLUG)
        mapped = set(OrgCalendarRule.objects.filter(org=org, is_active=True)
                     .values_list("match_value", flat=True))
        self.assertEqual(mapped, set(seed.CLIENTS.values()) | {"acme-demo.com"})

    def test_pending_rows_are_needs_you_rows_on_past_days_only(self):
        run("--password", "x", "--days", "3")
        org = Organization.objects.get(slug=seed.ORG_SLUG)
        today = timezone.now().astimezone(seed.TZ).date()
        pending = list(Block.objects.filter(org=org, classification_state="proposed"))
        self.assertTrue(pending)
        self.assertTrue(all(is_pending_review_block(b) for b in pending))
        self.assertTrue(all(b.day < today for b in pending))
        self.assertTrue(any(is_gmail_block(b) for b in pending))
        self.assertFalse(Block.objects.filter(org=org, start__gt=timezone.now()).exists())

    def test_confirmed_rows_are_committed_and_never_pending(self):
        run("--password", "x", "--days", "3")
        committed = Block.objects.filter(org__slug=seed.ORG_SLUG, classification_state="committed")
        self.assertTrue(committed.exists())
        self.assertFalse(any(is_pending_review_block(b) for b in committed))

    def test_rerun_refuses_then_reset_and_teardown(self):
        run("--password", "x", "--days", "1")
        with self.assertRaises(CommandError):
            run("--password", "x", "--days", "1")
        run("--password", "x", "--days", "1", "--reset")
        self.assertEqual(Organization.all_objects.filter(slug=seed.ORG_SLUG).count(), 1)
        run("--teardown")
        self.assertFalse(Organization.all_objects.filter(slug=seed.ORG_SLUG).exists())
        self.assertFalse(User.objects.filter(username=seed.DEFAULT_EMAIL).exists())

    def test_generated_password_is_printed_and_works(self):
        out = run("--days", "1")
        password = next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("Password: "))
        self.assertIsNotNone(authenticate(username=seed.DEFAULT_EMAIL, password=password))

    def test_remote_host_needs_confirmation(self):
        remote = {**connection.settings_dict, "HOST": "ep-prod.neon.tech"}
        with mock.patch.object(connection, "settings_dict", remote):
            with self.assertRaises(CommandError):
                run("--password", "x")
            with self.assertRaises(CommandError):
                run("--password", "x", "--confirm-host", "wrong-host")
        self.assertFalse(Organization.all_objects.filter(slug=seed.ORG_SLUG).exists())
