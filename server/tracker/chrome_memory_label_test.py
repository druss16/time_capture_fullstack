"""
Chrome's "High memory usage - N MB" tab label is not part of any title.

Real database for the backfill (TestCase): run against a THROWAWAY Postgres,
never the default settings (the local docker DB is production):

    python manage.py test tracker.chrome_memory_label_test --noinput < /dev/null
"""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tracker.models import Block, Organization, OrganizationMembership, RawEvent
from tracker.utils.content_identity import (
    content_identity, normalize_ingested_title, strip_chrome_memory_label,
)

GMAIL = ('Dauphin & Fantacone - New Phone Number - dan@mavops.ai - MavOps Mail'
         ' - High memory usage - 805 MB - Google Chrome - dan@mavops.ai')
CLEAN = 'Dauphin & Fantacone - New Phone Number - dan@mavops.ai - MavOps Mail - Google Chrome - dan@mavops.ai'


class StripTest(SimpleTestCase):
    def test_only_the_label_goes(self):
        self.assertEqual(strip_chrome_memory_label(GMAIL), CLEAN)
        self.assertEqual(strip_chrome_memory_label(
            'Managed Payments - MAVOPS - Stripe - High memory usage - 1.2 GB - Google Chrome'),
            'Managed Payments - MAVOPS - Stripe - Google Chrome')
        self.assertEqual(strip_chrome_memory_label('Inbox – High memory usage – 830 MB – Google Chrome'),
                         'Inbox – Google Chrome')

    def test_titles_without_it_are_untouched(self):
        for t in ('Q3 workpapers.xlsx - Excel', 'Memory usage report - Google Docs - Google Chrome',
                  'High memory usage notes.txt', ''):
            self.assertEqual(strip_chrome_memory_label(t), t)

    def test_stripped_at_ingestion(self):
        self.assertEqual(normalize_ingested_title(GMAIL, 'com.google.Chrome', 'Google Chrome'), CLEAN)

    def test_changing_number_no_longer_splits_one_email(self):
        a = GMAIL
        b = GMAIL.replace('805 MB', '830 MB')
        self.assertEqual(content_identity(a), content_identity(b))


class BackfillTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MavOps Test', slug='mavops-test')
        self.user = get_user_model().objects.create_user('u@x.com', email='u@x.com', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        now = timezone.now() - timedelta(hours=1)
        self.block = Block.objects.create(
            org=self.org, user=self.user, hostname='mac', start=now, end=now + timedelta(minutes=5),
            window_title=GMAIL, title=GMAIL, classification_state='committed', is_categorized=True)
        self.other = Block.objects.create(
            org=self.org, user=self.user, hostname='mac', start=now, end=now + timedelta(minutes=5),
            window_title='Q3 workpapers.xlsx - Excel', title='Q3 workpapers.xlsx - Excel',
            classification_state='committed', is_categorized=True)
        self.event = RawEvent.objects.create(
            start_ts=now, end_ts=now + timedelta(minutes=1), user=self.user, window_title=GMAIL)

    def run_cmd(self, *args):
        out = StringIO()
        call_command('strip_chrome_memory_label', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        out = self.run_cmd()
        self.assertIn('Would strip the label from 3 title(s)', out)
        self.block.refresh_from_db()
        self.assertEqual(self.block.window_title, GMAIL)

    def test_apply_strips_only_the_label(self):
        self.run_cmd('--apply', '--org', str(self.org.id))
        self.block.refresh_from_db()
        self.other.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual((self.block.window_title, self.block.title), (CLEAN, CLEAN))
        self.assertEqual(self.event.window_title, CLEAN)
        self.assertEqual(self.other.window_title, 'Q3 workpapers.xlsx - Excel')
        self.assertEqual(self.block.classification_state, 'committed')
