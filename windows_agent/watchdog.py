"""
Drop-in replacement for the watchdog + tracking loop heartbeat in main.py.

THE PROBLEM WITH THE OLD WATCHDOG:
- It only checked `tracking_thread.is_alive()`
- A frozen thread is still "alive" — Python has no idea it's stuck
- After sleep, win32 calls (GetForegroundWindow, GetLastInputInfo) can block
  indefinitely, keeping the thread alive but completely frozen
- The _suspended gap check inside the loop never fires if the loop is blocked
  BEFORE reaching that check

THE FIX:
- Tracking loop writes a heartbeat timestamp every iteration
- Watchdog checks if heartbeat is stale (>90s = frozen)
- If frozen: os._exit(0) — hard kill, Task Scheduler restarts the whole process
- This is the same fix as the Mac agent's os._exit(1) on wake

INTEGRATION: 
Replace the existing watchdog() function and add _heartbeat_touch() calls
in the tracking loop. See comments marked "ADD" and "REPLACE" below.
"""

import os
import time
import threading
import traceback

# ── Heartbeat state (module-level so watchdog can read it) ──────────────────
_heartbeat_lock = threading.Lock()
_last_heartbeat: float = 0.0
_heartbeat_started: float = 0.0

WATCHDOG_FROZEN_THRESHOLD = 90    # Seconds of no heartbeat = frozen
WATCHDOG_CHECK_INTERVAL   = 30    # How often watchdog checks
WATCHDOG_GRACE_PERIOD     = 120   # Don't kill during first 2min of startup


def heartbeat_touch():
    """
    Call this at the TOP of every tracking loop iteration.
    Takes <1ms. Thread-safe.
    """
    global _last_heartbeat
    with _heartbeat_lock:
        _last_heartbeat = time.time()


def heartbeat_age() -> float:
    """Returns seconds since last heartbeat. 0 if never set."""
    with _heartbeat_lock:
        if _last_heartbeat == 0.0:
            return 0.0
        return time.time() - _last_heartbeat


def watchdog(tracking_thread_ref: list, tracking_loop_fn, log_fn, report_error_fn=None):
    """
    Bulletproof watchdog. Detects BOTH dead threads AND frozen threads.

    Args:
        tracking_thread_ref: A list with one element [thread] so we can
                             swap it out when we restart (nonlocal workaround)
        tracking_loop_fn:    The tracking_loop function to restart
        log_fn:              The agent's log() function
        report_error_fn:     Optional report_error_to_backend() function

    Usage in run_agent():

        _thread_ref = [tracking_thread]   # wrap in list

        watchdog_thread = threading.Thread(
            target=watchdog,
            args=(_thread_ref, tracking_loop, log, report_error_to_backend),
            daemon=True,
        )
        watchdog_thread.start()
        log("[WATCHDOG] Started watchdog thread")

        # Then wherever you use tracking_thread, use _thread_ref[0] instead.
    """
    global _heartbeat_started
    _heartbeat_started = time.time()

    log("[WATCHDOG] Started watchdog thread")

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)

        thread = tracking_thread_ref[0]
        uptime = time.time() - _heartbeat_started
        age = heartbeat_age()

        # ── Still in grace period ──────────────────────────────────────────
        if uptime < WATCHDOG_GRACE_PERIOD:
            continue

        # ── Case 1: Thread is dead ─────────────────────────────────────────
        if not thread.is_alive():
            log("[WATCHDOG] ⚠️ Tracking thread DIED — restarting process")
            if report_error_fn:
                try:
                    report_error_fn("watchdog_dead", "Tracking thread died", "")
                except Exception:
                    pass
            # Ship logs before dying so we have a record
            try:
                from main import ship_logs_to_backend
                ship_logs_to_backend(tail_lines=200, trigger="watchdog_dead")
                time.sleep(2)
            except Exception:
                pass
            os._exit(1)  # Task Scheduler / startup task restarts us

        # ── Case 2: Thread is alive but frozen (no heartbeat) ─────────────
        if age > WATCHDOG_FROZEN_THRESHOLD:
            log(f"[WATCHDOG] 🥶 Tracking thread FROZEN for {int(age)}s — restarting process")
            if report_error_fn:
                try:
                    report_error_fn(
                        "watchdog_frozen",
                        f"Tracking thread frozen for {int(age)}s",
                        f"Last heartbeat: {age:.1f}s ago\nUptime: {uptime:.0f}s",
                    )
                except Exception:
                    pass
            try:
                from main import ship_logs_to_backend
                ship_logs_to_backend(tail_lines=200, trigger="watchdog_frozen")
                time.sleep(2)
            except Exception:
                pass
            os._exit(1)  # Hard kill — clean restart

        # ── Case 3: GUI thread hung — force restart ────────────────────────
        if _heartbeat_started > 0:
            try:
                from main import gui_menu_bar
                if gui_menu_bar and hasattr(gui_menu_bar, 'icon'):
                    if gui_menu_bar.icon is None:
                        log("[WATCHDOG] ⚠️ GUI icon is None — forcing restart")
                        os._exit(1)
            except Exception:
                pass

        # ── All good ──────────────────────────────────────────────────────
        # Uncomment for debug:
        # log(f"[WATCHDOG] ✅ Heartbeat OK ({age:.0f}s ago)")