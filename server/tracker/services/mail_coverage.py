"""
How much email time is attributed WITHOUT any mail evidence?

Read-only. Answers one question and refuses to answer more than one:

    Of the time your people spend in their email client, how much does the
    classifier attribute with no mail signal to go on — and of that, how much
    lands somewhere weak enough that better mail evidence could have changed
    the answer?

That last number is the CEILING on what reading more mail folders could buy.
It is an upper bound, not an estimate. Sent Items only helps where someone
wrote to a client who had not written to them inside Stage 7's window; this
measurement cannot see which of the gap blocks those are, because the evidence
that would prove it is in the folder we do not read. Treat the number as "no
more than this", and if it is small, the question is settled without anyone
having to widen a mailbox scope.

Method — what the classifier RECORDED, not what it would do today.

Every classified block carries `proposed_signals`, the serialized list of
signals that ran. A block whose list contains type 'mail' is one where Stage 7
spoke. This is deliberately read instead of re-deriving Stage 7's window
against MailSignal: those rows are pruned on the org's retention window
(30 days by default), so re-deriving would score every older block as
uncovered no matter what actually happened, and the report would grow more
alarming the further back you looked.

Buckets (email-client blocks only, suppressed blocks excluded):

  mail_used       Stage 7 emitted a mail signal. Covered today.
  no_mailbox      The user had no connected mailbox when the block happened.
                  Folder scope is irrelevant here; connecting mail is the fix.
  other_evidence  No mail signal, but the block has a client and at least one
                  non-weak signal — a file path, a tax package, a QuickBooks
                  fingerprint. Mail would have been redundant.
  gap             No mail signal, and the block either has no client at all or
                  rests only on weak signals (agent stickiness, the previous
                  block). THIS IS THE CEILING.
  unmeasured      No recorded signals — never classified, or predates the
                  field. Reported separately rather than assumed either way.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from tracker.models import Block, UserIntegration
from tracker.services.classification_service import ClassificationService
from tracker.utils.db_iter import keyset_iter

MAIL_USED = 'mail_used'
NO_MAILBOX = 'no_mailbox'
OTHER_EVIDENCE = 'other_evidence'
GAP = 'gap'
UNMEASURED = 'unmeasured'

BUCKETS = (MAIL_USED, OTHER_EVIDENCE, NO_MAILBOX, GAP, UNMEASURED)

BUCKET_LABELS = {
    MAIL_USED:      'Mail evidence used',
    NO_MAILBOX:     'No mailbox connected yet',
    OTHER_EVIDENCE: 'No mail signal, but other evidence carried it',
    GAP:            'No mail signal, weak or no attribution  <- ceiling',
    UNMEASURED:     'No recorded signals (unclassified)',
}

# Signals that name a client but only because something else already did.
# A block resting on nothing but these is one better evidence could move.
WEAK_SIGNAL_TYPES = frozenset({
    'agent_current_client',
    'agent_inference',
    'prior_block',
})

MAIL_PROVIDERS = ('microsoft_mail', 'gmail')

# A SQL prefilter that must stay a strict SUPERSET of
# ClassificationService._is_outlook_or_email_block, which is the real predicate
# and the only thing allowed to decide. Every marker the predicate looks for is
# covered here by a shorter substring of itself ('outlook.office.com' by
# 'outlook', ' - inbox' by 'inbox'). Widen this freely; narrowing it silently
# drops blocks from the population.
EMAILISH_PREFILTER = (
    Q(app_name__icontains='outlook')
    | Q(app_name__iexact='olk')
    | Q(window_title__icontains='outlook')
    | Q(window_title__icontains='inbox')
    | Q(window_title__icontains='message (html)')
    | Q(window_title__icontains='message (plain text)')
    | Q(window_title__icontains='mail.google.com')
    | Q(title__icontains='outlook')
    | Q(title__icontains='inbox')
    | Q(title__icontains='message (html)')
    | Q(title__icontains='message (plain text)')
    | Q(title__icontains='mail.google.com')
)


def _mailbox_connected_since(org_id):
    """
    user_id -> when that user's mailbox was connected.

    A block that happened BEFORE the mailbox existed cannot be evidence of a
    folder-scope problem. Without this the report blames Inbox-only scoping for
    every block a firm recorded before it ever connected mail, which on a
    30-day window over a recent rollout is most of them.
    """
    since = {}
    rows = UserIntegration.objects.filter(
        org_id=org_id,
        provider__in=MAIL_PROVIDERS,
        is_connected=True,
    ).values_list('user_id', 'created_at')
    for user_id, created_at in rows:
        prev = since.get(user_id)
        if prev is None or (created_at and created_at < prev):
            since[user_id] = created_at
    return since


def _block_minutes(block) -> float:
    if block.minutes:
        return float(block.minutes)
    if block.start and block.end:
        return max(0.0, (block.end - block.start).total_seconds() / 60.0)
    return 0.0


def _bucket_for(block, connected_since) -> str:
    signals = block.proposed_signals or []
    types = {s.get('type') for s in signals if isinstance(s, dict)}

    if not types:
        return UNMEASURED
    if 'mail' in types:
        return MAIL_USED

    joined_at = connected_since.get(block.user_id)
    if joined_at is None or (block.start and block.start < joined_at):
        return NO_MAILBOX

    if block.client_id and (types - WEAK_SIGNAL_TYPES):
        return OTHER_EVIDENCE
    return GAP


def measure_org(org_id: int, days: int = 30) -> dict:
    """Bucket every email-client block of the window. Reads nothing else."""
    since = timezone.now() - timedelta(days=days)
    connected_since = _mailbox_connected_since(org_id)

    qs = (
        Block.objects
        .filter(org_id=org_id, start__gte=since)
        .exclude(classification_state='suppressed')
        .filter(EMAILISH_PREFILTER)
    )

    counts = defaultdict(int)
    minutes = defaultdict(float)
    per_user_gap = defaultdict(lambda: {'blocks': 0, 'minutes': 0.0})
    blocks = 0
    total_minutes = 0.0

    for block in keyset_iter(qs):
        # The prefilter is a superset; the shared predicate decides.
        if not ClassificationService._is_outlook_or_email_block(block):
            continue

        mins = _block_minutes(block)
        bucket = _bucket_for(block, connected_since)

        blocks += 1
        total_minutes += mins
        counts[bucket] += 1
        minutes[bucket] += mins

        if bucket == GAP:
            entry = per_user_gap[block.user_id]
            entry['blocks'] += 1
            entry['minutes'] += mins

    pct = {
        b: (minutes[b] / total_minutes * 100.0) if total_minutes else 0.0
        for b in BUCKETS
    }

    return {
        'org_id':        org_id,
        'days':          days,
        'since':         since.date().isoformat(),
        'blocks':        blocks,
        'total_minutes': total_minutes,
        'counts':        dict(counts),
        'minutes':       dict(minutes),
        'pct_of_all':    pct,
        'mailboxes':     len(connected_since),
        'per_user_gap':  dict(per_user_gap),
    }
