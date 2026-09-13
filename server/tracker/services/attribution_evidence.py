# tracker/services/attribution_evidence.py
"""
What is holding up the time you are about to bill?

The mismatch detector asks a narrow question — "does this title name a
DIFFERENT client than it is booked to?" — and on a healthy roster the answer is
almost always no. Org 21 produces roughly one finding a quarter. That is a
queue, not an answer.

This asks the question a firm actually has when it bills: for each client, over
this period, what evidence says this time belongs to them at all? Every block
falls into exactly one of four:

    a person chose it      somebody looked and decided. Nothing to check.
    independent evidence   something other than the window title agrees — the
                           file on disk, the QuickBooks company file, work
                           either side of it that a human filed, a prior human
                           ruling on the same title.
    the title only         the window title names them, and nothing else does.
    nothing at all         no text anywhere in or around the block points at
                           the client it is billed to.

A LOUD WARNING ABOUT THE LAST ONE, because a number this shape invites the
wrong conclusion: "nothing at all" is not "wrong". Most of it is short
QuickBooks modals — "Payments", "Select Checks to Print", "Print Checks -
Confirmation" — that inherit their client from the session the user was already
in. That inheritance is legitimate and this engine cannot see it, because it
reads a block's own text plus its neighbours and nothing else. Org 21's sampled
accuracy is ~94% while only ~38% of its billable blocks are backed here. The
gap is session inheritance, not error.

So read it as ATTENTION, not as a defect count: the hours with nothing behind
them are where a reviewer's time is worth most, and the ratio is a dial that
moves when capture improves. It is not an estimate of how much is misfiled —
`services/accuracy.py` is the only thing that measures that, because it uses a
random sample and a human verdict.
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Q

BACKED_PERSON = 'person'
BACKED_INDEPENDENT = 'independent'
BACKED_TITLE = 'title_only'
BACKED_NONE = 'none'

BUCKETS = (BACKED_PERSON, BACKED_INDEPENDENT, BACKED_TITLE, BACKED_NONE)

BUCKET_LABEL = {
    BACKED_PERSON: 'a person chose it',
    BACKED_INDEPENDENT: 'independent evidence',
    BACKED_TITLE: 'the window title only',
    BACKED_NONE: 'nothing at all',
}


def _is_human(b):
    return (b.state_changed_by in ('user', 'user_edit', 'correction')
            or b.categorized_by in ('manual', 'correction'))


def build_neighbour_index(blocks_by_user, window):
    """{block_id: (before, after)} for every block, from one ordered pass.

    The per-block query pair is fine for one flagged row and ruinous for a
    quarter of billable time — 7,724 blocks is 15,448 round trips. Here each
    user's blocks are already sorted by start, so the nearest attributed
    neighbour on each side is a walk outward, not a query.

    Deliberately mirrors the query version's rules: the neighbour must carry a
    client, must fall within the window, and the block itself is excluded.
    """
    index = {}
    for _uid, rows in blocks_by_user.items():
        attributed = [b for b in rows if b.client_id]
        for i, b in enumerate(rows):
            if not (b.start and b.end):
                continue
            before = after = None
            # Walk left for the nearest attributed block that ENDS before this
            # one starts, inside the window.
            for other in reversed(attributed):
                if other.id == b.id or not other.end:
                    continue
                if other.end <= b.start:
                    if other.end >= b.start - window:
                        before = other
                    break
            for other in attributed:
                if other.id == b.id or not other.start:
                    continue
                if other.start >= b.end:
                    if other.start <= b.end + window:
                        after = other
                    break
            index[b.id] = (before, after)
    return index


def classify_block(block, ctx):
    """Which of the four buckets this block's attribution falls in, plus signals."""
    from tracker.services.mismatch_agent import gather_signals

    if _is_human(block):
        return BACKED_PERSON, []

    sigs = [s for s in gather_signals(block, ctx) if s.supports == block.client_id]
    if any(s.independent for s in sigs):
        return BACKED_INDEPENDENT, sigs
    if sigs:
        return BACKED_TITLE, sigs
    return BACKED_NONE, sigs


