"""
QuickBooks sub-customers are projects of their company, never clients.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.qbo_subcustomer_test --noinput < /dev/null

What is pinned:
  - the QuickBooks Online import makes a project under the top-level company
    for each sub-customer (reusing the one QuickBooks Time made), and fetches
    the company when only the sub-customer was selected
  - a sub-customer imported as a client before is left alone and reported
  - the twin finder spots those leftover clients; fold_subcustomer_clients
    folds them into the company
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from tracker import views_integrations
from tracker.models import Block, Client, Integration, Organization, Project
from tracker.services.client_conversion import find_project_twins, find_qbo_subcustomer_clients

User = get_user_model()


def company(i, name):
    return {'Id': str(i), 'DisplayName': name}


def sub(i, name, parent):
    return {'Id': str(i), 'DisplayName': name, 'Job': True, 'ParentRef': {'value': str(parent)}}


def answer(*customers):
    return ({'QueryResponse': {'Customer': list(customers)}}, None)


class QboImportTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-qbo')
        self.integ = Integration.objects.create(organization=self.org, provider='quickbooks',
                                                is_connected=True, realm_id='R1')

    def run_import(self, responses, ids=None):
        with mock.patch.object(views_integrations, 'qb_api_call', side_effect=responses) as call, \
             mock.patch.object(views_integrations, 'run_post_import_alias_derivation'):
            result, err = views_integrations.import_qb_customers(self.org, self.integ, ids)
        self.assertIsNone(err)
        return result, call

    def test_sub_customers_become_projects_of_their_company(self):
        result, _ = self.run_import([answer(
            sub(11, 'Acme Spring Campaign', 1), company(1, 'Acme Motors'),
            sub(12, 'Acme Radio Cut', 11), company(2, 'Bolt Motors'))])
        acme = Client.objects.get(org=self.org, name='Acme Motors')
        self.assertEqual(set(Client.objects.filter(org=self.org, imported_from='quickbooks')
                             .values_list('name', flat=True)), {'Acme Motors', 'Bolt Motors'})
        self.assertEqual(set(Project.objects.filter(client=acme).values_list('name', flat=True)),
                         {'Acme Spring Campaign', 'Acme Radio Cut'})      # nested sub goes to the top
        self.assertEqual((result['summary']['imported_count'], result['summary']['project_count']), (2, 2))

    def test_reuses_the_project_quickbooks_time_made(self):
        acme = Client.objects.create(org=self.org, name='Acme Motors')
        qbt = Project.objects.create(org=self.org, client=acme, name='ACME Spring Campaign')
        self.run_import([answer(company(1, 'Acme Motors'), sub(11, 'Acme Spring Campaign', 1))])
        self.assertEqual(list(Project.objects.filter(client=acme)), [qbt])
        acme.refresh_from_db()
        self.assertEqual(acme.quickbooks_id, '1')                           # linked by name

    def test_selected_sub_customer_fetches_its_company(self):
        result, call = self.run_import([answer(sub(11, 'Acme Spring Campaign', 1)),
                                        answer(company(1, 'Acme Motors'))], ids=['11'])
        self.assertEqual(call.call_count, 2)
        self.assertIn("'1'", call.call_args_list[1].kwargs['params']['query'])
        acme = Client.objects.get(org=self.org, name='Acme Motors')
        self.assertTrue(Project.objects.filter(client=acme, name='Acme Spring Campaign').exists())

    def test_sub_customer_imported_as_a_client_before_is_reported(self):
        old = Client.objects.create(org=self.org, name='Acme Spring Campaign', quickbooks_id='11')
        result, _ = self.run_import([answer(company(1, 'Acme Motors'), sub(11, 'Acme Spring Campaign', 1))])
        old.refresh_from_db()
        self.assertTrue(old.is_active)
        self.assertIn('fold it into its company', result['skipped'][0]['reason'])

    def test_preview_marks_projects(self):
        from rest_framework.test import APIClient
        from tracker.models import OrganizationMembership
        u = User.objects.create_user('kim', email='k@mtc.test', password='x')
        OrganizationMembership.objects.create(user=u, organization=self.org, role='admin')
        api = APIClient()
        api.force_authenticate(u)
        with mock.patch.object(views_integrations, 'qb_api_call',
                               return_value=answer(company(1, 'Acme Motors'), sub(11, 'Acme Spring', 1))):
            r = api.get('/api/integrations/quickbooks/customers/')
        rows = {c['id']: c for c in r.json()['customers']}
        self.assertEqual((rows['1']['is_project'], rows['11']['is_project']), (False, True))
        self.assertEqual(rows['11']['parent_id'], '1')


class MarketingImportRuleTests(TestCase):
    """An agency's hands-off import makes clients only of customers with projects."""
    LIST = (company(1, 'Acme Motors'), sub(11, 'Acme Spring Campaign', 1),
            company(2, 'Visa Cardholder-3'), company(3, 'Stripe Sales'))

    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-rule', industry_type='marketing')
        self.integ = Integration.objects.create(organization=self.org, provider='quickbooks',
                                                is_connected=True, realm_id='R1')

    def run_import(self, ids=None, customers=None):
        with mock.patch.object(views_integrations, 'qb_api_call',
                               return_value=answer(*(customers or self.LIST))), \
             mock.patch.object(views_integrations, 'run_post_import_alias_derivation'):
            result, err = views_integrations.import_qb_customers(self.org, self.integ, ids)
        self.assertIsNone(err)
        return result

    def names(self):
        return set(Client.objects.filter(org=self.org, imported_from='quickbooks').values_list('name', flat=True))

    def test_agency_import_skips_customers_without_projects(self):
        result = self.run_import()
        self.assertEqual(self.names(), {'Acme Motors'})
        reasons = {s['name']: s['reason'] for s in result['skipped']}
        self.assertIn('No projects', reasons['Stripe Sales'])

    def test_a_customer_already_in_timetracker_is_still_linked(self):
        stripe = Client.objects.create(org=self.org, name='Stripe Sales')
        self.run_import()
        stripe.refresh_from_db()
        self.assertEqual(stripe.quickbooks_id, '3')

    def test_a_customer_picked_by_hand_is_imported(self):
        self.run_import(ids=['2'], customers=(company(2, 'Visa Cardholder-3'),))
        self.assertEqual(self.names(), {'Visa Cardholder-3'})

    def test_other_verticals_import_every_customer(self):
        Organization.objects.filter(pk=self.org.pk).update(industry_type='cpa')
        self.org.refresh_from_db()
        self.run_import()
        self.assertEqual(self.names(), {'Acme Motors', 'Visa Cardholder-3', 'Stripe Sales'})


class TwinCleanupTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-twins')
        self.user = User.objects.create_user('pat', email='p@mtc.test', password='x')
        self.acme = Client.objects.create(org=self.org, name='Acme Motors', imported_from='quickbooks')
        self.proj = Project.objects.create(org=self.org, client=self.acme, name='Acme Spring Campaign')
        self.twin = Client.objects.create(org=self.org, name='Acme Spring Campaign', imported_from='quickbooks')

    def test_finds_a_quickbooks_client_named_like_a_project(self):
        [t] = find_project_twins(self.org.id)
        self.assertEqual((t.client, t.parent, t.project), (self.twin, self.acme, self.proj))

    def test_ignores_hand_made_clients_unless_asked(self):
        Client.objects.filter(pk=self.twin.pk).update(imported_from='')
        self.assertEqual(find_project_twins(self.org.id), [])
        self.assertEqual(len(find_project_twins(self.org.id, any_source=True)), 1)

    def test_ignores_a_name_that_is_a_project_of_two_companies(self):
        bolt = Client.objects.create(org=self.org, name='Bolt Motors')
        Project.objects.create(org=self.org, client=bolt, name='Acme Spring Campaign')
        self.assertEqual(find_project_twins(self.org.id), [])

    def test_command_folds_into_the_existing_project(self):
        s = datetime(2026, 10, 6, 14, 0, tzinfo=dt_timezone.utc)
        b = Block.objects.create(org=self.org, user=self.user, hostname='mac', device_id='d', start=s,
                                 end=s + timedelta(minutes=30), day=s.date(), minutes=30, title='x',
                                 classification_state='committed', is_categorized=True, client=self.twin)
        out = StringIO()
        call_command('fold_subcustomer_clients', org_id=self.org.id, stdout=out)
        self.assertIn('DRY RUN', out.getvalue())
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.twin.id)

        call_command('fold_subcustomer_clients', org_id=self.org.id, apply=True, stdout=StringIO())
        b.refresh_from_db(); self.twin.refresh_from_db()
        self.assertEqual((b.client_id, b.project_id), (self.acme.id, self.proj.id))
        self.assertFalse(self.twin.is_active)
        self.assertEqual(Project.objects.filter(client=self.acme).count(), 1)

    def test_qbo_finder_reads_quickbooks(self):
        Client.objects.filter(pk=self.acme.pk).update(quickbooks_id='1')
        Client.objects.filter(pk=self.twin.pk).update(quickbooks_id='11')
        Integration.objects.create(organization=self.org, provider='quickbooks', is_connected=True, realm_id='R')
        with mock.patch.object(views_integrations, 'qb_api_call',
                               return_value=answer(company(1, 'Acme Motors'), sub(11, 'Acme Spring Campaign', 1))):
            [t] = find_qbo_subcustomer_clients(self.org.id)
        self.assertEqual((t.client.pk, t.parent.pk, t.project.pk), (self.twin.pk, self.acme.pk, self.proj.pk))
