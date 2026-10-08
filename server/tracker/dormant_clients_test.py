"""
Imported clients nobody works for are deactivated; anything with a sign of
real work is kept.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.dormant_clients_test --noinput < /dev/null
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from tracker.models import Block, Client, Invoice, Organization, Project, TimecardEntry
from tracker.services.client_conversion import fold_clients
from tracker.services.dormant_clients import find_dormant_clients

User = get_user_model()


class DormantClientTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-dormant')
        self.user = User.objects.create_user('pat', email='p@mtc.test', password='x')

    def client_(self, name, src='quickbooks'):
        return Client.objects.create(org=self.org, name=name, imported_from=src)

    def dormant_names(self, **kw):
        out, _kept = find_dormant_clients(self.org.id, **kw)
        return {d.client.name for d in out}

    def test_only_imported_clients_with_no_work_are_dormant(self):
        self.client_('Visa Cardholder-3')
        self.client_('Stripe Sales', src='qb_time')
        self.client_('Hand Made Client', src='')
        Project.objects.create(org=self.org, client=self.client_('Acme Motors'), name='Spring')
        s = datetime(2026, 10, 6, 14, 0, tzinfo=dt_timezone.utc)
        Block.objects.create(org=self.org, user=self.user, hostname='m', device_id='d', start=s,
                             end=s + timedelta(minutes=5), day=s.date(), minutes=5, title='x',
                             client=self.client_('Laura Murphy'))
        Block.objects.create(org=self.org, user=self.user, hostname='m', device_id='d', start=s,
                             end=s + timedelta(minutes=5), day=s.date(), minutes=5, title='y',
                             proposed_client=self.client_('Proposed Only'))
        TimecardEntry.objects.create(org=self.org, user=self.user, date=date(2026, 10, 6),
                                     client=self.client_('Timecard Co'), total_hours=Decimal('1'))
        self.assertEqual(self.dormant_names(), {'Visa Cardholder-3', 'Stripe Sales'})

    def test_internal_is_never_dormant(self):
        self.client_('Internal - Tax')
        self.assertEqual(self.dormant_names(), set())

    def test_invoiced_clients_are_kept_unless_asked(self):
        c = self.client_('CarGurus')
        Invoice.objects.create(org=self.org, client=c, invoice_number='1',
                               invoice_date=date(2026, 9, 1), amount=Decimal('100'))
        out, kept = find_dormant_clients(self.org.id)
        self.assertEqual(([d.client for d in out], [d.client for d in kept]), ([], [c]))
        self.assertEqual(self.dormant_names(include_invoiced=True), {'CarGurus'})

    def test_command_dry_run_then_apply(self):
        c = self.client_('Sample Customer')
        out = StringIO()
        call_command('prune_dormant_clients', org_id=self.org.id, stdout=out)
        c.refresh_from_db()
        self.assertTrue(c.is_active)
        self.assertIn('DRY RUN: 1 clients', out.getvalue())
        call_command('prune_dormant_clients', org_id=self.org.id, apply=True, stdout=StringIO())
        c.refresh_from_db()
        self.assertFalse(c.is_active)


class InternalGuardTests(TestCase):
    def test_a_meeting_named_internal_can_be_folded(self):
        org = Organization.objects.create(name='MTC', slug='mtc-guard')
        parent = Client.objects.create(org=org, name='Lexus of Lehigh Valley')
        meeting = Client.objects.create(org=org, name='LoLV 15-minute Weekly Internal Team Meeting')
        [r] = fold_clients(org.id, parent.id, [meeting.id], apply=True)
        meeting.refresh_from_db()
        self.assertFalse(meeting.is_active)
        self.assertTrue(Project.objects.filter(client=parent, name=meeting.name).exists())
