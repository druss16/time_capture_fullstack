"""
Gmail sync Celery tasks — the Google counterpart of tasks_mail.py.

  - sync_all_gmail:  master, every 5 min, dispatches staggered per-user syncs
  - sync_user_gmail: per-user. Every run reads users.history.list from the
                     stored historyId (new mail), then spends what is left of
                     a fixed time budget backfilling the last
                     INITIAL_WINDOW_DAYS of INBOX + SENT one page at a time.
                     A 404 on the historyId (too old) restarts the backfill.

Why the backfill is paged and resumable: a busy mailbox's 30-day window is
thousands of messages, one metadata GET each. Walking it in a single run
outlived the Celery time limit, so the run was killed before it saved
anything — and the next run started over, forever, with last_synced_at never
set. Now each page is committed as it lands and the position is kept in
sync_cursor (see _load_state), so a run that is cut short loses one page.

Direction, internal-mail dropping, public-domain handling and domain→client
matching are the Outlook code paths verbatim (_classify_direction and
mail_matching.find_mail_match), so a Gmail message and an Outlook message with
the same headers produce the same client.

Unlike Outlook, Gmail reads SENT as well as INBOX: sent mail is the one signal
that says what the user was working ON (and it is what compose duration is
measured against). A message carrying the SENT label is outbound by definition,
even when it went out under a send-as alias the header comparison would not
recognise as the user.

PRIVACY (see MailSignal docstring): Gmail rows store From/To/Cc addresses and
names and the full subject, readable ONLY by the owning user. Never the body,
snippet, or attachment names — the fetch mask in integrations/google.py keeps
them from ever being transmitted.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from email.utils import getaddresses, parseaddr

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tracker.integrations import google
from tracker.models import Client, MailSignal, OrgCalendarRule, UserIntegration
from tracker.tasks_mail import (
    MAX_FAILURE_COUNT,
    PUBLIC_EMAIL_DOMAINS,
    _classify_direction,
    _stagger_offset,
)

logger = logging.getLogger(__name__)

INITIAL_WINDOW_DAYS = 30          # mirrors fetch_mail_delta(initial_window_days=30)
BACKFILL_PAGE_SIZE = 100          # message ids per backfill page (one metadata GET each)
RUN_BUDGET_SECONDS = 120          # well inside task_soft_time_limit (240s)
COMPOSE_ANNOTATE_WINDOW = timedelta(hours=24)
SYNC_LABELS = ('INBOX', 'SENT')
SKIP_LABELS = {'DRAFT', 'SPAM', 'TRASH'}


# ─── Master dispatch ──────────────────────────────────────────────────────────

@shared_task(name='tracker.sync_all_gmail')
def sync_all_gmail():
    """Dispatch per-user Gmail syncs, staggered across the 5-minute window."""
    eligible = UserIntegration.objects.filter(
        provider='gmail',
        is_connected=True,
        sync_failure_count__lt=MAX_FAILURE_COUNT,
    ).filter(
        Q(org__disable_mail_integration=False) | Q(org__disable_mail_integration__isnull=True),
    )
    dispatched = 0
    for integration_id, user_id in eligible.values_list('id', 'user_id'):
        sync_user_gmail.apply_async(args=[integration_id], countdown=_stagger_offset(user_id))
        dispatched += 1
    logger.info(f"[GMAIL-SYNC] Dispatched {dispatched} Gmail sync subtasks (staggered)")
    return {'dispatched': dispatched}


# ─── Per-user sync ────────────────────────────────────────────────────────────

@shared_task(
    name='tracker.sync_user_gmail',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def sync_user_gmail(self, integration_id):
    try:
        integration = UserIntegration.objects.select_related('user', 'org').get(
            id=integration_id, provider='gmail', is_connected=True,
        )
    except UserIntegration.DoesNotExist:
        return {'status': 'skipped', 'reason': 'not_found'}

    if integration.sync_failure_count >= MAX_FAILURE_COUNT:
        return {'status': 'skipped', 'reason': 'too_many_failures'}
    if getattr(integration.org, 'disable_mail_integration', False):
        return {'status': 'skipped', 'reason': 'org_disabled'}

    user = integration.user
    try:
        result = run_gmail_sync(integration)
    except google.GoogleAuthError as e:
        logger.warning(f"[GMAIL-SYNC] Auth error for {user.username}: {e}")
        return {'status': 'auth_error', 'error': str(e)}
    except google.GoogleTransientError as e:
        # A dropped connection is not the account's fault. Note it, retry, and
        # do NOT count it toward MAX_FAILURE_COUNT — that cutoff stops syncing
        # for good. Pages committed before the drop are kept (resumable cursor).
        logger.warning(f"[GMAIL-SYNC] Transient network error for {user.username}: {e}")
        integration.last_sync_error = f"Temporary network error (will retry): {str(e)[:160]}"
        integration.save(update_fields=['last_sync_error'])
        try:
            raise self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            return {'status': 'transient', 'error': str(e)}
    except google.GoogleAPIError as e:
        logger.error(f"[GMAIL-SYNC] API error for {user.username}: {e}")
        _record_failure(integration, f"API error: {str(e)[:200]}")
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {'status': 'failed', 'error': str(e)}
    except Exception as e:
        logger.exception(f"[GMAIL-SYNC] Unexpected error for {user.username}")
        _record_failure(integration, f"Unexpected: {str(e)[:200]}")
        return {'status': 'error', 'error': str(e)}

    logger.info(f"[GMAIL-SYNC] {user.username}: {result}")
    return {'status': 'ok', 'user': user.username, **result}


def _record_failure(integration, msg):
    integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
    integration.last_sync_error = msg
    integration.save(update_fields=['sync_failure_count', 'last_sync_error'])


# sync_cursor holds either a bare historyId (backfill finished — the shape
# every earlier version wrote) or, while the window is still being walked, a
# JSON object: {"h": historyId, "since": ms, "bf": {label: pageToken | ""}}.
# A label leaves "bf" once its pages reach past "since".

def _load_state(cursor):
    cursor = (cursor or '').strip()
    if not cursor:
        return {}
    if cursor.startswith('{'):
        try:
            state = json.loads(cursor)
            if isinstance(state, dict) and state.get('h'):
                state.setdefault('bf', {})
                return state
        except ValueError:
            pass
        return {}
    return {'h': cursor, 'bf': {}}


def _dump_state(state):
    if state.get('bf'):
        return json.dumps(state, separators=(',', ':'))
    return str(state['h'])


def _fresh_state(integration):
    """The historyId is read FIRST, so mail arriving while the window is
    walked is picked up by the history read rather than falling in a gap."""
    profile = google.gmail_get_profile(integration)
    since = timezone.now() - timedelta(days=INITIAL_WINDOW_DAYS)
    return {
        'h': str(profile.get('historyId') or ''),
        'since': int(since.timestamp() * 1000),
        'bf': {label: '' for label in SYNC_LABELS},
    }


def _save_cursor(integration, state, established=False):
    integration.sync_cursor = _dump_state(state)
    fields = ['sync_cursor']
    if established:
        integration.sync_cursor_set_at = timezone.now()
        fields.append('sync_cursor_set_at')
    integration.save(update_fields=fields)


def _persist(messages, integration, ctx, deleted_ids=()):
    """Save one batch in its own transaction. Returns (saved, matched, skipped)."""
    saved = matched = skipped = 0
    with transaction.atomic():
        if deleted_ids:
            MailSignal.objects.filter(
                user=integration.user, provider='google', external_id__in=list(deleted_ids),
            ).delete()
        for msg in messages:
            try:
                sig = process_gmail_message(msg, integration, **ctx)
            except Exception as e:
                logger.warning(f"[GMAIL-SYNC] Failed to process msg {msg.get('id', '?')}: {e}")
                skipped += 1
                continue
            if sig is None:
                skipped += 1
                continue
            saved += 1
            if sig.extracted_client_id:
                matched += 1
    return saved, matched, skipped


def run_gmail_sync(integration, budget_seconds=RUN_BUDGET_SECONDS, clock=time.monotonic):
    """Fetch + persist within a time budget. Raises google.* errors for the
    task to classify; everything committed before an error is kept."""
    user = integration.user
    deadline = clock() + budget_seconds
    ctx = _matching_context(integration)
    totals = [0, 0, 0]  # saved, matched, skipped
    deleted_ids = []

    def add(counts):
        for i, n in enumerate(counts):
            totals[i] += n

    state = _load_state(integration.sync_cursor)
    if not state:
        mode = 'full'
        state = _fresh_state(integration)
        _save_cursor(integration, state, established=True)
    else:
        mode = 'incremental'
        try:
            added, deleted_ids, new_h = google.gmail_list_history(integration, state['h'])
            wanted = [
                a['id'] for a in added
                if set(a.get('labelIds') or []) & set(SYNC_LABELS)
                and not set(a.get('labelIds') or []) & SKIP_LABELS
            ]
            add(_persist(google.gmail_get_messages(integration, wanted),
                         integration, ctx, deleted_ids))
            state['h'] = str(new_h or state['h'])
            _save_cursor(integration, state)
        except google.GoogleCursorExpired:
            logger.warning(f"[GMAIL-SYNC] historyId expired for {user.username} — full resync")
            mode = 'full_resync'
            state = _fresh_state(integration)
            _save_cursor(integration, state, established=True)

    pages = 0
    while state['bf'] and clock() < deadline:
        label = next(iter(state['bf']))
        ids, next_token = google.gmail_list_page(
            integration, label, state['bf'][label] or None, BACKFILL_PAGE_SIZE,
        )
        msgs = google.gmail_get_messages(integration, ids)
        in_window = [m for m in msgs if int(m.get('internalDate') or 0) >= state['since']]
        add(_persist(in_window, integration, ctx))
        pages += 1
        if not ids or not next_token or len(in_window) < len(msgs):
            del state['bf'][label]       # reached past the window, or the end
        else:
            state['bf'][label] = next_token
        _save_cursor(integration, state)
    if mode == 'incremental' and pages:
        mode = 'backfill'

    now = timezone.now()
    integration.last_synced_at = now
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    integration.save(update_fields=['last_synced_at', 'last_sync_error', 'sync_failure_count'])

    # Compose durations need the user's Gmail BLOCKS, which may land after the
    # mail does — so recompute the last day's sends on every sync.
    composed = 0
    try:
        from tracker.services.mail_compose import annotate_compose_seconds
        composed = annotate_compose_seconds(user, now - COMPOSE_ANNOTATE_WINDOW, now)
    except Exception as e:
        logger.warning(f"[GMAIL-SYNC] compose annotation failed for {user.username}: {e}")

    saved, matched, skipped = totals
    return {
        'mode': mode, 'saved': saved, 'matched': matched, 'skipped': skipped,
        'deleted': len(deleted_ids), 'composed': composed,
        'backfill_pages': pages, 'backfill_remaining': sorted(state['bf']),
    }


def _matching_context(integration):
    org = integration.org
    user_email = (integration.provider_email or '').lower().strip()
    return {
        'user_email': user_email,
        'user_domain': user_email.split('@')[-1] if '@' in user_email else '',
        'clients_cache': list(
            Client.objects.filter(org=org, is_active=True).only('id', 'name', 'code', 'aliases')
        ),
        'rules_cache': list(
            OrgCalendarRule.objects.filter(
                org=org, is_active=True, match_type='attendee_domain',
            ).select_related('target_client').order_by('-priority', 'id')
        ),
    }


# ─── Message → MailSignal ─────────────────────────────────────────────────────

def _headers(msg):
    out = {}
    for h in ((msg.get('payload') or {}).get('headers') or []):
        name = (h.get('name') or '').lower()
        if name and name not in out:
            out[name] = h.get('value') or ''
    return out


def _parse_people(value):
    """'Jane <jane@acme.com>, bob@x.com' → [{'email','name'}], lowercased emails."""
    people = []
    for name, addr in getaddresses([value or '']):
        addr = (addr or '').strip().lower()
        if '@' not in addr:
            continue
        people.append({'email': addr[:254], 'name': (name or '').strip()[:255]})
    return people


def process_gmail_message(msg, integration, user_email, user_domain,
                          clients_cache, rules_cache):
    """One masked Gmail message dict → a MailSignal row, or None if skipped."""
    external_id = msg.get('id')
    if not external_id:
        return None
    labels = set(msg.get('labelIds') or [])
    if labels & SKIP_LABELS or not labels & set(SYNC_LABELS):
        return None

    try:
        occurred_at = datetime.fromtimestamp(int(msg['internalDate']) / 1000, tz=dt_timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None

    hdr = _headers(msg)
    from_name, from_addr = parseaddr(hdr.get('from', ''))
    from_addr = (from_addr or '').strip().lower()
    to_people = _parse_people(hdr.get('to', ''))
    cc_people = _parse_people(hdr.get('cc', ''))
    recipient_emails = [p['email'] for p in to_people + cc_people]
    recipient_domains = [e.split('@')[-1] for e in recipient_emails]

    is_sent = 'SENT' in labels
    if is_sent:
        # SENT is Gmail's own statement that the user sent it — even from a
        # send-as alias the header comparison would read as a stranger.
        sender_email, sender_domain = user_email, user_domain
    else:
        sender_email = from_addr
        sender_domain = from_addr.split('@')[-1] if '@' in from_addr else ''

    direction, other_party_domain = _classify_direction(
        sender_domain=sender_domain,
        recipient_domains=recipient_domains,
        user_domain=user_domain,
        sender_email=sender_email,
        recipient_emails=recipient_emails,
        user_email=user_email,
    )
    if direction in ('internal', 'unknown'):
        # Same rule as Outlook: internal mail is never stored. If a row exists
        # from an earlier classification, drop it too.
        MailSignal.objects.filter(
            user=integration.user, provider='google', external_id=external_id,
        ).delete()
        return None

    raw_subject = hdr.get('subject', '') or ''
    extracted_client = None
    subject_extract = ''
    if other_party_domain not in PUBLIC_EMAIL_DOMAINS:
        from tracker.mail_matching import find_mail_match
        client, conf, _method, subj_ext = find_mail_match(
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
        subject_extract = subj_ext

    signal, _ = MailSignal.objects.update_or_create(
        user=integration.user,
        provider='google',
        external_id=external_id,
        defaults={
            'org': integration.org,
            'occurred_at': occurred_at,
            'direction': 'in' if direction == 'inbound' else 'out',
            'other_party_domain': other_party_domain[:120],
            'subject_extract': subject_extract,
            'is_inbox': 'INBOX' in labels,
            # multipart/mixed is how an attachment-bearing message is built;
            # the attachment itself (and its name) is never requested.
            'has_attachment': ((msg.get('payload') or {}).get('mimeType') or '') == 'multipart/mixed',
            'extracted_client': extracted_client,
            # Owner-only fields (MailSignal PRIVACY GUARANTEES).
            'from_address': (user_email if is_sent and not from_addr else from_addr)[:254] or None,
            'from_name': (from_name or '').strip()[:255] or None,
            'to_recipients': to_people,
            'cc_recipients': cc_people,
            'subject': raw_subject[:2000],
        },
    )
    return signal
