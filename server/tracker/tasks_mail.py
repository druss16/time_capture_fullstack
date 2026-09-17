"""
Mail sync Celery tasks.

Architecture (mirrors tasks_calendar.py):
  - sync_all_mail: master, runs every 5 min, dispatches per-user subtasks
                   with hashed staggered offsets to spread load
  - sync_user_mail: per-user, fetches via /messages/delta, writes MailSignal
  - prune_mail_signals: nightly cleanup, drops rows older than retention window

Privacy:
  - NEVER stores message body (Mail.ReadBasic scope blocks it at API level)
  - NEVER stores email addresses (only domain extracted)
  - subject_extract only populated when client extraction confidence >= 0.85
  - Internal email (sender + recipient both in org's own domain) is dropped
    at sync time, never reaches MailSignal.
"""
import hashlib
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.db.models import Q

from tracker.models import (
    UserIntegration,
    MailSignal,
    Organization,
    Client,
    OrgCalendarRule,
)
from tracker.integrations import msgraph

logger = logging.getLogger(__name__)


MAX_FAILURE_COUNT = 5
PUBLIC_EMAIL_DOMAINS = {
    'outlook.com', 'gmail.com', 'hotmail.com', 'yahoo.com',
    'icloud.com', 'live.com', 'aol.com', 'me.com', 'msn.com',
}


# ─── Master dispatch ──────────────────────────────────────────────────────────

@shared_task(name='tracker.sync_all_mail')
def sync_all_mail():
    """
    Master task: dispatches per-user mail sync subtasks.
    Scheduled by Celery beat every 5 min.

    Stagger strategy: hash(user_id) % 300 → integer 0-299 used as countdown
    (seconds) before the per-user subtask actually runs. Spreads 200 users
    evenly across the 5-min window so we don't hammer Graph in a single
    burst at minute-zero.
    """
    eligible = UserIntegration.objects.filter(
        provider='microsoft_mail',
        is_connected=True,
        sync_failure_count__lt=MAX_FAILURE_COUNT,
    ).select_related('org').filter(
        # Respect per-org disable flag
        Q(org__disable_mail_integration=False) | Q(org__disable_mail_integration__isnull=True),
    )

    dispatched = 0
    for integration in eligible.iterator():
        offset = _stagger_offset(integration.user_id)
        sync_user_mail.apply_async(args=[integration.id], countdown=offset)
        dispatched += 1

    logger.info(f"[MAIL-SYNC] Dispatched {dispatched} mail sync subtasks (staggered)")
    return {'dispatched': dispatched}


def _stagger_offset(user_id: int, window_seconds: int = 300) -> int:
    """
    Deterministic offset 0..(window_seconds-1) based on user_id.
    Same user always lands in the same slot within the window — so a
    given mailbox gets polled at consistent intervals, not jittered.
    """
    digest = hashlib.md5(str(user_id).encode()).digest()
    return int.from_bytes(digest[:4], 'big') % window_seconds


# ─── Per-user sync ────────────────────────────────────────────────────────────

