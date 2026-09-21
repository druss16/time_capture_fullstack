"""
Clio webhook subscriptions: register, verify, handle, renew, deregister.

WHAT THIS BUYS
--------------
Seconds instead of an hour. A firm opens a new client in Clio and it is
matchable here before the intake form is closed — which matters because the
work on a brand-new client starts immediately, and time captured against a
client we do not know yet lands in the "no client" pile a human has to sort.

WHAT IT DOES NOT BUY
--------------------
Reliability. Clio webhooks are AT-LEAST-ONCE (the same event can arrive
twice) and they EXPIRE — 3 days by default, 31 days at the absolute maximum,
with no warning and no retry when they lapse. Clio does not track whether
you are listening; deliveries simply stop.

So webhooks here are strictly an accelerator layered on top of the hourly
sweep, never a replacement for it. Every path below is written to be safely
re-runnable and to degrade into "the sweep will get it" rather than into a
gap. If every webhook in the system died tonight, the worst outcome is that
we are back to an hour of latency.

THE SECURITY MODEL
------------------
A callback arrives unauthenticated at a public URL. Two independent things
have to hold before we write anything:

  1. ROUTING — the URL carries a random per-subscription token telling us
     which firm the callback claims to be for. This is a hint, not proof.
  2. AUTHORIZATION — X-Hook-Signature is a lowercase-hex HMAC-SHA256 of the
     RAW request body keyed with the secret we generated for that exact
     subscription. Verified in constant time, over the raw bytes, before the
     JSON is parsed.

Per-subscription secrets are the point of (2): one server-wide secret would
mean any firm that could read it could forge callbacks for every other firm.

THE HANDSHAKE
-------------
Immediately after a subscription is created (and whenever its URL changes)
Clio POSTs with an X-Hook-Secret header and no meaningful body. Echoing that
header back with a 200 is what activates the subscription. Get this wrong
and the subscription sits in `pending` forever, delivering nothing — which
is the single most common reason Clio webhooks appear not to work at all.
"""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from tracker.integrations.clio.client import ClioClient, ClioError
from tracker.models import ClioWebhook, Integration

logger = logging.getLogger(__name__)

# Which Clio models we subscribe to, and the fields each callback should
# carry. These MUST match the field lists the sync uses, because the payload
# is fed straight into the same upsert — a shorter list here would write a
# half-populated record over a complete one.
from tracker.integrations.clio.sync import CONTACT_FIELDS, MATTER_FIELDS

WATCHED_MODELS = {
    'contact': CONTACT_FIELDS,
    'matter': MATTER_FIELDS,
}

# Clio's ceiling is 31 days. Ask for 30 and renew at 7 days remaining, so a
# renewal has three weeks of retries to succeed in before anything lapses.
SUBSCRIPTION_DAYS = 30
RENEW_WHEN_REMAINING = timedelta(days=7)


# ============================================================================
# Callback URL
# ============================================================================

def webhook_base_url() -> str:
    """
    Public HTTPS origin Clio should call back on.

    Derived from CLIO_REDIRECT_URI by default rather than asking for another
    environment variable: the redirect URI is ALREADY a public HTTPS URL
    pointing at this API, and it is already required for OAuth to work. One
    fewer setting to get wrong in an environment that is hard to test.
    """
    override = getattr(settings, 'CLIO_WEBHOOK_BASE_URL', '')
    if override:
        return override.rstrip('/')

    redirect_uri = getattr(settings, 'CLIO_REDIRECT_URI', '')
    if not redirect_uri:
        return ''
    parts = urlsplit(redirect_uri)
    if not parts.scheme or not parts.netloc:
        return ''
    return urlunsplit((parts.scheme, parts.netloc, '', '', ''))


