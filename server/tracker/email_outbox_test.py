"""
The email outbox: nothing reaches SendGrid unless MavOps says so.

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.email_outbox_test --noinput < /dev/null

SendGrid is faked at email_service.post_to_sendgrid — no network.
"""
import secrets
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.email_service import send_email, send_password_reset
from tracker.models import (
    AuthToken, EmailSendSettings, Organization, OrganizationMembership, OrgEmailSetting,
    OutboundEmail,
)
from tracker.services import email_outbox as outbox

User = get_user_model()
SENDGRID = 'tracker.email_service.post_to_sendgrid'


def _ok(*a, **k):
    return True, 202, ''


def _send(to='sam@mtc.test', subject='Hello', html='<p>Hi</p>', categories=('weekly_summary',)):
    return send_email(to_email=to, subject=subject, html_content=html, categories=list(categories))


def _client_for(user):
    tok = AuthToken.objects.create(user=user, token=secrets.token_hex(20),
                                   expires_at=timezone.now() + timedelta(days=1))
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok.token}')
    return c


class EmailTypeTests(SimpleTestCase):
    def test_most_specific_category_wins(self):
        self.assertEqual(outbox.email_type_for(['onboarding', 'intake']), 'intake')
        self.assertEqual(outbox.email_type_for(['invitation', 'onboarding']), 'onboarding')
        self.assertEqual(outbox.email_type_for(['invitation', 'org_added']), 'org_added')
        self.assertEqual(outbox.email_type_for(['manager_approval', 'weekly']), 'manager_approval')

    def test_unknown_and_empty(self):
        self.assertEqual(outbox.email_type_for(['brand_new']), 'brand_new')
        self.assertEqual(outbox.email_type_for([]), 'other')

    def test_dedupe_buckets_keep_round_minutes_together(self):
        t = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        a = outbox._dedupe_key('x@y.test', 's', 'h', t)
        b = outbox._dedupe_key('X@Y.test', 's', 'h', t + timedelta(milliseconds=30))
        self.assertEqual(a, b)
        self.assertNotEqual(a, outbox._dedupe_key('x@y.test', 's', 'other body', t))


@override_settings(SENDGRID_API_KEY='test-key', DEFAULT_REPLY_TO_EMAIL='dan@mavops.test')
class DispatchTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='More Than Cars', slug='mtc-outbox')
        self.sam = User.objects.create_user('sam', 'sam@mtc.test', 'x')
        OrganizationMembership.objects.create(user=self.sam, organization=self.org)

    def test_default_is_hold_and_nothing_reaches_sendgrid(self):
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            self.assertTrue(_send())
        sg.assert_not_called()
        e = OutboundEmail.objects.get()
        self.assertEqual((e.status, e.email_type, e.to_email), ('held', 'weekly_summary', 'sam@mtc.test'))
        self.assertEqual((e.org_id, e.org_name), (self.org.id, 'More Than Cars'))

    def test_live_sends_to_the_recipient(self):
        outbox.save_settings(mode='live')
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            self.assertTrue(_send())
        self.assertEqual(sg.call_args.kwargs['to_email'], 'sam@mtc.test')
        self.assertEqual(OutboundEmail.objects.get().status, 'sent')

    def test_a_live_type_sends_while_everything_else_is_held(self):
        outbox.save_settings(mode='hold', live_types=['password_reset'])
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            send_password_reset('sam@mtc.test', 'Sam', 'https://x.test/reset/abc')
            _send()
        self.assertEqual(sg.call_count, 1)
        self.assertEqual(dict(OutboundEmail.objects.values_list('email_type', 'status')),
                         {'password_reset': 'sent', 'weekly_summary': 'held'})

    def test_redirect_goes_to_the_test_inbox_and_stays_releasable(self):
        outbox.save_settings(mode='redirect', redirect_to='qa@mavops.test')
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            _send(subject='Your week')
        kw = sg.call_args.kwargs
        self.assertEqual(kw['to_email'], 'qa@mavops.test')
        self.assertIn('sam@mtc.test', kw['subject'])
        self.assertTrue(kw['subject'].endswith('Your week'))
        e = OutboundEmail.objects.get()
        self.assertEqual((e.status, e.sent_to), ('redirected', 'qa@mavops.test'))

        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            self.assertTrue(outbox.release(e))
        self.assertEqual(sg.call_args.kwargs['to_email'], 'sam@mtc.test')
        self.assertEqual(sg.call_args.kwargs['subject'], 'Your week')
        e.refresh_from_db()
        self.assertEqual(e.status, 'sent')

    def test_redirect_without_an_inbox_falls_back_to_reply_to(self):
        outbox.save_settings(mode='redirect')
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            _send()
        self.assertEqual(sg.call_args.kwargs['to_email'], 'dan@mavops.test')

    def test_double_fired_task_sends_once(self):
        outbox.save_settings(mode='live')
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            self.assertTrue(_send())
            self.assertTrue(_send())
        self.assertEqual(sg.call_count, 1)
        self.assertEqual(OutboundEmail.objects.count(), 1)

    def test_unreadable_settings_send_nothing(self):
        with mock.patch.object(outbox, 'read_settings', side_effect=RuntimeError('no table')), \
                mock.patch(SENDGRID, side_effect=_ok) as sg:
            self.assertFalse(_send())
        sg.assert_not_called()
        self.assertFalse(OutboundEmail.objects.exists())

    def test_sendgrid_refusal_is_recorded(self):
        outbox.save_settings(mode='live')
        with mock.patch(SENDGRID, return_value=(False, 400, 'bad from')):
            self.assertFalse(_send())
        e = OutboundEmail.objects.get()
        self.assertEqual((e.status, e.error, e.sendgrid_status), ('failed', 'bad from', 400))


