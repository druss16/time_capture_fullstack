"""
Sign in with Microsoft / Google.

    GET  /api/auth/sso/providers/            which buttons the login page shows
    GET  /api/auth/sso/<provider>/start/     browser navigates here; 302 to the provider
    GET  /api/auth/sso/<provider>/callback/  provider redirects here; 302 to the SPA
    POST /api/auth/sso/exchange/             SPA trades the one-time code for a token

Rules, each one load-bearing:

  * SSO never creates a User. Onboarding is white-glove: a person exists
    because a firm invited or provisioned them. An unknown identity is sent
    back to /login with sso_error=no_account.
  * First sign-in matches the invited User by a VERIFIED email, then records
    a SocialLogin; every later sign-in matches on the provider subject only
    (see models_sso.py for why that matters on Microsoft).
  * Microsoft uses the `organizations` authority — work/school accounts only.
    A personal Microsoft account can be registered under any address, so its
    email proves less than a tenant's UPN, whose domain the tenant had to
    verify. Microsoft's mutable `email` claim is never read.
  * Login CSRF: `state` is signed and carries a nonce that must equal the
    HttpOnly cookie set on /start/, so a callback URL lifted from someone
    else's browser signs in nobody.
  * The 14-day token never rides in a URL. The callback hands the SPA a signed
    one-time code in the fragment (not sent to servers, not logged); the SPA
    POSTs it to /exchange/ within two minutes, once.
"""
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from tracker.models_sso import SocialLogin

logger = logging.getLogger(__name__)
User = get_user_model()

PROVIDERS = ('microsoft', 'google')
NONCE_COOKIE = 'tt_sso_nonce'
STATE_SALT = 'tracker.sso.state'
TICKET_SALT = 'tracker.sso.ticket'
STATE_MAX_AGE = 600      # seconds the person has to finish at the provider
TICKET_MAX_AGE = 120     # seconds the SPA has to redeem the hand-off code

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
MS_AUTHORITY = 'https://login.microsoftonline.com/organizations'


class SSOError(Exception):
    """Carries the short code the login page turns into a message."""

    def __init__(self, code, detail=''):
        super().__init__(detail or code)
        self.code = code


# ── Provider configuration ───────────────────────────────────────────────

def _credentials(provider):
    """(client_id, client_secret), falling back as a PAIR to the integration
    app — never one field from each registration."""
    if provider == 'microsoft':
        if settings.SSO_MICROSOFT_CLIENT_ID:
            return settings.SSO_MICROSOFT_CLIENT_ID, settings.SSO_MICROSOFT_CLIENT_SECRET
        return settings.MS_GRAPH_CLIENT_ID, settings.MS_GRAPH_CLIENT_SECRET
    if settings.SSO_GOOGLE_CLIENT_ID:
        return settings.SSO_GOOGLE_CLIENT_ID, settings.SSO_GOOGLE_CLIENT_SECRET
    return settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET


def _redirect_uri(provider):
    return (settings.SSO_MICROSOFT_REDIRECT_URI if provider == 'microsoft'
            else settings.SSO_GOOGLE_REDIRECT_URI)


def enabled_providers():
    return [p for p in settings.SSO_PROVIDERS
            if p in PROVIDERS and all(_credentials(p))]


def _msal_app(provider):
    import msal
    client_id, secret = _credentials(provider)
    return msal.ConfidentialClientApplication(
        client_id=client_id, client_credential=secret, authority=MS_AUTHORITY)


def _auth_url(provider, state):
    if provider == 'microsoft':
        # MSAL adds openid/profile/offline_access itself; asking for `email`
        # alone keeps Graph (and admin consent) out of the request entirely.
        return _msal_app(provider).get_authorization_request_url(
            scopes=['email'], state=state, redirect_uri=_redirect_uri(provider),
            prompt='select_account')
    client_id, _ = _credentials(provider)
    return f'{GOOGLE_AUTH_URL}?' + urlencode({
        'client_id': client_id,
        'redirect_uri': _redirect_uri(provider),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    })


def fetch_identity(provider, code):
    """Trade the auth code for (subject, email, email_is_verified)."""
    if provider == 'microsoft':
        result = _msal_app(provider).acquire_token_by_authorization_code(
            code=code, scopes=['email'], redirect_uri=_redirect_uri(provider))
        if 'error' in result:
            raise SSOError('provider', result.get('error_description', result['error']))
        claims = result.get('id_token_claims') or {}
        tid, oid = claims.get('tid'), claims.get('oid')
        if not (tid and oid):
            raise SSOError('provider', 'id_token missing tid/oid')
        # preferred_username is the UPN under the organizations authority;
        # its domain is one the tenant verified.
        upn = (claims.get('preferred_username') or '').strip().lower()
        return f'{tid}:{oid}', upn, '@' in upn

    client_id, secret = _credentials(provider)
    try:
        tok = requests.post(GOOGLE_TOKEN_URL, data={
            'code': code, 'client_id': client_id, 'client_secret': secret,
            'redirect_uri': _redirect_uri(provider), 'grant_type': 'authorization_code',
        }, timeout=15)
        tok.raise_for_status()
        info = requests.get(GOOGLE_USERINFO_URL, timeout=15, headers={
            'Authorization': f"Bearer {tok.json()['access_token']}"})
        info.raise_for_status()
        info = info.json()
    except (requests.RequestException, KeyError, ValueError) as e:
        raise SSOError('provider', str(e))
    email = (info.get('email') or '').strip().lower()
    return info['sub'], email, info.get('email_verified') is True