def callback_url(hook: ClioWebhook) -> str:
    """
    The absolute URL Clio will POST to for this subscription.

    The path comes from reverse() rather than a literal, because this string
    is sent to Clio ONCE at creation and then lives on their side for a month.
    A literal that drifted from urls.py would not fail at deploy — it would
    fail as a stream of 404s from Clio that nothing here is watching for.
    """
    base = webhook_base_url()
    if not base:
        return ''
    from django.urls import reverse
    path = reverse('clio-webhook', kwargs={'url_token': hook.url_token})
    return f'{base}{path}'


# ============================================================================
# Registration
# ============================================================================

def register_webhooks(integration: Integration) -> dict:
    """
    Ensure this firm has a live subscription for every watched model.

    Idempotent and best-effort by design. It is called on connect and on every
    renewal pass, and it must never be the reason a sync or an OAuth callback
    fails — the sweep already covers everything this accelerates.
    """
    stats = {'created': 0, 'renewed': 0, 'skipped': 0, 'errors': []}

    base = webhook_base_url()
    if not base:
        stats['errors'].append('no_public_url')
        logger.warning(
            'Clio webhooks skipped for org %s: neither CLIO_WEBHOOK_BASE_URL '
            'nor a usable CLIO_REDIRECT_URI is set.', integration.organization_id,
        )
        return stats

    if not base.startswith('https://'):
        # Clio refuses plaintext callbacks. Say so here rather than letting it
        # come back as an opaque 422 from the API.
        stats['errors'].append('insecure_url')
        logger.warning('Clio webhooks skipped for org %s: callback base %r is not HTTPS.',
                       integration.organization_id, base)
        return stats

    try:
        api = ClioClient(integration)
    except ClioError as e:
        stats['errors'].append(str(e)[:200])
        return stats

    for model in WATCHED_MODELS:
        try:
            outcome = _ensure_subscription(api, integration, model)
            if outcome in stats:
                stats[outcome] += 1
        except Exception as e:
            stats['errors'].append(f'{model}: {str(e)[:150]}')
            logger.warning('Clio webhook registration failed (%s, org %s): %s',
                           model, integration.organization_id, e, exc_info=True)

    return stats


def _ensure_subscription(api: ClioClient, integration: Integration, model: str) -> str:
    """Create or renew one subscription. Returns 'created'|'renewed'|'skipped'."""
    hook, _ = ClioWebhook.objects.get_or_create(
        integration=integration, model=model,
        defaults={'url_token': secrets.token_urlsafe(32)},
    )

    healthy = (
        hook.external_id
        and hook.status == 'active'
        and hook.expires_at
        and hook.expires_at - RENEW_WHEN_REMAINING > timezone.now()
    )
    if healthy:
        return 'skipped'

    if hook.external_id and hook.status in ('active', 'pending'):
        # Still registered with Clio — extend it rather than piling up a
        # second subscription delivering duplicate events to the same URL.
        try:
            return _renew_subscription(api, hook)
        except ClioError as e:
            logger.info('Clio webhook %s renew failed (%s), re-creating: %s',
                        hook.external_id, model, e)
            # Fall through and create fresh. The old one expires on its own.

    expires_at = timezone.now() + timedelta(days=SUBSCRIPTION_DAYS)
    # A fresh secret on every (re)creation. If an old secret ever leaked, it
    # stops being useful the moment the subscription is rebuilt.
    shared_secret = secrets.token_urlsafe(48)
    hook.shared_secret = shared_secret
    hook.save(update_fields=['shared_secret', 'updated_at'])

    payload = {
        'url': callback_url(hook),
        'model': model,
        'events': ['created', 'updated'],
        'fields': WATCHED_MODELS[model],
        'shared_secret': shared_secret,
        'expires_at': expires_at.isoformat(),
    }
    response = api.post('/webhooks', payload, fields='id,status,expires_at')
    data = response.get('data') or {}

    hook.external_id = str(data.get('id') or '')
    # Clio reports 'pending' until the handshake completes. We do not fake
    # 'active' here — the callback handler flips it when the echo succeeds,
    # so the status in our table means "we have actually heard from Clio".
    #
    # But re-read it first. Clio fires the handshake the INSTANT the create
    # returns, and it routinely lands before this function gets to save.
    # Writing 'pending' unconditionally would un-record a handshake that had
    # already completed, leaving the card reporting a live subscription as
    # pending indefinitely.
    already_active = ClioWebhook.objects.filter(
        pk=hook.pk, status='active',
    ).exists()
    hook.status = 'active' if already_active else 'pending'
    hook.expires_at = expires_at
    hook.last_error = ''
    hook.save(update_fields=[
        'external_id', 'status', 'expires_at', 'last_error', 'updated_at',
    ])

    logger.info('Clio webhook created: org %s, model %s, id %s',
                integration.organization_id, model, hook.external_id)
    return 'created'


