"""
Asana project links learned from the firm's own time (learning.py).

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.asana_learning_test --noinput < /dev/null
"""
from datetime import timedelta

from django.utils import timezone

from tracker.asana_onboarding_test import Base
from tracker.integrations.asana import learning, sync as s
from tracker.models import Block, Integration, Project
from tracker.models_asana import AsanaActivity
from tracker.models_task_type_sets import (
    ExternalMatterMapping, ExternalStaffMapping, QbtPushedTimesheet,
)


class FakeQbt:
    def __init__(self, rows):
        self.rows = rows

    def paginated(self, endpoint, **params):
        assert endpoint == 'timesheets'
        return list(self.rows)


class LearnBase(Base):
    def setUp(self):
        super().setUp()
        self.offers = Project.objects.create(org=self.org, client=self.tgb, name='TG Buick Monthly Offers')
        self.web = Project.objects.create(org=self.org, client=self.tgb, name='TG Buick Website')
        self.asana = self.link('Tom Gill Buick GMC: 2026 Monthly Video Offers',
                               client=self.tgb, link_source='client')
        self.user = self.operator
        self.n = 0

    def act(self, at, gid=None):
        self.n += 1
        AsanaActivity.objects.create(integration=self.integ, story_gid=f's{self.n}', user=self.user,
                                     at=at, asana_project_gid=gid or self.asana.asana_gid,
                                     client=self.tgb, kind='comment_added')

    def block(self, start, project, by='user'):
        return Block.objects.create(org=self.org, user=self.user, hostname='h', start=start,
                                    end=start + timedelta(minutes=30), client=project.client,
                                    project=project, state_changed_by=by)

    def days_ago(self, d, hour=15):
        return (timezone.now() - timedelta(days=d)).replace(hour=hour, minute=0, second=0, microsecond=0)


class FromDailyReviewTests(LearnBase):
    def test_repeated_filing_links_the_project(self):
        for d in (1, 2, 3):
            t = self.days_ago(d)
            self.act(t + timedelta(minutes=5))
            self.block(t, self.offers)
        out = learning.learn_links(self.integ)
        self.assertEqual(out['linked'], 1)
        self.asana.refresh_from_db()
        self.assertEqual((self.asana.project_id, self.asana.link_source), (self.offers.id, 'learned'))
        # Recorded activity follows, so the sweep can file the time.
        self.assertTrue(AsanaActivity.objects.filter(project=self.offers).exists())

    def test_machine_filings_teach_nothing(self):
        for d in (1, 2, 3):
            t = self.days_ago(d)
            self.act(t + timedelta(minutes=5))
            self.block(t, self.offers, by='classifier')
        self.assertEqual(learning.learn_links(self.integ)['linked'], 0)

    def test_split_evidence_links_nothing(self):
        for d, p in ((1, self.offers), (2, self.web), (3, self.offers), (4, self.web)):
            t = self.days_ago(d)
            self.act(t + timedelta(minutes=5))
            self.block(t, p)
        self.assertEqual(learning.learn_links(self.integ)['linked'], 0)

    def test_one_day_is_not_enough(self):
        t = self.days_ago(1)
        for h in range(4):
            self.act(t + timedelta(hours=h, minutes=5))
            self.block(t + timedelta(hours=h), self.offers)
        self.assertEqual(learning.learn_links(self.integ)['linked'], 0)

    def test_other_clients_projects_never_chosen(self):
        other = Project.objects.create(org=self.org, client=self.tgc, name='TG Chevy Offers')
        for d in (1, 2, 3):
            t = self.days_ago(d)
            self.act(t + timedelta(minutes=5))
            self.block(t, other)
        self.assertEqual(learning.learn_links(self.integ)['linked'], 0)

    def test_dry_run_writes_nothing(self):
        for d in (1, 2, 3):
            t = self.days_ago(d)
            self.act(t + timedelta(minutes=5))
            self.block(t, self.offers)
        out = learning.learn_links(self.integ, dry_run=True)
        self.assertEqual(out['linked'], 1)
        self.asana.refresh_from_db()
        self.assertIsNone(self.asana.project_id)

    def test_relink_keeps_a_learned_link(self):
        self.asana.project = self.offers
        self.asana.link_source = 'learned'
        self.asana.save()
        s.relink(self.integ)
        self.asana.refresh_from_db()
        self.assertEqual((self.asana.project_id, self.asana.link_source), (self.offers.id, 'learned'))


class FromQuickBooksTimeTests(LearnBase):
    def setUp(self):
        super().setUp()
        self.qbt = Integration.objects.create(organization=self.org, provider='qb_time', is_connected=True)
        ExternalStaffMapping.objects.create(integration=self.qbt, user=self.user, external_id='u1')
        for jid, p in (('j1', self.offers), ('j2', self.web)):
            ExternalMatterMapping.objects.create(integration=self.qbt, project=p, external_id=jid)

    def run_with(self, rows):
        orig = learning.qbt_spans
        learning.qbt_spans = lambda org, since, api=None: orig(org, since, api=FakeQbt(rows))
        try:
            return learning.learn_links(self.integ)
        finally:
            learning.qbt_spans = orig

    def test_timed_timesheets_link(self):
        rows = []
        for i, d in enumerate((1, 2, 3)):
            t = self.days_ago(d)
            self.act(t + timedelta(minutes=20))
            rows.append({'id': i, 'user_id': 'u1', 'jobcode_id': 'j1', 'start': t.isoformat(),
                         'end': (t + timedelta(hours=1)).isoformat(), 'date': str(t.date())})
        self.assertEqual(self.run_with(rows)['linked'], 1)
        self.asana.refresh_from_db()
        self.assertEqual(self.asana.project_id, self.offers.id)

    def test_manual_day_entries_link_when_one_project_that_day(self):
        rows = []
        for i, d in enumerate((1, 2, 3)):
            t = self.days_ago(d, hour=17)
            self.act(t)
            rows.append({'id': i, 'user_id': 'u1', 'jobcode_id': 'j1', 'start': '', 'end': '',
                         'date': str(t.astimezone(learning._tz(self.org)).date()), 'duration': 3600})
        self.assertEqual(self.run_with(rows)['linked'], 1)

    def test_our_own_pushed_rows_are_ignored(self):
        rows = []
        for i, d in enumerate((1, 2, 3)):
            t = self.days_ago(d)
            self.act(t + timedelta(minutes=20))
            rows.append({'id': f'ours{i}', 'user_id': 'u1', 'jobcode_id': 'j1', 'start': t.isoformat(),
                         'end': (t + timedelta(hours=1)).isoformat()})
            QbtPushedTimesheet.objects.create(integration=self.qbt, timesheet_id=f'ours{i}',
                                              qbt_user_id='u1', jobcode_id='j1', day=t.date())
        self.assertEqual(self.run_with(rows)['linked'], 0)

