"""
mac_watchdog.py — Internal watchdog thread for the TimeTracker Mac agent.

Ported from windows/watchdog.py. Detects BOTH dead threads AND frozen threads.

THE PROBLEM WITH THE OLD MAC WATCHDOG:
  - It was defined inside run_agent() but the thread-start was indented INSIDE
    the watchdog() function itself — so it was never actually called.
  - Even if it had been called, it only checked thread.is_alive(), which doesn't
    catch a frozen thread (alive but stuck on an osascript/Quartz call).

THE FIX (two complementary signals):
  1. heartbeat_touch() / heartbeat_age()
     Called at the TOP of every tracking loop iteration. If the loop is stuck
     on get_frontmost_app() (osascript blocking after sleep/wake), the heartbeat
     goes stale and the watchdog fires. This is the primary defense against hard
     freezes.

  2. thread.is_alive() check
     Catches outright thread death (unhandled exception, etc.)

On freeze/death: os._exit(1) — LaunchAgent sees non-zero exit and restarts
the agent cleanly. Same approach already used for the sleep/wake handler.

INTEGRATION (in main.py run_agent()):

    from mac_watchdog import heartbeat_touch, start_watchdog

    # 1. Declare _last_detect_heartbeat BEFORE def tracking_loop():
    _last_detect_heartbeat = heartbeat_touch()   # initializes and returns time.time()

    # 2. Inside tracking_loop(), at the very top of the while True: loop:
    def tracking_loop():
        nonlocal _last_detect_heartbeat
        ...
        while not _tracking_stop_event.is_set():
            heartbeat_touch()    # ← FIRST LINE of every iteration
            ...

    # 3. After starting tracking_thread:
    tracking_thread = threading.Thread(target=tracking_loop, daemon=False)
    tracking_thread.start()

    _thread_ref = [tracking_thread]
    start_watchdog(_thread_ref, tracking_loop, log, report_error_to_backend)
"""

import os
import time
import threading
import logging

logger = logging.getLogger("timetracker")

# ── Heartbeat state ──────────────────────────────────────────────────────────
_heartbeat_lock = threading.Lock()
_last_heartbeat: float = 0.0
_heartbeat_started: float = 0.0

# Tuning constants (match Windows values)
WATCHDOG_FROZEN_THRESHOLD = 90   # Seconds of no heartbeat → frozen (hard freeze)
WATCHDOG_CHECK_INTERVAL   = 30   # How often the watchdog polls
WATCHDOG_GRACE_PERIOD     = 120  # Don't fire during first 2 min of startup


def heartbeat_touch() -> float:
    """
    Call this at the TOP of every tracking loop iteration.
    Returns current time so callers can use it (e.g. for _last_detect_heartbeat).
    Takes <1ms. Thread-safe.
    """
    global _last_heartbeat
    now = time.time()
    with _heartbeat_lock:
        _last_heartbeat = now
    return now


def heartbeat_age() -> float:
    """Returns seconds since last heartbeat. 0.0 if never set."""
    with _heartbeat_lock:
        if _last_heartbeat == 0.0:
            return 0.0
        return time.time() - _last_heartbeat


def start_watchdog(
    tracking_thread_ref: list,
    tracking_loop_fn,
    log_fn,
    report_error_fn=None,
):
    """
    Start the watchdog thread. Call this AFTER starting tracking_thread.

    Args:
        tracking_thread_ref:  A list with one element [thread] so we can read
                              the current thread reference even after restarts.
                              (nonlocal workaround — same pattern as Windows)
        tracking_loop_fn:     The tracking_loop function (used for restart).
        log_fn:               The agent's log() function.
        report_error_fn:      Optional report_error_to_backend() function.

    The watchdog runs on a daemon thread so it dies with the process.
    It calls os._exit(1) on freeze/death — LaunchAgent restarts cleanly.
    """
    global _heartbeat_started
    _heartbeat_started = time.time()

    def _watchdog():
        log_fn("[WATCHDOG] ✅ Started watchdog thread")

        while True:
            time.sleep(WATCHDOG_CHECK_INTERVAL)

            thread = tracking_thread_ref[0]
            uptime = time.time() - _heartbeat_started
            age    = heartbeat_age()

            # ── Grace period: don't fire during startup ────────────────────
            if uptime < WATCHDOG_GRACE_PERIOD:
                continue

            # ── Case 1: Thread is dead ─────────────────────────────────────
            if not thread.is_alive():
                log_fn("[WATCHDOG] ⚠️ Tracking thread DIED — forcing restart via LaunchAgent")
                if report_error_fn:
                    try:
                        report_error_fn("watchdog_dead", "Tracking thread died", "")
                    except Exception:
                        pass
                _ship_logs_before_exit(log_fn)
                os._exit(1)  # LaunchAgent restarts us

            # ── Case 2: Thread alive but heartbeat stale (hard freeze) ─────
            # Typical cause: osascript / System Events blocked after wake,
            # or Quartz call hanging due to PyObjC state corruption post-sleep.
            if age > WATCHDOG_FROZEN_THRESHOLD:
                log_fn(
                    f"[WATCHDOG] 🥶 Tracking thread FROZEN — "
                    f"no heartbeat for {int(age)}s "
                    f"(threshold={WATCHDOG_FROZEN_THRESHOLD}s) — "
                    f"killing osascript and forcing restart"
                )

                # Kill any hung osascript processes (common freeze vector)
                try:
                    import subprocess
                    subprocess.run(["pkill", "-f", "osascript"], capture_output=True)
                    log_fn("[WATCHDOG] Killed hung osascript processes")
                except Exception:
                    pass

                if report_error_fn:
                    try:
                        report_error_fn(
                            "watchdog_frozen",
                            f"Tracking thread frozen: no heartbeat for {int(age)}s",
                            f"heartbeat_age={age:.1f}s\nuptime={uptime:.0f}s",
                        )
                    except Exception:
                        pass

                _ship_logs_before_exit(log_fn)
                os._exit(1)  # LaunchAgent restarts us

            # ── All good ───────────────────────────────────────────────────
            # Uncomment for debug:
            # log_fn(f"[WATCHDOG] ✅ OK — heartbeat {age:.0f}s ago, uptime {int(uptime)}s")

    watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
    watchdog_thread.start()
    return watchdog_thread


def _ship_logs_before_exit(log_fn):
    """
    Best-effort log ship before os._exit(1).
    Mirrors Windows watchdog behavior — gives backend visibility into freeze.
    Times out quickly so it doesn't delay the restart.
    """
    try:
        # Lazy import — only available if main.py has ship_logs_to_backend
        from main import ship_logs_to_backend
        ship_logs_to_backend(tail_lines=200, trigger="watchdog_freeze")
        time.sleep(2)
    except Exception:
        pass  # Non-fatal — proceed with exit regardless