@override_settings(SENDGRID_API_KEY='test-key')
class MavOpsEmailApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('ops', 'ops@mavops.test', 'x', is_staff=True)
        self.api = _client_for(self.staff)
        with mock.patch(SENDGRID, side_effect=_ok):
            _send(subject='One')
            _send(subject='Two', categories=['password_reset'])
        self.one = OutboundEmail.objects.get(subject='One')

    def test_non_staff_cannot_see_the_outbox(self):
        user = User.objects.create_user('sam', 'sam@mtc.test', 'x')
        self.assertEqual(_client_for(user).get('/api/mavops/email/').status_code, 403)

    def test_list_shows_mode_types_and_held_counts(self):
        r = self.api.get('/api/mavops/email/?status=held')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d['settings']['mode'], 'hold')
        held = {t['key']: t['held'] for t in d['types']}
        self.assertEqual((held['weekly_summary'], held['password_reset']), (1, 1))
        self.assertEqual(len(d['emails']), 2)
        self.assertNotIn('html', d['emails'][0])
        self.assertEqual(self.api.get(f'/api/mavops/email/{self.one.id}/').json()['html'], '<p>Hi</p>')

    def test_settings_round_trip_and_validation(self):
        r = self.api.post('/api/mavops/email/settings/',
                          {'mode': 'redirect', 'redirect_to': 'qa@mavops.test',
                           'live_types': ['password_reset']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        row = EmailSendSettings.objects.get(pk=1)
        self.assertEqual((row.mode, row.redirect_to, row.live_types, row.updated_by_id),
                         ('redirect', 'qa@mavops.test', ['password_reset'], self.staff.id))
        self.assertEqual(self.api.post('/api/mavops/email/settings/', {'mode': 'yolo'},
                                       format='json').status_code, 400)
        self.assertEqual(self.api.post('/api/mavops/email/settings/', {'redirect_to': 'nope'},
                                       format='json').status_code, 400)

    def test_send_me_a_copy_leaves_it_held(self):
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            r = self.api.post(f'/api/mavops/email/{self.one.id}/test/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sg.call_args.kwargs['to_email'], 'ops@mavops.test')
        self.one.refresh_from_db()
        self.assertEqual(self.one.status, 'held')

    def test_release_and_discard(self):
        two = OutboundEmail.objects.get(subject='Two')
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            self.assertEqual(self.api.post(f'/api/mavops/email/{self.one.id}/release/').status_code, 200)
            self.assertEqual(self.api.post(f'/api/mavops/email/{two.id}/discard/').status_code, 200)
            # Neither can be acted on again.
            self.assertEqual(self.api.post(f'/api/mavops/email/{self.one.id}/release/').status_code, 400)
            self.assertEqual(self.api.post(f'/api/mavops/email/{two.id}/release/').status_code, 400)
        self.assertEqual(sg.call_count, 1)
        self.assertEqual(dict(OutboundEmail.objects.values_list('subject', 'status')),
                         {'One': 'sent', 'Two': 'discarded'})

    def test_failed_release_says_why(self):
        with mock.patch(SENDGRID, return_value=(False, 401, 'bad key')):
            r = self.api.post(f'/api/mavops/email/{self.one.id}/release/')
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()['error'], 'bad key')

    def test_bulk(self):
        ids = list(OutboundEmail.objects.values_list('id', flat=True))
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            r = self.api.post('/api/mavops/email/bulk/', {'action': 'release', 'ids': ids}, format='json')
        self.assertEqual(sorted(r.json()['done']), sorted(ids))
        self.assertEqual(sg.call_count, 2)
        r = self.api.post('/api/mavops/email/bulk/', {'action': 'discard', 'ids': ids}, format='json')
        self.assertEqual((r.json()['done'], sorted(r.json()['skipped'])), ([], sorted(ids)))


@override_settings(SENDGRID_API_KEY='test-key', DEFAULT_REPLY_TO_EMAIL='dan@mavops.test')
class PerCompanyTests(TestCase):
    """One company's own mode overrides the global one; globally live types still send."""

    def setUp(self):
        self.mtc = Organization.objects.create(name='More Than Cars', slug='mtc-percompany')
        self.ham = Organization.objects.create(name='Hamilton CPA', slug='ham-percompany')
        for name, org in (('sam', self.mtc), ('jo', self.ham)):
            u = User.objects.create_user(name, f'{name}@{org.slug}.test', 'x')
            OrganizationMembership.objects.create(user=u, organization=org)

    def _route(self):
        """Send one weekly summary to each firm; return {org_id: status}."""
        with mock.patch(SENDGRID, side_effect=_ok):
            _send(to='sam@mtc-percompany.test')
            _send(to='jo@ham-percompany.test')
        return dict(OutboundEmail.objects.values_list('org_id', 'status'))

    def test_one_company_live_while_global_holds(self):
        outbox.set_org_mode(self.mtc.id, 'live')
        self.assertEqual(self._route(), {self.mtc.id: 'sent', self.ham.id: 'held'})

    def test_one_company_held_while_global_live(self):
        outbox.save_settings(mode='live')
        outbox.set_org_mode(self.ham.id, 'hold')
        self.assertEqual(self._route(), {self.mtc.id: 'sent', self.ham.id: 'held'})

    def test_company_redirect(self):
        outbox.save_settings(redirect_to='qa@mavops.test')
        outbox.set_org_mode(self.mtc.id, 'redirect')
        self.assertEqual(self._route(), {self.mtc.id: 'redirected', self.ham.id: 'held'})

    def test_globally_live_type_beats_a_held_company(self):
        outbox.save_settings(live_types=['password_reset'])
        outbox.set_org_mode(self.mtc.id, 'hold')
        with mock.patch(SENDGRID, side_effect=_ok) as sg:
            send_password_reset('sam@mtc-percompany.test', 'Sam', 'https://x.test/r/1')
        self.assertEqual(sg.call_count, 1)

    def test_default_removes_the_override(self):
        outbox.set_org_mode(self.mtc.id, 'live')
        outbox.set_org_mode(self.mtc.id, 'default')
        self.assertFalse(OrgEmailSetting.objects.exists())
        self.assertEqual(self._route(), {self.mtc.id: 'held', self.ham.id: 'held'})

    def test_unreadable_company_setting_holds(self):
        outbox.save_settings(mode='live')
        with mock.patch.object(OrgEmailSetting.objects, 'filter', side_effect=RuntimeError('no table')):
            self.assertEqual(outbox.route_for('weekly_summary', self.mtc.id, outbox.read_settings()), 'hold')

    def test_api_sets_lists_and_filters_by_company(self):
        staff = User.objects.create_user('ops', 'ops@mavops.test', 'x', is_staff=True)
        api = _client_for(staff)
        r = api.post(f'/api/mavops/email/org/{self.mtc.id}/', {'mode': 'live'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(api.post(f'/api/mavops/email/org/{self.mtc.id}/', {'mode': 'yolo'},
                                  format='json').status_code, 400)
        self.assertEqual(api.post('/api/mavops/email/org/999999/', {'mode': 'live'},
                                  format='json').status_code, 404)
        self._route()
        d = api.get(f'/api/mavops/email/?org_id={self.ham.id}').json()
        self.assertEqual(d['org_overrides'], [{'org_id': self.mtc.id, 'org_name': 'More Than Cars', 'mode': 'live'}])
        self.assertEqual([e['org_id'] for e in d['emails']], [self.ham.id])
        self.assertEqual(d['counts'], {'held': 1})
        api.post(f'/api/mavops/email/org/{self.mtc.id}/', {'mode': 'default'}, format='json')
        self.assertEqual(api.get('/api/mavops/email/').json()['org_overrides'], [])
