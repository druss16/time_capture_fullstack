"""
tracker/services/sandwich_correlation.py

Stage Sandwich — temporal fallback attribution for the classification pipeline.

THE IDEA
--------
When a block has NO client signal but is surrounded in time by blocks
attributed to the SAME client, attribute the middle block to that client too.

    09:00–09:30  Excel — TungDNguyen_Q3.xlsx        → Tung D Nguyen (strong)
    09:31–09:38  Outlook — RE: returns finalized     → no client  ← sandwiched
    09:39–10:15  QuickBooks — Tung D Nguyen          → Tung D Nguyen (strong)

The middle block is "the meat" between two same-client slices of bread. A CPA
batches into client sessions; a short email/PDF/research block between two
same-client work blocks is almost always the same client's work.

WHERE THIS RUNS
---------------
Called from ClassificationService._finalize_decision() ONLY when no real
evidence produced a client (decision.client_id is None), AFTER the
moderate>=2 auto-commit check and BEFORE FIX 6's non-billable default.
Precedence: real evidence (Stages 0-10) > sandwich (temporal) > safe default.

Sandwich NEVER auto-commits. Its strongest output is 0.70, and the caller
forces recommended_state='proposed' regardless. A human confirms.

SAFETY GATES (return None — no signal emitted)
----------------------------------------------
  - Target block is idle / shell window (Program Manager, etc.)
  - Target block is a browser block (news/personal-browsing inheritance magnet)
  - Target block is too long (> MAX_SANDWICH_MINUTES) — likely lunch, not a
    quick context switch
  - No same-day committed/proposed bread blocks on BOTH sides
  - The two sides disagree on client
  - Cross-day (handled implicitly by same-day query)

STRENGTH TIERS
--------------
  0.70  both sides same client, tight gaps (<= GAP_TIGHT_MINUTES each side)
  0.55  same client but one side gap > GAP_TIGHT_MINUTES
  0.40  same client but bread blocks themselves are very brief (< MIN_BREAD)
        — below the 0.65 caller threshold, so effectively "no sandwich"

The caller only acts on strength >= 0.65, so only the 0.70 tier attributes.
The lower tiers are emitted for audit/telemetry visibility but won't fire.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional, List

from django.utils import timezone

logger = logging.getLogger('timetracker.classification')

# ── Tunables (see brief §"Sandwich strength tuning — the levers") ────────────
WINDOW_MINUTES = 30          # look this far before B.start and after B.end
GAP_TIGHT_MINUTES = 15       # gap on each side at or under this = strong tier
MIN_BREAD_MINUTES = 5        # bread blocks shorter than this are too weak
MAX_SANDWICH_MINUTES = 25    # target blocks longer than this aren't quick switches
MAX_IDLE_FRACTION = 0.80     # target >80% idle is not active work — skip

STRENGTH_STRONG = 0.70
STRENGTH_MODERATE = 0.55
STRENGTH_WEAK = 0.40

BROWSER_APPS = {
    'msedge', 'chrome', 'firefox', 'brave',
    'safari', 'opera', 'iexplore',
}


def _is_idle_block(block) -> bool:
    """Mirror of ClassificationService._stage_8 idle detection.

    Kept in sync deliberately. If the service extracts a shared
    _is_idle_block staticmethod, swap this for a call to it.
    """
    title_lower = (getattr(block, 'window_title', '') or
                   getattr(block, 'title', '') or '').strip().lower()
    app_lower = (getattr(block, 'app_name', '') or '').strip().lower()
    return (
        title_lower == 'idle/uncategorized'
        or title_lower == 'idle'
        or app_lower == 'idle'
        or title_lower == 'program manager'
        or title_lower == 'new notification'
    )


def _is_browser_block(block) -> bool:
    return (getattr(block, 'app_name', '') or '').strip().lower() in BROWSER_APPS


def _idle_fraction(block) -> float:
    """Best-effort idle fraction for the target block.

    Blocks may carry idle metrics under a few possible field names depending
    on agent version. We check the common ones and fall back to 0.0 (treat as
    active) when none are present — better to allow a sandwich than to silently
    suppress every block on a schema we don't recognize.
    """
    minutes = getattr(block, 'minutes', None) or 0
    if minutes <= 0:
        return 0.0
    for attr in ('idle_minutes', 'idle_seconds', 'idle_time'):
        val = getattr(block, attr, None)
        if val is None:
            continue
        idle_min = val / 60.0 if attr == 'idle_seconds' else float(val)
        return max(0.0, min(1.0, idle_min / minutes))
    return 0.0


def find_sandwich_attribution(block, user, org) -> Optional['Signal']:
    """
    Return a sandwich_correlation Signal if `block` is sandwiched between
    same-client work, else None.

    Args:
        block: the target Block being classified (client_id is None at call site)
        user:  the block's user
        org:   the block's organization

    The Signal mirrors the shape produced by the pipeline stages:
        type='sandwich_correlation', strength in {0.40, 0.55, 0.70},
        detail={'client_id', 'client_name', 'is_billable',
                'bread_before_id', 'bread_after_id',
                'gap_before_min', 'gap_after_min', 'tier'}
    """
    # Import here to avoid a circular import at module load
    # (classification_service imports this module lazily too).
    from tracker.services.classification_service import Signal
    from tracker.models import Block

    if not getattr(block, 'start', None) or not getattr(block, 'end', None):
        return None

    # ── Hard gates on the TARGET block ───────────────────────────────────────
    if _is_idle_block(block):
        return None

    if _is_browser_block(block):
        # Browser blocks are the inheritance-bug magnet. A news break between
        # two client blocks must not be attributed to the client. Stage 8
        # already hardens against this for stickiness; sandwich must too.
        return None

    duration_min = getattr(block, 'minutes', None) or 0
    if duration_min > MAX_SANDWICH_MINUTES:
        # Too long to be a quick context switch — likely lunch or a real
        # standalone activity. Hard gate, not a strength penalty.
        return None

    if _idle_fraction(block) > MAX_IDLE_FRACTION:
        return None

    # ── Find candidate bread blocks (same user, same day, ±window) ───────────
    day_start = block.start.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    win_start = block.start - timedelta(minutes=WINDOW_MINUTES)
    win_end = block.end + timedelta(minutes=WINDOW_MINUTES)

    bread_qs = (
        Block.objects
        .filter(
            user=user,
            classification_state__in=('committed', 'proposed'),
            client_id__isnull=False,
            is_billable=True,
            # same-day clamp (no cross-midnight sandwiches)
            start__gte=day_start,
            start__lt=day_end,
        )
        .exclude(pk=getattr(block, 'pk', None))
        .order_by('start')
    )

    before_candidates: List = []
    after_candidates: List = []

    for b in bread_qs:
        if not b.start or not b.end:
            continue
        b_minutes = b.minutes or 0
        if b_minutes < MIN_BREAD_MINUTES:
            continue  # bread too brief to be trustworthy evidence
        if _is_idle_block(b):
            continue
        # "before" = ends at or before target start, within the window
        if b.end <= block.start and b.end >= win_start:
            before_candidates.append(b)
        # "after" = starts at or after target end, within the window
        elif b.start >= block.end and b.start <= win_end:
            after_candidates.append(b)

    # Require true sandwich: at least one bread block on EACH side.
    if not before_candidates or not after_candidates:
        return None

    # Closest bread on each side (proximity-ordered)
    bread_before = max(before_candidates, key=lambda b: b.end)    # latest-ending before
    bread_after = min(after_candidates, key=lambda b: b.start)    # earliest-starting after

    # ── Both sides must agree on client ──────────────────────────────────────
    if bread_before.client_id != bread_after.client_id:
        return None  # one side Client X, other side Client Y → no sandwich

    client_id = bread_before.client_id

    # ── Gaps drive the strength tier ─────────────────────────────────────────
    gap_before_min = (block.start - bread_before.end).total_seconds() / 60.0
    gap_after_min = (bread_after.start - block.end).total_seconds() / 60.0

    # Bread-billability propagation: only mark billable if BOTH bread blocks
    # agree on billable. (They're both is_billable=True per the query, so this
    # is True here — but kept explicit so a future query relaxation is safe.)
    both_billable = bool(bread_before.is_billable and bread_after.is_billable)

    # Strength tiering
    if gap_before_min <= GAP_TIGHT_MINUTES and gap_after_min <= GAP_TIGHT_MINUTES:
        strength = STRENGTH_STRONG
        tier = 'strong'
    else:
        strength = STRENGTH_MODERATE
        tier = 'moderate'

    # Resolve client name for evidence text (best-effort)
    client_name = ''
    try:
        from tracker.models import Client
        c = Client.objects.filter(pk=client_id).only('name').first()
        if c:
            client_name = c.name
    except Exception:
        pass

    evidence = (
        f"Block sandwiched between {client_name or f'client {client_id}'} work "
        f"({_fmt(bread_before.start)}-{_fmt(bread_before.end)} and "
        f"{_fmt(bread_after.start)}-{_fmt(bread_after.end)}, "
        f"gap {gap_before_min:.0f}min before / {gap_after_min:.0f}min after)"
    )

    logger.info(
        f"[SANDWICH] Block {getattr(block, 'pk', '?')}: {tier} sandwich "
        f"@ {strength:.2f} → client {client_id} ({client_name}); "
        f"bread {bread_before.pk}/{bread_after.pk}, "
        f"gaps {gap_before_min:.0f}/{gap_after_min:.0f}min"
    )

    return Signal(
        type='sandwich_correlation',
        strength=strength,
        evidence=evidence,
        detail={
            'client_id':       client_id,
            'client_name':     client_name,
            'is_billable':     both_billable,
            'bread_before_id': bread_before.pk,
            'bread_after_id':  bread_after.pk,
            'gap_before_min':  round(gap_before_min, 1),
            'gap_after_min':   round(gap_after_min, 1),
            'tier':            tier,
        },
    )


def _fmt(dt) -> str:
    """HH:MM in the dt's own tz — purely for human-readable evidence."""
    try:
        return timezone.localtime(dt).strftime('%H:%M')
    except Exception:
        try:
            return dt.strftime('%H:%M')
        except Exception:
            return '??:??'