def _renew_subscription(api: ClioClient, hook: ClioWebhook) -> str:
    """Push `expires_at` out. Keeps the same id, URL, and secret."""
    expires_at = timezone.now() + timedelta(days=SUBSCRIPTION_DAYS)
    api.patch(
        f'/webhooks/{hook.external_id}',
        {'expires_at': expires_at.isoformat()},
        fields='id,expires_at',
    )
    hook.expires_at = expires_at
    hook.last_error = ''
    hook.save(update_fields=['expires_at', 'last_error', 'updated_at'])
    logger.info('Clio webhook %s renewed until %s', hook.external_id, expires_at)
    return 'renewed'


def deregister_webhooks(integration: Integration) -> int:
    """
    Delete this firm's subscriptions at Clio, then locally.

    Called on disconnect. Best-effort against Clio — a firm that revoked our
    grant makes the DELETE impossible, and leaving a dead subscription
    pointing at a URL that now rejects it is harmless. The local rows go
    either way, so reconnecting builds fresh ones with fresh secrets.
    """
    hooks = list(ClioWebhook.objects.filter(integration=integration))
    if not hooks:
        return 0

    try:
        api = ClioClient(integration)
    except ClioError:
        api = None

    for hook in hooks:
        if api and hook.external_id:
            try:
                api.delete(f'/webhooks/{hook.external_id}')
            except Exception as e:
                logger.info('Clio webhook %s delete skipped: %s', hook.external_id, e)

    count = len(hooks)
    ClioWebhook.objects.filter(integration=integration).delete()
    return count


# ============================================================================
# Inbound callback
# ============================================================================

def verify_signature(hook: ClioWebhook, raw_body: bytes, signature: str) -> bool:
    """
    Constant-time check of X-Hook-Signature against the raw request body.

    Raw bytes, before any parsing: re-serializing the JSON would change key
    order and whitespace and the HMAC would never match. Clio sends lowercase
    hex, but both sides are normalized so a casing change upstream does not
    silently reject every callback.

    Accepts a match against EITHER stored secret — the one we supplied at
    creation or the one Clio handed us in the handshake. See ClioWebhook for
    why both exist. Every candidate is compared in constant time and the
    result is OR-ed at the end rather than returning early, so this does not
    leak which secret matched through timing.
    """
    if not signature:
        return False

    candidates = [sk for sk in (hook.shared_secret, hook.handshake_secret) if sk]
    if not candidates:
        return False

    provided = signature.strip().lower()
    matched = False
    for secret in candidates:
        expected = hmac.new(
            secret.encode('utf-8'), raw_body, hashlib.sha256,
        ).hexdigest()
        matched |= hmac.compare_digest(expected.lower(), provided)
    return matched


