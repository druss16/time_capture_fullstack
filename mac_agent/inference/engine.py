"""
Inference engine — combines evidence into a single InferenceResult.

Pure function: takes a list of Evidence (positive + anti-evidence mixed)
and returns one InferenceResult. The caller (typically the agent's
on_window_change handler) is responsible for running the collectors and
passing their output here.

Algorithm:
  1. Separate evidence into positive (per-client) and anti-evidence.
  2. For each client, compute combined confidence:
       base = max(strength of evidence pointing to this client)
       bonus = +0.05 per additional Tier 1/2 evidence (max +0.10)
       cap = lowest anti-evidence cap applicable
       final = min(base + bonus, cap)
  3. Pick the client with highest final confidence as best_guess.
  4. If best confidence < 0.4 → return InferenceResult(client_id=None).
  5. If two clients tied within 0.1 → mark disagreement.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional, Dict, Tuple

from .evidence import Evidence, InferenceResult, WindowContext
from .decay import current_strength

logger = logging.getLogger("timetracker.inference.engine")


# =============================================================================
# Anti-evidence caps
# =============================================================================

# When these anti-evidence sources fire, they cap the maximum confidence
# any client can reach. The lowest cap wins.
ANTI_EVIDENCE_CAPS = {
    "os_idle": 0.0,                      # forces confidence to zero
    "generic_browser_tab": 0.5,          # weak signals can't attribute
    "personal_app_foreground": 0.3,      # very strong signals only
    "firm_name_in_title": 0.0,           # routes to Internal, blocks client attribution
                                          # (unless an Internal client_id was also voted for —
                                          # handled separately below)
}

# Score thresholds
CONFIDENCE_FLOOR = 0.4                   # below this → client_id = None
DISAGREEMENT_DELTA = 0.1                 # within this → flag as ambiguous
CORROBORATION_BONUS_PER = 0.05           # per additional Tier 1/2 evidence
CORROBORATION_BONUS_MAX = 0.10           # max total bonus


# =============================================================================
# Main entry point
# =============================================================================

def compute_inference(
    evidence_list: List[Evidence],
    now: Optional[datetime] = None,
) -> InferenceResult:
    """
    Combine the evidence list into a single InferenceResult.

    Pure function — does not mutate inputs. Safe to call from any thread.

    Args:
        evidence_list: Mix of positive and anti-evidence from collectors
        now: Current time for decay calculations (defaults to utcnow())

    Returns:
        InferenceResult with best_guess client_id, confidence, evidence
        trail, and disagreement flag if multiple clients tied.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if not evidence_list:
        return _empty_result(now)

    # Apply current decay to every piece of evidence
    decayed = []
    for e in evidence_list:
        eff = current_strength(e, now)
        if eff <= 0.0:
            continue
        # Create a "live" copy with the decayed strength baked in.
        # We don't mutate the original Evidence.
        decayed.append((e, eff))

    if not decayed:
        return _empty_result(now)

    # Separate positive evidence (has client_id) from anti-evidence
    positive: Dict[int, List[Tuple[Evidence, float]]] = defaultdict(list)
    anti: List[Tuple[Evidence, float]] = []
    for e, eff in decayed:
        if e.is_anti_evidence:
            anti.append((e, eff))
        elif e.client_id is not None:
            positive[e.client_id].append((e, eff))
        # Evidence with no client_id and not anti-evidence: ignore

    # Determine the anti-evidence cap (most restrictive)
    cap_value = 1.0
    cap_source = None
    for e, _eff in anti:
        c = ANTI_EVIDENCE_CAPS.get(e.source, 1.0)
        if c < cap_value:
            cap_value = c
            cap_source = e.source

    # Score each candidate client
    client_scores: Dict[int, Tuple[float, List[Evidence]]] = {}
    for client_id, ev_pairs in positive.items():
        if not ev_pairs:
            continue

        # base = max effective strength
        base = max(eff for _e, eff in ev_pairs)

        # corroboration bonus = +0.05 per ADDITIONAL Tier 1/2 evidence beyond the strongest
        sorted_pairs = sorted(ev_pairs, key=lambda p: p[1], reverse=True)
        tier12_corroborators = sum(
            1 for e, _eff in sorted_pairs[1:]
            if e.tier in (1, 2)
        )
        bonus = min(
            tier12_corroborators * CORROBORATION_BONUS_PER,
            CORROBORATION_BONUS_MAX,
        )

        # Apply anti-evidence cap
        raw = base + bonus
        capped = min(raw, cap_value)

        # Special case: firm_name_in_title routes to Internal positively, so
        # if THIS client is the Internal client voted for by firm_name evidence,
        # the cap doesn't apply (the cap is meant to block CLIENT attribution,
        # not Internal routing).
        firm_voted_for_this_client = any(
            e.source == "firm_name_in_title" and e.client_id == client_id
            for e, _eff in ev_pairs
        )
        if firm_voted_for_this_client and cap_source == "firm_name_in_title":
            capped = raw  # bypass the cap for the firm-name-voted Internal client

        client_scores[client_id] = (
            capped,
            [e for e, _eff in ev_pairs],
        )

    if not client_scores:
        # No positive evidence after caps — return empty
        return _empty_result(now, evidence=[e for e, _eff in decayed])

    # Pick best
    ranked = sorted(
        client_scores.items(),
        key=lambda kv: kv[1][0],
        reverse=True,
    )
    best_client_id, (best_confidence, best_evidence) = ranked[0]

    # Below floor → no client
    if best_confidence < CONFIDENCE_FLOOR:
        return _empty_result(
            now,
            evidence=[e for e, _eff in decayed],
            confidence_below_floor=best_confidence,
        )

    # Check for disagreement (within DISAGREEMENT_DELTA of the top)
    candidates = []
    disagreement = False
    if len(ranked) > 1:
        for cid, (conf, _evs) in ranked[1:]:
            if best_confidence - conf <= DISAGREEMENT_DELTA:
                candidates.append({"client_id": cid, "confidence": conf})
                disagreement = True
        if disagreement:
            # Include the top in candidates list for completeness
            candidates.insert(0, {
                "client_id": best_client_id,
                "confidence": best_confidence,
            })

    # last_affirming_signal_at = most recent detected_at among contributing
    # Tier 1/2/3 evidence for the chosen client
    last_affirming = max(
        (e.detected_at for e in best_evidence),
        default=now,
    )

    return InferenceResult(
        client_id=best_client_id,
        confidence=best_confidence,
        last_affirming_signal_at=last_affirming,
        evidence=best_evidence,
        disagreement=disagreement,
        candidates=candidates if disagreement else None,
        computed_at=now,
    )


