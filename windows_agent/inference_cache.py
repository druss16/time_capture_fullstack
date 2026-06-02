"""
windows_agent/inference_cache.py

Single source of truth for "what client is the user working on right now"
post-v1.4.0. The state machine in AIClientSwitcher and WidgetStateTracker
no longer holds authoritative client state — they read from here.

Two state stores, both module-level, both thread-safe:

  1. Last inference result — set by the event handler after computing
     inference. Read by the tray, the floating widget, and anything else
     that needs to know the current client. Decay is applied on read so
     callers always see the current effective confidence.

  2. Manual override — set when the user picks a client in the tray.
     Becomes Tier 1 evidence (strength 0.85) at the next event evaluation
     via WindowContext.manual_override. Expires after 15 minutes (same
     freshness window as other evidence).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional


# =============================================================================
# Inference cache — what the agent currently believes
# =============================================================================

_inference_lock = threading.Lock()
_inference_dict: Optional[dict] = None       # InferenceResult.to_dict()
_inference_client_name: Optional[str] = None  # cached at compute time


def update_inference_cache(
    inference_dict: dict,
    client_name: Optional[str],
) -> None:
    """
    Called by main.py's event handler after computing inference.

    inference_dict is the serialized InferenceResult (from .to_dict()).
    client_name is looked up at compute time so the tray doesn't have to
    scan the client list on every read.
    """
    global _inference_dict, _inference_client_name
    with _inference_lock:
        _inference_dict = inference_dict
        _inference_client_name = client_name


def get_current_inference() -> Optional[dict]:
    """
    Return the most recent inference result with decay applied to the
    confidence value. Returns None when:
      - No inference has been computed yet
      - The result has decayed below the action floor (0.4)
      - The result had no client_id to begin with

    Shape of returned dict:
      {
        'client_id': int,
        'client_name': str,
        'confidence': float,       # post-decay
        'evidence_sources': [str], # source names from the original evidence
        'last_affirming_signal_at': str (iso8601),
      }

    Tray, floating widget, and any other consumer call this. They never
    need to think about decay — it's handled here.
    """
    # Lazy import to avoid a circular import at module load.
    # Path-robust: works whether cwd is windows_agent/ (agent runtime)
    # or the repo root (tests, scripts).
    try:
        from inference import apply_decay_to_inference, InferenceResult
    except ImportError:
        from windows_agent.inference import apply_decay_to_inference, InferenceResult

    with _inference_lock:
        if not _inference_dict:
            return None
        last_at_str = _inference_dict.get('last_affirming_signal_at')
        if not last_at_str:
            return None
        try:
            last_at = datetime.fromisoformat(last_at_str)
        except Exception:
            return None

        # Build a minimal InferenceResult so decay logic can run.
        synthetic = InferenceResult(
            client_id=_inference_dict.get('client_id'),
            confidence=_inference_dict.get('confidence', 0.0) or 0.0,
            last_affirming_signal_at=last_at,
            evidence=[],  # not needed for decay
        )
        decayed = apply_decay_to_inference(synthetic)
        if decayed.is_stale or not decayed.has_client:
            return None

        return {
            'client_id': decayed.client_id,
            'client_name': _inference_client_name,
            'confidence': decayed.confidence,
            'evidence_sources': [
                e.get('source') for e in _inference_dict.get('evidence', [])
            ],
            'last_affirming_signal_at': last_at_str,
        }


def get_current_widget_state() -> str:
    """
    Translate current inference confidence into the widget's color state.
    Replaces WidgetStateTracker's separate state machine.

      confidence >= 0.85   -> 'committed' (green dot)
      confidence >= 0.60   -> 'proposed'  (yellow dot)
      confidence >= 0.40   -> 'captured'  (gray dot)
      no client / stale    -> 'no_client' (red or empty)
    """
    inf = get_current_inference()
    if not inf or not inf.get('client_id'):
        return 'no_client'
    conf = inf.get('confidence', 0.0) or 0.0
    if conf >= 0.85:
        return 'committed'
    if conf >= 0.60:
        return 'proposed'
    return 'captured'


# =============================================================================
# Manual override — user picked a client in the tray
# =============================================================================

_override_lock = threading.Lock()
_override: Optional[dict] = None


def set_manual_override(
    client_id: Optional[int],
    client_name: Optional[str],
) -> None:
    """
    Called when the user manually picks a client in the tray.

    Two things happen:
      1. The override is recorded so the next event-driven inference
         picks it up as Tier 1 evidence (strength 0.85, 15-min decay).
      2. A synthetic inference is pushed to the cache immediately so
         the tray, widget, and any other reader reflect the user's
         choice without waiting for the next event capture.

    The synthetic inference is short-lived — the next real inference
    computation will overwrite it. If the user's window context
    corroborates the override (e.g., they really are in Holly Corbett's
    QB file), the real inference will produce equal-or-higher confidence.

    Pass client_id=None to clear the override (e.g., user picks
    'No Client').
    """
    global _override
    now = datetime.now(timezone.utc)

    with _override_lock:
        if client_id is None:
            _override = None
        else:
            _override = {
                'client_id': client_id,
                'client_name': client_name,
                'set_at': now,
                'set_by': 'user',
            }

    # Push a synthetic inference so consumers see the override right away.
    # Without this, the tray would show stale state for 5-30s until the
    # next event-driven inference picks up the override as evidence.
    if client_id is None:
        # User cleared their override — push empty inference. Next event
        # will compute correctly from window evidence (if any).
        update_inference_cache({}, None)
    else:
        synthetic = {
            'client_id': client_id,
            'confidence': 0.85,
            'last_affirming_signal_at': now.isoformat(),
            'evidence': [{
                'source': 'manual_user_override',
                'strength': 0.85,
                'detected_at': now.isoformat(),
                'client_id': client_id,
                'freshness_window_seconds': 900,
                'detail': {'set_by': 'user'},
            }],
            'disagreement': False,
            'candidates': None,
            'schema_version': '1.0',
            'computed_at': now.isoformat(),
        }
        update_inference_cache(synthetic, client_name)


def get_manual_override() -> Optional[dict]:
    """
    Get the current manual override for use by the event handler.

    Returns the override dict if it exists and is fresh (< 15 min old).
    Returns None if no override is set or it has aged out. Callers do
    not need to check expiration themselves.

    The 15-min cap matches the standard evidence freshness window — the
    engine's decay model handles the actual confidence drop within that
    window.
    """
    with _override_lock:
        if not _override:
            return None
        age = (
            datetime.now(timezone.utc) - _override['set_at']
        ).total_seconds()
        if age > 900:  # 15 min
            return None
        return dict(_override)  # return a copy


def clear_manual_override() -> None:
    """
    Explicit clear — delegates to set_manual_override(None, None) so the
    inference cache is also reset for immediate UI reflection.
    """
    set_manual_override(None, None)


# =============================================================================
# Debug / introspection
# =============================================================================

def snapshot() -> dict:
    """For debug logging — read everything atomically."""
    with _inference_lock:
        inf = dict(_inference_dict) if _inference_dict else None
        name = _inference_client_name
    with _override_lock:
        ov = dict(_override) if _override else None
    return {
        'inference': inf,
        'client_name': name,
        'manual_override': ov,
    }
