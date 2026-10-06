"""
Early weekly submit: a finished week goes before Tuesday — and only a finished one.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.settled_submit_test --noinput < /dev/null
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.models import (
    Block, Client, DayReview, Organization, OrganizationMembership, Timesheet,
)
from tracker.tasks import submit_settled_timesheets

User = get_user_model()
WEEK = date(2026, 9, 28)          # a Monday well before "this week"
TUE = WEEK + timedelta(days=1)


class SettledSubmitTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-settled',
                                               industry_type='marketing', auto_submit_timesheets=True)
        self.user = User.objects.create_user('ann', email='ann@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='member')
        self.client_ = Client.objects.create(org=self.org, name='Chevy')
        self.ts = Timesheet.objects.create(org=self.org, user=self.user, week_start=WEEK, status='draft')
        for name in ('_queue_notify', '_queue_clio_push'):
            p = mock.patch.object(Timesheet, name)
            p.start()
            self.addCleanup(p.stop)

    def block(self, day=TUE, **kw):
        at = datetime.combine(day, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(hours=14)
        fields = dict(org=self.org, user=self.user, hostname='mac', device_id='d', start=at,
                      end=at + timedelta(minutes=30), minutes=30, day=day, app_name='Photoshop',
                      window_title='Hero.psd', title='Hero.psd',
                      classification_state='committed', is_categorized=True, client=self.client_)
        fields.update(kw)
        return Block.objects.create(**fields)

    def seen(self, day=TUE):
        DayReview.objects.create(org=self.org, user=self.user, day=day)

    def status(self):
        self.ts.refresh_from_db()
        return self.ts.status

    def test_finished_week_goes_early(self):
        self.block()
        self.seen()
        self.assertEqual(submit_settled_timesheets()['submitted'], 1)
        self.assertEqual(self.status(), 'submitted')

    def test_seen_but_needs_you_still_open_waits(self):
        # Opening the day marks it seen; an item still in Needs You means the
        # week is not finished, however recently it was looked at.
        self.block()
        self.block(classification_state='proposed', is_categorized=False, client=None,
                   proposed_client=self.client_, proposed_reasoning='title match')
        self.seen()
        out = submit_settled_timesheets()
        self.assertEqual((out['submitted'], out['not_settled']), (0, 1))
        self.assertEqual(self.status(), 'draft')

    def test_unreviewed_day_waits(self):
        self.block()
        self.block(day=TUE + timedelta(days=1))
        self.seen()                                   # only Tuesday looked at
        self.assertEqual(submit_settled_timesheets()['submitted'], 0)
        self.assertEqual(self.status(), 'draft')

    def test_new_work_after_review_waits(self):
        self.seen()
        self.block()                                  # landed after the review
        self.assertEqual(submit_settled_timesheets()['submitted'], 0)

    def test_firm_without_auto_submit_is_left_alone(self):
        Organization.objects.filter(id=self.org.id).update(auto_submit_timesheets=False)
        self.block()
        self.seen()
        self.assertEqual(submit_settled_timesheets()['submitted'], 0)
        self.assertEqual(self.status(), 'draft')

    def test_runs_again_without_resubmitting(self):
        self.block()
        self.seen()
        submit_settled_timesheets()
        self.assertEqual(submit_settled_timesheets()['submitted'], 0)
        self.assertEqual(self.status(), 'submitted')
