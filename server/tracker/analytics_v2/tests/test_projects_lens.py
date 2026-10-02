"""
Projects lens — agency budget vs actual.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.analytics_v2.tests.test_projects_lens --noinput < /dev/null
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tracker.models import (
    Block, Client, Organization, OrganizationMembership, Project,
)
from tracker.services import project_budgets as pb

User = get_user_model()
OCT = date(2026, 10, 1)


def oct_body(**over):
    body = {"scope": {"type": "firm", "ids": []}, "lens": "projects",
            "time": {"type": "absolute", "value": {"start": "2026-10-01", "end": "2026-10-31"}}}
    body.update(over)
    return body


class Base(TestCase):
    industry = 'marketing'

    def setUp(self):
        self.org = Organization.objects.create(
            name='MTC', slug=f'mtc-l-{self.industry}', industry_type=self.industry,
            plan='executive', billing_rate_default=Decimal('165'), cost_rate_default=Decimal('40'))
        self.owner = User.objects.create_user('lown', email='lown@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.owner, organization=self.org, role='owner')
        self.admin = User.objects.create_user('ladm', email='ladm@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.admin, organization=self.org, role='admin')
        self.acme = Client.objects.create(org=self.org, name='Acme Motors')
        self.bay = Client.objects.create(org=self.org, name='Bayside')
        self.spring = Project.objects.create(org=self.org, client=self.acme, name='Spring Launch')
        self.web = Project.objects.create(org=self.org, client=self.acme, name='Website')
        self.radio = Project.objects.create(org=self.org, client=self.bay, name='Radio')
        self.misc = Project.objects.create(org=self.org, client=self.bay, name='Misc')
        pb.set_monthly_budget(self.spring, 20, month=date(2026, 9, 1))
        pb.set_monthly_budget(self.web, 30, month=OCT)
        pb.set_monthly_budget(self.radio, 10, month=OCT)

        t = datetime(2026, 10, 6, 15, 0, tzinfo=dt_timezone.utc)
        self.block(self.spring, t, 26 * 60 + 30)      # 26.5h on a 20h budget
        self.block(self.web, t + timedelta(days=1), 6 * 60)
        self.block(self.misc, t + timedelta(days=2), 90)  # time, no budget

    def block(self, project, start, minutes, user=None):
        # One block per hour so no single block trips the >6h anomaly rule.
        user = user or self.owner
        made = 0
        while made < minutes:
            m = min(60, minutes - made)
            s = start + timedelta(minutes=made * 2)
            Block.objects.create(
                org=self.org, user=user, hostname='mac', device_id='d', start=s,
                end=s + timedelta(minutes=m), minutes=m, app_name='Photoshop',
                window_title='x.psd', title='x.psd', classification_state='committed',
                is_categorized=True, is_billable=True, client=project.client, project=project,
                category_hours={'Design': m / 60})
            made += m

    def query(self, user, **over):
        api = APIClient()
        api.force_authenticate(user)
        return api.post('/api/analytics/query/', oct_body(**over), format='json')


class WindowMathTests(Base):
    def test_proration_by_calendar_days(self):
        # 10 days of a 31-day October holds 10/31 of the budget.
        out = pb.window_budget(self.org, date(2026, 10, 1), date(2026, 10, 10), [self.web])
        self.assertEqual(out[self.web.id][0], (Decimal('30') * 10 / 31).quantize(Decimal('0.01')))
        # A quarter holds three months of a carried-forward budget.
        q = pb.window_budget(self.org, date(2026, 10, 1), date(2026, 12, 31), [self.spring])
        self.assertEqual(q[self.spring.id], (Decimal('60.00'), Decimal('9900.00')))

    def test_to_date_period_judges_the_whole_month(self):
        """'This month' on Oct 10 must budget all of October with 10/31 gone —
        not ten days of budget with the period called finished."""
        from tracker.analytics_v2.lenses.projects import build_rows
        from tracker.analytics_v2.types import Scope, TimeRange
        t = TimeRange(OCT, date(2026, 10, 10), 'October 2026', 'this_month')
        with mock.patch('django.utils.timezone.localdate', return_value=date(2026, 10, 10)):
            data = build_rows(self.org, Scope(type='firm'), t)
        web = next(r for r in data['rows'] if r['label'] == 'Website')
        gone = round(10 / 31, 3)
        self.assertEqual(web['budget_hours'], 30.0)
        self.assertEqual(data['totals']['elapsed'], gone)
        # Earned so far (fee × share gone) over hours used — not the whole
        # month's fee over ten days of hours.
        self.assertEqual(web['effective_rate'], round(4950 * gone / 6, 2))

    def test_elapsed(self):
        self.assertEqual(pb.window_elapsed(OCT, date(2026, 10, 31), today=date(2026, 11, 5)), 1.0)
        self.assertEqual(pb.window_elapsed(OCT, date(2026, 10, 31), today=date(2026, 9, 5)), 0.0)


class LensTests(Base):
    def test_rows_flags_and_effective_rate(self):
        with mock.patch.object(pb, 'window_elapsed', return_value=1.0):
            r = self.query(self.owner)
        self.assertEqual(r.status_code, 200, r.content[:300])
        sections = r.data['sections']
        table = sections[1]['children'][0]
        rows = {x['label']: x for x in table['rows']}

        spring = rows['Spring Launch']
        self.assertEqual((spring['budget_hours'], spring['hours'], spring['fee']), (20.0, 26.5, 3300.0))
        self.assertEqual(spring['effective_rate'], round(3300 / 26.5, 2))   # $124.53, not $165
        self.assertEqual(spring['flag_label'], 'Over budget')
        self.assertEqual(spring['cost'], 26.5 * 40)
        self.assertEqual(rows['Misc']['flag_label'], 'No budget')
        self.assertIsNone(rows['Misc']['fee'])
        self.assertEqual(rows['Radio']['hours'], 0)         # budgeted, untouched -> still listed

        tiles = {t['id']: t for t in sections[0]['tiles']}
        self.assertEqual(tiles['project_fees']['metric']['value'], 3300 + 4950 + 1650)
        self.assertEqual(tiles['projects_over_budget']['metric']['value'], 1)
        self.assertIn('labor_cost', tiles)                  # owner sees cost

        clients = sections[2]['children'][0]['rows']
        self.assertEqual([c['label'] for c in clients], ['Acme Motors', 'Bayside'])

    def test_ahead_of_pace_only_while_running(self):
        with mock.patch.object(pb, 'window_elapsed', return_value=0.2):
            rows = {x['label']: x for x in self.query(self.owner).data['sections'][1]['children'][0]['rows']}
        self.assertEqual(rows['Website']['flag_label'], '')    # 20% burn at 20% gone
        self.web_more = self.block(self.web, datetime(2026, 10, 8, 15, tzinfo=dt_timezone.utc), 6 * 60)
        with mock.patch.object(pb, 'window_elapsed', return_value=0.2):
            rows = {x['label']: x for x in self.query(self.owner).data['sections'][1]['children'][0]['rows']}
        self.assertEqual(rows['Website']['flag_label'], 'Ahead of pace')  # 40% burn at 20% gone

    def test_cost_is_owner_only(self):
        r = self.query(self.admin)
        self.assertEqual(r.status_code, 200)
        tile_ids = {t['id'] for t in r.data['sections'][0]['tiles']}
        self.assertNotIn('labor_cost', tile_ids)
        self.assertNotIn('gross_margin', tile_ids)
        self.assertIn('project_effective_rate', tile_ids)
        table = r.data['sections'][1]['children'][0]
        self.assertFalse({'cost', 'margin', 'margin_pct'} & {c['key'] for c in table['columns']})
        self.assertFalse({'cost', 'margin', 'margin_pct'} & set(table['rows'][0]))

    def test_client_scope(self):
        r = self.query(self.owner, scope={"type": "client", "ids": [self.bay.id]})
        self.assertEqual(r.status_code, 200)
        labels = {x['label'] for x in r.data['sections'][1]['children'][0]['rows']}
        self.assertEqual(labels, {'Radio', 'Misc'})
        self.assertEqual(len(r.data['sections']), 2)        # no client roll-up inside one client

    def test_offered_in_permissions(self):
        api = APIClient()
        api.force_authenticate(self.owner)
        perms = api.get('/api/analytics/permissions/').data
        self.assertIn('projects', perms['capabilities']['available_lenses'])


class CpaTests(Base):
    industry = 'cpa'

    def test_not_offered_and_refused(self):
        api = APIClient()
        api.force_authenticate(self.owner)
        perms = api.get('/api/analytics/permissions/').data
        self.assertNotIn('projects', perms['capabilities']['available_lenses'])
        self.assertEqual(self.query(self.owner).status_code, 403)
