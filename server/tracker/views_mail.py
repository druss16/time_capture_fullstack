"""Mail integration views — OAuth flow + connection management.

Mirrors views_calendar.py. Key differences:
  - Provider is 'microsoft_mail' (not 'microsoft_calendar')
  - Scopes are MAIL_DELEGATED_SCOPES (Mail.ReadBasic + User.Read)
  - On successful connect, kicks off immediate sync (no 5-min wait)
  - Webhook stub responds to validation token handshake (not yet wired
    to actual Graph subscriptions — Stage 7.5)
"""
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from tracker.models import UserIntegration
from tracker.integrations import msgraph
from tracker.views import get_request_org_override


logger = logging.getLogger(__name__)


# ─── Shared OAuth helpers ─────────────────────────────────────────────────────

def oauth_frontend_base():
    """Base URL of the SPA — where every OAuth flow lands the user."""
    base = (
        getattr(settings, 'FRONTEND_BASE_URL', '')
        or getattr(settings, 'FRONTEND_URL', '')
        or settings.MS_GRAPH_REDIRECT_URI.rsplit('/api/', 1)[0]
    )
    return base.rstrip('/')


# ─── OAuth Start ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def microsoft_mail_auth_start(request):
    """Initiate Microsoft Mail OAuth flow."""
    user = request.user
    org = get_request_org_override(request)
    if not org:
        return Response({'error': 'no_org'}, status=400)

    # Honor per-org kill switch — block connection attempts at the source
    if getattr(org, 'disable_mail_integration', False):
        logger.info(f"[MAIL-OAUTH] Connect blocked for org {org.id} — flag set")
        return Response(
            {'error': 'mail_integration_disabled', 'detail': 'Mail integration is disabled for your organization.'},
            status=403,
        )

    state = secrets.token_urlsafe(32)

    integration, _ = UserIntegration.objects.get_or_create(
        user=user,
        provider='microsoft_mail',
        defaults={'org': org},
    )
    integration.org = org
    integration.oauth_state = state
    integration.save(update_fields=['org', 'oauth_state'])

    auth_url = msgraph.build_auth_url_mail(
        state=state,
        redirect_uri=settings.MS_GRAPH_MAIL_REDIRECT_URI,
    )

    return Response({'auth_url': auth_url})


# ─── OAuth Callback ───────────────────────────────────────────────────────────

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def microsoft_mail_auth_callback(request):
    """
    Microsoft redirects here after the user grants Mail.ReadBasic consent —
    when MS_GRAPH_MAIL_REDIRECT_URI is registered in Azure AD as its own
    redirect URI.
    URL: /api/mail/auth/callback/?code=...&state=...

    If mail and calendar instead share a single registered redirect URI, the
    calendar callback receives the redirect and delegates to
    finish_mail_connection() below — it tells the two flows apart by the
    provider on the UserIntegration row the state token matches. Either way
    the same completion code runs.
    """
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')

    frontend_base = oauth_frontend_base()
    error_base = f"{frontend_base}/account/connections?mail=error"

    if error:
        logger.warning(f"[MAIL-OAUTH] User cancelled or denied: {error}")
        # A shared redirect URI means this may be an abandoned calendar flow —
        # name the right card on the connections page.
        key = 'calendar' if (state and UserIntegration.objects.filter(
            provider='microsoft_calendar', oauth_state=state,
        ).exists()) else 'mail'
        params = urlencode({key: 'error', 'reason': error})
        return HttpResponseRedirect(f"{frontend_base}/account/connections?{params}")

    if not code or not state:
        logger.warning("[MAIL-OAUTH] Missing code or state in callback")
        return HttpResponseRedirect(f"{error_base}&reason=missing_params")

    try:
        integration = UserIntegration.objects.select_related('user', 'org').get(
            provider__in=('microsoft_mail', 'microsoft_calendar'),
            oauth_state=state,
        )
    except UserIntegration.DoesNotExist:
        logger.warning(f"[MAIL-OAUTH] No matching state token: {state[:8]}...")
        return HttpResponseRedirect(f"{error_base}&reason=invalid_state")

    if integration.provider == 'microsoft_calendar':
        # Calendar consent arriving on a shared redirect URI. Imported here
        # rather than at module scope: views_calendar imports this module, so
        # a top-level import back would be circular.
        from tracker.views_calendar import finish_calendar_connection
        return finish_calendar_connection(integration, code)

    return finish_mail_connection(integration, code)