def _empty_result(
    now: datetime,
    evidence: Optional[List[Evidence]] = None,
    confidence_below_floor: float = 0.0,
) -> InferenceResult:
    """Return an InferenceResult with no client (low confidence or no evidence)."""
    return InferenceResult(
        client_id=None,
        confidence=confidence_below_floor,
        last_affirming_signal_at=None,
        evidence=evidence or [],
        disagreement=False,
        candidates=None,
        computed_at=now,
    )


# =============================================================================
# Convenience: full pipeline (collect + compute) in one call
# =============================================================================

def infer_client(
    ctx: WindowContext,
    clients: List[dict],
    learned_rules=None,
    is_idle: bool = False,
    firm_name_patterns: Optional[List[str]] = None,
    internal_client_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> InferenceResult:
    """
    Full inference pipeline: collect all evidence, then compute the result.

    This is the main entry point the agent calls from on_window_change().

    Args:
        ctx: WindowContext snapshot
        clients: list of {id, name, aliases, associated_domains?} dicts
        learned_rules: LearnedRules instance or None
        is_idle: OS-reported user idle state
        firm_name_patterns: list of firm name strings (e.g., ['T.L. Wall Accounting'])
        internal_client_id: client_id of "Internal - Tax" for firm-name routing
        now: timestamp for decay (defaults to utcnow)

    Returns:
        InferenceResult ready to be stamped on RawEvent.inference
    """
    from .collectors import collect_all_evidence

    evidence_list = collect_all_evidence(
        ctx=ctx,
        clients=clients,
        learned_rules=learned_rules,
        is_idle=is_idle,
        firm_name_patterns=firm_name_patterns,
        internal_client_id=internal_client_id,
    )
    return compute_inference(evidence_list, now=now)
