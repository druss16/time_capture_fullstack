"""
Gmail + Google Calendar integration — OAuth, sync, privacy, compose time.

Every Google HTTP call is mocked (tracker.integrations.google.requests). The
database is real, so these are TestCase: run against a THROWAWAY Postgres,
never the default settings (the local docker DB is production):

    python manage.py test tracker.google_integration_test --noinput < /dev/null

What these guard, in order of how badly it would hurt to lose:

  * Privacy. Gmail rows store addresses + subject; ONLY the owning user may
    ever receive them. A manager opening a colleague's block evidence gets no
    mail section at all, and no address or subject anywhere in the payload.
    Outlook rows keep storing no addresses.
  * The fetch itself never asks Google for a snippet or attachment parts.
  * Sync correctness: initial window, history increments, 404 historyId →
    full resync; calendar syncToken increments, 410 → wipe + full resync.
  * Compose attribution: one client → strong signal; sends to 2+ clients in
    one Gmail block → no auto-attribution, flagged for review.
"""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.integrations import google
from tracker.models import (
    Block, CalendarEvent, Client, MailSignal, Organization,
    OrganizationMembership, OrgCalendarRule, UserIntegration,
)

User = get_user_model()

GOOGLE_SETTINGS = dict(
    GOOGLE_OAUTH_CLIENT_ID='cid.apps.googleusercontent.com',
    GOOGLE_OAUTH_CLIENT_SECRET='csecret',
    GOOGLE_GMAIL_REDIRECT_URI='https://api.example.test/api/google/gmail/auth/callback/',
    GOOGLE_CALENDAR_REDIRECT_URI='https://api.example.test/api/google/calendar/auth/callback/',
    FRONTEND_BASE_URL='https://app.example.test',
)


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)
        self.headers = {}

    def json(self):
        return self._body


def ms(dt):
    return str(int(dt.timestamp() * 1000))


def gmail_msg(mid, when, labels, frm, to='', cc='', subject='', mime='multipart/alternative'):
    headers = [{'name': 'From', 'value': frm}, {'name': 'Subject', 'value': subject}]
    if to:
        headers.append({'name': 'To', 'value': to})
    if cc:
        headers.append({'name': 'Cc', 'value': cc})
    return {
        'id': mid, 'threadId': 't' + mid, 'labelIds': labels,
        'internalDate': ms(when), 'payload': {'mimeType': mime, 'headers': headers},
    }


class GoogleRouter:
    """Routes mocked requests.get by URL. `calls` records (url, params)."""

    def __init__(self):
        self.messages = {}           # id -> message dict
        self.label_ids = {}          # label -> [ids] newest first
        self.history = None          # FakeResp or dict
        self.profile_history_id = '9000'
        self.calendar_pages = []     # list of FakeResp, consumed in order
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        if url.endswith('/profile'):
            return FakeResp(200, {'emailAddress': 'me@agency.com', 'historyId': self.profile_history_id})
        if url.endswith('/users/me/messages'):
            label = params['labelIds']
            return FakeResp(200, {'messages': [{'id': i} for i in self.label_ids.get(label, [])]})
        if '/users/me/messages/' in url:
            mid = url.rsplit('/', 1)[-1]
            if mid not in self.messages:
                return FakeResp(404, {})
            return FakeResp(200, self.messages[mid])
        if url.endswith('/history'):
            h = self.history
            return h if isinstance(h, FakeResp) else FakeResp(200, h)
        if '/calendars/primary/events' in url:
            return self.calendar_pages.pop(0)
        if 'userinfo' in url:
            return FakeResp(200, {'sub': 'g-123', 'email': 'me@agency.com'})
        raise AssertionError(f'unexpected GET {url}')


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Agency', slug='agency')
        self.user = User.objects.create_user('me', email='me@agency.com', password='x')
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='member')
        self.acme = Client.objects.create(org=self.org, name='Acme Widgets')
        self.beta = Client.objects.create(org=self.org, name='Beta Foods')
        OrgCalendarRule.objects.create(
            org=self.org, match_type='attendee_domain', match_value='acme.com',
            target_client=self.acme, is_active=True,
        )
        OrgCalendarRule.objects.create(
            org=self.org, match_type='attendee_domain', match_value='betafoods.com',
            target_client=self.beta, is_active=True,
        )

    def gmail_integration(self, **kw):
        defaults = dict(
            user=self.user, org=self.org, provider='gmail', is_connected=True,
            access_token='at', refresh_token='rt',
            token_expires_at=timezone.now() + timedelta(hours=1),
            provider_email='me@agency.com',
        )
        defaults.update(kw)
        return UserIntegration.objects.create(**defaults)


