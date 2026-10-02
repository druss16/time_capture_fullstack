"""
"Switch Project" in the desktop ticker, behind a MavOps per-org switch.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.project_switch_test --noinput < /dev/null
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.models import (
    Block, Client, CurrentProject, Organization, OrganizationMembership, Project,
)
from tracker.services.feature_flags import PROJECT_SWITCH, feature_enabled, set_feature
from tracker.services.matter_attribution import attribute_matters_for_org

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Agency', slug='agency-ps', industry_type='marketing')
        self.user = User.objects.create_user('ps', email='ps@a.test', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='member')
        self.acme = Client.objects.create(org=self.org, name='Acme Motors', code='ACM')
        self.bay = Client.objects.create(org=self.org, name='Bayside', code='BAG')
        self.spring = Project.objects.create(org=self.org, client=self.acme, name='Spring Launch')
        self.web = Project.objects.create(org=self.org, client=self.acme, name='Website Refresh')
        self.radio = Project.objects.create(org=self.org, client=self.bay, name='Radio')
        self.bay_social = Project.objects.create(org=self.org, client=self.bay, name='Social')
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def block(self, client, minutes_ago, title='untitled.psd', length=5):
        start = timezone.now() - timedelta(minutes=minutes_ago)
        return Block.objects.create(
            org=self.org, user=self.user, hostname='mac', device_id='d', start=start,
            end=start + timedelta(minutes=length), minutes=length, app_name='Photoshop',
            window_title=title, title=title, classification_state='committed',
            is_categorized=True, client=client, categorized_by='ai', category_hours={'Design': 0.1})

    def pick(self, project_id):
        return self.api.post('/api/project/set-current/', {'project_id': project_id}, format='json')


class FlagTests(Base):
    def test_off_by_default_and_refused(self):
        self.assertFalse(feature_enabled(self.org, PROJECT_SWITCH))
        self.assertEqual(self.pick(self.spring.id).status_code, 403)

    def test_sync_carries_the_flag(self):
        set_feature(self.org, PROJECT_SWITCH, True)
        from tracker.views_sync import _project_switch_on
        self.assertTrue(_project_switch_on(self.org))

    def test_mavops_toggle_is_staff_only(self):
        self.assertEqual(self.api.post(f'/api/mavops/orgs/{self.org.id}/feature/',
                                       {'key': 'project_switch', 'enabled': True}, format='json').status_code, 403)
        staff = User.objects.create_user('staff', email='s@mavops.ai', password='x', is_staff=True)
        api = APIClient()
        api.force_authenticate(staff)
        r = api.post(f'/api/mavops/orgs/{self.org.id}/feature/', {'key': 'project_switch', 'enabled': True},
                     format='json')
        self.assertEqual((r.status_code, r.data['enabled']), (200, True))
        self.assertTrue(feature_enabled(self.org, PROJECT_SWITCH))
        bad = api.post(f'/api/mavops/orgs/{self.org.id}/feature/', {'key': 'nope', 'enabled': True}, format='json')
        self.assertEqual(bad.status_code, 400)
        listed = api.get('/api/mavops/orgs/').data
        rows = listed['orgs'] if isinstance(listed, dict) and 'orgs' in listed else listed
        row = next(o for o in rows if o['id'] == self.org.id)
        self.assertTrue(row['project_switch'])


class PickTests(Base):
    def setUp(self):
        super().setUp()
        set_feature(self.org, PROJECT_SWITCH, True)

    def test_backfills_recent_same_client_time_only(self):
        recent = self.block(self.acme, 10)
        old = self.block(self.acme, 60)
        other = self.block(self.bay, 5)
        r = self.pick(self.spring.id)
        self.assertEqual((r.status_code, r.data['retroactive_blocks']), (200, 1))
        for b in (recent, old, other):
            b.refresh_from_db()
        self.assertEqual(recent.project_id, self.spring.id)
        self.assertIsNone(old.project_id)
        self.assertIsNone(other.project_id)

    def test_sweep_files_later_work_but_convention_wins(self):
        self.pick(self.spring.id)
        CurrentProject.objects.update(started_at=timezone.now() - timedelta(minutes=30))
        later = self.block(self.acme, 5)
        named = self.block(self.acme, 3, title='ACM_AcmeMotors_WebsiteRefresh_hero.psd')
        bay = self.block(self.bay, 2)
        attribute_matters_for_org(self.org, days=1)
        for b in (later, named, bay):
            b.refresh_from_db()
        self.assertEqual(later.project_id, self.spring.id)
        self.assertEqual(named.project_id, self.web.id)       # the file is more specific
        self.assertIsNone(bay.project_id)                     # different client

    def test_stale_pick_is_ignored(self):
        self.pick(self.spring.id)
        CurrentProject.objects.update(started_at=timezone.now() - timedelta(hours=6))
        b = self.block(self.acme, 5)
        attribute_matters_for_org(self.org, days=1)
        b.refresh_from_db()
        self.assertIsNone(b.project_id)

    def test_clear_and_foreign_project(self):
        self.pick(self.spring.id)
        self.assertEqual(self.pick(None).status_code, 200)
        self.assertFalse(CurrentProject.objects.exists())
        other_org = Organization.objects.create(name='Other', slug='other-ps', industry_type='marketing')
        foreign = Project.objects.create(org=other_org,
                                         client=Client.objects.create(org=other_org, name='X'), name='Y')
        self.assertEqual(self.pick(foreign.id).status_code, 404)
