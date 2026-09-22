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
from django.db import models
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

import requests

from tracker.models import ClioWebhook, Integration, Organization, OrganizationMembership
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

    _start_first_sync(integration)

    return _oauth_success_response('clio')


def _start_first_sync(integration):
    """
    Import the firm's clients and matters the moment they connect.

    Before this, connecting Clio produced a card that said "Connected" and
    "0 clients" until someone happened to find the Sync button. That reads as
    a broken integration, and it is the first thing a firm sees.

    Queued, not inline: this runs inside an OAuth redirect the browser is
    waiting on, and a large firm's sync can sit behind rate-limit pauses for
    minutes. But queuing is exactly what hid earlier failures — a dropped
    task was indistinguishable from a sync that never ran. So the status is
    written to 'pending' FIRST, which means the card can distinguish three
    states it previously could not: never connected, importing now, and
    imported. If the worker never picks it up, 'pending' is what stays on
    screen, and the hourly sweep repairs it within the hour.
    """
    integration.last_sync_status = 'pending'
    integration.last_sync_error = ''
    integration.save(update_fields=[
        'last_sync_status', 'last_sync_error', 'updated_at',
    ])

    try:
        from tracker.integrations.clio.sync import sync_clio_full
        sync_clio_full.delay(integration.id)
    except Exception as e:
        # The broker is unreachable. Say so on the card rather than leaving a
        # 'pending' that will never resolve without explanation.
        logger.warning('Clio first-sync enqueue failed for org %s: %s',
                       integration.organization_id, e)
        integration.last_sync_status = 'failed'
        integration.last_sync_error = (
            f'Could not start the first import ({type(e).__name__}). '
            f'Press Sync to run it now.'
        )[:500]
        integration.save(update_fields=[
            'last_sync_status', 'last_sync_error', 'updated_at',
        ])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clio_sync(request):
    """
    Run a full contacts/matters/staff sync and return what it did.

    Deliberately INLINE, not queued. Someone pressing Sync is watching, and a
    queued task can only ever answer "started" — which is indistinguishable
    from "silently dropped" when the worker is misconfigured or running older
    code. Both happened during rollout, and the button reported success each
    time while importing nothing.

    Running it here means the response carries real counts, and any failure is
    raised to the person who asked for it instead of a worker log they will
    never read. A typical firm's sync is three paginated scans and takes
    seconds; `sync_clio_full` remains for the scheduled sweep, where nobody is
    waiting on the answer.
    """
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'clio')
    if err:
        return err

    from tracker.integrations.clio.sync import full_sync

    stats = full_sync(integration)

    if stats.get('errors'):
        logger.warning('Clio sync failed for org %s: %s', org.id, stats['errors'])
        return error_response(
            f"Sync failed: {stats['errors'][0]}"[:300], 502, 'sync_failed',
        )

    contacts = stats.get('contacts', {})
    matters = stats.get('matters', {})
    staff = stats.get('staff', {})
    logger.info('Clio sync complete for org %s by user %s: %s', org.id, request.user.id, stats)

    # Attribution is best-effort so it cannot fail a sync that worked — but
    # "cannot fail the sync" became "fails invisibly forever": a pooler
    # incompatibility broke every run and the only trace was a log line. If it
    # errored, say so here, where the person who pressed Sync will see it.
    attribution = stats.get('attribution') or {}
    message = (
        f"Synced {contacts.get('fetched', 0)} clients and "
        f"{matters.get('fetched', 0)} matters. "
        f"{staff.get('matched', 0)} team member(s) matched."
    )
    if attribution.get('error'):
        message += ' Matter attribution failed — see integration status.'
    elif attribution:
        attributed = sum(
            v for k, v in attribution.items()
            if k.startswith('by_') and isinstance(v, int)
        )
        if attributed:
            message += f' {attributed} activit(ies) matched to a matter.'

    return Response({'synced': True, 'message': message, 'stats': stats})


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