def handle_event(hook: ClioWebhook, raw_body: bytes) -> dict:
    """
    Apply one verified callback. Returns a small result dict for the response.

    Assumes the signature has ALREADY been checked — this function trusts its
    input, which is exactly why the caller must not reorder those two steps.

    Every branch here is safe to run twice. Clio delivers at-least-once, so
    duplicate events are normal traffic, not an error: the upserts are keyed
    on (integration, external_id) and a repeat is an idempotent no-op rather
    than a second client.
    """
    try:
        body = json.loads(raw_body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        return {'ok': False, 'reason': f'bad_json: {e}'}

    integration = hook.integration
    data = body.get('data') or {}
    event = str(body.get('event') or body.get('type') or '').lower()

    external_id = str(data.get('id') or '')
    if not external_id:
        return {'ok': False, 'reason': 'no_record_id'}

    # Deletions are recorded, never acted on. Deactivating a client because
    # Clio deleted a contact would strand every block already booked to it,
    # and Clio deletions are frequently corrections made seconds later. The
    # sweep's last_seen_in_source is the honest signal for "gone", and a
    # human decides what that means.
    if event.endswith('deleted'):
        logger.info('Clio %s %s deleted upstream (org %s) — recorded, no local change',
                    hook.model, external_id, integration.organization_id)
        return {'ok': True, 'action': 'noted_delete'}

    from tracker.integrations.clio.sync import (
        MatterCache, resolve_matter_client, upsert_contact, upsert_matter,
    )

    if hook.model == 'contact':
        client, outcome = upsert_contact(integration, data)
        if client is None:
            return {'ok': True, 'action': 'skipped'}
        _derive_aliases(integration, outcome)
        return {'ok': True, 'action': outcome, 'client_id': client.id}

    if hook.model == 'matter':
        # An api handle is passed here — unlike the batch path — because a new
        # matter's client may be a contact whose own callback has not arrived
        # yet. See resolve_matter_client.
        try:
            api = ClioClient(integration)
        except ClioError:
            api = None
        cache = MatterCache(integration)
        client, _clio_client_id = resolve_matter_client(
            integration, data, cache, api=api,
        )
        if client is None:
            return {'ok': True, 'action': 'skipped_no_client'}
        project, outcome = upsert_matter(integration, data, client, cache=cache)
        if project is None:
            return {'ok': True, 'action': 'skipped'}
        return {'ok': True, 'action': outcome, 'project_id': project.id}

    return {'ok': False, 'reason': f'unhandled_model: {hook.model}'}


def _derive_aliases(integration: Integration, outcome: str):
    """
    Give a newly-created client its aliases immediately.

    Without this a webhook-created client is invisible to file and window
    matching until the nightly alias sweep — which would hand back most of
    the latency the webhook just saved.
    """
    if outcome != 'created':
        return
    try:
        from tracker.views_integrations import run_post_import_alias_derivation
        run_post_import_alias_derivation(integration.organization)
    except Exception as e:
        logger.warning('Clio webhook alias derivation failed: %s', e, exc_info=True)


# ============================================================================
# Renewal
# ============================================================================

@shared_task(name='tracker.renew_clio_webhooks')
def renew_clio_webhooks() -> dict:
    """
    Nightly: extend every subscription nearing expiry, register missing ones.

    Runs for every connected firm, not just those with rows, so a firm that
    connected before webhooks existed — or whose registration failed at
    connect time because the worker was down — picks one up on its own.
    """
    stats = {'orgs': 0, 'created': 0, 'renewed': 0, 'skipped': 0, 'failed': 0}

    integrations = Integration.objects.filter(
        provider='clio', is_connected=True,
    ).select_related('organization')

    for integration in integrations:
        stats['orgs'] += 1
        result = register_webhooks(integration)
        stats['created'] += result['created']
        stats['renewed'] += result['renewed']
        stats['skipped'] += result['skipped']
        if result['errors']:
            stats['failed'] += 1
            ClioWebhook.objects.filter(integration=integration).update(
                last_error='; '.join(result['errors'])[:500],
            )

    # Anything past its expiry is dead at Clio whether or not we noticed.
    # Marking it here is what makes the Settings card able to say so.
    expired = ClioWebhook.objects.filter(
        expires_at__lt=timezone.now(),
    ).exclude(status='expired').update(status='expired')
    stats['expired'] = expired

    logger.info('Clio webhook renewal: %s', stats)
    return stats
