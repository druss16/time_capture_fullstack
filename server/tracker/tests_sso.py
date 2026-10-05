"""
Sign in with Microsoft / Google — see views_sso.py for the rules under test.
"""
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from tracker import views_sso
from tracker.models import AuthToken
from tracker.models_sso import SocialLogin

User = get_user_model()

SSO = dict(
    SSO_PROVIDERS=['microsoft', 'google'],
    SSO_MICROSOFT_CLIENT_ID='ms-id', SSO_MICROSOFT_CLIENT_SECRET='ms-secret',
    SSO_GOOGLE_CLIENT_ID='g-id', SSO_GOOGLE_CLIENT_SECRET='g-secret',
    FRONTEND_URL='https://app.test',
)


@override_settings(**SSO)
class SSOFlowTests(TestCase):
    def setUp(self):
        self.jane = User.objects.create_user('jane@firm.test', 'jane@firm.test')
        self.c = APIClient()

    # ── helpers ──
    def start(self, provider='google', next_='/reports'):
        with mock.patch.object(views_sso, '_auth_url', return_value='https://idp.test/auth'):
            r = self.c.get(f'/api/auth/sso/{provider}/start/', {'next': next_})
        self.assertEqual(r.status_code, 302)
        return r

    def callback(self, identity, provider='google', state=None):
        if state is None:
            r = self.start(provider)
            state = None
            # pull the state the start view signed, via the nonce cookie
            nonce = r.cookies[views_sso.NONCE_COOKIE].value
            state = signing.dumps({'p': provider, 'n': nonce, 'next': '/reports'},
                                  salt=views_sso.STATE_SALT)
        with mock.patch.object(views_sso, 'fetch_identity', return_value=identity):
            return self.c.get(f'/api/auth/sso/{provider}/callback/',
                              {'code': 'abc', 'state': state})

    def fragment(self, r):
        return {k: v[0] for k, v in parse_qs(urlparse(r['Location']).fragment).items()}

    def login_error(self, r):
        return parse_qs(urlparse(r['Location']).query).get('sso_error', [''])[0]

    # ── tests ──
    def test_providers_lists_only_enabled_and_configured(self):
        self.assertEqual(self.c.get('/api/auth/sso/providers/').json()['providers'],
                         ['microsoft', 'google'])
        with override_settings(SSO_PROVIDERS=[]):
            self.assertEqual(self.c.get('/api/auth/sso/providers/').json()['providers'], [])

    def test_full_flow_links_by_verified_email_and_issues_token(self):
        r = self.callback(('g-sub-1', 'Jane@Firm.test', True))
        self.assertTrue(r['Location'].startswith('https://app.test/auth/sso/complete#'))
        frag = self.fragment(r)
        self.assertEqual(frag['next'], '/reports')

        r = self.c.post('/api/auth/sso/exchange/', {'code': frag['code']}, format='json')
        self.assertEqual(r.status_code, 200, r.json())
        body = r.json()
        self.assertTrue(AuthToken.objects.filter(user=self.jane, token=body['token']).exists())
        self.assertEqual(body['user']['email'], 'jane@firm.test')
        link = SocialLogin.objects.get()
        self.assertEqual((link.user, link.provider, link.subject), (self.jane, 'google', 'g-sub-1'))

    def test_code_is_single_use(self):
        code = self.fragment(self.callback(('g-sub-1', 'jane@firm.test', True)))['code']
        self.assertEqual(self.c.post('/api/auth/sso/exchange/', {'code': code}, format='json').status_code, 200)
        self.assertEqual(self.c.post('/api/auth/sso/exchange/', {'code': code}, format='json').status_code, 400)

    def test_stale_code_is_refused(self):
        code = self.fragment(self.callback(('g-sub-1', 'jane@firm.test', True)))['code']
        SocialLogin.objects.update(ticket_issued_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.c.post('/api/auth/sso/exchange/', {'code': code}, format='json').status_code, 400)

    def test_never_creates_an_account(self):
        r = self.callback(('g-sub-x', 'stranger@gmail.test', True))
        self.assertEqual(self.login_error(r), 'no_account')
        self.assertFalse(User.objects.filter(email='stranger@gmail.test').exists())
        self.assertFalse(SocialLogin.objects.exists())

    def test_unverified_email_does_not_match(self):
        r = self.callback(('g-sub-1', 'jane@firm.test', False))
        self.assertEqual(self.login_error(r), 'no_account')
        self.assertFalse(SocialLogin.objects.exists())

    def test_ambiguous_email_does_not_guess(self):
        User.objects.create_user('jane-dup', 'JANE@firm.test')
        r = self.callback(('g-sub-1', 'jane@firm.test', True))
        self.assertEqual(self.login_error(r), 'no_account')

    def test_linked_subject_wins_over_a_changed_email(self):
        SocialLogin.objects.create(user=self.jane, provider='microsoft', subject='t1:o1')
        mallory = User.objects.create_user('mallory@evil.test', 'mallory@evil.test')
        # Same subject now reports Mallory's address: still Jane's link.
        r = self.callback(('t1:o1', 'mallory@evil.test', True), provider='microsoft')
        code = self.fragment(r)['code']
        body = self.c.post('/api/auth/sso/exchange/', {'code': code}, format='json').json()
        self.assertEqual(body['user']['id'], self.jane.id)
        # And a different subject claiming Jane's email can't reach her via the link.
        self.assertFalse(SocialLogin.objects.filter(user=mallory).exists())

    def test_disabled_user_is_refused(self):
        self.jane.is_active = False
        self.jane.save()
        self.assertEqual(self.login_error(self.callback(('g-sub-1', 'jane@firm.test', True))), 'disabled')

    def test_state_without_matching_cookie_is_refused(self):
        # A callback URL replayed in a browser that never started the flow.
        state = signing.dumps({'p': 'google', 'n': 'attacker', 'next': '/'}, salt=views_sso.STATE_SALT)
        r = self.callback(('g-sub-1', 'jane@firm.test', True), state=state)
        self.assertEqual(self.login_error(r), 'expired')

    def test_provider_cancel_returns_to_login(self):
        self.start()
        r = self.c.get('/api/auth/sso/google/callback/', {'error': 'access_denied'})
        self.assertEqual(self.login_error(r), 'cancelled')

    def test_disabled_provider_redirects_to_login(self):
        with override_settings(SSO_PROVIDERS=['google']):
            r = self.c.get('/api/auth/sso/microsoft/start/')
        self.assertEqual(self.login_error(r), 'unavailable')

    def test_next_is_kept_on_site(self):
        for bad in ('https://evil.test', '//evil.test', '/\\evil.test'):
            self.assertEqual(views_sso._safe_next(bad), '/daily')
        self.assertEqual(views_sso._safe_next('/reports?x=1'), '/reports?x=1')

    def test_microsoft_falls_back_to_integration_app_as_a_pair(self):
        with override_settings(SSO_MICROSOFT_CLIENT_ID='', MS_GRAPH_CLIENT_ID='cal-id',
                               MS_GRAPH_CLIENT_SECRET='cal-secret'):
            self.assertEqual(views_sso._credentials('microsoft'), ('cal-id', 'cal-secret'))


class MicrosoftIdentityTests(TestCase):
    @override_settings(**SSO)
    def test_subject_is_tenant_scoped_and_email_is_the_upn(self):
        app = mock.Mock()
        app.acquire_token_by_authorization_code.return_value = {'id_token_claims': {
            'tid': 'T', 'oid': 'O', 'preferred_username': 'Jane@Firm.test',
            'email': 'someone-else@victim.test',  # mutable claim — must be ignored
        }}
        with mock.patch.object(views_sso, '_msal_app', return_value=app):
            self.assertEqual(views_sso.fetch_identity('microsoft', 'code'),
                             ('T:O', 'jane@firm.test', True))


class PasswordLoginStillWorksTests(TestCase):
    """auth_login now shares issue_login_payload with SSO; same response shape."""

    def test_password_login_returns_token_and_user(self):
        u = User.objects.create_user('pat@firm.test', 'pat@firm.test', 'pw-123456')
        r = APIClient().post('/api/auth/login/', {'username': 'pat@firm.test', 'password': 'pw-123456'},
                             format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(AuthToken.objects.filter(user=u, token=r.json()['token']).exists())
        self.assertEqual(r.json()['user']['email'], 'pat@firm.test')