@shared_task(
    name='tracker.sync_user_mail',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def sync_user_mail(self, integration_id):
    """
    Sync mail for one user. Uses delta queries — first run grabs last 30 days,
    subsequent runs fetch only changed messages.

    Idempotent: MailSignal has unique_together on (user, provider, external_id)
    so re-syncing the same message is a no-op (update_or_create).
    """
    try:
        integration = UserIntegration.objects.select_related('user', 'org').get(
            id=integration_id,
            provider='microsoft_mail',
            is_connected=True,
        )
    except UserIntegration.DoesNotExist:
        logger.warning(f"[MAIL-SYNC] Integration {integration_id} not found or inactive")
        return {'status': 'skipped', 'reason': 'not_found'}

    if integration.sync_failure_count >= MAX_FAILURE_COUNT:
        logger.warning(f"[MAIL-SYNC] Skipping {integration.user.username} — too many failures")
        return {'status': 'skipped', 'reason': 'too_many_failures'}

    org = integration.org
    user = integration.user

    # Honor per-org kill switch
    if getattr(org, 'disable_mail_integration', False):
        logger.info(f"[MAIL-SYNC] Skipping {user.username} — org disable flag set")
        return {'status': 'skipped', 'reason': 'org_disabled'}

    # Pre-load org clients + domain rules ONCE (avoid N+1 queries during matching)
    clients_cache = list(
        Client.objects.filter(org=org, is_active=True)
        .only('id', 'name', 'code', 'aliases')
    )
    rules_cache = list(
        OrgCalendarRule.objects.filter(
            org=org,
            is_active=True,
            match_type='attendee_domain',
        ).select_related('target_client').order_by('-priority', 'id')
    )

    # User's own email + domain — used to compute message direction
    user_email = (integration.provider_email or '').lower().strip()
    user_domain = user_email.split('@')[-1] if '@' in user_email else ''

    # Inbox folder ID — used to populate MailSignal.is_inbox
    # Cached on the integration instance for this run only
    try:
        inbox_folder_id = msgraph.fetch_inbox_folder_id(integration)
    except Exception as e:
        logger.warning(f"[MAIL-SYNC] Inbox folder lookup failed for {user.username}: {e}")
        inbox_folder_id = ''

    # Fetch via delta
    try:
        messages, new_delta_link = msgraph.fetch_mail_delta(
            integration=integration,
            initial_window_days=30,
        )
    except msgraph.MSGraphAuthError as e:
        logger.warning(f"[MAIL-SYNC] Auth error for {user.username}: {e}")
        return {'status': 'auth_error', 'error': str(e)}
    except msgraph.MSGraphAPIError as e:
        logger.error(f"[MAIL-SYNC] API error for {user.username}: {e}")
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.last_sync_error = f"API error: {str(e)[:200]}"
        integration.save(update_fields=['sync_failure_count', 'last_sync_error'])
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {'status': 'failed', 'error': str(e)}
    except Exception as e:
        logger.exception(f"[MAIL-SYNC] Unexpected error for {user.username}")
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.last_sync_error = f"Unexpected: {str(e)[:200]}"
        integration.save(update_fields=['sync_failure_count', 'last_sync_error'])
        return {'status': 'error', 'error': str(e)}

    saved = 0
    skipped = 0
    matched = 0

    from tracker.mail_matching import find_mail_match

    with transaction.atomic():
        for msg in messages:
            try:
                processed = _process_message(
                    msg=msg,
                    integration=integration,
                    user_email=user_email,
                    user_domain=user_domain,
                    inbox_folder_id=inbox_folder_id,
                    clients_cache=clients_cache,
                    rules_cache=rules_cache,
                )
            except Exception as e:
                logger.warning(f"[MAIL-SYNC] Failed to process msg {msg.get('id', '?')}: {e}")
                skipped += 1
                continue

            if processed is None:
                skipped += 1
                continue

            saved += 1
            if processed.extracted_client_id:
                matched += 1

    # Update integration state
    integration.last_synced_at = timezone.now()
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    if new_delta_link:
        integration.mail_delta_link = new_delta_link
    integration.save(update_fields=[
        'last_synced_at', 'last_sync_error', 'sync_failure_count', 'mail_delta_link',
    ])

    logger.info(
        f"[MAIL-SYNC] ✅ {user.username}: {saved} saved, {matched} matched, {skipped} skipped"
    )
    return {
        'status': 'ok',
        'user': user.username,
        'saved': saved,
        'matched': matched,
        'skipped': skipped,
    }


def _process_message(msg, integration, user_email, user_domain,
                     inbox_folder_id, clients_cache, rules_cache):
    """
    Process a single Graph message dict into a MailSignal row.
    Returns the saved MailSignal, or None if skipped (drafts, internal, etc.).

    Privacy enforcement happens here:
      - Email addresses are extracted to domain only
      - Internal emails (sender + all recipients in user_domain) are dropped
      - Drafts are dropped
      - Subject is conditionally stored only if matching confidence >= 0.85
    """
    external_id = msg.get('id')
    if not external_id:
        return None

    # Drop drafts — they're not real activity
    if msg.get('isDraft'):
        return None

    # Tombstone marker from delta API — message was deleted; remove our row
    # Graph signals deletion via @removed annotation
    if msg.get('@removed'):
        MailSignal.objects.filter(
            user=integration.user,
            provider='microsoft',
            external_id=external_id,
        ).delete()
        return None

    received_iso = msg.get('receivedDateTime')
    if not received_iso:
        return None

    from datetime import datetime
    occurred_at = datetime.fromisoformat(received_iso.replace('Z', '+00:00'))

    # Sender domain
    from_addr = ((msg.get('from') or {}).get('emailAddress') or {}).get('address', '')
    sender_email = (from_addr or '').lower().strip()
    sender_domain = sender_email.split('@')[-1] if '@' in sender_email else ''

    # Recipient addresses + domains (combine to + cc). The addresses are kept
    # only for the direction call below — a personal mailbox has no org domain
    # to compare against, so identity there is the address itself. Nothing but
    # the domain is ever persisted.
    recipient_emails = []
    recipient_domains = []
    for recip_field in ('toRecipients', 'ccRecipients'):
        for r in (msg.get(recip_field) or []):
            addr = ((r or {}).get('emailAddress') or {}).get('address', '')
            addr = (addr or '').lower().strip()
            if '@' not in addr:
                continue
            recipient_emails.append(addr)
            d = addr.split('@')[-1]
            if d:
                recipient_domains.append(d)

    # Determine direction + other_party_domain
    direction, other_party_domain = _classify_direction(
        sender_domain=sender_domain,
        recipient_domains=recipient_domains,
        user_domain=user_domain,
        sender_email=sender_email,
        recipient_emails=recipient_emails,
        user_email=user_email,
    )

    if direction == 'internal':
        # Drop internal email — not useful for client attribution, no point storing
        return None
    if direction == 'unknown':
        # Couldn't determine — drop. Don't pollute MailSignal with junk.
        return None

    # Drop emails from public domains for matching purposes (still store the
    # row, but no client attribution will fire). This is so we still see "user
    # got an email at this time" without the noise of @gmail.com matching.
    is_public_other_party = other_party_domain in PUBLIC_EMAIL_DOMAINS

    # Inbox flag
    is_inbox = bool(inbox_folder_id) and msg.get('parentFolderId') == inbox_folder_id

    # Run matching (only when other party is non-public)
    extracted_client = None
    subject_extract = ''
    raw_subject = msg.get('subject') or ''

    if not is_public_other_party:
        from tracker.mail_matching import find_mail_match
        client, conf, method, subj_ext = find_mail_match(
            mail_dict={
                'other_party_domain': other_party_domain,
                'subject': raw_subject,
                'direction': direction,
            },
            org=integration.org,
            clients_cache=clients_cache,
            rules_cache=rules_cache,
        )
        if client and conf >= 0.70:
            extracted_client = client
        subject_extract = subj_ext  # already gated at 0.85 inside find_mail_match

    # Map our internal direction to the model's choices
    direction_db = 'in' if direction == 'inbound' else 'out'

    signal, _created = MailSignal.objects.update_or_create(
        user=integration.user,
        provider='microsoft',
        external_id=external_id,
        defaults={
            'org':                  integration.org,
            'occurred_at':          occurred_at,
            'direction':            direction_db,
            'other_party_domain':   other_party_domain[:120],
            'subject_extract':      subject_extract,
            'is_inbox':             is_inbox,
            'has_attachment':       bool(msg.get('hasAttachments')),
            'extracted_client':     extracted_client,
        },
    )
    return signal


def _classify_direction(sender_domain: str, recipient_domains: list, user_domain: str,
                        sender_email: str = '', recipient_emails: list = None,
                        user_email: str = ''):
    """
    Classify message direction and identify the 'other party' domain.

    Returns (direction, other_party_domain) where direction is one of:
        'inbound'  — sender is external, user is recipient
        'outbound' — user is sender, recipient is external
        'internal' — sender + all recipients share the user's identity
        'unknown'  — can't determine (shouldn't happen with valid data)

    "Internal" normally means the user's org domain: colleague-to-colleague
    mail, which carries no client signal and is dropped by the caller.

    A mailbox on a PUBLIC domain (@outlook.com, @gmail.com) has no org domain
    to compare against — everyone on earth shares it. Treating it as one made
    every stranger on that domain look like a colleague and silently discarded
    their mail, so a personal or trial mailbox produced almost no signal. When
    the connected mailbox is public, identity is the ADDRESS, not the domain:
    only the user's own address counts as internal. Addresses are used for this
    comparison only — the caller persists nothing but the domain.
    """
    if not user_domain:
        return ('unknown', '')

    user_email = (user_email or '').lower().strip()
    mailbox_is_public = user_domain in PUBLIC_EMAIL_DOMAINS

    if mailbox_is_public:
        if not user_email:
            # No address to compare against — domain equality would call the
            # whole of outlook.com a colleague, so refuse rather than guess.
            return ('unknown', '')
        me = user_email
        sender_internal = (sender_email or '').lower().strip() == me
        recipients = [(e or '').lower().strip() for e in (recipient_emails or []) if e]
        externals = [e for e in recipients if e != me]
        external_domains = [e.split('@')[-1] for e in externals if '@' in e]
    else:
        sender_internal = sender_domain == user_domain
        recipients = [d.lower() for d in recipient_domains if d]
        external_domains = [d for d in recipients if d != user_domain]

    recipients_internal_only = bool(recipients) and not external_domains

    if sender_internal and recipients_internal_only:
        return ('internal', '')

    if sender_internal and external_domains:
        # Outbound — pick the most common external recipient domain as "other party"
        from collections import Counter
        counter = Counter(external_domains)
        dominant = counter.most_common(1)[0][0]
        return ('outbound', dominant)

    if not sender_internal and sender_domain:
        # Inbound — sender's domain is the other party
        return ('inbound', sender_domain)

    return ('unknown', '')


# ─── Nightly prune ────────────────────────────────────────────────────────────

@shared_task(name='tracker.prune_mail_signals')
def prune_mail_signals():
    """
    Delete MailSignal rows older than each org's retention window.
    Runs nightly via Celery beat.
    """
    total_deleted = 0
    for org in Organization.objects.iterator():
        retention_days = getattr(org, 'mail_signal_retention_days', 30) or 30
        cutoff = timezone.now() - timedelta(days=retention_days)
        deleted, _ = MailSignal.objects.filter(
            org=org,
            occurred_at__lt=cutoff,
        ).delete()
        if deleted:
            logger.info(f"[MAIL-PRUNE] Org {org.id}: deleted {deleted} signals older than {cutoff}")
            total_deleted += deleted

    return {'deleted': total_deleted}