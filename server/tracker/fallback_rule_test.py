"""
A firm's own company gets its own work, but only when no client is named.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.fallback_rule_test --noinput < /dev/null

More Than Cars' "Meet - MTC Heads" sat in Needs You ("second-pass:
unrecognized"). An ordinary routing rule would fix it and break "Easterns
weekly recap - MTC", because routing rules run first and override every
client. A fallback_to_client rule applies only after the classifier found no
client, and never reaches the agents.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tracker.models import Block, Client, Organization, OrganizationMembership, OrgRoutingRule
from tracker.services.classification_service import ClassificationService

User = get_user_model()
T0 = datetime(2026, 10, 8, 14, 0, tzinfo=dt_timezone.utc)
HOUSE = r'\b(?-i:MTC)\b|More Than Cars(?!\s+Media)'


class FallbackRuleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='More Than Cars', slug='mtc-fb', industry_type='marketing')
        self.user = User.objects.create_user('al', email='al@mtc.test', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.creative = Client.objects.create(org=self.org, name='More Than Cars Creative')
        self.media = Client.objects.create(org=self.org, name='More Than Cars Media')
        self.easterns = Client.objects.create(org=self.org, name='Easterns Automotive Group',
                                              aliases=['Easterns'])
        self.rule = OrgRoutingRule.objects.create(
            org=self.org, match_type='title_regex', match_value=HOUSE,
            action='fallback_to_client', target_client=self.creative,
            runs_at='classifier', priority=100)
        self._n = 0

    def classify(self, title, client=None):
        self._n += 1
        s = T0 + timedelta(minutes=30 * self._n)
        block = Block.objects.create(
            org=self.org, user=self.user, hostname='mac', device_id='d', start=s,
            end=s + timedelta(minutes=12), day=s.date(), minutes=12, app_name='Google Chrome',
            window_title=title, title=title, client=client)
        return ClassificationService(self.org, self.user).classify(block, skip_ai=True)

    def test_house_meeting_goes_to_the_house_client(self):
        d = self.classify('Meet - MTC Heads')
        self.assertEqual((d.client_id, d.recommended_state), (self.creative.id, 'committed'))

    def test_firm_name_spelled_out(self):
        d = self.classify('Marketing Account Executive | Syracuse, NY | More Than Cars')
        self.assertEqual(d.client_id, self.creative.id)

    def test_a_named_client_wins(self):
        d = self.classify('Easterns weekly recap - MTC')
        self.assertEqual(d.client_id, self.easterns.id)

    def test_media_is_its_own_client(self):
        d = self.classify('More Than Cars Media - rate card')
        self.assertNotEqual(d.client_id, self.creative.id)

    def test_block_that_already_has_a_client_is_left_alone(self):
        d = self.classify('Meet - MTC Heads', client=self.easterns)
        self.assertFalse(any(s.type == 'org_rule' for s in d.matched_signals))

    def test_lowercase_mtc_is_not_the_firm(self):
        d = self.classify('docs.google.com/d/1mtc9x - Google Docs')
        self.assertNotEqual(d.client_id, self.creative.id)

    def test_agents_never_receive_fallback_rules(self):
        OrgRoutingRule.objects.create(org=self.org, match_type='title_contains', match_value='UltraTax',
                                      action='route_to_client', target_client=self.easterns)
        api = APIClient()
        api.force_authenticate(self.user)
        rules = api.get('/api/sync/full/').json()['routing_rules']
        self.assertEqual([r['action'] for r in rules], ['route_to_client'])
