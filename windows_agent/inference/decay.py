"""
Linear decay model for evidence and inference results.

Core principle: every piece of evidence has a strength when fresh and
decays linearly to zero over its freshness_window_seconds. The default
window is 15 minutes for most evidence sources.

Decay is computed at read time, not stored. The Evidence object holds
(strength, detected_at, freshness_window_seconds); current_strength() is
called whenever the engine evaluates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .evidence import Evidence, InferenceResult


# =============================================================================
# Evidence-level decay
# =============================================================================

def current_strength(evidence: Evidence, now: Optional[datetime] = None) -> float:
    """
    Return the current effective strength of an evidence item, after linear
    decay from its detected_at timestamp.

    At detected_at:           returns evidence.strength
    At detected_at + window:  returns 0.0
    Linear interpolation in between.
    Past the window:          returns 0.0
    """
    if now is None:
        now = datetime.now(timezone.utc)

    age_seconds = (now - evidence.detected_at).total_seconds()

    if age_seconds <= 0:
        return evidence.strength
    if age_seconds >= evidence.freshness_window_seconds:
        return 0.0

    decay_fraction = age_seconds / evidence.freshness_window_seconds
    return evidence.strength * (1.0 - decay_fraction)


def is_expired(evidence: Evidence, now: Optional[datetime] = None) -> bool:
    """True if the evidence has fully decayed (strength == 0)."""
    return current_strength(evidence, now) <= 0.0


# =============================================================================
# Inference-level decay
# =============================================================================

def apply_decay_to_inference(
    inference: InferenceResult,
    now: Optional[datetime] = None,
) -> InferenceResult:
    """
    Recompute an InferenceResult's confidence based on the current time.

    Used when reading a stored InferenceResult some time after it was first
    computed (e.g., the agent stamped it on a RawEvent 8 minutes ago; what
    is its effective confidence right now?).

    Returns a new InferenceResult; does not mutate the input.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if inference.last_affirming_signal_at is None:
        # No anchor; treat as fully decayed.
        return InferenceResult(
            client_id=None,
            confidence=0.0,
            last_affirming_signal_at=None,
            evidence=inference.evidence,
            decay_function=inference.decay_function,
            disagreement=False,
            candidates=None,
            schema_version=inference.schema_version,
            computed_at=now,
        )

    age_seconds = (now - inference.last_affirming_signal_at).total_seconds()

    # Default freshness window for inference-level decay matches Tier 1/2
    # evidence default (15 min). Could be parameterized if other decay
    # functions are introduced.
    window_seconds = 900  # 15 min

    if age_seconds <= 0:
        new_confidence = inference.confidence
    elif age_seconds >= window_seconds:
        new_confidence = 0.0
    else:
        decay_fraction = age_seconds / window_seconds
        new_confidence = inference.confidence * (1.0 - decay_fraction)

    # If decayed below the floor, drop the client_id; the agent no longer
    # has enough belief to claim a client.
    if new_confidence < 0.4:
        return InferenceResult(
            client_id=None,
            confidence=new_confidence,
            last_affirming_signal_at=inference.last_affirming_signal_at,
            evidence=inference.evidence,
            decay_function=inference.decay_function,
            disagreement=False,
            candidates=None,
            schema_version=inference.schema_version,
            computed_at=now,
        )

    return InferenceResult(
        client_id=inference.client_id,
        confidence=new_confidence,
        last_affirming_signal_at=inference.last_affirming_signal_at,
        evidence=inference.evidence,
        decay_function=inference.decay_function,
        disagreement=inference.disagreement,
        candidates=inference.candidates,
        schema_version=inference.schema_version,
        computed_at=now,
    )
