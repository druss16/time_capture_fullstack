"""
Attribution audit — how much of a firm's booked time is backed by evidence?

"Accuracy" for a time tracker is two numbers, never one: coverage (how much time
got attributed at all) and precision (how much of it is right). Precision can't
be measured by re-running the classifier — it agrees with itself. What CAN be
measured, cheaply and for every block, is whether the block's own text contains
enough to tell the client it was booked to apart from its look-alikes. That is
the number this reports.

It asks exactly the question the Stage-11 commit gate asks, through the same
`client_families` service, so the audit and the runtime can never drift: the
audit's AMBIGUOUS bucket is the population the gate stops.

  SINGULAR    nothing to confuse this client with — either the text fits only
              them, or the roster holds no look-alike at all.
  RESOLVED    the text carries a word that separates it from every look-alike.
  AMBIGUOUS   the text names the group but not the member. Whatever picked this
              client did so without evidence — it may be right, but the data
              cannot show it.
  NO EVIDENCE the text names nothing at all ("Print Checks - Confirmation").
              Inherited from session context; only as good as its root.

It also reports the roster entries worth renaming — a client name or alias that
cannot exclude another client (org 21's client 130 is named the bare "St.
Patrick's Church" while 390 and 392 carry "-Jordan" and "Taberg", so every bare
QuickBooks title in that group defaults to 130 and nothing can contradict it).
Renaming one fixes a whole group, which is why this runs off the roster alone
and is worth running at onboarding, before a single block is captured.
"""
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from tracker.models import Block
from tracker.services import client_families

RESOLVED = 'resolved'
AMBIGUOUS = 'ambiguous'
NO_EVIDENCE = 'no_evidence'
SINGULAR = 'singular'

BUCKET_LABELS = {
    RESOLVED: 'RESOLVED    (distinguishing word in the text)',
    AMBIGUOUS: 'AMBIGUOUS   (names the group, not the member)',
    NO_EVIDENCE: 'NO EVIDENCE (text names nothing)',
    SINGULAR: 'SINGULAR    (no look-alike to confuse it with)',
}

# Consecutive un-evidenced work closer together than this is one sitting, so a
# single pick would settle all of it. Mirrors ambiguous_groups.SESSION_GAP.
_SESSION_GAP = timedelta(minutes=60)


def classify_block(block, lookalikes):
    """Which evidence bucket does this block's attribution fall into?"""
    words = client_families.text_words(
        block.window_title or block.title or '',
        block.file_path or '',
        block.url or '',
    )
    candidates = lookalikes.candidates_for(words)
    if block.client_id not in candidates:
        # The text points somewhere else, or names nobody. That only matters
        # when there IS somebody to confuse this client with — a block booked to
        # a one-of-a-kind client off session context is not a trust problem.
        return NO_EVIDENCE if lookalikes.has_lookalikes(block.client_id) else SINGULAR
    if len(candidates) == 1:
        return SINGULAR
    return RESOLVED if lookalikes.resolve(words) == block.client_id else AMBIGUOUS


def audit_org(org_id, days=30):
    """
    Score every attributed block of the last `days` and return a report dict.

    Read-only — it never writes a block.
    """
    lookalikes = client_families.for_org(org_id, use_cache=False)

    since = (timezone.now() - timedelta(days=days)).date()
    blocks = list(
        Block.objects
        .filter(org_id=org_id, day__gte=since, client__isnull=False)
        .exclude(classification_state='rejected')
        .order_by('user_id', 'start')
    )

    counts = defaultdict(int)
    minutes = defaultdict(int)
    per_client = defaultdict(lambda: defaultdict(int))
    committed_without_evidence = 0
    unresolved = []

    for block in blocks:
        bucket = classify_block(block, lookalikes)
        counts[bucket] += 1
        minutes[bucket] += (block.minutes or 0)
        if bucket in (AMBIGUOUS, NO_EVIDENCE):
            per_client[block.client_id][bucket] += (block.minutes or 0)
            unresolved.append(block)
            if block.classification_state == 'committed':
                committed_without_evidence += 1

    # How many human picks would settle the unresolved pile, if consecutive
    # same-user work counted as one decision?
    sessions = defaultdict(list)
    for block in unresolved:
        sessions[block.user_id].append(block)
    session_decisions = 0
    for run in sessions.values():
        run.sort(key=lambda b: b.start)
        session_decisions += 1
        for prev, nxt in zip(run, run[1:]):
            if (nxt.start - prev.end) > _SESSION_GAP:
                session_decisions += 1

    total_min = sum(minutes.values()) or 1
    lookalike_min = sum(minutes[k] for k in (RESOLVED, AMBIGUOUS, NO_EVIDENCE)) or 1
    return {
        'org_id': org_id,
        'days': days,
        'since': since,
        'blocks': len(blocks),
        'clients': len(lookalikes.by_id),
        'by_id': lookalikes.by_id,
        'counts': dict(counts),
        'minutes': dict(minutes),
        'total_minutes': sum(minutes.values()),
        'pct_of_all': {k: 100.0 * minutes[k] / total_min for k in minutes},
        'pct_of_lookalikes': {
            k: 100.0 * minutes[k] / lookalike_min
            for k in (RESOLVED, AMBIGUOUS, NO_EVIDENCE)
        },
        'per_client': per_client,
        'committed_without_evidence': committed_without_evidence,
        'unresolved_blocks': len(unresolved),
        'unresolved_minutes': minutes[AMBIGUOUS] + minutes[NO_EVIDENCE],
        'session_decisions': session_decisions,
        'ambiguous_name_forms': lookalikes.ambiguous_name_forms(),
    }
