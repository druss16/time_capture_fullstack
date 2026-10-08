"""
A sub-2-minute sliver isn't billed on the agent's word that the title names a
client unless the server can read that client in the title itself.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.sliver_agent_title_test --noinput < /dev/null

The case: a "New 2026 Chrysler Pacifica Select Passenger Van ... | Easterns
Chrysler Dodge Jeep Ram" listing. The agent matched "Van" to the acronym of
Vehicle Acquisition Network (title_alias_match, 0.85); the server had nothing
to contradict it, and the 1-minute sliver auto-committed to the wrong client.

Drives the REAL ClassificationService._finalize_decision.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.models import Block, Client, Organization, RawEvent
from tracker.services.classification_service import (
    ClassificationDecision, ClassificationService, Signal,
)

User = get_user_model()
T0 = datetime(2026, 10, 7, 23, 12, tzinfo=dt_timezone.utc)
LISTING = ('New 2026 Chrysler Pacifica Select Passenger Van in Camp Springs #C181444 '
           '| Easterns Chrysler Dodge Jeep Ram')


class SliverAgentTitleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-sliver')
        self.user = User.objects.create_user('pat', email='p@mtc.test', password='x')
        self.van = Client.objects.create(org=self.org, name='Vehicle Acquisition Network')

    def finalize(self, window_title, sources=('title_alias_match',), minutes=1, extra=()):
        block = Block.objects.create(
            org=self.org, user=self.user, hostname='mac', device_id='d', start=T0,
            end=T0 + timedelta(minutes=minutes), day=T0.date(), minutes=minutes,
            title='Google Chrome', app_name='Google Chrome')
        RawEvent.objects.create(user=self.user, device_id='d', hostname='mac', block=block,
                                start_ts=T0, end_ts=T0 + timedelta(seconds=30),
                                app_name='Google Chrome', window_title=window_title)
        svc = ClassificationService(self.org, self.user)
        svc._clients = list(Client.objects.filter(org=self.org, is_active=True))
        decision = ClassificationDecision()
        decision.matched_signals = [Signal(
            type='agent_inference', strength=0.75, evidence='agent',
            detail={'client_id': self.van.id, 'inference_evidence_sources': list(sources)},
        ), *extra]
        return ClassificationService._finalize_decision(svc, decision, block)

    def types(self, d):
        return {s.type for s in d.matched_signals}

    def test_title_that_does_not_name_the_client_files_no_client(self):
        d = self.finalize(LISTING)
        self.assertIsNone(d.client_id)
        self.assertEqual(d.recommended_state, 'committed')
        self.assertIn('agent_title_unverified', self.types(d))
        self.assertIn('auto_confirm_immaterial_noclient', self.types(d))

    def test_title_naming_the_client_still_commits(self):
        d = self.finalize('Vehicle Acquisition Network - Q3 invoices - Google Sheets')
        self.assertEqual((d.client_id, d.recommended_state), (self.van.id, 'committed'))

    def test_uppercase_acronym_still_commits(self):
        d = self.finalize('VAN Q3 report.xlsx')
        self.assertEqual(d.client_id, self.van.id)

    def test_a_tray_pick_is_not_second_guessed(self):
        d = self.finalize(LISTING, sources=('manual_user_override',))
        self.assertEqual(d.client_id, self.van.id)
        self.assertNotIn('agent_title_unverified', self.types(d))

    def test_a_corroborated_claim_is_not_second_guessed(self):
        other = Signal(type='prior_block', strength=0.7, evidence='same client before',
                       detail={'client_id': self.van.id})
        d = self.finalize(LISTING, extra=(other,))
        self.assertEqual(d.client_id, self.van.id)

    def test_material_blocks_are_untouched(self):
        d = self.finalize(LISTING, minutes=5)
        self.assertNotIn('agent_title_unverified', self.types(d))
        self.assertNotEqual(d.recommended_state, 'committed')