@csrf_exempt
def clio_webhook(request, url_token):
    """
    Inbound Clio callback. Unauthenticated by necessity — Clio calls this.

    ORDER IS THE SECURITY PROPERTY HERE. Routing by `url_token` only selects
    which secret to check against; it proves nothing on its own, because a
    token in a URL is a token an attacker could have captured from a log or a
    proxy. Nothing is written until the HMAC over the RAW body verifies.

    Always answers fast. Clio retries on non-2xx, and a slow handler turns a
    burst of matter updates into a pile of duplicate deliveries.
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    hook = (
        ClioWebhook.objects
        .select_related('integration', 'integration__organization')
        .filter(url_token=url_token)
        .first()
    )
    if hook is None:
        # Deliberately 404 rather than 401: an unknown token should look like
        # an unknown URL, not like a wrong password on a known one.
        logger.warning('Clio webhook: unknown url_token')
        return HttpResponse(status=404)

    from tracker.integrations.clio import webhooks as clio_hooks

    # ── Handshake ───────────────────────────────────────────────────────
    # Clio POSTs a fresh secret in X-Hook-Secret right after creation and on
    # any URL change. Echoing it back is what flips the subscription from
    # `pending` to live. Skipping this is THE reason Clio webhooks silently
    # deliver nothing, so it is handled before anything else — the handshake
    # request has no signature to verify and no body worth reading.
    handshake_secret = request.headers.get('X-Hook-Secret')
    if handshake_secret:
        # Stored ALONGSIDE the secret we supplied at creation, not over it.
        # Clio's docs describe both mechanisms without saying which one signs
        # the callbacks, so we keep both and verify against either — see
        # ClioWebhook. Discarding ours here on a guess would make every later
        # delivery fail its signature check, and a failing signature is
        # indistinguishable from an attack in the logs.
        hook.handshake_secret = handshake_secret
        hook.status = 'active'
        hook.last_error = ''
        hook.save(update_fields=[
            'handshake_secret', 'status', 'last_error', 'updated_at',
        ])
        logger.info('Clio webhook handshake completed: org %s, model %s',
                    hook.integration.organization_id, hook.model)
        response = HttpResponse(status=200)
        response['X-Hook-Secret'] = handshake_secret
        return response

    # ── Signature ───────────────────────────────────────────────────────
    signature = request.headers.get('X-Hook-Signature', '')
    if not clio_hooks.verify_signature(hook, request.body, signature):
        # RECORD IT. A rejected callback and a callback that never arrived are
        # both "events_received == 0" with an empty last_error — identical from
        # the outside, opposite in cause. One means Clio is not sending; the
        # other means Clio IS sending and we are refusing, which is the far
        # more urgent problem because it looks like silence.
        #
        # This is deliberately not an error the caller can probe with: the
        # response stays a bare 401 either way, so a forged request learns
        # nothing from the fact that we wrote a log row.
        logger.warning('Clio webhook: bad signature for org %s (%s)',
                       hook.integration.organization_id, hook.model)
        ClioWebhook.objects.filter(pk=hook.pk).update(
            last_error=(
                'A callback arrived but its signature did not match either '
                'stored secret, so it was rejected. Clio IS sending events; '
                'we cannot verify them. Reconnecting Clio re-creates the '
                'subscription with a fresh secret.'
            ),
            rejected_count=models.F('rejected_count') + 1,
            last_rejected_at=timezone.now(),
        )
        return HttpResponse(status=401)

    # ── Apply ───────────────────────────────────────────────────────────
    try:
        result = clio_hooks.handle_event(hook, request.body)
    except Exception as e:
        # 500 so Clio retries — this is our fault, not a bad payload.
        logger.exception('Clio webhook handling failed for org %s (%s)',
                         hook.integration.organization_id, hook.model)
        ClioWebhook.objects.filter(pk=hook.pk).update(
            last_error=f'{type(e).__name__}: {e}'[:500],
        )
        return HttpResponse(status=500)

    ClioWebhook.objects.filter(pk=hook.pk).update(
        last_event_at=timezone.now(),
        events_received=models.F('events_received') + 1,
        status='active',
        last_error='' if result.get('ok') else str(result.get('reason', ''))[:500],
    )

    # 200 even on a payload we chose not to act on. Retrying a matter we
    # skipped for a missing client would just fail identically five more
    # times; the hourly sweep is what resolves that case.
    logger.info('Clio webhook %s/%s → %s', hook.model,
                hook.integration.organization_id, result)
    return HttpResponse(status=200)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def clio_status(request):
    """Connection state for the Settings card."""
    org = get_user_org(request.user)
    integration, _ = get_integration(org, 'clio', connected_only=False)
    if not integration:
        return Response({'connected': False})

    # Live-sync health, collapsed to one word the card can render. A firm
    # does not care which of two subscriptions lapsed; they care whether new
    # clients are arriving on their own. 'off' is an honest answer — it means
    # the hourly sweep is doing the work, which is a slower but working state,
    # not an error.
    from tracker.integrations.clio.webhooks import live_sync_error, live_sync_state
    live_sync, live_sync_detail = live_sync_state(integration)

    return Response({
        'connected': integration.is_connected,
        'region': integration.api_region or None,
        'api_host': REGION_HOSTS.get(integration.api_region or DEFAULT_REGION),
        'last_synced_at': integration.last_synced_at,
        'last_sync_status': integration.last_sync_status or None,
        'last_sync_error': integration.last_sync_error or None,
        'live_sync': live_sync,
        'live_sync_error': live_sync_error(integration) or None,
        'live_sync_detail': live_sync_detail,
        'push_trigger': org.clio_push_trigger,
        'push_trigger_choices': [
            {'value': v, 'label': label}
            for v, label in Organization.CLIO_PUSH_TRIGGER_CHOICES
        ],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clio_push_trigger(request):
    """Choose when captured time is written to Clio.

    A firm's own policy, not something inferable from its org chart: an org can
    have several owners who simply never review each other, in which case
    waiting for an approval that no one will give strands the time forever.
    Whether anyone reviews is a decision only the firm can state.
    """
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization', 404)

    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return error_response('Only an owner or admin can change this', 403)

    value = (request.data.get('push_trigger') or '').strip()
    valid = [v for v, _ in Organization.CLIO_PUSH_TRIGGER_CHOICES]
    if value not in valid:
        return error_response(f'push_trigger must be one of {valid}', 400)

    org.clio_push_trigger = value
    org.save(update_fields=['clio_push_trigger'])
    logger.info('Org %s set clio_push_trigger=%s by %s', org.id, value, request.user)
    return Response({'push_trigger': org.clio_push_trigger})


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

    # Tear down subscriptions BEFORE dropping the token — deleting them at
    # Clio needs the very credential the next lines destroy. Left behind, they
    # would keep firing at a URL whose secret no longer exists, and every one
    # of those deliveries would be a 401 in our logs until they expired.
    try:
        from tracker.integrations.clio.webhooks import deregister_webhooks
        removed = deregister_webhooks(integration)
        if removed:
            logger.info('Clio: removed %s webhook(s) for org %s', removed, org.id)
    except Exception as e:
        logger.warning('Clio webhook teardown failed for org %s: %s', org.id, e)

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