def evidence_report(org_id, days=90, client_id=None, billable_only=True,
                    weak_limit=25, block_cap=20000):
    """Per-client evidence breakdown over the period.

    Only SETTLED time (classification_state='committed') on a named client —
    the same scope the review tab reads, because this is a statement about time
    that is going to be billed, not time still being decided.
    """
    from django.utils import timezone

    from tracker.models import Block
    from tracker.services.mismatch_agent import NEIGHBOUR_WINDOW, context_for

    cutoff = timezone.now() - timedelta(days=days)
    qs = (Block.objects
          .filter(org_id=org_id, deleted_at__isnull=True,
                  client_id__isnull=False, classification_state='committed',
                  start__gte=cutoff)
          .exclude(window_title__isnull=True)
          .exclude(window_title=''))
    if billable_only:
        qs = qs.filter(is_billable=True)
    if client_id:
        qs = qs.filter(client_id=client_id)

    blocks = list(
        qs.select_related('client')
          .only('id', 'org_id', 'client_id', 'user_id', 'window_title',
                'file_path', 'app_name', 'minutes', 'start', 'end',
                'state_changed_by', 'categorized_by')
          .order_by('user_id', 'start')[:block_cap]
    )

    ctx = context_for(org_id)
    by_user = defaultdict(list)
    for b in blocks:
        by_user[b.user_id].append(b)
    ctx.neighbour_index = build_neighbour_index(by_user, NEIGHBOUR_WINDOW)
    try:
        return _tally(blocks, ctx, weak_limit)
    finally:
        # The context is cached and shared; an index built for one period must
        # never silently answer questions about another.
        ctx.neighbour_index = None


def _tally(blocks, ctx, weak_limit):
    per_client = defaultdict(lambda: {
        'client_id': None, 'client_name': '', 'blocks': 0, 'minutes': 0,
        'buckets': {k: {'blocks': 0, 'minutes': 0} for k in BUCKETS},
    })
    totals = {k: {'blocks': 0, 'minutes': 0} for k in BUCKETS}
    weak = []
    signal_counts = defaultdict(int)

    for b in blocks:
        bucket, sigs = classify_block(b, ctx)
        mins = b.minutes or 0
        for s in sigs:
            signal_counts[s.kind] += 1

        row = per_client[b.client_id]
        row['client_id'] = b.client_id
        row['client_name'] = ctx.name(b.client_id) or (
            b.client.name if b.client_id else '')
        row['blocks'] += 1
        row['minutes'] += mins
        row['buckets'][bucket]['blocks'] += 1
        row['buckets'][bucket]['minutes'] += mins

        totals[bucket]['blocks'] += 1
        totals[bucket]['minutes'] += mins

        if bucket == BACKED_NONE:
            weak.append({
                'block_id': b.id,
                'client_id': b.client_id,
                'client_name': row['client_name'],
                'minutes': mins,
                'date': b.start.date().isoformat() if b.start else None,
                'app_name': b.app_name or '',
                'window_title': (b.window_title or '')[:180],
            })

    clients = sorted(per_client.values(),
                     key=lambda r: -r['buckets'][BACKED_NONE]['minutes'])
    weak.sort(key=lambda r: -r['minutes'])

    total_minutes = sum(v['minutes'] for v in totals.values())
    total_blocks = sum(v['blocks'] for v in totals.values())
    backed = (totals[BACKED_PERSON]['minutes']
              + totals[BACKED_INDEPENDENT]['minutes'])

    return {
        'total_blocks': total_blocks,
        'total_minutes': total_minutes,
        # The headline: how much of the time about to be billed can say why.
        'backed_minutes': backed,
        'backed_pct': round(backed / total_minutes, 4) if total_minutes else None,
        'totals': totals,
        'labels': BUCKET_LABEL,
        'signal_counts': dict(sorted(signal_counts.items(),
                                     key=lambda kv: -kv[1])),
        'clients': clients,
        'weakest': weak[:weak_limit],
    }
