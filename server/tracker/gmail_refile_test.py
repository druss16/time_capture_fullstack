"""
Gmail compose re-file — the block that reached the server before its mail.

Real database (TestCase): run against a THROWAWAY Postgres, never the default
settings (the local docker DB is production):

    python manage.py test tracker.gmail_refile_test --noinput < /dev/null
"""
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase

from tracker.google_integration_test import ComposeBase
from tracker.models import Block, Client, ClassificationAudit, Project
from tracker.services.gmail_refile import refile_composed_gmail_blocks
from tracker.services.mail_compose import is_gmail_block
from tracker.utils.client_name_match import strip_app_chrome

BRANDED = 'Re: proofs - me@agency.com - Agency Mail - High memory usage - 859 MB - Google Chrome - me@agency.com'


class RefileBase(ComposeBase):
    def setUp(self):
        super().setUp()
        # The firm's own client — what a branded mailbox title used to name.
        self.own = Client.objects.create(org=self.org, name='Agency')

    def filed_block(self, start_min, end_min, client, **kw):
        """A Gmail block the classifier already filed, before any mail synced."""
        defaults = dict(
            url='', window_title=BRANDED, title=BRANDED,
            classification_state='committed', is_categorized=True, client=client,
            state_changed_by='classifier', category_hours={'Admin': 0.2},
        )
        defaults.update(kw)
        b = self.block(start_min, end_min)
        Block.objects.filter(pk=b.pk).update(**defaults)
        b.refresh_from_db()
        return b

    def refile(self):
        return refile_composed_gmail_blocks(
            self.user, self.org, self.T0 - timedelta(hours=1), self.T0 + timedelta(hours=2))



class RefileTest(RefileBase):
    def test_late_mail_refiles_the_block_to_the_compose_client(self):
        b = self.filed_block(0, 10, self.own)
        self.sent('o1', 9, 'bob@acme.com', self.acme, 'acme.com')  # 9 of 10 min writing
        self.assertEqual(self.refile(), 1)
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.acme.id)
        self.assertEqual(b.classification_state, 'committed')
        audit = ClassificationAudit.objects.filter(block=b).latest('id')
        self.assertEqual((audit.client_before_id, audit.client_after_id), (self.own.id, self.acme.id))

    def test_a_person_s_decision_is_never_overturned(self):
        for source in ('user', 'user_edit', 'correction'):
            b = self.filed_block(0, 10, self.own, state_changed_by=source)
            self.sent(f'o-{source}', 9, 'bob@acme.com', self.acme, 'acme.com')
            self.refile()
            b.refresh_from_db()
            self.assertEqual(b.client_id, self.own.id, source)
            b.delete()

    def test_a_short_reply_inside_long_inbox_time_is_not_enough(self):
        b = self.filed_block(0, 40, self.own)
        self.sent('o-x', 30, 'someone@unmapped.io', None, 'unmapped.io')
        self.sent('o-a', 32, 'bob@acme.com', self.acme, 'acme.com')  # 2 of 40 min
        self.assertEqual(self.refile(), 0)
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.own.id)

    def test_two_clients_in_one_block_are_left_for_review(self):
        b = self.filed_block(0, 10, self.own)
        self.sent('o-a', 4, 'bob@acme.com', self.acme, 'acme.com')
        self.sent('o-b', 9, 'ann@betafoods.com', self.beta, 'betafoods.com')
        self.assertEqual(self.refile(), 0)
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.own.id)

    def test_already_on_the_compose_client_is_a_no_op(self):
        self.filed_block(0, 10, self.acme)
        self.sent('o1', 9, 'bob@acme.com', self.acme, 'acme.com')
        self.assertEqual(self.refile(), 0)

    def test_old_client_s_project_is_dropped(self):
        project = Project.objects.create(org=self.org, client=self.own, name='Retainer')
        b = self.filed_block(0, 10, self.own, project=project)
        self.sent('o1', 9, 'bob@acme.com', self.acme, 'acme.com')
        self.refile()
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.acme.id)
        self.assertIsNone(b.project_id)

    def test_mail_integration_kill_switch(self):
        self.org.disable_mail_integration = True
        self.org.save(update_fields=['disable_mail_integration'])
        self.filed_block(0, 10, self.own)
        self.sent('o1', 9, 'bob@acme.com', self.acme, 'acme.com')
        self.assertEqual(self.refile(), 0)


