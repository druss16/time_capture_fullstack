"""
Drop-in replacement for the watchdog + tracking loop heartbeat in main.py.

THE PROBLEM WITH THE OLD WATCHDOG:
- It only checked `tracking_thread.is_alive()`
- A frozen thread is still "alive" — Python has no idea it's stuck
- After sleep, win32 calls (GetForegroundWindow, GetLastInputInfo) can block
  indefinitely, keeping the thread alive but completely frozen
- The _suspended gap check inside the loop never fires if the loop is blocked
  BEFORE reaching that check

THE FIX (two complementary signals):
- heartbeat_touch() / heartbeat_age(): catches win32 API freezes — the thread
  is blocked BEFORE progress_tick() even fires, so this is the first line of
  defense against hard freezes (GetForegroundWindow blocking after sleep, etc.)
- watchdog_check() from tracking_health: catches subtler logic stalls where
  the thread is running but not making forward progress through the loop body
  (e.g. stuck in a tight retry loop, blocked on DB, etc.)

Either signal alone triggers an os._exit(1) hard kill — Task Scheduler
restarts the whole process cleanly.

INTEGRATION:
Replace the existing watchdog() function and add heartbeat_touch() calls
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

WATCHDOG_FROZEN_THRESHOLD = 90    # Seconds of no heartbeat = frozen (hard freeze)
WATCHDOG_CHECK_INTERVAL   = 30    # How often watchdog checks
WATCHDOG_GRACE_PERIOD     = 120   # Don't kill during first 2min of startup

_watchdog_stop = threading.Event()

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

    Two frozen-detection signals:
      1. heartbeat_age() > WATCHDOG_FROZEN_THRESHOLD
         — catches hard win32 API freezes (GetForegroundWindow blocking after
           sleep/wake). The thread is stuck BEFORE progress_tick() fires.

      2. watchdog_check() from tracking_health
         — catches subtler logic stalls where the thread is technically running
           but not making forward progress (stuck retry loop, DB block, etc.)
           Uses a tighter 60s timeout vs the 90s heartbeat threshold.

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
    """
    global _heartbeat_started
    _heartbeat_started = time.time()

    log_fn("[WATCHDOG] Started watchdog thread")

    # Import here to avoid circular import at module load time
    from tracking_health import watchdog_check, get_loop_stats

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
            log_fn("[WATCHDOG] ⚠️ Tracking thread DIED — restarting process")
            if report_error_fn:
                try:
                    report_error_fn("watchdog_dead", "Tracking thread died", "")
                except Exception:
                    pass
            try:
                from main import ship_logs_to_backend
                ship_logs_to_backend(tail_lines=200, trigger="watchdog_dead")
                time.sleep(2)
            except Exception:
                pass
            os._exit(1)  # Task Scheduler / startup task restarts us

        # ── Case 2: Thread alive but frozen (heartbeat OR progress timeout) ──
        # Signal 1: heartbeat_age — hard freeze (win32 API blocking)
        # Signal 2: watchdog_check — soft freeze (logic stall, no forward progress)
        progress_ok = watchdog_check(timeout_s=60, log_fn=log_fn, report_fn=report_error_fn)

        if age > WATCHDOG_FROZEN_THRESHOLD or not progress_ok:
            stats = get_loop_stats()

            if age > WATCHDOG_FROZEN_THRESHOLD:
                freeze_reason = f"heartbeat stale ({int(age)}s > {WATCHDOG_FROZEN_THRESHOLD}s threshold)"
            else:
                freeze_reason = f"no loop progress for {stats['last_tick_age_s']}s (logic stall)"

            log_fn(
                f"[WATCHDOG] 🥶 Tracking thread FROZEN — {freeze_reason} | "
                f"heartbeat_age={int(age)}s, last_tick={stats['last_tick_age_s']}s, "
                f"longest_gap={stats['longest_gap_s']}s, freeze_count={stats['freeze_count']}"
            )

            if report_error_fn:
                try:
                    report_error_fn(
                        "watchdog_frozen",
                        f"Tracking thread frozen: {freeze_reason}",
                        f"heartbeat_age={age:.1f}s\nuptime={uptime:.0f}s",
                        context=stats,
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
        try:
            from main import gui_menu_bar
            if gui_menu_bar and hasattr(gui_menu_bar, 'icon'):
                if gui_menu_bar.icon is None:
                    log_fn("[WATCHDOG] ⚠️ GUI icon is None — forcing restart")
                    os._exit(1)
        except Exception:
            pass

        # ── All good ──────────────────────────────────────────────────────
        # Uncomment for debug:
        # log_fn(f"[WATCHDOG] ✅ Heartbeat OK ({age:.0f}s ago), tick_age={get_loop_stats()['last_tick_age_s']}s")