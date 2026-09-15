"""
tracking_health.py — Progress-based watchdog heartbeat + idle classification

Drop-in companion to main.py.

HEARTBEAT
---------
The tracking loop calls `progress_tick()` every iteration.  The watchdog
calls `is_making_progress(timeout_s)` — if the tick counter hasn't moved
in `timeout_s` seconds the loop is considered frozen (thread alive but stuck).

IDLE CLASSIFICATION
--------------------
Call `record_window_change()` on every genuine focus change and
`record_idle_enter()` / `record_idle_exit()` at those transitions.

`classify_idle(idle_seconds)` returns one of:

    IdleKind.INTENTIONAL   — user deliberately stopped (normal screen-lock,
                             end of day, predictable lead-up)
    IdleKind.UNINTENTIONAL — loop froze, machine slept, OS hiccup; the idle
                             gap is not a real work absence

Decision logic:
  1. Was there a recent, normal window-change right before idle started?
     Yes → intentional.
  2. Did the loop clock show a large gap (> FREEZE_GAP_S) just before idle?
     Yes → unintentional (loop was frozen).
  3. Is the idle duration way longer than MOUSE_IDLE_PAUSE_S would explain?
     (i.e. we're "discovering" a very long idle retroactively)
     Yes → unintentional.
  4. Does the idle span a wake event (power cycle)?
     Yes → unintentional.
  5. Default → intentional (trust the system).
"""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ──────────────────────────────────────────────
# Tunables (override after import if needed)
# ──────────────────────────────────────────────

# How long without a progress tick before declaring the loop frozen
PROGRESS_TIMEOUT_S: int = 60          # 1 minute

# A gap between consecutive loop iterations larger than this is a freeze
FREEZE_GAP_S: float = 45.0

# If idle is discovered to be longer than this multiple of the configured
# mouse-idle-pause threshold it's suspicious (likely a retroactive gap)
RETROACTIVE_IDLE_MULTIPLIER: float = 3.0

# Window-change recency: if the last real focus-change was within this many
# seconds of idle entry, the idle is considered intentional
NORMAL_LEAD_IN_S: float = 30.0


# ──────────────────────────────────────────────
# Idle classification result
# ──────────────────────────────────────────────

class IdleKind(str, Enum):
    INTENTIONAL   = "intentional"    # Normal user absence — track it
    UNINTENTIONAL = "unintentional"  # Loop/OS fault — discard or cap it


@dataclass
class IdleVerdict:
    kind: IdleKind
    reason: str                      # Human-readable explanation for logging
    confidence: float = 1.0          # 0–1; <0.7 means the call was ambiguous


# ──────────────────────────────────────────────
# Internal state  (module-level singletons)
# ──────────────────────────────────────────────

@dataclass
class _ProgressState:
    tick:            int   = 0          # Monotonically increasing
    last_tick_time:  float = 0.0        # wall time of last progress_tick()
    last_iter_time:  float = 0.0        # wall time of PREVIOUS iteration (gap calc)
    last_gap:        float = 0.0        # gap between last two iterations
    lock: threading.Lock = field(default_factory=threading.Lock)

    # Idle tracking
    idle_entered_at:      float = 0.0   # wall time we entered idle
    last_window_change:   float = 0.0   # wall time of last real focus event
    last_freeze_at:       float = 0.0   # wall time of last detected freeze gap
    last_wake_at:         float = 0.0   # wall time of last power-wake event

    # Running stats (useful for diagnostics)
    total_ticks:     int   = 0
    freeze_count:    int   = 0          # How many freeze gaps detected this session
    longest_gap:     float = 0.0

    last_unintentional_log: float = 0.0  # dedup guard


_state = _ProgressState()


# ──────────────────────────────────────────────
# Heartbeat API  (call from tracking loop)
# ──────────────────────────────────────────────

def progress_tick() -> int:
    """
    Call once per tracking-loop iteration (before the sleep).
    Returns the new tick count.

    Also computes the inter-iteration gap so freeze detection is automatic.
    """
    now = time.time()
    with _state.lock:
        _state.total_ticks += 1
        _state.tick += 1

        if _state.last_tick_time > 0:
            gap = now - _state.last_tick_time
            _state.last_gap = gap
            if gap > _state.longest_gap:
                _state.longest_gap = gap
            if gap > FREEZE_GAP_S:
                _state.freeze_count += 1
                _state.last_freeze_at = now  # Record when freeze was *detected*

        _state.last_iter_time = _state.last_tick_time
        _state.last_tick_time = now
        return _state.tick


def is_making_progress(timeout_s: int = PROGRESS_TIMEOUT_S) -> bool:
    """
    Returns True if the loop ticked within the last `timeout_s` seconds.
    Returns False (frozen) otherwise.

    Call from the watchdog thread.
    """
    with _state.lock:
        if _state.last_tick_time == 0:
            return True  # Never started yet — not frozen, just initialising
        return (time.time() - _state.last_tick_time) < timeout_s


def get_loop_stats() -> dict:
    """Snapshot of loop health for logging / remote error reports."""
    with _state.lock:
        return {
            "tick":            _state.tick,
            "total_ticks":     _state.total_ticks,
            "last_tick_age_s": round(time.time() - _state.last_tick_time, 1),
            "last_gap_s":      round(_state.last_gap, 1),
            "longest_gap_s":   round(_state.longest_gap, 1),
            "freeze_count":    _state.freeze_count,
        }


# ──────────────────────────────────────────────
# Idle-classification API  (call from tracking loop)
# ──────────────────────────────────────────────

def record_window_change():
    """
    Call every time sig != current_sig (genuine focus change, not idle).
    This is the "normal lead-in" signal used by classify_idle.
    """
    with _state.lock:
        _state.last_window_change = time.time()