class BrandedGmailTitleTest(SimpleTestCase):
    def gmail(self, title):
        return is_gmail_block(SimpleNamespace(url='', window_title=title, title=title))

    def test_renamed_workspace_gmail_is_gmail(self):
        self.assertTrue(self.gmail(BRANDED))
        self.assertTrue(self.gmail('Inbox - MavOps Mail - High memory usage - 830 MB - Google Chrome'))

    def test_other_mail_is_not(self):
        for t in ('Inbox - Yahoo Mail - Google Chrome',
                  'Mail - Dan Russell - Outlook - Google Chrome',
                  'Mail merge guide - Google Docs - Google Chrome',
                  'Acme Mail Campaign brief.docx - Word'):
            self.assertFalse(self.gmail(t), t)

    def test_mailbox_owner_is_not_scored_as_a_client(self):
        self.assertEqual(strip_app_chrome(BRANDED), 'Re: proofs')
        self.assertEqual(strip_app_chrome('Inbox (3) - jane@acme.com - Gmail - Google Chrome'), 'Inbox (3)')
        self.assertEqual(
            strip_app_chrome('Managed Payments - MAVOPS - Stripe - High memory usage - 1.2 GB - Google Chrome'
                             ' - dan@mavops.ai'),
            'Managed Payments - MAVOPS - Stripe')


READING = 'Re: Q3 engagement letter - me@agency.com - Agency Mail - Google Chrome - me@agency.com'


class ReadingTest(RefileBase):
    """Stage 7b: the thread open in a Gmail block, matched to synced mail."""

    def received(self, ext, minute, subject, client, domain):
        from tracker.models import MailSignal
        return MailSignal.objects.create(
            org=self.org, user=self.user, provider='google', external_id=ext,
            occurred_at=self.T0 + timedelta(minutes=minute), direction='in',
            other_party_domain=domain, extracted_client=client,
            to_recipients=[{'email': 'me@agency.com', 'name': ''}], cc_recipients=[],
            from_address=f'jane@{domain}', subject=subject,
        )

    def classify(self, block):
        from tracker.services.classification_service import ClassificationService
        return ClassificationService(org=self.org, user=self.user).classify(block, skip_ai=True)

    def test_reading_a_client_thread_files_the_block_to_that_client(self):
        self.received('i1', -60, 'Q3 engagement letter', self.acme, 'acme.com')
        b = self.filed_block(0, 12, None, window_title=READING, title=READING,
                             classification_state='captured', is_categorized=False,
                             state_changed_by=None)
        d = self.classify(b)
        self.assertEqual(d.client_id, self.acme.id)
        self.assertEqual(d.recommended_state, 'committed')
        reading = [s for s in d.matched_signals if (s.detail or {}).get('match_method') == 'gmail_reading']
        self.assertEqual(len(reading), 1)
        # Managers can read proposed_signals: domain + client, never the subject.
        self.assertNotIn('engagement', reading[0].evidence.lower())
        self.assertIn('acme.com', reading[0].evidence)

    def test_late_thread_mail_refiles_a_reading_block(self):
        b = self.filed_block(0, 12, self.own, window_title=READING, title=READING)
        self.received('i1', 5, 'RE: Q3 Engagement Letter', self.acme, 'acme.com')
        self.assertEqual(self.refile(), 1)
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.acme.id)

    def test_list_views_and_short_subjects_name_no_thread(self):
        from tracker.services.mail_compose import open_message_subject
        for title in ('Inbox (3) - me@agency.com - Agency Mail - Google Chrome',
                      'Sent Mail - me@agency.com - Gmail - Google Chrome',
                      'Search results - me@agency.com - Gmail - Google Chrome',
                      'Re: hi - me@agency.com - Gmail - Google Chrome'):
            b = self.block(0, 5)
            b.window_title = b.title = title
            self.assertEqual(open_message_subject(b), '', title)

    def test_thread_with_two_clients_goes_to_review(self):
        self.received('i1', -60, 'Q3 engagement letter', self.acme, 'acme.com')
        self.received('i2', -30, 'Re: Q3 engagement letter', self.beta, 'betafoods.com')
        b = self.filed_block(0, 12, None, window_title=READING, title=READING,
                             classification_state='captured', is_categorized=False,
                             state_changed_by=None)
        d = self.classify(b)
        self.assertNotEqual(d.recommended_state, 'committed')
        self.assertTrue(d.needs_review)

    def test_thread_on_an_unmapped_domain_says_nothing(self):
        self.received('i1', -60, 'Q3 engagement letter', None, 'unmapped.io')
        b = self.filed_block(0, 12, self.own, window_title=READING, title=READING)
        self.assertEqual(self.refile(), 0)

    def test_composing_beats_reading(self):
        # Reading an Acme thread, but most of the block was writing to Beta.
        self.received('i1', -60, 'Q3 engagement letter', self.acme, 'acme.com')
        b = self.filed_block(0, 10, self.own, window_title=READING, title=READING)
        self.sent('o1', 9, 'ann@betafoods.com', self.beta, 'betafoods.com')
        self.refile()
        b.refresh_from_db()
        self.assertEqual(b.client_id, self.beta.id)
