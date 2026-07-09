"""
In-process watchdog + tracking-loop heartbeat for the TimeTracker agent.

THE PROBLEM WITH THE OLD WATCHDOG:
- It only checked `tracking_thread.is_alive()`
- A frozen thread is still "alive" — Python has no idea it's stuck
- After sleep, win32 calls (GetForegroundWindow, GetLastInputInfo) can block
  indefinitely, keeping the thread alive but completely frozen
- The _suspended gap check inside the loop never fires if the loop is blocked
  BEFORE reaching that check

THE FREEZE-DETECTION FIX (two complementary signals):
- heartbeat_touch() / heartbeat_age(): catches win32 API freezes — the thread
  is blocked BEFORE progress_tick() even fires, so this is the first line of
  defense against hard freezes (GetForegroundWindow blocking after sleep, etc.)
- watchdog_check() from tracking_health: catches subtler logic stalls where
  the thread is running but not making forward progress through the loop body
  (e.g. stuck in a tight retry loop, blocked on DB, etc.)

Either signal alone triggers a hard restart of the whole process.

THE RESTART FIX (v1.5.x — self-relaunch):
Previously every restart path called a bare `os._exit(1)` and relied on an
EXTERNAL restarter (tt_watchdog.exe, or a logon scheduled task) to bring the
agent back. That assumption can fail: the agent and tt_watchdog.exe are
mutually dependent (the agent launches tt_watchdog at startup; tt_watchdog
relaunches the agent). If a single sleep/wake event takes BOTH down at once,
neither is left alive to restart the other, and the machine resumes into an
already-logged-in session so the ONLOGON task never re-fires. Result: agent
dead until the next interactive logon — observed once on a TL Wall machine
that stayed dark for 4 days.

The fix: before exiting, the agent spawns its OWN replacement. It no longer
trusts any external restarter to be alive. The single-instance mutex in
main() (with its self-relaunch retry window) guarantees we never end up with
two live agents. A rate cap prevents fork storms if the agent freezes on
startup repeatedly.

INTEGRATION:
- Replace the existing watchdog() function with this one.
- Keep calling heartbeat_touch() at the top of every tracking-loop iteration.
"""

import os
import sys
import time
import threading
import traceback
import subprocess

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


# ── Disk heartbeat (read by the EXTERNAL tt_watchdog.exe) ──────────────────
# The in-process heartbeat above is memory-only — another process can't see it.
# We ALSO stamp a file from the watchdog loop so tt_watchdog.exe can detect a
# WHOLE-PROCESS freeze (every thread wedged after a sleep/wake), which is the one
# case the in-process watchdog cannot recover from because it is wedged too.
# Stamped from the watchdog thread (not the tracking loop) so it keeps pulsing
# even when tracking is paused — it signals process liveness, not activity.
_HEARTBEAT_FILE = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "TimeTracker", "agent.heartbeat"
)


def _write_disk_heartbeat():
    """Best-effort atomic stamp of the current time. Never raises."""
    try:
        os.makedirs(os.path.dirname(_HEARTBEAT_FILE), exist_ok=True)
        tmp = _HEARTBEAT_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(str(time.time()))
        os.replace(tmp, _HEARTBEAT_FILE)   # atomic — reader never sees a half-write
    except Exception:
        pass


# ── Mutual supervision (no admin required) ─────────────────────────────────
# On locked-down machines a standard user can't create the Scheduled Task, so a
# killed watchdog would stay dead. Close that gap the other direction: the agent
# relaunches the watchdog if it has died. Supervision becomes two-way — as long
# as EITHER process survives, it resurrects the other. Just launches a process;
# no elevation involved.
_WATCHDOG_EXE_NAME = "tt_watchdog.exe"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _watchdog_exe_path() -> str:
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.join(os.environ.get("LOCALAPPDATA", ""), "TimeTracker"))
    return os.path.join(base, _WATCHDOG_EXE_NAME)


def _is_watchdog_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq " + _WATCHDOG_EXE_NAME, "/NH"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        return _WATCHDOG_EXE_NAME.lower() in (out.stdout or "").lower()
    except Exception:
        return True   # on error, assume up — never risk spawning duplicates