def finish_mail_connection(integration, code):
    """
    Complete a mail connection: trade the code for tokens, persist them, and
    kick off the first sync. Called by the mail callback, and by the calendar
    callback when both flows share one registered redirect URI.

    The exchange repeats MS_GRAPH_MAIL_REDIRECT_URI because that is what
    auth_start signed in with — Graph rejects a redirect_uri that differs from
    the one the code was issued for, whichever path the redirect landed on.

    Returns the HttpResponseRedirect to send the user back to the app with.
    """
    frontend_base = oauth_frontend_base()
    success_url = f"{frontend_base}/account/connections?mail=connected"
    error_base = f"{frontend_base}/account/connections?mail=error"

    # Re-check kill switch — org policy may have flipped between auth_start and callback
    if getattr(integration.org, 'disable_mail_integration', False):
        logger.warning(f"[MAIL-OAUTH] Org {integration.org.id} flag set during flow — aborting")
        return HttpResponseRedirect(f"{error_base}&reason=org_disabled")

    try:
        result = msgraph.exchange_code_for_tokens_mail(
            code=code,
            redirect_uri=settings.MS_GRAPH_MAIL_REDIRECT_URI,
        )
    except msgraph.MSGraphAuthError as e:
        logger.error(f"[MAIL-OAUTH] Token exchange failed: {e}")
        return HttpResponseRedirect(f"{error_base}&reason=token_exchange_failed")

    try:
        profile = msgraph.fetch_user_profile(result['access_token'])
    except Exception as e:
        logger.error(f"[MAIL-OAUTH] Profile fetch failed: {e}")
        profile = {}

    integration.access_token = result['access_token']
    integration.refresh_token = result.get('refresh_token', '')
    integration.token_expires_at = timezone.now() + timedelta(seconds=result.get('expires_in', 3600))
    integration.scopes = (
        result.get('scope', '').split(' ')
        if result.get('scope')
        else msgraph.MAIL_DELEGATED_SCOPES
    )
    integration.is_connected = True
    integration.oauth_state = ''
    integration.provider_account_id = profile.get('id', '')
    integration.provider_email = profile.get('mail') or profile.get('userPrincipalName', '')
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    integration.mail_delta_link = ''  # First sync starts fresh
    integration.save()

    logger.info(
        f"[MAIL-OAUTH] ✅ Connected {integration.user.username} → {integration.provider_email}"
    )

    # Kick off immediate sync — don't make the user wait 5 min for the first poll cycle.
    # Runs as a Celery task so the OAuth redirect returns instantly.
    try:
        from tracker.tasks_mail import sync_user_mail
        sync_user_mail.delay(integration.id)
    except Exception as e:
        logger.warning(f"[MAIL-OAUTH] Failed to enqueue immediate sync: {e}")
        # Non-fatal — beat will pick it up on next cycle

    return HttpResponseRedirect(success_url)


# ─── Status / Disconnect ──────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def microsoft_mail_status(request):
    """Return current mail connection status for the user."""
    user = request.user

    try:
        integration = UserIntegration.objects.get(
            user=user,
            provider='microsoft_mail',
        )
    except UserIntegration.DoesNotExist:
        return Response({'connected': False})

    # Surface the org-level disable so the frontend can show a "disabled by admin" state
    org_disabled = bool(getattr(integration.org, 'disable_mail_integration', False))

    return Response({
        'connected': integration.is_connected and not org_disabled,
        'org_disabled': org_disabled,
        'email': integration.provider_email,
        'last_synced_at': integration.last_synced_at.isoformat() if integration.last_synced_at else None,
        'last_sync_error': integration.last_sync_error,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def microsoft_mail_disconnect(request):
    """Disconnect mail — clears tokens and deletes derived MailSignal rows."""
    user = request.user

    try:
        integration = UserIntegration.objects.get(
            user=user,
            provider='microsoft_mail',
        )
    except UserIntegration.DoesNotExist:
        return Response({'ok': True, 'noop': True})

    # The model's disconnect() already deletes MailSignal rows (it checks is_mail)
    integration.disconnect()
    # Clear the delta link too so a future reconnect starts fresh
    integration.mail_delta_link = ''
    integration.save(update_fields=['mail_delta_link'])

    return Response({'ok': True})


# ─── Webhook stub (Stage 7.5) ─────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def microsoft_mail_webhook(request):
    """
    Stub for Microsoft Graph mail change notifications.

    Stage 7.5 will wire this up to actual /subscriptions endpoints. For now,
    this endpoint:
      - Responds to Graph's validation token handshake (required for any
        webhook URL Microsoft considers registering)
      - Logs incoming POSTs without acting on them

    When Stage 7.5 lands, the POST handler will:
      1. Verify clientState matches what we stored on the subscription
      2. Enqueue sync_user_mail.delay() for the affected user (lookup via
         subscription_id → UserIntegration)
      3. Return 202 Accepted within 30s (Graph requirement)

    The actual fetching still happens via /messages/delta — webhook is just
    the trigger that says "go check now instead of waiting for the next poll."
    """
    # Validation handshake — Microsoft sends GET with ?validationToken=...
    # when registering the subscription
    validation_token = request.GET.get('validationToken')
    if validation_token:
        return HttpResponse(validation_token, content_type='text/plain', status=200)

    # POST = actual notification (not handled yet)
    if request.method == 'POST':
        logger.info(f"[MAIL-WEBHOOK] Received notification (stub, not processed): {request.body[:200]}")
        return HttpResponse(status=202)

    return HttpResponse(status=200)