# ─── OAuth ────────────────────────────────────────────────────────────────────

@override_settings(**GOOGLE_SETTINGS)
class OAuthTests(Base):
    def test_auth_start_asks_for_offline_consent_with_metadata_scope(self):
        c = APIClient()
        c.force_authenticate(self.user)
        r = c.get('/api/google/gmail/auth/start/')
        self.assertEqual(r.status_code, 200)
        q = parse_qs(urlparse(r.json()['auth_url']).query)
        self.assertEqual(q['access_type'], ['offline'])
        self.assertEqual(q['prompt'], ['consent'])
        self.assertEqual(q['include_granted_scopes'], ['true'])
        # Only this flow's own scopes are requested.
        self.assertEqual(q['scope'][0].split(),
                         ['openid', 'email', 'https://www.googleapis.com/auth/gmail.metadata'])
        self.assertIn('https://www.googleapis.com/auth/gmail.metadata', q['scope'][0])
        self.assertEqual(q['redirect_uri'], [GOOGLE_SETTINGS['GOOGLE_GMAIL_REDIRECT_URI']])
        row = UserIntegration.objects.get(user=self.user, provider='gmail')
        self.assertEqual(q['state'], [row.oauth_state])

    def test_calendar_start_uses_its_own_redirect_uri(self):
        c = APIClient()
        c.force_authenticate(self.user)
        q = parse_qs(urlparse(c.get('/api/google/calendar/auth/start/').json()['auth_url']).query)
        self.assertEqual(q['redirect_uri'], [GOOGLE_SETTINGS['GOOGLE_CALENDAR_REDIRECT_URI']])
        self.assertEqual(q['scope'][0].split(),
                         ['openid', 'email', 'https://www.googleapis.com/auth/calendar.readonly'])

    def _callback(self, token_body, path='/api/google/gmail/auth/callback/', provider='gmail'):
        row = UserIntegration.objects.create(
            user=self.user, org=self.org, provider=provider, oauth_state='st8',
        )
        router = GoogleRouter()
        with mock.patch.object(google.requests, 'post', return_value=FakeResp(200, token_body)) as post, \
                mock.patch.object(google.requests, 'get', side_effect=router.get), \
                mock.patch('tracker.tasks_gmail.sync_user_gmail.delay') as gdelay, \
                mock.patch('tracker.tasks_google_calendar.sync_user_google_calendar.delay') as cdelay:
            r = self.client.get(path, {'code': 'abc', 'state': 'st8'})
        row.refresh_from_db()
        return r, row, post, gdelay, cdelay

    def test_callback_stores_tokens_identity_and_starts_sync(self):
        r, row, post, gdelay, _ = self._callback({
            'access_token': 'AT1', 'refresh_token': 'RT1', 'expires_in': 3599,
            'scope': 'openid https://www.googleapis.com/auth/userinfo.email '
                     'https://www.googleapis.com/auth/gmail.metadata',
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn('gmail=connected', r['Location'])
        self.assertTrue(row.is_connected)
        self.assertEqual(row.access_token, 'AT1')
        self.assertEqual(row.refresh_token, 'RT1')
        self.assertEqual(row.provider_email, 'me@agency.com')
        self.assertEqual(row.oauth_state, '')
        # Exchange repeats the flow's own redirect URI.
        self.assertEqual(post.call_args.kwargs['data']['redirect_uri'],
                         GOOGLE_SETTINGS['GOOGLE_GMAIL_REDIRECT_URI'])
        gdelay.assert_called_once_with(row.id)

    def test_calendar_consent_landing_on_gmail_callback_still_uses_calendar_uri(self):
        r, row, post, gdelay, cdelay = self._callback(
            {'access_token': 'AT', 'refresh_token': 'RT', 'expires_in': 3600,
             'scope': 'openid email https://www.googleapis.com/auth/calendar.readonly'},
            provider='google_calendar',
        )
        self.assertIn('gcal=connected', r['Location'])
        self.assertEqual(post.call_args.kwargs['data']['redirect_uri'],
                         GOOGLE_SETTINGS['GOOGLE_CALENDAR_REDIRECT_URI'])
        cdelay.assert_called_once()
        gdelay.assert_not_called()

    def test_unticked_gmail_permission_is_refused_not_stored(self):
        r, row, *_ = self._callback({
            'access_token': 'AT1', 'refresh_token': 'RT1', 'expires_in': 3599,
            'scope': 'openid https://www.googleapis.com/auth/userinfo.email',
        })
        self.assertIn('permission_not_granted', r['Location'])
        self.assertFalse(row.is_connected)
        self.assertEqual(row.refresh_token, '')
        self.assertEqual(row.access_token, '')
        c = APIClient()
        c.force_authenticate(self.user)
        health = c.get('/api/google/gmail/status/').json()['health']
        self.assertEqual(health['state'], 'permission_denied')
        self.assertTrue(health['needs_action'])

    def test_missing_scope_field_is_treated_as_not_granted(self):
        r, row, *_ = self._callback({'access_token': 'AT1', 'refresh_token': 'RT1', 'expires_in': 3599})
        self.assertIn('permission_not_granted', r['Location'])
        self.assertFalse(row.is_connected)

    def test_gmail_grant_that_also_carries_calendar_scope_is_accepted(self):
        # include_granted_scopes: a person who connected Calendar first gets a
        # union grant back from the Gmail flow.
        r, row, *_ = self._callback({
            'access_token': 'AT1', 'refresh_token': 'RT1', 'expires_in': 3599,
            'scope': 'openid email https://www.googleapis.com/auth/calendar.readonly '
                     'https://www.googleapis.com/auth/gmail.metadata',
        })
        self.assertIn('gmail=connected', r['Location'])
        self.assertTrue(row.is_connected)

    def test_bad_state_is_rejected(self):
        r = self.client.get('/api/google/gmail/auth/callback/', {'code': 'x', 'state': 'nope'})
        self.assertIn('invalid_state', r['Location'])

    def test_status_reports_never_connected_with_google_wording(self):
        UserIntegration.objects.create(user=self.user, org=self.org, provider='gmail', oauth_state='s')
        c = APIClient()
        c.force_authenticate(self.user)
        body = c.get('/api/google/gmail/status/').json()
        self.assertEqual(body['health']['state'], 'never_connected')
        self.assertIn('Google', body['health']['guidance'])


@override_settings(**GOOGLE_SETTINGS)
class RefreshTests(Base):
    def test_refresh_success_resets_failure_state(self):
        integ = self.gmail_integration(token_expires_at=timezone.now() - timedelta(minutes=1),
                                       sync_failure_count=2)
        with mock.patch.object(google.requests, 'post',
                               return_value=FakeResp(200, {'access_token': 'NEW', 'expires_in': 3600})):
            self.assertEqual(google.get_valid_token(integ), 'NEW')
        integ.refresh_from_db()
        self.assertEqual(integ.access_token, 'NEW')
        self.assertEqual(integ.refresh_token, 'rt')  # Google keeps the old one
        self.assertEqual(integ.sync_failure_count, 0)
        self.assertGreater(integ.token_expires_at, timezone.now())

    def test_invalid_grant_disconnects_immediately(self):
        integ = self.gmail_integration(token_expires_at=timezone.now() - timedelta(minutes=1))
        with mock.patch.object(google.requests, 'post',
                               return_value=FakeResp(400, {'error': 'invalid_grant'})):
            with self.assertRaises(google.GoogleAuthError):
                google.get_valid_token(integ)
        integ.refresh_from_db()
        self.assertFalse(integ.is_connected)
        self.assertIn('reconnect', integ.last_sync_error)

    def test_transient_failure_keeps_connection(self):
        integ = self.gmail_integration(token_expires_at=timezone.now() - timedelta(minutes=1))
        with mock.patch.object(google.requests, 'post',
                               return_value=FakeResp(500, {'error': 'backend_error'})):
            with self.assertRaises(google.GoogleAuthError):
                google.get_valid_token(integ)
        integ.refresh_from_db()
        self.assertTrue(integ.is_connected)
        self.assertEqual(integ.sync_failure_count, 1)

    def test_no_refresh_token_says_never_connected(self):
        integ = self.gmail_integration(refresh_token='', token_expires_at=timezone.now() - timedelta(1))
        with self.assertRaises(google.GoogleAuthError):
            google.get_valid_token(integ)
        integ.refresh_from_db()
        self.assertIn('Never connected', integ.last_sync_error)


# ─── Gmail sync ───────────────────────────────────────────────────────────────

@override_settings(**GOOGLE_SETTINGS)
class GmailSyncTests(Base):
    def setUp(self):
        super().setUp()
        self.integ = self.gmail_integration()
        self.now = timezone.now()
        self.router = GoogleRouter()
        r = self.router
        r.messages = {
            'in1': gmail_msg('in1', self.now - timedelta(hours=2), ['INBOX', 'UNREAD'],
                             'Jane Doe <jane@acme.com>', to='me@agency.com',
                             subject='Q3 launch plan', mime='multipart/mixed'),
            'out1': gmail_msg('out1', self.now - timedelta(hours=1), ['SENT'],
                              'Me <me@agency.com>', to='Bob <bob@betafoods.com>',
                              cc='Ann <ann@betafoods.com>, me@agency.com', subject='Re: menu'),
            'int1': gmail_msg('int1', self.now - timedelta(hours=1), ['INBOX'],
                              'colleague@agency.com', to='me@agency.com', subject='lunch?'),
            'old1': gmail_msg('old1', self.now - timedelta(days=45), ['INBOX'],
                              'x@acme.com', to='me@agency.com', subject='ancient'),
            'draft': gmail_msg('draft', self.now, ['DRAFT', 'SENT'],
                               'me@agency.com', to='z@acme.com', subject='wip'),
        }
        r.label_ids = {'INBOX': ['in1', 'int1', 'old1'], 'SENT': ['out1']}

    def sync(self):
        from tracker.tasks_gmail import run_gmail_sync
        with mock.patch.object(google.requests, 'get', side_effect=self.router.get):
            res = run_gmail_sync(self.integ)
        self.integ.refresh_from_db()
        return res

    def test_initial_sync_window_direction_matching_and_cursor(self):
        res = self.sync()
        self.assertEqual(res['mode'], 'full')
        rows = {s.external_id: s for s in MailSignal.objects.filter(user=self.user)}
        # internal dropped, older-than-window dropped
        self.assertEqual(set(rows), {'in1', 'out1'})

        inbound = rows['in1']
        self.assertEqual(inbound.provider, 'google')
        self.assertEqual(inbound.direction, 'in')
        self.assertEqual(inbound.other_party_domain, 'acme.com')
        self.assertEqual(inbound.extracted_client, self.acme)
        self.assertTrue(inbound.is_inbox)
        self.assertTrue(inbound.has_attachment)
        self.assertEqual(inbound.from_address, 'jane@acme.com')
        self.assertEqual(inbound.from_name, 'Jane Doe')
        self.assertEqual(inbound.subject, 'Q3 launch plan')

        sent = rows['out1']
        self.assertEqual(sent.direction, 'out')
        self.assertEqual(sent.other_party_domain, 'betafoods.com')
        self.assertEqual(sent.extracted_client, self.beta)
        self.assertEqual([p['email'] for p in sent.to_recipients], ['bob@betafoods.com'])
        self.assertEqual([p['email'] for p in sent.cc_recipients], ['ann@betafoods.com', 'me@agency.com'])
        self.assertFalse(sent.is_inbox)

        self.assertEqual(self.integ.sync_cursor, '9000')
        self.assertIsNotNone(self.integ.sync_cursor_set_at)

    def test_fetch_never_requests_snippet_or_parts(self):
        self.sync()
        gets = [p for (u, p) in self.router.calls if '/users/me/messages/' in u]
        self.assertTrue(gets)
        for params in gets:
            d = dict(p for p in params if p[0] != 'metadataHeaders')
            self.assertEqual(d['format'], 'metadata')
            self.assertNotIn('snippet', d['fields'])
            self.assertNotIn('parts', d['fields'])
        list_calls = [p for (u, p) in self.router.calls if u.endswith('/users/me/messages')]
        for params in list_calls:
            self.assertNotIn('q', params)   # rejected under gmail.metadata

    def test_history_increment_adds_and_deletes(self):
        self.sync()
        self.router.messages['in2'] = gmail_msg(
            'in2', self.now, ['INBOX'], 'ops@acme.com', to='me@agency.com', subject='ping')
        self.router.history = {
            'history': [
                {'messagesAdded': [{'message': {'id': 'in2', 'labelIds': ['INBOX']}}]},
                {'messagesAdded': [{'message': {'id': 'draft', 'labelIds': ['DRAFT']}}]},
                {'messagesDeleted': [{'message': {'id': 'in1'}}]},
            ],
            'historyId': '9100',
        }
        res = self.sync()
        self.assertEqual(res['mode'], 'incremental')
        ids = set(MailSignal.objects.filter(user=self.user).values_list('external_id', flat=True))
        self.assertEqual(ids, {'out1', 'in2'})
        self.assertEqual(self.integ.sync_cursor, '9100')
        history_calls = [p for (u, p) in self.router.calls if u.endswith('/history')]
        self.assertEqual(dict(history_calls[-1])['startHistoryId'], '9000')

    def test_expired_history_id_falls_back_to_full_resync(self):
        self.integ.sync_cursor = '1'
        self.integ.save()
        self.router.history = FakeResp(404, {'error': {'code': 404}})
        self.router.profile_history_id = '9500'
        res = self.sync()
        self.assertEqual(res['mode'], 'full_resync')
        self.assertEqual(self.integ.sync_cursor, '9500')
        self.assertEqual(MailSignal.objects.filter(user=self.user).count(), 2)

    def test_resync_is_idempotent(self):
        self.sync()
        self.integ.sync_cursor = ''
        self.integ.save()
        self.sync()
        self.assertEqual(MailSignal.objects.filter(user=self.user).count(), 2)

    def test_disconnect_deletes_rows_and_cursor(self):
        self.sync()
        self.integ.disconnect()
        self.assertFalse(MailSignal.objects.filter(user=self.user).exists())
        self.assertEqual(self.integ.sync_cursor, '')


class GmailDirectionTests(SimpleTestCase):
    """SENT label is authoritative, even for a send-as alias."""

    def test_send_as_alias_is_still_outbound(self):
        from tracker import tasks_gmail
        msg = gmail_msg('a1', timezone.now(), ['SENT'], 'Brand <hello@brand-alias.com>',
                        to='client@acme.com', subject='hi')
        captured = {}

        def fake_uoc(**kw):
            captured.update(kw)
            return SimpleNamespace(extracted_client_id=None), True

        integ = SimpleNamespace(user=object(), org=object())
        with mock.patch.object(tasks_gmail.MailSignal.objects, 'update_or_create', side_effect=fake_uoc), \
                mock.patch('tracker.mail_matching.find_mail_match', return_value=(None, 0.0, 'unmatched', '')):
            tasks_gmail.process_gmail_message(
                msg, integ, user_email='me@agency.com', user_domain='agency.com',
                clients_cache=[], rules_cache=[],
            )
        self.assertEqual(captured['defaults']['direction'], 'out')
        self.assertEqual(captured['defaults']['other_party_domain'], 'acme.com')


class OutlookStoresNoAddressesTests(Base):
    def test_outlook_row_keeps_address_fields_null(self):
        from tracker.tasks_mail import _process_message
        integ = UserIntegration.objects.create(
            user=self.user, org=self.org, provider='microsoft_mail', is_connected=True,
            provider_email='me@agency.com',
        )
        sig = _process_message(
            msg={
                'id': 'AAMk1', 'receivedDateTime': '2026-09-29T14:00:00Z',
                'from': {'emailAddress': {'address': 'jane@acme.com', 'name': 'Jane'}},
                'toRecipients': [{'emailAddress': {'address': 'me@agency.com'}}],
                'subject': 'Totally private subject', 'parentFolderId': 'inbox',
            },
            integration=integ, user_email='me@agency.com', user_domain='agency.com',
            inbox_folder_id='inbox', clients_cache=list(Client.objects.filter(org=self.org)),
            rules_cache=list(OrgCalendarRule.objects.filter(org=self.org)),
        )
        sig.refresh_from_db()
        self.assertEqual(sig.extracted_client, self.acme)
        self.assertIsNone(sig.from_address)
        self.assertIsNone(sig.from_name)
        self.assertIsNone(sig.to_recipients)
        self.assertIsNone(sig.cc_recipients)
        self.assertIsNone(sig.subject)
        self.assertEqual(sig.subject_extract, '')  # unchanged privacy gate


# ─── Compose duration + Stage 7a ──────────────────────────────────────────────

class ComposeMathTests(SimpleTestCase):
    T0 = datetime(2026, 9, 29, 14, 0, tzinfo=dt_timezone.utc)

    def blk(self, i, start_min, end_min, url='https://mail.google.com/mail/u/0/#inbox'):
        return SimpleNamespace(id=i, start=self.T0 + timedelta(minutes=start_min),
                               end=self.T0 + timedelta(minutes=end_min), url=url,
                               title='', window_title='')

    def send(self, i, minute):
        return SimpleNamespace(id=i, occurred_at=self.T0 + timedelta(minutes=minute), compose_seconds=None)

    def test_gmail_detection(self):
        from tracker.services.mail_compose import is_gmail_block
        self.assertTrue(is_gmail_block(SimpleNamespace(url='', title='', window_title='Inbox (3) - me@x.com - Gmail')))
        self.assertTrue(is_gmail_block(SimpleNamespace(url='', title='', window_title='Re: hi - me@x.com - Gmail - Google Chrome')))
        self.assertFalse(is_gmail_block(SimpleNamespace(url='https://docs.google.com/x', title='Doc', window_title='Doc')))

    def test_compose_spans_contiguous_blocks_and_restarts_after_each_send(self):
        from tracker.services.mail_compose import attribute_sends
        blocks = [self.blk(1, 0, 4), self.blk(2, 5, 10)]  # 1-min gap → one chain
        out = attribute_sends(blocks, [self.send(10, 6), self.send(11, 10.5)])
        self.assertEqual(out[10].compose_seconds, 6 * 60)
        self.assertEqual(out[10].block.id, 2)
        # Second send lands just after the block closed (grace) — composed
        # from the first send to the end of the chain.
        self.assertEqual(out[11].compose_seconds, 4 * 60)
        self.assertEqual(out[11].block.id, 2)

    def test_send_with_no_gmail_block_has_no_compose_time(self):
        from tracker.services.mail_compose import attribute_sends
        out = attribute_sends([self.blk(1, 0, 4)], [self.send(10, 30)])
        self.assertNotIn(10, out)

    def test_non_gmail_blocks_are_ignored(self):
        from tracker.services.mail_compose import attribute_sends
        out = attribute_sends([self.blk(1, 0, 10, url='https://acme.com')], [self.send(10, 5)])
        self.assertEqual(out, {})


class ComposeBase(Base):
    T0 = datetime(2026, 9, 29, 14, 0, tzinfo=dt_timezone.utc)

    def block(self, start_min, end_min, **kw):
        return Block.objects.create(
            org=self.org, user=self.user, hostname='mac',
            start=self.T0 + timedelta(minutes=start_min), end=self.T0 + timedelta(minutes=end_min),
            minutes=end_min - start_min, app_name='Google Chrome',
            url='https://mail.google.com/mail/u/0/#inbox',
            window_title='Compose - me@agency.com - Gmail', **kw,
        )

    def sent(self, ext, minute, to, client, domain):
        return MailSignal.objects.create(
            org=self.org, user=self.user, provider='google', external_id=ext,
            occurred_at=self.T0 + timedelta(minutes=minute), direction='out',
            other_party_domain=domain, extracted_client=client,
            to_recipients=[{'email': to, 'name': ''}], cc_recipients=[],
            from_address='me@agency.com', subject=f'Secret subject {ext}',
        )

    def stage7(self, block):
        from tracker.services.classification_service import (
            ClassificationDecision, ClassificationService,
        )
        svc = ClassificationService(org=self.org, user=self.user)
        d = ClassificationDecision()
        svc._stage_7_mail(block, d)
        return d


class ComposeAttributionTests(ComposeBase):

    def test_single_client_send_is_a_strong_signal_with_compose_time(self):
        b = self.block(0, 8)
        self.sent('s1', 6, 'jane@acme.com', self.acme, 'acme.com')
        d = self.stage7(b)
        self.assertEqual(len(d.matched_signals), 1)
        s = d.matched_signals[0]
        self.assertEqual(s.type, 'mail')
        self.assertGreaterEqual(s.strength, 0.85)
        self.assertEqual(s.detail['client_id'], self.acme.id)
        self.assertEqual(s.detail['compose_seconds'], 360)
        self.assertIn('~6 min', s.evidence)
        # Signal evidence is visible to managers: domain + client only.
        blob = json.dumps(s.to_dict())
        self.assertNotIn('jane@acme.com', blob)
        self.assertNotIn('Secret subject', blob)

    def test_sends_to_two_clients_do_not_auto_attribute(self):
        b = self.block(0, 20)
        self.sent('s1', 5, 'jane@acme.com', self.acme, 'acme.com')
        self.sent('s2', 15, 'bob@betafoods.com', self.beta, 'betafoods.com')
        d = self.stage7(b)
        self.assertEqual({s.detail['client_id'] for s in d.matched_signals}, {self.acme.id, self.beta.id})
        self.assertTrue(all(s.strength < 0.85 for s in d.matched_signals))
        self.assertTrue(d.needs_review)
        self.assertNotIn('mail_proposed_client_id', getattr(d, 'detail', {}) or {})

    def test_two_client_block_is_never_committed_by_the_full_pipeline(self):
        from tracker.services.classification_service import ClassificationService
        b = self.block(0, 20)
        self.sent('s1', 5, 'jane@acme.com', self.acme, 'acme.com')
        self.sent('s2', 15, 'bob@betafoods.com', self.beta, 'betafoods.com')
        d = ClassificationService(org=self.org, user=self.user).classify(b, skip_ai=True)
        self.assertNotEqual(d.recommended_state, 'committed')

    def test_single_client_block_commits_through_the_full_pipeline(self):
        from tracker.services.classification_service import ClassificationService
        b = self.block(0, 8)
        self.sent('s1', 6, 'jane@acme.com', self.acme, 'acme.com')
        d = ClassificationService(org=self.org, user=self.user).classify(b, skip_ai=True)
        self.assertEqual(d.client_id, self.acme.id)
        self.assertEqual(d.recommended_state, 'committed')

    def test_inbox_triage_with_short_reply_is_not_auto_committed(self):
        """40-min Gmail block of triage; one 2-min reply to Acme at minute 20.
        5% coverage: a weak contributor, never a commit."""
        from tracker.services.classification_service import ClassificationService
        b = self.block(0, 40)
        # A Gmail block elsewhere earlier resets nothing; the 2-min compose is
        # measured from the previous send in the same session.
        self.sent('s0', 18, 'noreply@unmapped.org', None, 'unmapped.org')
        self.sent('s1', 20, 'jane@acme.com', self.acme, 'acme.com')
        d7 = self.stage7(b)
        compose = [s for s in d7.matched_signals
                   if (s.detail or {}).get('match_method', '').startswith('gmail_compose')]
        self.assertEqual(len(compose), 1)
        self.assertLessEqual(compose[0].strength, 0.70)
        self.assertEqual(compose[0].detail['match_method'], 'gmail_compose_partial')
        self.assertEqual(compose[0].detail['compose_seconds_in_block'], 120)
        d = ClassificationService(org=self.org, user=self.user).classify(b, skip_ai=True)
        self.assertNotEqual(d.recommended_state, 'committed')

    def test_ten_min_block_mostly_composing_commits_to_that_client(self):
        from tracker.services.classification_service import ClassificationService
        b = self.block(0, 10)
        self.sent('s1', 8, 'jane@acme.com', self.acme, 'acme.com')
        d = ClassificationService(org=self.org, user=self.user).classify(b, skip_ai=True)
        self.assertEqual(d.client_id, self.acme.id)
        self.assertEqual(d.recommended_state, 'committed')

    def test_owner_still_sees_compose_line_for_partial_block(self):
        b = self.block(0, 40)
        self.sent('s0', 18, 'noreply@unmapped.org', None, 'unmapped.org')
        self.sent('s1', 20, 'jane@acme.com', self.acme, 'acme.com')
        c = APIClient()
        c.force_authenticate(self.user)
        mail = c.get(f'/api/blocks/{b.id}/evidence/').json()['mail']
        self.assertIn('Emailed jane@acme.com — ~2 min composing',
                      [x['line'] for x in mail['compose']])

    def test_annotator_persists_compose_seconds(self):
        from tracker.services.mail_compose import annotate_compose_seconds
        self.block(0, 8)
        sig = self.sent('s1', 6, 'jane@acme.com', self.acme, 'acme.com')
        n = annotate_compose_seconds(self.user, self.T0 - timedelta(hours=1), self.T0 + timedelta(hours=1))
        sig.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertEqual(sig.compose_seconds, 360)


# ─── Own-user-only visibility ────────────────────────────────────────────────

class EvidenceVisibilityTests(ComposeBase):
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user('boss', email='boss@agency.com', password='x')
        OrganizationMembership.objects.create(user=self.manager, organization=self.org, role='manager')
        self.b = self.block(0, 8)
        self.sent('s1', 6, 'jane@acme.com', self.acme, 'acme.com')

    def evidence_as(self, who):
        c = APIClient()
        c.force_authenticate(who)
        r = c.get(f'/api/blocks/{self.b.id}/evidence/')
        self.assertEqual(r.status_code, 200)
        return r.json(), r.content.decode()

    def test_owner_sees_addresses_subject_and_compose_line(self):
        body, _ = self.evidence_as(self.user)
        mail = body['mail']
        self.assertEqual(mail['compose'][0]['line'], 'Emailed jane@acme.com — ~6 min composing')
        self.assertEqual(mail['messages'][0]['to'][0]['email'], 'jane@acme.com')
        self.assertEqual(mail['messages'][0]['subject'], 'Secret subject s1')

    def test_manager_viewing_another_users_block_gets_no_addresses_or_subject(self):
        body, raw = self.evidence_as(self.manager)
        self.assertIsNone(body.get('mail'))
        self.assertNotIn('jane@acme.com', raw)
        self.assertNotIn('Secret subject', raw)


# ─── Google Calendar sync ────────────────────────────────────────────────────

@override_settings(**GOOGLE_SETTINGS)
class GoogleCalendarSyncTests(Base):
    def setUp(self):
        super().setUp()
        self.integ = UserIntegration.objects.create(
            user=self.user, org=self.org, provider='google_calendar', is_connected=True,
            access_token='at', refresh_token='rt',
            token_expires_at=timezone.now() + timedelta(hours=1), provider_email='me@agency.com',
        )
        self.router = GoogleRouter()
        start = (timezone.now() + timedelta(hours=2)).replace(microsecond=0)
        self.meeting = {
            'id': 'ev1', 'status': 'confirmed', 'summary': 'Weekly sync',
            'start': {'dateTime': start.isoformat()},
            'end': {'dateTime': (start + timedelta(hours=1)).isoformat()},
            'attendees': [
                {'email': 'me@agency.com', 'self': True, 'responseStatus': 'accepted'},
                {'email': 'jane@acme.com', 'responseStatus': 'tentative'},
            ],
            'hangoutLink': 'https://meet.google.com/abc-defg-hij',
        }
        self.pto = {
            'id': 'ev2', 'status': 'confirmed', 'summary': 'Vacation', 'eventType': 'outOfOffice',
            'start': {'date': '2026-10-05'}, 'end': {'date': '2026-10-07'},
        }

    def sync(self):
        from tracker.tasks_google_calendar import run_google_calendar_sync
        with mock.patch.object(google.requests, 'get', side_effect=self.router.get):
            res = run_google_calendar_sync(self.integ)
        self.integ.refresh_from_db()
        return res

    def test_full_sync_maps_events_matches_client_and_stores_sync_token(self):
        self.router.calendar_pages = [
            FakeResp(200, {'items': [self.meeting], 'nextPageToken': 'p2'}),
            FakeResp(200, {'items': [self.pto], 'nextSyncToken': 'SYNC1'}),
        ]
        res = self.sync()
        self.assertEqual(res['mode'], 'full')
        ev = CalendarEvent.objects.get(user=self.user, provider='google', external_id='ev1')
        self.assertEqual(ev.extracted_client, self.acme)  # attendee_domain rule
        self.assertEqual(ev.meeting_url, 'https://meet.google.com/abc-defg-hij')
        self.assertEqual(ev.show_as, 'busy')
        self.assertEqual(ev.attendees[1], {'email': 'jane@acme.com', 'domain': 'acme.com',
                                           'response': 'tentativelyAccepted'})
        pto = CalendarEvent.objects.get(external_id='ev2')
        self.assertTrue(pto.is_all_day)
        self.assertEqual(pto.show_as, 'oof')
        self.assertEqual(pto.start, datetime(2026, 10, 5, tzinfo=dt_timezone.utc))
        self.assertEqual(self.integ.sync_cursor, 'SYNC1')
        first = self.router.calls[0][1]
        self.assertEqual(first['singleEvents'], 'true')
        self.assertIn('timeMin', first)

    def test_incremental_uses_sync_token_and_applies_cancellations(self):
        self.router.calendar_pages = [FakeResp(200, {'items': [self.meeting], 'nextSyncToken': 'SYNC1'})]
        self.sync()
        self.router.calendar_pages = [FakeResp(200, {
            'items': [{'id': 'ev1', 'status': 'cancelled'}], 'nextSyncToken': 'SYNC2'})]
        res = self.sync()
        self.assertEqual(res['mode'], 'incremental')
        params = self.router.calls[-1][1]
        self.assertEqual(params['syncToken'], 'SYNC1')
        self.assertNotIn('timeMin', params)
        self.assertFalse(CalendarEvent.objects.filter(external_id='ev1').exists())
        self.assertEqual(self.integ.sync_cursor, 'SYNC2')

    def test_410_wipes_and_resyncs(self):
        self.router.calendar_pages = [FakeResp(200, {'items': [self.meeting, self.pto], 'nextSyncToken': 'S1'})]
        self.sync()
        self.router.calendar_pages = [
            FakeResp(410, {'error': {'code': 410}}),
            FakeResp(200, {'items': [self.meeting], 'nextSyncToken': 'S2'}),
        ]
        res = self.sync()
        self.assertEqual(res['mode'], 'full_resync')
        ids = set(CalendarEvent.objects.filter(user=self.user).values_list('external_id', flat=True))
        self.assertEqual(ids, {'ev1'})
        self.assertEqual(self.integ.sync_cursor, 'S2')

    def test_event_the_user_declined_is_not_stored(self):
        self.meeting['attendees'][0]['responseStatus'] = 'declined'
        self.router.calendar_pages = [FakeResp(200, {'items': [self.meeting], 'nextSyncToken': 'S'})]
        self.sync()
        self.assertFalse(CalendarEvent.objects.filter(external_id='ev1').exists())
