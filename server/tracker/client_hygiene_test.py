"""
MavOps flags a firm whose client list isn't what it works for.

Real database for the TestCase classes: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.client_hygiene_test --noinput < /dev/null

What is pinned:
  - idle imported clients are flagged when many or most of the list
  - a client named like another client's project is flagged
  - QuickBooks connected on a 'general' firm is flagged
  - the MavOps org list carries the flag as a 'warn', never 'critical'
  - prune_dormant_clients --all-orgs summarises and can't write
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from tracker.models import Client, Integration, Organization, Project
from tracker.services.client_hygiene import client_hygiene_by_org, hygiene_reasons

User = get_user_model()


class ReasonTests(SimpleTestCase):
    def test_thresholds(self):
        self.assertEqual(hygiene_reasons({'idle': 24, 'active': 400}), [])
        self.assertTrue(hygiene_reasons({'idle': 25, 'active': 400}))          # many
        self.assertTrue(hygiene_reasons({'idle': 11, 'active': 20}))           # most
        self.assertEqual(hygiene_reasons({'idle': 3, 'active': 5}), [])        # a new firm
        self.assertIn('fold_subcustomer_clients', hygiene_reasons({'twins': 2})[0])
        self.assertIn("'general'", hygiene_reasons({'vertical_unset': True})[0])


class HygieneTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-hyg', industry_type='marketing')
        acme = Client.objects.create(org=self.org, name='Acme Motors', imported_from='quickbooks')
        Project.objects.create(org=self.org, client=acme, name='Acme Spring Campaign')
        Client.objects.create(org=self.org, name='Acme Spring Campaign', imported_from='quickbooks')
        for i in range(30):
            Client.objects.create(org=self.org, name=f'Visa Cardholder-{i}', imported_from='qb_time')
        Client.objects.create(org=self.org, name='Hand Made', imported_from='')

    def test_counts(self):
        h = client_hygiene_by_org([self.org.id])[self.org.id]
        # Internal (made with the org) is not counted; the twin is idle too.
        self.assertEqual((h['active'], h['idle'], h['twins'], h['vertical_unset']), (33, 31, 1, False))
        self.assertEqual(len(h['reasons']), 2)

    def test_general_firm_with_quickbooks(self):
        Organization.objects.filter(pk=self.org.pk).update(industry_type='general')
        Integration.objects.create(organization=self.org, provider='qb_time', is_connected=True)
        self.assertTrue(client_hygiene_by_org([self.org.id])[self.org.id]['vertical_unset'])

    def test_mavops_org_list_warns(self):
        staff = User.objects.create_user('ops', email='ops@mavops.test', password='x', is_staff=True)
        api = APIClient()
        api.force_authenticate(staff)
        row = {o['id']: o for o in api.get('/api/mavops/orgs/').json()['orgs']}[self.org.id]
        self.assertEqual(row['client_hygiene']['idle'], 31)
        self.assertEqual(row['health']['status'], 'warn')
        self.assertTrue(any('prune_dormant_clients' in r for r in row['health']['reasons']))

    def test_prune_all_orgs_is_read_only(self):
        out = StringIO()
        call_command('prune_dormant_clients', all_orgs=True, stdout=out)
        self.assertIn('MTC', out.getvalue())
        self.assertIn('31 dormant clients across 1 orgs', out.getvalue())
        self.assertEqual(Client.objects.filter(org=self.org, is_active=True).count(), 34)  # 33 + Internal
        with self.assertRaises(CommandError):
            call_command('prune_dormant_clients', all_orgs=True, apply=True, stdout=StringIO())
