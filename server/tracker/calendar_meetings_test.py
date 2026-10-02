"""
Off-computer calendar meetings -> proposed Needs You entries, and meeting
detection for telehealth / web platforms.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.calendar_meetings_test --noinput < /dev/null
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.models import (
    Block, CalendarEvent, Client, Organization, OrganizationMembership,
    UserIntegration,
)
from tracker.services.calendar_meetings import propose_for_user, is_calendar_block

User = get_user_model()

T0 = datetime(2026, 9, 29, 14, 0, tzinfo=dt_timezone.utc)   # 10:00 New York
NOW = T0 + timedelta(hours=4)


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name='MavOps', slug='mavops', calendar_classification_enabled=True)
        self.user = User.objects.create_user('dan', email='dan@mavops.ai', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='owner')
        self.acme = Client.objects.create(org=self.org, name='Acme Widgets')
        UserIntegration.objects.create(
            user=self.user, org=self.org, provider='google_calendar',
            is_connected=True, provider_email='dan@mavops.ai')
        self._n = 0

    def event(self, start_min=0, end_min=60, attendees=('bob@acme.com',), client=True, **kw):
        self._n += 1
        defaults = dict(
            org=self.org, user=self.user, provider='google',
            external_id=kw.pop('external_id', f'ev{self._n}'),
            title=kw.pop('title', 'Acme quarterly review'),
            start=T0 + timedelta(minutes=start_min), end=T0 + timedelta(minutes=end_min),
            show_as='busy',
            attendees=[{'email': 'dan@mavops.ai', 'domain': 'mavops.ai', 'response': 'accepted'}]
            + [{'email': a, 'domain': a.split('@')[1], 'response': 'accepted'} for a in attendees],
            extracted_client=self.acme if client else None,
            extraction_confidence=0.95 if client else 0.0,
        )
        defaults.update(kw)
        return CalendarEvent.objects.create(**defaults)

    def agent_block(self, start_min, end_min, **kw):
        defaults = dict(
            org=self.org, user=self.user, hostname='mac', device_id='dev1',
            start=T0 + timedelta(minutes=start_min), end=T0 + timedelta(minutes=end_min),
            minutes=end_min - start_min, app_name='EXCEL.EXE',
            window_title='Acme ledger.xlsx - Excel',
            classification_state='committed', is_categorized=True,
            client=self.acme, category_hours={'Project Work': 0.1},
        )
        defaults.update(kw)
        return Block.objects.create(**defaults)

    def run_(self, now=NOW):
        return propose_for_user(self.org, self.user, now=now)

    def cal_blocks(self):
        return list(Block.objects.filter(user=self.user, device_id='calendar').order_by('start'))


class ProposalTests(Base):
    def test_off_computer_meeting_becomes_proposed_needs_you_entry(self):
        self.event()
        stats = self.run_()
        self.assertEqual(stats['created'], 1)
        [b] = self.cal_blocks()
        self.assertTrue(is_calendar_block(b))
        self.assertEqual(b.classification_state, 'proposed')
        self.assertFalse(b.is_categorized)
        self.assertEqual(b.minutes, 60)
        self.assertEqual(b.app_name, 'Calendar')
        self.assertEqual(b.window_title, 'Acme quarterly review')
        self.assertEqual(b.proposed_client_id, self.acme.id)
        self.assertEqual(b.attendees, ['bob@acme.com'])
        self.assertIn('no computer activity was captured', b.proposed_reasoning)
        from tracker.views_reports import is_pending_review_block
        self.assertTrue(is_pending_review_block(b))

    def test_unmatched_client_still_asks_and_names_domain(self):
        self.event(attendees=('kim@newco.com',), client=False)
        self.run_()
        [b] = self.cal_blocks()
        self.assertIsNone(b.client_id)
        self.assertIsNone(b.proposed_client_id)
        from tracker.views_reports import is_pending_review_block
        self.assertTrue(is_pending_review_block(b))
        from tracker.views_block_evidence import why_summary
        sentence, sid, _n, _c = why_summary(b, self.org)
        self.assertTrue(sentence.startswith('From your calendar'))
        self.assertIn('newco.com', sentence)
        self.assertIsNone(sid)

    def test_meeting_with_captured_activity_is_left_to_stage_6(self):
        self.event()
        self.agent_block(0, 30)       # 50% covered
        self.run_()
        self.assertEqual(self.cal_blocks(), [])

    def test_partial_coverage_fills_only_uncovered_minutes(self):
        self.event()
        self.agent_block(20, 25)      # 8% covered: off-computer, but not those minutes
        self.agent_block(30, 50, bundle_id='__idle__', app_name='idle',
                         category_hours={'Idle': 0.3}, client=None)   # idle is fillable
        self.run_()
        blocks = self.cal_blocks()
        self.assertEqual([(b.start, b.end) for b in blocks], [
            (T0, T0 + timedelta(minutes=20)),
            (T0 + timedelta(minutes=25), T0 + timedelta(minutes=60)),
        ])
        self.assertEqual(sum(b.minutes for b in blocks), 55)

    def test_skips_internal_declined_all_day_free_and_unfinished(self):
        self.event(attendees=('amy@mavops.ai',))                       # internal only
        ev = self.event(start_min=120, end_min=150)                     # declined
        ev.attendees[0]['response'] = 'declined'
        ev.save()
        self.event(start_min=-600, end_min=200, is_all_day=True)        # all-day
        self.event(start_min=160, end_min=170, show_as='free')          # free
        self.event(start_min=230, end_min=300)                          # ends after NOW
        stats = self.run_()
        self.assertEqual(self.cal_blocks(), [])
        for why in ('internal_only', 'declined', 'all_day', 'show_as_free'):
            self.assertIn(why, stats['skipped'])

    def test_cancelled_google_event_withdraws_the_entry(self):
        from tracker.tasks_google_calendar import _apply_events
        self.event(external_id='g-1')
        self.run_()
        self.assertEqual(len(self.cal_blocks()), 1)
        integ = UserIntegration.objects.get(user=self.user)
        _apply_events(integ, [{'id': 'g-1', 'status': 'cancelled'}])
        self.run_()
        self.assertEqual(self.cal_blocks(), [])

    def test_rerun_is_idempotent(self):
        self.event()
        self.run_()
        first = [b.id for b in self.cal_blocks()]
        stats = self.run_()
        self.assertEqual((stats['created'], stats['updated'], stats['removed']), (0, 0, 0))
        self.assertEqual([b.id for b in self.cal_blocks()], first)

    def test_moved_event_moves_unconfirmed_entry(self):
        ev = self.event()
        self.run_()
        [before] = self.cal_blocks()
        ev.start, ev.end = T0 + timedelta(minutes=30), T0 + timedelta(minutes=75)
        ev.save()
        self.run_()
        [after] = self.cal_blocks()
        self.assertEqual(after.id, before.id)
        self.assertEqual((after.start, after.minutes), (ev.start, 45))

    def test_deleted_event_removes_unconfirmed_entry(self):
        ev = self.event()
        self.run_()
        ev.delete()
        self.run_()
        self.assertEqual(Block.all_objects.filter(device_id='calendar').count(), 0)

    def test_confirmed_entry_survives_event_deletion(self):
        ev = self.event()
        self.run_()
        [b] = self.cal_blocks()
        b.classification_state, b.is_categorized = 'committed', True
        b.save(force_classifier=True)
        ev.delete()
        self.run_()
        self.assertEqual([x.id for x in self.cal_blocks()], [b.id])

    def test_dismissed_entry_is_never_recreated(self):
        self.event()
        self.run_()
        [b] = self.cal_blocks()
        api = APIClient()
        api.force_authenticate(self.user)
        r = api.delete(f'/api/blocks/{b.id}/delete/')
        self.assertEqual(r.status_code, 200)
        self.run_()
        self.run_(now=NOW + timedelta(minutes=30))
        self.assertEqual(self.cal_blocks(), [])

    def test_flag_off_does_nothing(self):
        self.org.calendar_classification_enabled = False
        self.org.save()
        self.event()
        stats = self.run_()
        self.assertTrue(stats.get('disabled'))
        self.assertEqual(self.cal_blocks(), [])

    def test_time_off_day_is_skipped(self):
        from tracker.models import TimeOff
        d = timezone.localtime(T0).date()
        TimeOff.objects.create(org=self.org, user=self.user, start_date=d, end_date=d)
        self.event()
        self.run_()
        self.assertEqual(self.cal_blocks(), [])


class SoloAppointmentTests(Base):
    """An appointment only the user is on ("Derek Baker", a telehealth slot)
    has no outside attendee, but its title names the client."""

    def solo(self, title='Derek Baker', conf=0.80, client=True, **kw):
        derek = Client.objects.get_or_create(org=self.org, name='Derek Baker')[0]
        return self.event(attendees=(), title=title,
                          extracted_client=derek if client else None,
                          extraction_confidence=conf if client else 0.0, **kw), derek

    def test_solo_appointment_named_for_a_client_is_proposed(self):
        _, derek = self.solo()
        stats = self.run_()
        self.assertEqual(stats['created'], 1)
        [b] = self.cal_blocks()
        self.assertEqual(b.proposed_client_id, derek.id)
        self.assertEqual(b.window_title, 'Derek Baker')
        self.assertEqual(b.attendees, [])
        self.assertIn('no computer activity was captured', b.proposed_reasoning)

    def test_solo_event_without_a_client_name_stays_skipped(self):
        self.solo(title='Focus time', client=False)
        stats = self.run_()
        self.assertEqual(self.cal_blocks(), [])
        self.assertIn('internal_only', stats['skipped'])

    def test_alias_only_match_is_not_enough_for_a_solo_event(self):
        self.solo(conf=0.75)                      # alias tier, below the 0.80 bar
        self.run_()
        self.assertEqual(self.cal_blocks(), [])

    def test_colleagues_only_meeting_naming_a_client_stays_internal(self):
        self.event(attendees=('amy@mavops.ai',), title='Acme review prep')
        stats = self.run_()
        self.assertEqual(self.cal_blocks(), [])
        self.assertIn('internal_only', stats['skipped'])

    def test_solo_appointment_covered_by_computer_activity_proposes_nothing(self):
        self.solo()
        self.agent_block(0, 55, window_title='Telehealth - Camera and microphone recording',
                         app_name='Google Chrome')
        self.run_()
        self.assertEqual(self.cal_blocks(), [])


class BillingAndDailyReviewTests(Base):
    def _totals(self):
        from tracker.services.billing_totals import compute_totals
        return compute_totals(self.org, T0 - timedelta(hours=6), T0 + timedelta(hours=12),
                              user_id=self.user.id, can_see_all=False)

    def test_excluded_from_billing_until_confirmed(self):
        self.event()
        self.run_()
        t = self._totals()
        self.assertEqual(t['billable_hours'], 0)
        self.assertEqual(t['total_hours'], 0)
        self.assertEqual(t['needs_review_min'], 60)

        [b] = self.cal_blocks()
        api = APIClient()
        api.force_authenticate(self.user)
        r = api.patch(f'/api/blocks/{b.id}/recategorize/',
                      {'client_id': self.acme.id, 'category': 'Project Work',
                       'source': 'single_confirm'}, format='json')
        self.assertEqual(r.status_code, 200)
        t = self._totals()
        self.assertEqual(t['billable_hours'], 1.0)
        self.assertEqual(t['needs_review_min'], 0)
        # Confirmed: a later run must leave it alone.
        stats = self.run_()
        self.assertEqual((stats['created'], stats['updated'], stats['removed']), (0, 0, 0))

    def test_today_time_lists_it_in_needs_you_with_calendar_source(self):
        self.event()
        self.run_()
        api = APIClient()
        api.force_authenticate(self.user)
        day = timezone.localtime(T0).date().isoformat()
        r = api.get(f'/api/today-time/?date={day}')
        self.assertEqual(r.status_code, 200)
        rows = [p for p in r.data['proposed_inline'] if p['source'] == 'calendar']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['minutes'], 60)
        self.assertEqual(rows[0]['why_suggested_client_id'], self.acme.id)
        self.assertIn('From your calendar', rows[0]['why_explanation'])
        self.assertIn('bob@acme.com', rows[0]['why_explanation'])
        self.assertEqual(r.data['billable_hours'], 0)


class MeetingPlatformTests(SimpleTestCase):
    def test_telehealth_and_web_platforms(self):
        from tracker.utils.meeting_platforms import detect_meeting_platform as d
        t = 'Telehealth - Camera and microphone recording - Google Chrome'
        self.assertEqual(d('chrome.exe', t, 'https://telehealth.kareo.com/visit/abc'),
                         'Kareo Telehealth')
        self.assertEqual(d('chrome.exe', t, ''), 'Telehealth')
        for url, label in [
            ('https://doxy.me/drsmith', 'Doxy.me'),
            ('https://video.simplepractice.com/x', 'SimplePractice'),
            ('https://us02web.zoom.us/wc/123/join', 'Zoom'),
            ('https://whereby.com/room', 'Whereby'),
            ('https://meet.goto.com/123', 'GoTo Meeting'),
            ('https://bluejeans.com/123', 'BlueJeans'),
            ('https://v.ringcentral.com/join/1', 'RingCentral Video'),
            ('https://vsee.com/c/x', 'VSee'),
            ('https://member.teladoc.com/visit', 'Teladoc'),
            ('https://app.chime.aws/meetings/1', 'Amazon Chime'),
            ('https://meet.jit.si/room', 'Jitsi'),
            ('https://around.co/r/x', 'Around'),
        ]:
            self.assertEqual(d('Google Chrome', 'x', url), label, url)
        self.assertEqual(d('slack.exe', 'Huddle with Kim - Slack', ''), 'Huddle')
        self.assertEqual(d('msedge.exe', 'Video visit with Dr. Lee - Edge', ''), 'Video visit')

    def test_not_meetings(self):
        from tracker.utils.meeting_platforms import detect_meeting_platform as d
        self.assertIsNone(d('WINWORD.EXE', 'Telehealth policy.docx - Word', ''))
        self.assertIsNone(d('WINWORD.EXE', 'huddle notes.docx - Word', ''))
        self.assertIsNone(d('ms-teams.exe', 'Chat | Kim Barnes | Microsoft Teams', ''))
        self.assertIsNone(d('chrome.exe', 'Kareo - Billing', 'https://app.kareo.com/billing'))
        self.assertIsNone(d('SearchHost.exe', 'huddle', ''))


class TelehealthBlockTests(Base):
    """Block 79634: an 82-min Kareo telehealth visit in Chrome."""
    TITLE = 'Telehealth - Camera and microphone recording - Google Chrome'

    def setUp(self):
        super().setUp()
        self.ev = self.event(start_min=0, end_min=90, title='Telehealth: J. Smith follow-up')
        self.block = self.agent_block(
            2, 84, app_name='chrome.exe', window_title=self.TITLE,
            url='https://telehealth.kareo.com/session/abc', client=None,
            classification_state='captured', is_categorized=False, category_hours={})

    def test_stage_6_emits_calendar_signal(self):
        from tracker.services.classification_service import (
            ClassificationDecision, ClassificationService,
        )
        d = ClassificationDecision()
        ClassificationService(org=self.org, user=self.user)._stage_6_calendar(self.block, d)
        sigs = [s for s in d.matched_signals if s.type == 'calendar']
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].detail['client_id'], self.acme.id)
        self.assertTrue(d.is_meeting)

    def test_why_says_you_were_in_a_meeting_with(self):
        from tracker.views_block_evidence import why_summary
        sentence, sid, sname, _c = why_summary(self.block, self.org)
        self.assertTrue(sentence.startswith('You were in a Kareo Telehealth meeting'), sentence)
        self.assertIn('with bob@acme.com', sentence)
        self.assertEqual(sid, self.acme.id)

        api = APIClient()
        api.force_authenticate(self.user)
        r = api.get(f'/api/blocks/{self.block.id}/why/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['tier'], 'meeting')
        self.assertIn('with bob@acme.com', r.data['explanation'])
        self.assertEqual(r.data['suggested_client_id'], self.acme.id)

    def test_captured_call_is_not_also_proposed_from_calendar(self):
        self.run_()
        self.assertEqual(self.cal_blocks(), [])


class StatusCommandTests(Base):
    def test_calendar_status_is_read_only_and_reports_flag(self):
        from io import StringIO
        from django.core.management import call_command
        self.event(start=timezone.now() - timedelta(hours=3),
                   end=timezone.now() - timedelta(hours=2))
        out = StringIO()
        call_command('calendar_status', '--org', str(self.org.id), stdout=out)
        text = out.getvalue()
        self.assertIn('calendar_classification_enabled = True', text)
        self.assertIn('google_calendar', text)
        self.assertIn('matched 1', text)
        self.assertIn('qualifies 1', text)
        self.org.refresh_from_db()
        self.assertTrue(self.org.calendar_classification_enabled)
        self.assertEqual(self.cal_blocks(), [])

    def test_calendar_status_endpoint_exposes_flag(self):
        api = APIClient()
        api.force_authenticate(self.user)
        r = api.get('/api/google/calendar/status/')
        self.assertTrue(r.data['calendar_classification_enabled'])
