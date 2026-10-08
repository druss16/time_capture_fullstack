"""
The agent re-pulls its client list when /sync/status/ says something changed.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.sync_status_hash_test --noinput < /dev/null

The clients hash used to be max id + count, so an alias added or a client
renamed never reached a running agent; deactivating a client did (the count
moved). All three must change it now, and an unrelated edit must not.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tracker.models import Client, Organization, OrganizationMembership, Project

User = get_user_model()


class ClientHashTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-sync')
        self.user = User.objects.create_user('pat', email='p@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.acme = Client.objects.create(org=self.org, name='Acme Motors')
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def hashes(self):
        e = self.api.get('/api/sync/status/').json()['entities']
        return e['clients']['hash'], e['projects']['hash']

    def test_alias_rename_and_deactivation_change_the_clients_hash(self):
        seen = {self.hashes()[0]}
        Client.objects.filter(pk=self.acme.pk).update(aliases=['Acme'])
        seen.add(self.hashes()[0])
        Client.objects.filter(pk=self.acme.pk).update(name='Acme Motors Group')
        seen.add(self.hashes()[0])
        Client.objects.filter(pk=self.acme.pk).update(is_active=False)
        seen.add(self.hashes()[0])
        self.assertEqual(len(seen), 4)

    def test_project_rename_changes_the_projects_hash(self):
        p = Project.objects.create(org=self.org, client=self.acme, name='Spring')
        before = self.hashes()[1]
        Project.objects.filter(pk=p.pk).update(name='Spring Launch')
        self.assertNotEqual(self.hashes()[1], before)

    def test_unrelated_edit_does_not(self):
        before = self.hashes()
        Client.objects.filter(pk=self.acme.pk).update(email='x@acme.test')
        self.assertEqual(self.hashes(), before)