# ── Matching ─────────────────────────────────────────────────────────────

def resolve_user(provider, subject, email, email_ok):
    """The SocialLogin for this identity, linking it on first sign-in."""
    link = SocialLogin.objects.select_related('user').filter(
        provider=provider, subject=subject).first()
    if link:
        if not link.user.is_active:
            raise SSOError('disabled')
        return link

    if not (email and email_ok):
        raise SSOError('no_account', f'{provider} gave no verified email')
    users = list(User.objects.filter(email__iexact=email)[:2])
    if len(users) != 1:
        # Zero: not invited. Two: ambiguous, and guessing is how a session
        # lands in the wrong person's account.
        raise SSOError('no_account', f'{len(users)} users for {email}')
    user = users[0]
    if not user.is_active:
        raise SSOError('disabled')
    link, _ = SocialLogin.objects.get_or_create(
        provider=provider, subject=subject,
        defaults={'user': user, 'email_at_link': email})
    logger.info('[SSO] linked %s %s to user %s', provider, email, user.id)
    return link


# ── Helpers ──────────────────────────────────────────────────────────────

def _safe_next(raw):
    raw = raw or ''
    return raw if raw.startswith('/') and not raw.startswith('//') and '\\' not in raw else '/daily'


def _frontend():
    return settings.FRONTEND_URL.rstrip('/')


def _to_login(code):
    resp = HttpResponseRedirect(f'{_frontend()}/login?' + urlencode({'sso_error': code}))
    resp.delete_cookie(NONCE_COOKIE, path='/api/auth/sso/')
    return resp


# ── Views ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def sso_providers(request):
    return Response({'providers': enabled_providers()})


def sso_start(request, provider):
    if provider not in enabled_providers():
        return _to_login('unavailable')
    # The nonce cookie must be set on the host the provider returns to. The SPA
    # may call the API on another name (timetracker-api-k375.onrender.com vs
    # api.timetracker.mavops.ai); a cookie set there never reaches the callback
    # and every sign-in fails as "expired". Hop to the callback's host first.
    callback = urlsplit(_redirect_uri(provider))
    if request.get_host().lower() != callback.netloc.lower():
        return HttpResponseRedirect(
            f'{callback.scheme}://{callback.netloc}{request.get_full_path()}')
    nonce = secrets.token_urlsafe(24)
    state = signing.dumps({'p': provider, 'n': nonce,
                           'next': _safe_next(request.GET.get('next'))}, salt=STATE_SALT)
    resp = HttpResponseRedirect(_auth_url(provider, state))
    # Lax, not Strict: it must ride along on the provider's top-level GET back.
    resp.set_cookie(NONCE_COOKIE, nonce, max_age=STATE_MAX_AGE, path='/api/auth/sso/',
                    httponly=True, secure=not settings.DEBUG, samesite='Lax')
    return resp


def sso_callback(request, provider):
    if provider not in enabled_providers():
        return _to_login('unavailable')
    if request.GET.get('error'):
        return _to_login('cancelled')
    try:
        state = signing.loads(request.GET.get('state', ''), salt=STATE_SALT,
                              max_age=STATE_MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        return _to_login('expired')
    cookie = request.COOKIES.get(NONCE_COOKIE, '')
    if state.get('p') != provider or not cookie or not secrets.compare_digest(cookie, state.get('n', '')):
        return _to_login('expired')

    try:
        subject, email, email_ok = fetch_identity(provider, request.GET.get('code', ''))
        link = resolve_user(provider, subject, email, email_ok)
    except SSOError as e:
        logger.warning('[SSO] %s sign-in refused: %s (%s)', provider, e.code, e)
        return _to_login(e.code)

    ticket = secrets.token_urlsafe(24)
    link.ticket_nonce = ticket
    link.ticket_issued_at = timezone.now()
    link.save(update_fields=['ticket_nonce', 'ticket_issued_at'])
    code = signing.dumps({'l': link.id, 'n': ticket}, salt=TICKET_SALT)

    resp = HttpResponseRedirect(f'{_frontend()}/auth/sso/complete#' + urlencode(
        {'code': code, 'next': state.get('next') or '/daily'}))
    resp.delete_cookie(NONCE_COOKIE, path='/api/auth/sso/')
    return resp


@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def sso_exchange(request):
    from tracker.views import issue_login_payload

    try:
        data = signing.loads((request.data or {}).get('code', ''), salt=TICKET_SALT,
                             max_age=TICKET_MAX_AGE)
    except signing.BadSignature:
        return Response({'ok': False, 'error': 'Sign-in link expired. Please try again.'}, status=400)

    now = timezone.now()
    # Single use: only the request that clears the nonce wins.
    claimed = SocialLogin.objects.filter(
        id=data.get('l'), ticket_nonce=data.get('n') or '-',
        ticket_issued_at__gte=now - timedelta(seconds=TICKET_MAX_AGE),
    ).update(ticket_nonce='', last_login_at=now)
    if claimed != 1:
        return Response({'ok': False, 'error': 'Sign-in link already used. Please try again.'}, status=400)

    link = SocialLogin.objects.select_related('user').get(id=data['l'])
    if not link.user.is_active:
        return Response({'ok': False, 'error': 'Account is disabled.'}, status=400)
    return Response(issue_login_payload(request, link.user))
