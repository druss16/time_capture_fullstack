"""
QuickBooks Time OAuth + sync endpoints: connect, callback, sync, disconnect.

Same shape as Clio's (integrations/clio/views.py): one app registration for
every firm, one Integration row per firm, connect/sync/disconnect limited to
owners and admins because the connection is firm-wide, and a first import
queued the moment the grant lands so the card never sits at "0 projects".
"""
import logging
import secrets

import requests
from django.conf import settings
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from tracker.integrations.clio.views import _require_admin
from tracker.integrations.qb_time.client import (
    apply_tokens, authorize_url, grant_url, is_configured,
)
from tracker.models import Integration
from tracker.views_integrations import _oauth_success_response, error_response, get_integration

logger = logging.getLogger(__name__)


def _fail(reason):
    return redirect(f"{settings.FRONTEND_URL}/settings?tab=integrations&integration_error={reason}")


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def qb_time_connect(request):
    org, denied = _require_admin(request, 'connect QuickBooks Time')
    if denied:
        return denied
    if not is_configured():
        return error_response('QuickBooks Time is not configured on this server.', 503, 'not_configured')

    state = secrets.token_urlsafe(32)
    Integration.objects.update_or_create(
        organization=org, provider='qb_time', defaults={'oauth_state': state},
    )
    return Response({'auth_url': authorize_url(
        settings.QBTIME_CLIENT_ID, settings.QBTIME_REDIRECT_URI, state)})


@api_view(['GET'])
@permission_classes([AllowAny])
def qb_time_callback(request):
    """Exchange the code for tokens. Reached by redirect, with no session."""
    code, state, error = request.GET.get('code'), request.GET.get('state'), request.GET.get('error')
    if error:
        return _fail(error)
    if not code or not state:
        return _fail('missing_code')
    try:
        integration = Integration.objects.get(oauth_state=state, provider='qb_time')
    except Integration.DoesNotExist:
        return _fail('invalid_state')

    try:
        resp = requests.post(grant_url(), data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': settings.QBTIME_REDIRECT_URI,
            'client_id': settings.QBTIME_CLIENT_ID,
            'client_secret': settings.QBTIME_CLIENT_SECRET,
        }, timeout=30)
    except requests.RequestException as e:
        logger.error('QB Time token exchange failed: %s', e)
        return _fail('token_exchange_failed')
    if resp.status_code != 200:
        logger.error('QB Time token exchange %s: %s', resp.status_code, resp.text[:300])
        return _fail('token_exchange_failed')

    tokens = resp.json()
    apply_tokens(integration, tokens)
    # The QuickBooks Time company this grant belongs to — the card's identity.
    integration.realm_id = str(tokens.get('company_id') or '')[:100]
    integration.oauth_state = ''
    integration.is_connected = True
    integration.last_sync_status = 'pending'
    integration.last_sync_error = ''
    integration.save()

    try:
        from tracker.integrations.qb_time.sync import sync_qb_time_full
        sync_qb_time_full.delay(integration.id)
    except Exception as e:
        integration.last_sync_status = 'failed'
        integration.last_sync_error = (
            f'Could not start the first import ({type(e).__name__}). Press Sync to run it now.')[:500]
        integration.save(update_fields=['last_sync_status', 'last_sync_error', 'updated_at'])

    return _oauth_success_response('qb_time')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def qb_time_sync(request):
    """Run the sync inline so the person who pressed it sees real counts."""
    org, denied = _require_admin(request, 'run a QuickBooks Time sync')
    if denied:
        return denied
    integration, err = get_integration(org, 'qb_time')
    if err:
        return err

    from tracker.integrations.qb_time.sync import full_sync
    stats = full_sync(integration)
    if stats.get('errors'):
        return error_response(f"Sync failed: {stats['errors'][0]}"[:300], 502, 'sync_failed')

    c, p, e = stats['clients'], stats['projects'], stats['estimates']
    message = (f"Synced {p['fetched']} projects across "
               f"{c['created'] + c['matched']} clients ({c['created']} new).")
    if e['available']:
        message += f" {e['projects_with_estimate']} have an hours estimate."
    else:
        message += ' No project estimates on this QuickBooks Time account.'
    return Response({'synced': True, 'message': message, 'stats': stats})


