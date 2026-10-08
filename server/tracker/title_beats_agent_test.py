"""
When the classifier and the agent disagree about a block's client, the window
titles decide if they name one side and not the other.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.title_beats_agent_test --noinput < /dev/null

The case: a block opened while the tray said Direct Exteriors, then spent on
"Easterns Automotive Group Scope Addendum 6-1 - Google Docs". The classifier
said Easterns (its own title match and the agent's later guess); apply() kept
the block's first, agent-set client and committed it to Direct Exteriors.

Drives the REAL ClassificationService.apply, with arbitrate_disagreements off
(the default).
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.models import Block, Client, Organization, RawEvent
from tracker.services.classification_service import (
    ClassificationDecision, ClassificationService,
)

User = get_user_model()
T0 = datetime(2026, 10, 8, 14, 0, tzinfo=dt_timezone.utc)
EASTERNS_DOC = 'Easterns Automotive Group Scope Addendum 6-1 - Google Docs'
DIRECT_DOC = 'Direct Exteriors Fall Mailer - Google Docs'


class TitleBeatsAgentTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-arb')
        self.assertFalse(self.org.arbitrate_disagreements)
        self.user = User.objects.create_user('pat', email='p@mtc.test', password='x')
        self.easterns = Client.objects.create(org=self.org, name='Easterns Automotive Group')
        self.direct = Client.objects.create(org=self.org, name='Direct Exteriors')

    def apply(self, spans, agent_client):
        """spans: [(title, seconds)] in order; the block starts on the agent's client."""
        total = sum(s for _, s in spans)
        block = Block.objects.create(
            org=self.org, user=self.user, hostname='mac', device_id='d', start=T0,
            end=T0 + timedelta(seconds=total), day=T0.date(), minutes=max(1, total // 60),
            title='Google Chrome', app_name='Google Chrome', client=agent_client)
        t = T0
        for title, secs in spans:
            RawEvent.objects.create(user=self.user, device_id='d', hostname='mac', block=block,
                                    start_ts=t, end_ts=t + timedelta(seconds=secs),
                                    app_name='Google Chrome', window_title=title)
            t += timedelta(seconds=secs)
        decision = ClassificationDecision()
        decision.client_id = self.easterns.id
        decision.recommended_state = 'committed'
        decision.confidence = 0.83
        decision.is_billable = True
        svc = ClassificationService(self.org, self.user)
        svc._clients = list(Client.objects.filter(org=self.org))
        svc.apply(block, decision)
        block.refresh_from_db()
        return block

    def test_title_naming_the_classifiers_client_wins(self):
        b = self.apply([(DIRECT_DOC, 10), (EASTERNS_DOC, 50)], agent_client=self.direct)
        self.assertEqual(b.client_id, self.easterns.id)

    def test_agent_kept_when_titles_mostly_name_its_client(self):
        b = self.apply([(DIRECT_DOC, 50), (EASTERNS_DOC, 10)], agent_client=self.direct)
        self.assertEqual(b.client_id, self.direct.id)

    def test_agent_kept_when_titles_name_neither(self):
        b = self.apply([('Inbox (5,301) - Gmail', 60)], agent_client=self.direct)
        self.assertEqual(b.client_id, self.direct.id)
        self.assertTrue(b.ai_disagrees_with_agent)   # still flagged for review