def record_idle_enter():
    """Call at the moment current_sig transitions to IDLE_SIG."""
    with _state.lock:
        _state.idle_entered_at = time.time()


def record_idle_exit():
    """Call when idle ends (user comes back)."""
    with _state.lock:
        _state.idle_entered_at = 0.0


def record_wake_event():
    """Call from register_power_notifications → _on_wake()."""
    with _state.lock:
        _state.last_wake_at = time.time()


def classify_idle(
    idle_seconds: float,
    mouse_idle_pause_s: int,
) -> IdleVerdict:
    """
    Decide whether the current idle period is intentional or unintentional.

    Parameters
    ----------
    idle_seconds       : seconds since last mouse/keyboard input
                         (from mouse_idle_seconds())
    mouse_idle_pause_s : configured MOUSE_IDLE_PAUSE_S threshold

    Returns
    -------
    IdleVerdict
    """
    now = time.time()

    with _state.lock:
        entered_at        = _state.idle_entered_at
        last_window_chg   = _state.last_window_change
        last_freeze       = _state.last_freeze_at
        last_wake         = _state.last_wake_at
        last_gap          = _state.last_gap

    # ── Guard: no idle entry recorded yet ──────────────────────────────────
    if entered_at == 0:
        return IdleVerdict(
            IdleKind.INTENTIONAL,
            "no idle entry recorded — assuming intentional",
            confidence=0.5,
        )

    idle_wall = now - entered_at          # how long we've been in idle state

    # ── Rule 1: FREEZE GAP right before idle ───────────────────────────────
    # If the loop had a large gap (freeze) in the seconds leading up to idle
    # entry, the "idle" is really an undetected freeze.
    if last_freeze > 0:
        freeze_age = entered_at - last_freeze  # negative = freeze happened during idle
        if -5 < freeze_age < FREEZE_GAP_S * 2:
            return IdleVerdict(
                IdleKind.UNINTENTIONAL,
                f"loop freeze detected {freeze_age:.0f}s relative to idle entry "
                f"(gap={last_gap:.0f}s)",
                confidence=0.95,
            )

    # ── Rule 2: WAKE EVENT spans the idle period ────────────────────────────
    if last_wake > 0 and entered_at < last_wake < now:
        return IdleVerdict(
            IdleKind.UNINTENTIONAL,
            f"power-wake event occurred during idle (wake={now - last_wake:.0f}s ago)",
            confidence=0.98,
        )

    # ── Rule 3: RETROACTIVE idle — discovered gap much longer than threshold ─
    # If the idle_seconds reading is >> MOUSE_IDLE_PAUSE_S, the user was away
    # for a long time before the loop even detected it (e.g. Modern Standby).
    # ── Rule 3: RETROACTIVE idle ──
    retroactive_threshold = mouse_idle_pause_s * RETROACTIVE_IDLE_MULTIPLIER
    if idle_seconds > retroactive_threshold:
        now_t = time.time()
        with _state.lock:
            last_log = _state.last_unintentional_log
            if now_t - last_log > 5:
                _state.last_unintentional_log = now_t
                should_log = True
            else:
                should_log = False

        return IdleVerdict(
            IdleKind.UNINTENTIONAL,
            f"retroactive idle: mouse_idle={idle_seconds:.0f}s >> "
            f"{retroactive_threshold:.0f}s threshold" if should_log else "retroactive idle (suppressed)",
            confidence=0.85,
        )

    # ── Rule 4: NORMAL LEAD-IN — recent window change before idle entry ─────
    if last_window_chg > 0:
        lead_in_age = entered_at - last_window_chg
        if 0 <= lead_in_age <= NORMAL_LEAD_IN_S:
            return IdleVerdict(
                IdleKind.INTENTIONAL,
                f"normal lead-in: last window-change {lead_in_age:.0f}s before idle",
                confidence=0.9,
            )

    # ── Rule 5: Very long wall-clock idle with no freeze/wake signal ────────
    # This catches legitimate long absences (lunch, end of day).
    if idle_wall > 3600:
        return IdleVerdict(
            IdleKind.INTENTIONAL,
            f"long intentional absence: idle for {idle_wall / 60:.0f} min",
            confidence=0.8,
        )

    # ── Default ─────────────────────────────────────────────────────────────
    return IdleVerdict(
        IdleKind.INTENTIONAL,
        "default: no freeze/wake signal detected",
        confidence=0.6,
    )


# ──────────────────────────────────────────────
# Watchdog helper  (call from watchdog.py)
# ──────────────────────────────────────────────

def watchdog_check(
    timeout_s: int = PROGRESS_TIMEOUT_S,
    log_fn=print,
    report_fn=None,
) -> bool:
    """
    Returns True if the loop is healthy, False if it's frozen.

    Designed to be called from your existing watchdog thread every ~30s.

    Example in watchdog.py:
        from tracking_health import watchdog_check
        if not watchdog_check(timeout_s=60, log_fn=log, report_fn=report_error_to_backend):
            log("[WATCHDOG] Loop frozen — restarting tracking thread")
            # ... restart logic
    """
    if is_making_progress(timeout_s):
        return True

    stats = get_loop_stats()
    msg = (
        f"[HEALTH] ⚠️ Tracking loop FROZEN — last tick "
        f"{stats['last_tick_age_s']}s ago "
        f"(longest_gap={stats['longest_gap_s']}s, "
        f"freeze_count={stats['freeze_count']})"
    )
    log_fn(msg)

    if report_fn:
        try:
            report_fn(
                "tracking_loop_frozen",
                msg,
                context=stats,
            )
        except Exception:
            pass

    return False