# A month of one firm's time is a few hundred rows — a handful of batched
# writes. Wider than that is a backfill and should be asked for on purpose.
MAX_PUSH_DAYS = 31


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def qb_time_push(request):
    """
    Send confirmed time to QuickBooks Time as timesheets.

    Body: {start_date, end_date (YYYY-MM-DD), user_ids?: [int], dry_run?: bool}

    dry_run returns the plan and writes nothing. A real run re-plans from what
    QuickBooks Time holds right now rather than trusting the preview, so a
    timesheet someone entered in between is netted, not duplicated.
    Inline rather than queued: batched, a month is a few requests.
    """
    from datetime import datetime

    from tracker.integrations.qb_time.client import QBTimeAuthError, QBTimeError
    from tracker.integrations.qb_time.push import build_push_plan, execute_push, push_lock

    org, denied = _require_admin(request, 'send time to QuickBooks Time')
    if denied:
        return denied
    integration, err = get_integration(org, 'qb_time')
    if err:
        return err

    try:
        start = datetime.strptime(str(request.data.get('start_date') or ''), '%Y-%m-%d').date()
        end = datetime.strptime(str(request.data.get('end_date') or ''), '%Y-%m-%d').date()
    except ValueError:
        return error_response('start_date and end_date are required as YYYY-MM-DD.')
    if end < start:
        return error_response('end_date is before start_date.')
    if (end - start).days + 1 > MAX_PUSH_DAYS:
        return error_response(f'Send at most {MAX_PUSH_DAYS} days at a time.')

    user_ids = request.data.get('user_ids') or None
    if user_ids is not None and not (
            isinstance(user_ids, list) and all(isinstance(u, int) for u in user_ids)):
        return error_response('user_ids must be a list of user ids.')
    dry_run = bool(request.data.get('dry_run', False))

    try:
        if dry_run:
            plan = build_push_plan(integration, start, end, user_ids=user_ids)
            return Response({'dry_run': True, **plan})
        # Plan and write under the firm's push lock, so an approval sending the
        # same week at this moment cannot also write the hours.
        with push_lock(integration):
            plan = build_push_plan(integration, start, end, user_ids=user_ids)
            result = execute_push(integration, plan)
    except QBTimeAuthError as e:
        return error_response(f'{e}', 401, 'reconnect_required')
    except QBTimeError as e:
        logger.warning('QB Time push failed for org %s: %s', org.id, e)
        return error_response(f'QuickBooks Time push failed: {e}'[:300], 502, 'push_failed')

    return Response({'dry_run': False, 'window': plan['window'], **result})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def qb_time_push_trigger(request):
    """Choose whether approved timesheets go to QuickBooks Time on their own.

    Body: {push_trigger: 'approve' | 'off'}. Off by default — see QbtPushSettings
    for why connecting QuickBooks Time must not start writing timesheets.
    """
    from tracker.models_task_type_sets import QbtPushSettings

    org, denied = _require_admin(request, 'change when time is sent to QuickBooks Time')
    if denied:
        return denied
    integration, err = get_integration(org, 'qb_time')
    if err:
        return err

    value = (request.data.get('push_trigger') or '').strip()
    valid = [v for v, _ in QbtPushSettings.TRIGGER_CHOICES]
    if value not in valid:
        return error_response(f'push_trigger must be one of {valid}', 400)

    QbtPushSettings.objects.update_or_create(integration=integration, defaults={'push_trigger': value})
    logger.info('Org %s set QB Time push_trigger=%s by %s', org.id, value, request.user)
    return Response({'push_trigger': value})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def qb_time_disconnect(request):
    """Drop the grant locally. Synced clients and projects stay."""
    org, denied = _require_admin(request, 'disconnect QuickBooks Time')
    if denied:
        return denied
    integration = Integration.objects.filter(organization=org, provider='qb_time').first()
    if integration:
        integration.is_connected = False
        integration.access_token = ''
        integration.refresh_token = ''
        integration.token_expires_at = None
        integration.oauth_state = ''
        integration.save()
    return Response({'success': True})
