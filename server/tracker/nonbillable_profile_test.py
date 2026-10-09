"""
A client marked Non-billable on its billing profile is non-billable everywhere.

The case: More Than Cars Creative is the firm's OWN company, sitting in its
client list. Analytics already dropped Non-billable clients from utilization
and value, but Daily Review, Reports, timesheets and billing read the stored
Block.is_billable flag, so her own-company hours still showed as Billable.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.nonbillable_profile_test --noinput < /dev/null
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.models import Block, Client, ClientBillingProfile, Organization

User = get_user_model()
DAY = date(2026, 10, 6)


class NonBillableProfileTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-nonbill')
        self.user = User.objects.create_user('eileen', email='e@mtc.test', password='x')
        self.own_co = Client.objects.create(org=self.org, name='More Than Cars Creative')
        self.real = Client.objects.create(org=self.org, name='Easterns Automotive')

    def block(self, client, **kw):
        at = datetime.combine(DAY, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(hours=14)
        fields = dict(org=self.org, user=self.user, hostname='mac', start=at,
                      end=at + timedelta(minutes=30), minutes=30, day=DAY,
                      client=client, is_billable=True,
                      classification_state='committed', is_categorized=True)
        fields.update(kw)
        return Block.objects.create(**fields)

    def mark_non_billable(self, client):
        ClientBillingProfile.objects.create(org=self.org, client=client,
                                            billing_type='non_billable')

    def test_marking_the_client_clears_its_existing_time(self):
        own = self.block(self.own_co)
        other = self.block(self.real)
        self.mark_non_billable(self.own_co)
        own.refresh_from_db(); other.refresh_from_db()
        self.assertFalse(own.is_billable)
        self.assertTrue(other.is_billable, "another client's time must be untouched")

    def test_invoiced_and_locked_time_is_left_as_billed(self):
        invoiced = self.block(self.own_co, invoiced=True)
        locked = self.block(self.own_co, locked=True)
        self.mark_non_billable(self.own_co)
        invoiced.refresh_from_db(); locked.refresh_from_db()
        self.assertTrue(invoiced.is_billable)
        self.assertTrue(locked.is_billable)

    def test_new_time_on_the_client_saves_non_billable(self):
        self.mark_non_billable(self.own_co)
        self.assertFalse(self.block(self.own_co).is_billable)
        self.assertTrue(self.block(self.real).is_billable)

    def test_daily_review_totals_stop_counting_it_as_billable(self):
        from tracker.services.billing_totals import billable_block_q
        self.block(self.own_co)
        self.block(self.real)
        self.mark_non_billable(self.own_co)
        billable = Block.objects.filter(org=self.org).filter(billable_block_q(self.org))
        self.assertEqual(list(billable.values_list('client__name', flat=True)),
                         ['Easterns Automotive'])
