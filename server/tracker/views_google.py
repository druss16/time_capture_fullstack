"""Google (Gmail + Google Calendar) per-user OAuth views.

Mirrors views_mail.py / views_calendar.py. Two providers, one module, because
everything but the scope, redirect URI and sync task is identical:

    provider          start / callback / status / disconnect
    gmail             /api/google/gmail/...
    google_calendar   /api/google/calendar/...

Each flow has its own registered redirect URI (settings.GOOGLE_GMAIL_REDIRECT_URI,
settings.GOOGLE_CALENDAR_REDIRECT_URI). The code exchange repeats the URI the
flow STARTED with — taken from the provider on the row the state token
matches, never from which callback path the redirect happened to land on —
because Google rejects an exchange whose redirect_uri differs from the one the
code was issued for.

The post-OAuth landing page is /account/connections?gmail=... or ?gcal=...
"""
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from tracker.integrations import google
from tracker.models import UserIntegration
from tracker.services.integration_health import PERMISSION_DENIED_MARKER, health_payload
from tracker.views import get_request_org_override
from tracker.views_mail import oauth_frontend_base

logger = logging.getLogger(__name__)

GOOGLE_PROVIDERS = ('gmail', 'google_calendar')
# Query-string key the Connections page reads for each card.
RESULT_KEY = {'gmail': 'gmail', 'google_calendar': 'gcal'}


def _is_mail(provider):
    return provider == 'gmail'


def _org_mail_disabled(org):
    return bool(getattr(org, 'disable_mail_integration', False))


def _landing(provider, **params):
    return HttpResponseRedirect(
        f"{oauth_frontend_base()}/account/connections?"
        + urlencode({RESULT_KEY[provider]: params.pop('result'), **params})
    )


def _configured():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


# ─── Start ────────────────────────────────────────────────────────────────────

