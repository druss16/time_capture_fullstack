"""Calendar integration views — OAuth flow + connection management."""
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from tracker.models import UserIntegration
from tracker.integrations import msgraph
from tracker.views import get_request_org_override


logger = logging.getLogger(__name__)


# ─── OAuth Start ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def microsoft_auth_start(request):
    """..."""
    user = request.user
    org = get_request_org_override(request)
    if not org:
        return Response({'error': 'no_org'}, status=400)
    
    # Generate CSRF state token (stored on integration row)
    state = secrets.token_urlsafe(32)
    
    integration, _ = UserIntegration.objects.get_or_create(
        user=user,
        provider='microsoft_calendar',
        defaults={'org': org},
    )
    integration.org = org
    integration.oauth_state = state
    integration.save(update_fields=['org', 'oauth_state'])
    
    auth_url = msgraph.build_auth_url(
        state=state,
        redirect_uri=settings.MS_GRAPH_REDIRECT_URI,
    )
    
    return Response({'auth_url': auth_url})


# ─── OAuth Callback (no auth required — Microsoft hits this) ─────────────────

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def microsoft_auth_callback(request):
    """
    Microsoft redirects here after user grants consent.
    URL: /api/calendar/auth/callback/?code=...&state=...
    
    No auth on this endpoint because Microsoft is the caller, not a logged-in user.
    Identity is established by the state token matching a row in UserIntegration.
    """
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')
    
    frontend_base = getattr(settings, 'FRONTEND_BASE_URL', None) or settings.MS_GRAPH_REDIRECT_URI.rsplit('/api/', 1)[0]
    success_url = f"{frontend_base}/settings?calendar=connected"
    error_url = f"{frontend_base}/settings?calendar=error"
    
    if error:
        logger.warning(f"[CAL-OAUTH] User cancelled or denied: {error}")
        params = urlencode({'calendar': 'error', 'reason': error})
        return HttpResponseRedirect(f"{frontend_base}/settings?{params}")
    
    if not code or not state:
        logger.warning("[CAL-OAUTH] Missing code or state in callback")
        return HttpResponseRedirect(f"{error_url}&reason=missing_params")
    
    # Find integration by oauth_state (no user context yet — state is the lookup)
    try:
        integration = UserIntegration.objects.select_related('user', 'org').get(
            provider='microsoft_calendar',
            oauth_state=state,
        )
    except UserIntegration.DoesNotExist:
        logger.warning(f"[CAL-OAUTH] No matching state token: {state[:8]}...")
        return HttpResponseRedirect(f"{error_url}&reason=invalid_state")
    
    # Exchange code for tokens
    try:
        result = msgraph.exchange_code_for_tokens(
            code=code,
            redirect_uri=settings.MS_GRAPH_REDIRECT_URI,
        )
    except msgraph.MSGraphAuthError as e:
        logger.error(f"[CAL-OAUTH] Token exchange failed: {e}")
        return HttpResponseRedirect(f"{error_url}&reason=token_exchange_failed")
    
    # Get user profile from Microsoft (email, ID)
    try:
        profile = msgraph.fetch_user_profile(result['access_token'])
    except Exception as e:
        logger.error(f"[CAL-OAUTH] Profile fetch failed: {e}")
        profile = {}
    
    # Save tokens + metadata
    integration.access_token = result['access_token']
    integration.refresh_token = result.get('refresh_token', '')
    integration.token_expires_at = timezone.now() + timedelta(seconds=result.get('expires_in', 3600))
    integration.scopes = result.get('scope', '').split(' ') if result.get('scope') else msgraph.DELEGATED_SCOPES
    integration.is_connected = True
    integration.oauth_state = ''  # one-time use
    integration.provider_account_id = profile.get('id', '')
    integration.provider_email = profile.get('mail') or profile.get('userPrincipalName', '')
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    integration.save()
    
    logger.info(
        f"[CAL-OAUTH] ✅ Connected {integration.user.username} → {integration.provider_email}"
    )
    
    return HttpResponseRedirect(success_url)


# ─── Status / Disconnect ──────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def microsoft_calendar_status(request):
    """Return current calendar connection status for the user."""
    user = request.user
    
    try:
        integration = UserIntegration.objects.get(
            user=user,
            provider='microsoft_calendar',
        )
    except UserIntegration.DoesNotExist:
        return Response({'connected': False})
    
    return Response({
        'connected': integration.is_connected,
        'email': integration.provider_email,
        'last_synced_at': integration.last_synced_at.isoformat() if integration.last_synced_at else None,
        'last_sync_error': integration.last_sync_error,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def microsoft_calendar_disconnect(request):
    """Disconnect calendar — clears tokens, deletes derived events."""
    user = request.user
    
    try:
        integration = UserIntegration.objects.get(
            user=user,
            provider='microsoft_calendar',
        )
    except UserIntegration.DoesNotExist:
        return Response({'ok': True, 'noop': True})
    
    integration.disconnect()
    return Response({'ok': True})