def _ensure_watchdog_running(log_fn):
    """If the external watchdog has died, bring it back. No admin needed."""
    if sys.platform != "win32":
        return
    try:
        if _is_watchdog_running():
            return
        exe = _watchdog_exe_path()
        if not os.path.exists(exe):
            return
        subprocess.Popen(
            [exe],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        log_fn("[WATCHDOG] 🔄 External watchdog was down — relaunched it (mutual supervision)")
    except Exception as e:
        log_fn(f"[WATCHDOG] Could not relaunch external watchdog: {e}")


# ── Self-relaunch (v1.5.x) ──────────────────────────────────────────────────
# Track relaunch timestamps so a freeze-on-startup loop can't fork-bomb.
_relaunch_times = []
_RELAUNCH_WINDOW_S = 600   # 10 minutes
_RELAUNCH_MAX = 3          # max relaunches per window before giving up


def _self_relaunch_then_exit(log_fn, trigger):
    """
    Spawn a fresh agent process, then hard-exit this one.

    Why spawn-before-exit instead of bare os._exit(1):
      The old code trusted tt_watchdog.exe or a logon task to restart us.
      Both can be dead simultaneously after a sleep/wake event, leaving
      nothing to bring the agent back. Spawning our own replacement makes
      the agent its own anchor — on startup run_agent() also re-launches
      tt_watchdog.exe, so both keep-alive layers get rebuilt.

    Safety:
      - Frozen-only: in dev (unfrozen), sys.executable is python.exe, not the
        agent exe, so we must NOT spawn it with a "start" arg. Just exit.
      - Rate-capped: if we've relaunched _RELAUNCH_MAX times within
        _RELAUNCH_WINDOW_S, stop relaunching and stay down. A persistent
        startup freeze should surface via server-side staleness alerting
        rather than spin forever.
      - Mutex-safe: the spawned child hits main()'s CreateMutexW. Because this
        parent is still alive for ~the Popen call, the child may briefly see
        ERROR_ALREADY_EXISTS — main() retries the mutex for ~5s to cover this
        handoff window, so the child wins the lock as soon as we exit.
    """
    # Dev mode: sys.executable is the interpreter, not the frozen agent.
    # Spawning [python.exe, "start"] would do the wrong thing. Just exit.
    if not getattr(sys, 'frozen', False):
        log_fn(f"[WATCHDOG] dev mode — exiting without self-relaunch ({trigger})")
        os._exit(1)

    now = time.time()
    # Drop relaunch timestamps older than the window.
    while _relaunch_times and now - _relaunch_times[0] > _RELAUNCH_WINDOW_S:
        _relaunch_times.pop(0)

    if len(_relaunch_times) >= _RELAUNCH_MAX:
        log_fn(
            f"[WATCHDOG] 🛑 {_RELAUNCH_MAX} relaunches within "
            f"{_RELAUNCH_WINDOW_S // 60} min — NOT relaunching, staying down "
            f"({trigger}). Staleness alerting should surface this."
        )
        os._exit(1)

    _relaunch_times.append(now)

    try:
        # sys.executable is the frozen agent exe (this thread runs inside the
        # agent process). main() routes the "start" arg → run_agent().
        subprocess.Popen(
            [sys.executable, "start"],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        log_fn(f"[WATCHDOG] ↻ self-relaunched before exit ({trigger})")
    except Exception as e:
        log_fn(f"[WATCHDOG] self-relaunch FAILED ({trigger}): {e}")

    # Give the child a moment to start coming up before we release the mutex
    # by exiting. main()'s mutex retry covers the rest of the handoff window.
    time.sleep(1)
    os._exit(1)


def _ship_logs_safe(trigger):
    """Best-effort log ship before restart. Never blocks the restart path."""
    try:
        from main import ship_logs_to_backend
        ship_logs_to_backend(tail_lines=200, trigger=trigger)
        time.sleep(2)
    except Exception:
        pass


def watchdog(tracking_thread_ref: list, tracking_loop_fn, log_fn, report_error_fn=None):
    """
    Bulletproof watchdog. Detects BOTH dead threads AND frozen threads,
    and self-relaunches the agent before exiting so recovery never depends
    on an external restarter being alive.

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
    _write_disk_heartbeat()   # stamp immediately so the file exists at startup

    log_fn("[WATCHDOG] Started watchdog thread")

    # Import here to avoid circular import at module load time
    from tracking_health import watchdog_check, get_loop_stats

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)
        _write_disk_heartbeat()       # external tt_watchdog reads this to spot a frozen process
        _ensure_watchdog_running(log_fn)  # two-way supervision: revive the watchdog if it died

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
            _ship_logs_safe("watchdog_dead")
            _self_relaunch_then_exit(log_fn, "dead")

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

            _ship_logs_safe("watchdog_frozen")
            _self_relaunch_then_exit(log_fn, "frozen")

        # ── Case 3: GUI thread hung — force restart ────────────────────────
        try:
            from main import gui_menu_bar
            if gui_menu_bar and hasattr(gui_menu_bar, 'icon'):
                if gui_menu_bar.icon is None:
                    log_fn("[WATCHDOG] ⚠️ GUI icon is None — forcing restart")
                    _ship_logs_safe("watchdog_gui")
                    _self_relaunch_then_exit(log_fn, "gui")
        except Exception:
            pass

        # ── All good ──────────────────────────────────────────────────────
        # Uncomment for debug:
        # log_fn(f"[WATCHDOG] ✅ Heartbeat OK ({age:.0f}s ago), tick_age={get_loop_stats()['last_tick_age_s']}s")