"""
Monthly project budgets (agencies: fee = rate × estimated hours per month).

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.project_budgets_test --noinput < /dev/null
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from tracker.models import (
    BillingRate, Block, Client, Organization, OrganizationMembership, Project, ProjectBudget,
)
from tracker.services import project_budgets as pb

User = get_user_model()
OCT = date(2026, 10, 1)


class PureTests(SimpleTestCase):
    def test_months(self):
        self.assertEqual(pb.parse_month('2026-10'), OCT)
        self.assertEqual(pb.parse_month('2026-10-17'), OCT)
        self.assertEqual(pb.next_month(date(2026, 12, 1)), date(2027, 1, 1))
        self.assertEqual(pb.month_elapsed(OCT, today=date(2026, 11, 3)), 1.0)
        self.assertEqual(pb.month_elapsed(OCT, today=date(2026, 9, 3)), 0.0)
        self.assertAlmostEqual(pb.month_elapsed(OCT, today=date(2026, 10, 31)), 1.0)
        self.assertAlmostEqual(pb.month_elapsed(OCT, today=date(2026, 10, 1)), round(1 / 31, 3))


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-b', industry_type='marketing',
                                               billing_rate_default=Decimal('165'))
        self.owner = User.objects.create_user('own', email='own@mtc.test', password='x')
        self.m = OrganizationMembership.objects.create(user=self.owner, organization=self.org, role='owner')
        self.acme = Client.objects.create(org=self.org, name='Acme Motors')
        self.bay = Client.objects.create(org=self.org, name='Bayside')
        self.spring = Project.objects.create(org=self.org, client=self.acme, name='Spring Launch')
        self.web = Project.objects.create(org=self.org, client=self.acme, name='Website')
        self.radio = Project.objects.create(org=self.org, client=self.bay, name='Radio')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def block(self, project, start, minutes=60):
        return Block.objects.create(
            org=self.org, user=self.owner, hostname='mac', device_id='d', start=start,
            end=start + timedelta(minutes=minutes), minutes=minutes, app_name='Photoshop',
            window_title='x.psd', title='x.psd', classification_state='committed',
            is_categorized=True, is_billable=True, client=project.client, project=project,
            category_hours={'Design': minutes / 60})


class BudgetTests(Base):
    def test_carries_forward_and_keeps_history(self):
        pb.set_monthly_budget(self.spring, 20, month=date(2026, 8, 1))
        pb.set_monthly_budget(self.spring, 30, month=OCT)
        get = lambda m: pb.budgets_in_effect(self.org, m)[self.spring.id].monthly_hours
        self.assertEqual(get(date(2026, 9, 1)), Decimal('20'))   # carried forward
        self.assertEqual(get(date(2026, 8, 1)), Decimal('20'))
        self.assertEqual(get(date(2026, 12, 1)), Decimal('30'))
        self.assertNotIn(self.spring.id, pb.budgets_in_effect(self.org, date(2026, 7, 1)))

    def test_source_estimate_never_overrides_a_person(self):
        with mock.patch.object(pb, 'month_start', return_value=OCT):
            self.assertEqual(pb.apply_source_estimate(self.spring, Decimal('20')), 'applied')
            self.assertEqual(pb.apply_source_estimate(self.spring, Decimal('20')), 'unchanged')
            self.assertEqual(pb.apply_source_estimate(self.spring, Decimal('25')), 'applied')
            pb.set_monthly_budget(self.spring, 18, month=OCT, source='manual')
            self.assertEqual(pb.apply_source_estimate(self.spring, Decimal('40')), 'kept_manual')
        self.assertEqual(ProjectBudget.objects.get(project=self.spring).monthly_hours, Decimal('18'))

    def test_fee_rate_client_override_else_firm(self):
        BillingRate.objects.create(org=self.org, user=None, client=self.bay, rate=Decimal('140'),
                                   effective_date=date(2026, 1, 1))
        # A per-person rate is not the client's fee rate.
        BillingRate.objects.create(org=self.org, user=self.owner, client=self.acme, rate=Decimal('99'),
                                   effective_date=date(2026, 1, 1))
        rates = pb.fee_rates(self.org, {self.acme.id, self.bay.id}, OCT)
        self.assertEqual(rates, {self.acme.id: Decimal('165'), self.bay.id: Decimal('140')})

    def test_summary(self):
        pb.set_monthly_budget(self.spring, 20, month=OCT)
        pb.set_monthly_budget(self.radio, 10, month=OCT)
        t = datetime(2026, 10, 6, 15, 0, tzinfo=dt_timezone.utc)
        self.block(self.spring, t, 90)
        self.block(self.spring, t + timedelta(hours=2), 30)
        self.block(self.spring, datetime(2026, 9, 20, 15, 0, tzinfo=dt_timezone.utc), 600)  # other month
        s = pb.month_summary(self.org, OCT)
        rows = {r['project']: r for r in s['rows']}
        self.assertEqual(rows['Spring Launch']['actual_hours'], 2.0)
        self.assertEqual(rows['Spring Launch']['fee'], 3300.0)
        self.assertEqual(rows['Spring Launch']['burn_pct'], 10.0)
        self.assertIsNone(rows['Website']['budget_hours'])
        acme = next(c for c in s['clients'] if c['client'] == 'Acme Motors')
        self.assertEqual((acme['fee'], acme['unbudgeted_projects']), (3300.0, 1))
        self.assertEqual(rows['Spring Launch']['delta_hours'], 18.0)    # 20 budgeted − 2 used
        self.assertIsNone(rows['Website']['delta_hours'])                # no budget, no delta

    def test_client_delta_counts_time_on_no_project(self):
        pb.set_monthly_budget(self.spring, 20, month=OCT)
        t = datetime(2026, 10, 6, 15, 0, tzinfo=dt_timezone.utc)
        self.block(self.spring, t, 300)                                  # 5h on the project
        loose = self.block(self.spring, t + timedelta(hours=8), 120)     # 2h, then unfiled
        Block.objects.filter(id=loose.id).update(project=None)
        acme = next(c for c in pb.month_summary(self.org, OCT)['clients'] if c['client'] == 'Acme Motors')
        self.assertEqual((acme['unassigned_hours'], acme['actual_hours'], acme['delta_hours']), (2.0, 7.0, 13.0))


class EndpointTests(Base):
    def test_set_and_read(self):
        r = self.api.put(f'/api/projects/{self.spring.id}/budget/',
                         {'monthly_hours': 20, 'month': '2026-10'}, format='json')
        self.assertEqual(r.status_code, 200)
        r = self.api.get('/api/projects/budgets/', {'month': '2026-11', 'client_id': self.acme.id})
        self.assertEqual(r.status_code, 200)
        row = next(x for x in r.data['rows'] if x['project_id'] == self.spring.id)
        self.assertEqual((row['budget_hours'], row['fee'], row['budget_source']), (20.0, 3300.0, 'manual'))
        self.assertEqual({x['client_id'] for x in r.data['rows']}, {self.acme.id})

    def test_validation_and_roles(self):
        bad = self.api.put(f'/api/projects/{self.spring.id}/budget/', {'monthly_hours': 'lots'}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.m.role = 'member'
        self.m.save()
        self.assertEqual(self.api.get('/api/projects/budgets/').status_code, 403)
        self.assertEqual(self.api.put(f'/api/projects/{self.spring.id}/budget/',
                                      {'monthly_hours': 5}, format='json').status_code, 403)

    def test_cpa_firm_has_no_project_budgets(self):
        self.org.industry_type = 'cpa'
        self.org.save()
        self.assertEqual(self.api.get('/api/projects/budgets/').status_code, 404)

    def test_csv_hours_column(self):
        text = 'Client,Project,Hours\nAcme Motors,Spring Launch,20\nAcme Motors,Social,12h\nBayside,Radio,abc'
        r = self.api.post('/api/projects/import/', {'text': text}, format='json')
        self.assertEqual(r.data['budgeted'], 2)
        self.assertEqual(len(r.data['skipped_lines']), 1)
        social = Project.objects.get(org=self.org, name='Social')
        self.assertEqual(ProjectBudget.objects.get(project=social).monthly_hours, Decimal('12'))
        self.assertEqual(ProjectBudget.objects.get(project=self.spring).source, 'csv')

    def test_picker_shows_monthly_hours(self):
        pb.set_monthly_budget(self.spring, 20)
        b = self.block(self.web, datetime.now(dt_timezone.utc) - timedelta(hours=1))
        r = self.api.get(f'/api/blocks/{b.id}/matter-options/')
        opt = next(o for o in r.data['options'] if o['project_id'] == self.spring.id)
        self.assertEqual(opt['monthly_hours'], 20.0)
