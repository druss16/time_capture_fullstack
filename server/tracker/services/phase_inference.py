"""
Phase inference — reading how far along a job is from what's on screen.

This is the piece that makes "65% of budget, 35% done" answerable without
asking anyone. Hours can never tell you progress. But tax work has an
observable order to it, and the agent already captures the app and the window
title for every minute:

    gathering   scanning, the portal, Outlook, the organizer
    preparing   input/interview screens in the tax software, the books
    review      diagnostics, prior-year comparison, review notes
    assembly    print, assembly, 8879, e-file transmission
    done        accepted

So progress can be captured the same way time is: passively.

SHADOW BY DEFAULT
-----------------
Nothing here overrides what a preparer said. Inference writes to
`Engagement.inferred_phase` and never to `Engagement.phase`. The point of the
shadow period is to find out how often the guess matches the preparer's own
answer before anyone bills on it — `agreement_report()` measures exactly that.

Phases are monotonic: you don't un-prepare a return. So the inferred phase is
the FURTHEST phase with real evidence, not the most common one — a preparer who
spends four hours in input screens and twenty minutes in diagnostics is in
review, and the twenty minutes is the informative part.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from tracker.models import Block, Engagement, Organization
from tracker.utils.db_iter import keyset_iter

logger = logging.getLogger(__name__)

# How far back to read activity when deciding the current phase.
LOOKBACK_DAYS = 21
# A phase needs at least this much evidence to count as reached.
MIN_PHASE_MINUTES = 5
MIN_PHASE_SHARE = 0.05

# Title fragments → phase. Matched case-insensitively against the window title
# (and app name) of the engagement's blocks. Ordered least→most advanced within
# each phase; the ladder order is what matters, not the order here.
#
# These are deliberately conservative: a fragment that fires on the wrong phase
# is worse than one that never fires, because a missing signal just means "no
# opinion" while a wrong one moves a number the firm might bill on.
PHASE_SIGNALS: dict[str, tuple[str, ...]] = {
    "gathering": (
        "organizer", "source document", "source docs", "scan", "scanner",
        "sharefile", "smartvault", "client portal", "secureshare",
        "engagement letter", "prior year file", "request list",
    ),
    "preparing": (
        "input", "interview", "worksheet", "data entry", "depreciation",
        "schedule c", "schedule e", "k-1 entry", "trial balance",
        "reconcile", "reconciliation", "journal entry", "adjusting entr",
    ),
    "review": (
        "diagnostic", "review", "compare", "comparison", "prior year comp",
        "check return", "error check", "tick mark", "reviewer note",
        "critical diagnostic",
    ),
    "assembly": (
        "print", "assembly", "assemble", "8879", "signature", "e-file",
        "efile", "ef center", "transmit", "electronic filing", "client copy",
        "deliver",
    ),
    "done": (
        "accepted", "e-file accepted", "acknowledgement", "acknowledgment",
        "filed",
    ),
}

# Compiled once. Word-ish boundaries so "print" doesn't fire on "footprint".
_COMPILED: dict[str, re.Pattern] = {
    phase: re.compile(
        "|".join(rf"(?<![a-z]){re.escape(frag)}" for frag in frags),
        re.IGNORECASE,
    )
    for phase, frags in PHASE_SIGNALS.items()
}


def phase_for_text(text: str) -> str | None:
    """Most advanced phase this one title suggests, or None."""
    if not text:
        return None
    hit = None
    for phase in ("gathering", "preparing", "review", "assembly", "done"):
        if _COMPILED[phase].search(text):
            hit = phase  # later phases overwrite earlier ones
    return hit


def infer_phase(engagement: Engagement, *, lookback_days: int = LOOKBACK_DAYS
                ) -> tuple[str | None, float, dict]:
    """Return (phase, confidence 0..1, signal breakdown) for an engagement.

    Confidence is the share of evidenced minutes sitting at or beyond the
    chosen phase — low confidence means the activity is scattered and the
    guess is weak.
    """
    # Anchor the window on the job's OWN most recent activity, not on today.
    # A return last touched in March is still sitting in whatever phase it
    # reached; anchoring on today would report "no opinion" for every job that
    # went quiet, which is exactly the set someone needs to chase.
    latest = (
        Block.objects.filter(engagement=engagement)
        .order_by("-day").values_list("day", flat=True).first()
    )
    if latest is None:
        return None, 0.0, {}
    since = latest - timedelta(days=lookback_days)
    blocks = (
        Block.objects.filter(engagement=engagement, day__gte=since)
        .only("minutes", "window_title", "title", "app_name")
    )

    minutes_by_phase: dict[str, float] = defaultdict(float)
    evidenced = 0.0
    for b in blocks:
        text = " ".join(filter(None, [b.window_title, b.title, b.app_name]))
        phase = phase_for_text(text)
        if not phase:
            continue
        mins = float(b.minutes or 0)
        minutes_by_phase[phase] += mins
        evidenced += mins

    if evidenced <= 0:
        return None, 0.0, {}

    ladder = [key for key, _label, _w in engagement.ladder]
    # Furthest phase with real evidence, not the loudest one.
    chosen = None
    for phase in ladder:
        mins = minutes_by_phase.get(phase, 0.0)
        if mins >= MIN_PHASE_MINUTES and mins / evidenced >= MIN_PHASE_SHARE:
            chosen = phase
    if chosen is None:
        return None, 0.0, dict(minutes_by_phase)

    idx = ladder.index(chosen)
    at_or_beyond = sum(minutes_by_phase.get(p, 0.0) for p in ladder[idx:])
    confidence = round(min(1.0, at_or_beyond / evidenced), 3)
    return chosen, confidence, {k: round(v, 1) for k, v in minutes_by_phase.items()}


def refresh_inferred_phases(org: Organization, *, dry_run: bool = True) -> dict:
    """Re-infer the phase of every open engagement. Shadow only — never sets
    `phase`, only `inferred_phase`."""
    now = timezone.now()
    counts: dict[str, int] = defaultdict(int)

    for eng in keyset_iter(Engagement.objects.filter(org=org, status="open"), 200):
        phase, confidence, signals = infer_phase(eng)
        if phase is None:
            counts["no_signal"] += 1
            continue
        counts[phase] += 1
        if eng.phase and eng.phase == phase:
            counts["agrees_with_user"] += 1
        elif eng.phase:
            counts["disagrees_with_user"] += 1

        if dry_run:
            continue
        eng.inferred_phase = phase
        eng.inferred_phase_confidence = confidence
        eng.inferred_phase_at = now
        eng.inferred_phase_signals = signals
        eng.save(update_fields=[
            "inferred_phase", "inferred_phase_confidence", "inferred_phase_at",
            "inferred_phase_signals", "updated_at",
        ])

    return {"org_id": org.id, "dry_run": dry_run, "counts": dict(counts)}


def agreement_report(org: Organization) -> dict:
    """How often does the inferred phase match what a preparer actually said?

    This is the gate on ever trusting inference. Read it before considering
    making the inferred phase authoritative for engagements nobody has touched.
    """
    qs = Engagement.objects.filter(org=org).exclude(phase="").exclude(inferred_phase="")
    total = exact = adjacent = 0
    confusion: dict[str, int] = defaultdict(int)

    for eng in keyset_iter(qs, 200):
        ladder = [k for k, _l, _w in eng.ladder]
        if eng.phase not in ladder or eng.inferred_phase not in ladder:
            continue
        total += 1
        gap = ladder.index(eng.inferred_phase) - ladder.index(eng.phase)
        if gap == 0:
            exact += 1
        elif abs(gap) == 1:
            adjacent += 1
        confusion[f"{eng.phase}->{eng.inferred_phase}"] += 1

    return {
        "org_id": org.id,
        "compared": total,
        "exact_match": exact,
        "within_one_phase": exact + adjacent,
        "exact_pct": round(exact / total * 100, 1) if total else None,
        "within_one_pct": round((exact + adjacent) / total * 100, 1) if total else None,
        "confusion": dict(sorted(confusion.items(), key=lambda kv: -kv[1])[:15]),
    }