def _auth_start(request, provider):
    user = request.user
    org = get_request_org_override(request)
    if not org:
        return Response({'error': 'no_org'}, status=400)
    if not _configured():
        return Response(
            {'error': 'google_not_configured',
             'detail': 'Google sign-in is not set up on this server yet.'},
            status=503,
        )
    if _is_mail(provider) and _org_mail_disabled(org):
        return Response(
            {'error': 'mail_integration_disabled',
             'detail': 'Mail integration is disabled for your organization.'},
            status=403,
        )

    state = secrets.token_urlsafe(32)
    integration, _ = UserIntegration.objects.get_or_create(
        user=user, provider=provider, defaults={'org': org},
    )
    integration.org = org
    integration.oauth_state = state
    integration.save(update_fields=['org', 'oauth_state'])

    return Response({
        'auth_url': google.build_auth_url(provider, state, login_hint=user.email or ''),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def gmail_auth_start(request):
    return _auth_start(request, 'gmail')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def google_calendar_auth_start(request):
    return _auth_start(request, 'google_calendar')


# ─── Callback ─────────────────────────────────────────────────────────────────

def _auth_callback(request, path_provider):
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')

    integration = None
    if state:
        integration = UserIntegration.objects.select_related('user', 'org').filter(
            provider__in=GOOGLE_PROVIDERS, oauth_state=state,
        ).first()
    provider = integration.provider if integration else path_provider

    if error:
        logger.warning(f"[GOOGLE-OAUTH] {provider}: user cancelled or denied: {error}")
        return _landing(provider, result='error', reason=error)
    if not code or not state:
        return _landing(provider, result='error', reason='missing_params')
    if integration is None:
        logger.warning(f"[GOOGLE-OAUTH] No matching state token: {state[:8]}...")
        return _landing(provider, result='error', reason='invalid_state')
    return finish_google_connection(integration, code)


def finish_google_connection(integration, code):
    """Exchange the code, store tokens + identity, kick off the first sync."""
    provider = integration.provider

    if _is_mail(provider) and _org_mail_disabled(integration.org):
        return _landing(provider, result='error', reason='org_disabled')

    try:
        result = google.exchange_code_for_tokens(provider, code)
    except google.GoogleAuthError as e:
        logger.error(f"[GOOGLE-OAUTH] {provider}: token exchange failed: {e}")
        return _landing(provider, result='error', reason='token_exchange_failed')

    missing = google.granted_scopes_missing(provider, result)
    if missing:
        # Granular consent: they approved sign-in but unticked the data box.
        # Store NOTHING from this exchange — a token without the scope would
        # produce five 403s and a "paused" card. A row that was never
        # connected is marked so the card says "Permission not granted"
        # rather than "Setup never finished"; a row that already holds a
        # working grant from before is left exactly as it was.
        logger.warning(f"[GOOGLE-OAUTH] {provider}: scopes not granted: {missing}")
        integration.oauth_state = ''
        fields = ['oauth_state']
        if not (integration.refresh_token or '').strip():
            integration.is_connected = False
            integration.last_sync_error = (
                f"{PERMISSION_DENIED_MARKER}: {', '.join(missing)}"
            )[:500]
            fields += ['is_connected', 'last_sync_error']
        integration.save(update_fields=fields)
        return _landing(provider, result='error', reason='permission_not_granted')

    try:
        profile = google.fetch_userinfo(result['access_token'])
    except Exception as e:
        logger.error(f"[GOOGLE-OAUTH] {provider}: userinfo failed: {e}")
        profile = {}

    integration.access_token = result['access_token']
    integration.refresh_token = result.get('refresh_token', '') or integration.refresh_token or ''
    integration.token_expires_at = timezone.now() + timedelta(seconds=int(result.get('expires_in', 3600)))
    integration.scopes = (result.get('scope') or '').split() or google.PROVIDER_CONFIG[provider]['scopes']
    integration.is_connected = True
    integration.oauth_state = ''
    integration.provider_account_id = profile.get('sub', '') or ''
    integration.provider_email = (profile.get('email') or '')[:254]
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    integration.sync_cursor = ''          # first sync is a full one
    integration.sync_cursor_set_at = None
    integration.save()

    logger.info(
        f"[GOOGLE-OAUTH] Connected {integration.user.username} → {provider} "
        f"({integration.provider_email})"
    )

    try:
        if _is_mail(provider):
            from tracker.tasks_gmail import sync_user_gmail
            sync_user_gmail.delay(integration.id)
        else:
            from tracker.tasks_google_calendar import sync_user_google_calendar
            sync_user_google_calendar.delay(integration.id)
    except Exception as e:
        logger.warning(f"[GOOGLE-OAUTH] Failed to enqueue immediate sync: {e}")

    return _landing(provider, result='connected')


@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def gmail_auth_callback(request):
    return _auth_callback(request, 'gmail')


@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def google_calendar_auth_callback(request):
    return _auth_callback(request, 'google_calendar')


# ─── Status / Disconnect ──────────────────────────────────────────────────────

def _status(request, provider):
    try:
        integration = UserIntegration.objects.select_related('org').get(
            user=request.user, provider=provider,
        )
    except UserIntegration.DoesNotExist:
        return Response({'connected': False, 'configured': _configured()})
    org_disabled = _is_mail(provider) and _org_mail_disabled(integration.org)
    extra = {}
    if not _is_mail(provider):
        # Read-only view of the org's calendar gate (see views_calendar).
        extra['calendar_classification_enabled'] = bool(
            getattr(integration.org, 'calendar_classification_enabled', False))
    return Response({
        **extra,
        'connected': integration.is_connected and not org_disabled,
        'configured': _configured(),
        'org_disabled': org_disabled,
        'email': integration.provider_email,
        'last_synced_at': integration.last_synced_at.isoformat() if integration.last_synced_at else None,
        'last_sync_error': integration.last_sync_error,
        'health': health_payload(integration),
    })


def _disconnect(request, provider):
    try:
        integration = UserIntegration.objects.get(user=request.user, provider=provider)
    except UserIntegration.DoesNotExist:
        return Response({'ok': True, 'noop': True})
    # disconnect() deletes the derived MailSignal / CalendarEvent rows and
    # clears the tokens + sync cursor. We do NOT call Google's revoke
    # endpoint: with include_granted_scopes one grant covers Gmail AND
    # Calendar, so revoking here would silently kill the other product. The
    # grant stays on the Google account until the user removes it at
    # myaccount.google.com/permissions (or disconnects both products).
    integration.disconnect()
    return Response({'ok': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def gmail_status(request):
    return _status(request, 'gmail')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def google_calendar_status(request):
    return _status(request, 'google_calendar')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def gmail_disconnect(request):
    return _disconnect(request, 'gmail')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def google_calendar_disconnect(request):
    return _disconnect(request, 'google_calendar')
