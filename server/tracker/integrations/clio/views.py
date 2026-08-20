"""
Clio Manage OAuth endpoints: connect, callback, status, disconnect.

Multi-tenant by construction — one Clio app registration serves every firm,
and each firm's grant lands on its own Integration row. Clio rate-limits per
access token, so firms do not contend with each other.

The one thing this flow has that QBO/Xero do not is REGION. Clio's four data
regions are separate installations; the consent screen, the token exchange,
and every later API call must all target the same host. The region is chosen
by the firm at connect time and pinned on the Integration row, and it is
carried through the OAuth round trip inside the state token — the callback
arrives on a bare redirect with no session, so state is the only channel.
"""

import logging
import secrets

from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

import requests

from tracker.models import Integration
from tracker.integrations.clio.client import (
    ClioClient,
    ClioError,
    REGION_HOSTS,
    DEFAULT_REGION,
    authorize_url,
    token_url,
)
from tracker.views_integrations import (
    get_user_org,
    error_response,
    get_integration,
    _oauth_success_response,
)

logger = logging.getLogger(__name__)

# Clio scopes are granted at the app-registration level rather than requested
# per-authorization, so no scope parameter is sent here. What the firm grants
# is whatever the registered app declares in the developer portal.


def _fail(reason):
    """Send the popup back to Settings with an error code it can render."""
    return redirect(f"{settings.FRONTEND_URL}/settings?integration_error={reason}")


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clio_connect(request):
    """
    Begin the OAuth handshake. Body: {"region": "us"|"ca"|"eu"|"au"}.

    Returns an auth_url for the frontend to open in a popup, mirroring the
    QBO/Xero connect endpoints.
    """
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization', 404)

    if not (settings.CLIO_CLIENT_ID and settings.CLIO_REDIRECT_URI):
        return error_response(
            'Clio is not configured on this server.', 503, 'not_configured'
        )

    region = (request.data.get('region') or DEFAULT_REGION).lower()
    if region not in REGION_HOSTS:
        return error_response(
            f'Unknown Clio region "{region}". Expected one of: '
            f'{", ".join(sorted(REGION_HOSTS))}.',
            400, 'bad_region',
        )

    # The callback has no session, so the region rides along in the state
    # token. Random half stays unguessable for CSRF purposes.
    state = f'{region}:{secrets.token_urlsafe(32)}'

    Integration.objects.update_or_create(
        organization=org, provider='clio',
        defaults={'oauth_state': state, 'api_region': region},
    )

    return Response({
        'auth_url': authorize_url(
            region, settings.CLIO_CLIENT_ID, settings.CLIO_REDIRECT_URI, state,
        ),
        'region': region,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def clio_callback(request):
    """Exchange the auth code for tokens. Reached by redirect, not by our SPA."""
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')

    if error:
        return _fail(error)
    if not code or not state:
        return _fail('missing_code')

    try:
        integration = Integration.objects.get(oauth_state=state, provider='clio')
    except Integration.DoesNotExist:
        return _fail('invalid_state')

    # Trust the region stored alongside the state, not the state string —
    # the row is ours, the query param is the caller's.
    region = integration.api_region or DEFAULT_REGION

    try:
        resp = requests.post(
            token_url(region),
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': settings.CLIO_REDIRECT_URI,
                'client_id': settings.CLIO_CLIENT_ID,
                'client_secret': settings.CLIO_CLIENT_SECRET,
            },
            timeout=30,
        )
    except requests.RequestException as e:
        logger.error('Clio token exchange failed: %s', e)
        return _fail('token_exchange_failed')

    if resp.status_code != 200:
        logger.error('Clio token exchange %s: %s', resp.status_code, resp.text[:300])
        return _fail('token_exchange_failed')

    tokens = resp.json()
    integration.access_token = tokens['access_token']
    integration.refresh_token = tokens.get('refresh_token', '')
    # Clio access tokens last 30 days; refresh tokens do not expire.
    integration.token_expires_at = timezone.now() + timedelta(
        seconds=int(tokens.get('expires_in', 30 * 24 * 3600))
    )
    integration.oauth_state = ''
    integration.is_connected = True
    integration.last_sync_status = ''
    integration.last_sync_error = ''
    integration.save()

    logger.info('Clio connected for org %s (region %s)',
                integration.organization_id, region)
    return _oauth_success_response('clio')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clio_sync(request):
    """
    Kick off a full contacts/matters/staff sync.

    Queued rather than run inline: a large firm's sync sits behind
    rate-limit pauses for minutes, which no request cycle should hold.
    """
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'clio')
    if err:
        return err

    from tracker.integrations.clio.sync import sync_clio_full

    sync_clio_full.delay(integration.id)
    logger.info('Clio sync queued for org %s by user %s', org.id, request.user.id)

    return Response({
        'queued': True,
        'message': 'Sync started. Matters and clients will appear as they import.',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clio_push_time(request):
    """
    Push captured time to Clio as TimeEntry activities.

    Body: {"start_date": "2026-08-01", "end_date": "2026-08-20",
           "user_ids": [], "dry_run": true}

    `dry_run` defaults to TRUE. This endpoint writes into a firm's billing
    system, so the safe outcome is the one you get by forgetting a parameter.
    The preview and the write are built from the same plan, so what a firm
    confirms is what lands.
    """
    from datetime import datetime as _dt
    from tracker.integrations.clio.push import build_push_plan, execute_push

    org = get_user_org(request.user)
    integration, err = get_integration(org, 'clio')
    if err:
        return err

    start_raw = request.data.get('start_date')
    end_raw = request.data.get('end_date')
    if not start_raw or not end_raw:
        return error_response('start_date and end_date are required')
    try:
        start_date = _dt.strptime(start_raw, '%Y-%m-%d').date()
        end_date = _dt.strptime(end_raw, '%Y-%m-%d').date()
    except ValueError:
        return error_response('Dates must be YYYY-MM-DD')
    if end_date < start_date:
        return error_response('end_date must not precede start_date')

    dry_run = request.data.get('dry_run', True)
    user_ids = request.data.get('user_ids') or None

    try:
        plan = build_push_plan(integration, start_date, end_date, user_ids=user_ids)
    except ClioError as e:
        logger.warning('Clio push planning failed for org %s: %s', org.id, e)
        return error_response(str(e)[:300], 502, 'clio_error')

    if dry_run:
        return Response({'dry_run': True, **plan})

    try:
        result = execute_push(integration, plan)
    except ClioError as e:
        logger.warning('Clio push failed for org %s: %s', org.id, e)
        return error_response(str(e)[:300], 502, 'clio_error')

    return Response({'dry_run': False, 'window': plan['window'], **result})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def clio_status(request):
    """Connection state for the Settings card."""
    org = get_user_org(request.user)
    integration, _ = get_integration(org, 'clio', connected_only=False)
    if not integration:
        return Response({'connected': False})

    return Response({
        'connected': integration.is_connected,
        'region': integration.api_region or None,
        'api_host': REGION_HOSTS.get(integration.api_region or DEFAULT_REGION),
        'last_synced_at': integration.last_synced_at,
        'last_sync_status': integration.last_sync_status or None,
        'last_sync_error': integration.last_sync_error or None,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clio_disconnect(request):
    """
    Drop the grant. Tells Clio to invalidate the token first so we do not
    leave live credentials behind, then clears them locally regardless.
    """
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization', 404)

    try:
        integration = Integration.objects.get(organization=org, provider='clio')
    except Integration.DoesNotExist:
        return Response({'success': True})

    if integration.is_connected and integration.access_token:
        try:
            ClioClient(integration).deauthorize()
        except ClioError as e:
            logger.warning('Clio deauthorize skipped for org %s: %s', org.id, e)

    integration.is_connected = False
    integration.access_token = ''
    integration.refresh_token = ''
    integration.token_expires_at = None
    integration.oauth_state = ''
    integration.save()

    return Response({'success': True})
