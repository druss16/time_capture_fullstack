"""
Turn gated blocks into the handful of questions a human should actually answer.

Stage 11 (ClassificationService._gate_family_ambiguity) refuses to auto-commit a
client the block's text cannot single out, and leaves a ``family_ambiguous``
signal naming the candidates. That is per-block, and per-block is the wrong unit
to ask about: a morning in one parish's QuickBooks file produces a dozen gated
blocks that all have the SAME answer. Asking twelve times is how a review queue
becomes something people click through without reading.

So blocks are folded into work sessions — same user, overlapping candidates,
no long gap — and each session becomes one row with one pick that fans out to
every block in it. Measured on org 21: 417 gated blocks collapse to 168 picks,
about 5.6 a day across the whole firm.
"""
from collections import defaultdict
from datetime import timedelta

# Consecutive gated work closer together than this is one sitting, so one pick
# settles all of it. An hour is long enough to survive a coffee break and short
# enough that a morning on one parish and an afternoon on another stay separate
# questions.
SESSION_GAP = timedelta(minutes=60)

SIGNAL_TYPE = 'family_ambiguous'


def _signal(block):
    """The Stage-11 signal on this block, if it was gated."""
    for sig in (block.proposed_signals or []):
        if isinstance(sig, dict) and sig.get('type') == SIGNAL_TYPE:
            return sig
    return None


def is_open_question(block):
    """Is this block still waiting on a human to say WHICH client?

    True when Stage 11 gated it and nothing has answered it since. The second
    half matters: a block gated this morning and resolved this afternoon (the
    QuickBooks company file capture finally reached that machine) still carries
    its old ``family_ambiguous`` signal, and treating it as unanswered shows the
    same block twice — once as "which parish?" and once already decided.

    Shared by the Daily Review lane (which renders the question) and Confirm-all
    (which must not answer it), so a bulk action can never quietly commit the
    guess the gate deliberately refused to commit.
    """
    if not _signal(block):
        return False
    from tracker.services.classification_service import ClassificationService
    return not any(
        ClassificationService._is_identifying(sig)
        for sig in (block.proposed_signals or [])
        if isinstance(sig, dict)
    )


def build_groups(blocks, client_names, recent_client_ids=()):
    """
    Fold gated blocks into one row per work session.

    ``blocks`` need not be pre-filtered — anything without a Stage-11 signal is
    ignored. ``recent_client_ids`` is this user's recently-worked clients, most
    recent first; it decides which button lands leftmost, so the picker usually
    opens with the right answer already in front.

    Returns a list of dicts the Daily Review lane renders directly.
    """
    gated = []
    for block in blocks:
        sig = _signal(block)
        if sig:
            gated.append((block, sig))
    if not gated:
        return []

    by_user = defaultdict(list)
    for block, sig in gated:
        by_user[block.user_id].append((block, sig))

    groups = []
    for items in by_user.values():
        items.sort(key=lambda pair: pair[0].start)
        run = []
        run_candidates = None
        for block, sig in items:
            candidates = [
                int(c) for c in (sig.get('detail') or {}).get('candidate_client_ids', [])
            ]
            overlap = (
                set(candidates) & run_candidates if run_candidates is not None else None
            )
            contiguous = run and (block.start - run[-1][0].end) <= SESSION_GAP
            if run and contiguous and overlap:
                run.append((block, sig))
                # Narrow to what the whole run agrees on — a session that starts
                # ambiguous between five parishes and later shows a title ruling
                # two out should ask about three, not five.
                run_candidates = overlap
            else:
                if run:
                    groups.append(_render(run, run_candidates, client_names, recent_client_ids))
                run = [(block, sig)]
                run_candidates = set(candidates)
        if run:
            groups.append(_render(run, run_candidates, client_names, recent_client_ids))

    groups.sort(key=lambda g: -g['minutes'])
    return groups


def _render(run, candidate_ids, client_names, recent_client_ids):
    """One session -> one row."""
    blocks = [b for b, _ in run]
    labels = {}
    order = []
    for _, sig in run:
        detail = sig.get('detail') or {}
        for cid in detail.get('candidate_client_ids', []):
            cid = int(cid)
            if cid in candidate_ids and cid not in order:
                order.append(cid)
        for cid, label in (detail.get('candidate_labels') or {}).items():
            if int(cid) in candidate_ids:
                labels.setdefault(int(cid), label)

    # Recently-worked clients first — the picker should feel like it already
    # knows the answer. Ties keep the classifier's own ranking.
    recent_rank = {cid: i for i, cid in enumerate(recent_client_ids)}
    # Snapshot the classifier's own ordering BEFORE sorting — reading
    # order.index() from inside the sort key reads a list mid-mutation.
    classifier_rank = {cid: i for i, cid in enumerate(order)}
    order.sort(key=lambda cid: (recent_rank.get(cid, len(recent_rank)),
                                classifier_rank[cid]))

    representative = max(blocks, key=lambda b: b.minutes or 0)
    return {
        'block_ids':    [b.id for b in blocks],
        'window_title': representative.window_title or representative.title or '',
        'minutes':      sum(b.minutes or 0 for b in blocks),
        'block_count':  len(blocks),
        'start':        min(b.start for b in blocks).isoformat(),
        'end':          max(b.end for b in blocks).isoformat(),
        'category': (
            list((representative.category_hours or {}).keys())[0]
            if representative.category_hours else 'General Client Work'
        ),
        'candidates': [
            {
                'client_id':   cid,
                'client_name': client_names.get(cid, ''),
                'short_name':  labels.get(cid) or client_names.get(cid, ''),
                'recent':      cid in recent_rank,
            }
            for cid in order
        ],
    }
