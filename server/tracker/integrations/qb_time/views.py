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
    # Started from a connect link (services/connect_link.py) rather than Settings?
    from tracker.services import connect_link
    link = connect_link.link_for_state('qb_time', state)

    def fail(reason):
        if link:
            return redirect(connect_link.return_url('qb_time', False, reason))
        return _fail(reason)

    if error:
        return fail(error)
    if not code or not state:
        return fail('missing_code')
    try:
        integration = Integration.objects.get(oauth_state=state, provider='qb_time')
    except Integration.DoesNotExist:
        return fail('invalid_state')

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
        return fail('token_exchange_failed')
    if resp.status_code != 200:
        logger.error('QB Time token exchange %s: %s', resp.status_code, resp.text[:300])
        return fail('token_exchange_failed')

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

    if link:
        connect_link.finish(link, 'qb_time', integration)
        return redirect(connect_link.return_url('qb_time', True))
    return _oauth_success_response('qb_time')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def qb_time_sync(request):
    """
    Start a sync in the background and answer at once (202).

    It used to run inline so the person who pressed it saw real counts. A firm
    the size of MTC (409 customers, 478 projects, then alias derivation and
    attribution) runs past gunicorn's 30-second worker timeout: the worker was
    killed mid-request and the browser said "Failed to fetch", though the data
    landed. Celery is eager in production, so .delay() would block the same
    way; a thread is what actually returns. The card polls the status until
    last_synced changes. full_sync records success or failure on the row.
    """
    org, denied = _require_admin(request, 'run a QuickBooks Time sync')
    if denied:
        return denied
    integration, err = get_integration(org, 'qb_time')
    if err:
        return err

    from tracker.integrations.qb_time.sync import _sync_unlock, _try_sync_lock
    # The same per-firm lock the scheduled sync takes. Probe it here so a
    # second press gets a clear answer; the thread takes it for real.
    if not _try_sync_lock(integration.id):
        return error_response('A QuickBooks Time sync is already running for this firm. '
                              'Give it a minute, then refresh.', 409, 'sync_running')
    _sync_unlock(integration.id)

    import threading
    threading.Thread(target=_sync_in_background, args=(integration.id,),
                     name=f'qbt-sync-{integration.id}', daemon=True).start()
    return Response({
        'started': True,
        'message': 'QuickBooks Time sync started. A large account takes a minute or two; '
                   'the counts update here when it finishes.',
    }, status=202)


def _sync_in_background(integration_id: int) -> None:
    from django.db import connection
    from tracker.integrations.qb_time.sync import _sync_unlock, _try_sync_lock, full_sync
    try:
        integration = Integration.objects.select_related('organization').get(id=integration_id)
        if not _try_sync_lock(integration_id):
            return          # someone else's sync got there first
        try:
            full_sync(integration)
        finally:
            _sync_unlock(integration_id)
    except Exception:       # full_sync records its own failures; this is the rest
        logger.exception('Background QuickBooks Time sync failed for integration %s', integration_id)
    finally:
        connection.close()  # this thread's own connection


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def qb_time_staff(request):
    """
    GET  — every QuickBooks Time user, whether and to whom they are linked,
           and the firm's TimeTracker people to link them to.
    POST {"external_id": "123", "user_id": 45 | null} — link or unlink one.

    The sync links people by email only. A person whose QuickBooks Time email
    is not their TimeTracker one (Alannah: a personal address in QBT,
    alannah@morethancars.com here) stayed unlinked, and the push skipped her
    time as user_not_mapped with no way to fix it short of a database edit.

    The user list is read live: an unlinked QBT user has no row to store it in
    (ExternalStaffMapping.user is required). A link made here survives later
    syncs, which only ever touch email (or unique full-name) matches.
    """
    from django.contrib.auth import get_user_model
    from tracker.integrations.qb_time.client import QBTimeClient, QBTimeError
    from tracker.models import OrganizationMembership
    from tracker.models_task_type_sets import ExternalStaffMapping

    org, denied = _require_admin(request, 'link QuickBooks Time users')
    if denied:
        return denied
    integration, err = get_integration(org, 'qb_time')
    if err:
        return err

    members = {
        m.user_id: m.user for m in
        OrganizationMembership.objects.filter(organization=org).select_related('user')
    }

    def _person(u):
        return {'id': u.id, 'name': u.get_full_name() or u.username, 'email': u.email or ''}

    if request.method == 'POST':
        external_id = str(request.data.get('external_id') or '').strip()
        user_id = request.data.get('user_id')
        if not external_id:
            return error_response('external_id required', 400, 'bad_request')
        if user_id in (None, '', 0):
            ExternalStaffMapping.objects.filter(integration=integration, external_id=external_id).delete()
            return Response({'ok': True, 'external_id': external_id, 'user': None})
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return error_response('user_id must be a number', 400, 'bad_request')
        if user_id not in members:
            return error_response('That person is not in this firm.', 400, 'not_a_member')
        # One QBT user per person and one person per QBT user: moving a link
        # clears whatever either side was linked to before.
        ExternalStaffMapping.objects.filter(integration=integration, user_id=user_id) \
            .exclude(external_id=external_id).delete()
        mapping, _ = ExternalStaffMapping.objects.update_or_create(
            integration=integration, external_id=external_id,
            defaults={'user_id': user_id, 'external_name': str(request.data.get('external_name') or '')[:255]},
        )
        return Response({'ok': True, 'external_id': external_id, 'user': _person(members[user_id])})

    try:
        qbt_users = list(QBTimeClient(integration).paginated('users', active='both'))
    except QBTimeError as e:
        return error_response(f'Could not read QuickBooks Time users: {e}'[:300], 502, 'qbt_error')

    links = {m.external_id: m.user_id for m in
             ExternalStaffMapping.objects.filter(integration=integration)}
    users = []
    for u in qbt_users:
        ext = str(u.get('id') or '').strip()
        if not ext:
            continue
        linked = links.get(ext)
        users.append({
            'external_id': ext,
            'name': f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip() or ext,
            'email': str(u.get('email') or ''),
            'active': bool(u.get('active', True)),
            'linked_user': _person(members[linked]) if linked in members else None,
        })
    # Unlinked active people first: that is the list someone came here to work.
    users.sort(key=lambda r: (r['linked_user'] is not None, not r['active'], r['name'].lower()))
    return Response({
        'users': users,
        'people': sorted((_person(u) for u in members.values()), key=lambda p: p['name'].lower()),
    })


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
