"""Startup watchdog — catches the agent hanging BEFORE tracking starts.

mac_watchdog guards the tracking loop, but only once it runs. Everything
before that — the update check, the permission check, the first hello, the
menu bar — had no guard at all. On 2026-10-07 a macOS 26 Mac hung forever in
AEDeterminePermissionToAutomateTarget during the permission check: no
tracking, no menu bar, no error anywhere, found only because a person asked.

run_agent() names each startup stage as it enters it:

    wd = StartupWatchdog(on_stall=...)
    wd.stage("update_check")
    ...
    wd.stage("permissions", skippable=True)
    ...
    wd.done()          # tracking loop is up

If one stage runs longer than its limit, on_stall gets the stage name and the
elapsed seconds; main.py logs every thread's stack, reports a 'startup_stall'
error to the server, and exits so the LaunchAgent restarts it.

No restart loop: the stall is remembered on disk. A stage marked skippable
that stalled last launch is skipped this launch (should_skip()). A stage that
cannot be skipped and keeps stalling is restarted at most MAX_RESTARTS times
in a row; after that the watchdog still reports, but stops killing the agent,
so a machine that will never get past it is not restarted every two minutes.
done() clears the record. A stage with limit=None (waiting for a person, e.g.
the pairing window) is never timed.

Plain Python: test_startup_watchdog.py drives it with a fake clock.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from typing import Callable, Optional

STALL_PATH = os.path.expanduser("~/.timetracker/startup_stall.json")
DEFAULT_LIMIT_S = 120
MAX_RESTARTS = 3


class StartupWatchdog:
    def __init__(self, on_stall: Callable[[str, float, bool], None],
                 path: str = STALL_PATH, clock: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = print, default_limit: float = DEFAULT_LIMIT_S):
        """on_stall(stage, elapsed_s, restart) — restart is False once the
        same stage has stalled MAX_RESTARTS launches in a row."""
        self.on_stall = on_stall
        self.path = path
        self.clock = clock
        self.log = log
        self.default_limit = default_limit
        self._lock = threading.Lock()
        self._stage: Optional[str] = None
        self._entered = 0.0
        self._limit: Optional[float] = None
        self._skippable = False
        self._done = False
        self._fired = False
        self.previous = self._read()   # last launch's stall, if any

    # ---- record on disk ----------------------------------------------------
    def _read(self) -> dict:
        try:
            with open(self.path) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _write(self, d: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(d, f)
            os.replace(tmp, self.path)
        except Exception as e:
            self.log(f"[STARTUP] could not save {self.path}: {e}")

    def _clear(self) -> None:
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception:
            pass

    # ---- the API -----------------------------------------------------------
    def should_skip(self, stage: str) -> bool:
        """True if `stage` is skippable and stalled on the last launch."""
        p = self.previous
        return bool(p.get("stage") == stage and p.get("skippable"))

    def stage(self, name: str, limit: Optional[float] = -1, skippable: bool = False) -> None:
        """Enter a stage. limit: seconds (-1 = default, None = never time out)."""
        with self._lock:
            self._stage = name
            self._entered = self.clock()
            self._limit = self.default_limit if limit == -1 else limit
            self._skippable = skippable
            self._fired = False

    def done(self) -> None:
        with self._lock:
            self._done = True
            self._stage = None
        if self.previous:
            self.log(f"[STARTUP] Started normally (last launch stalled in "
                     f"'{self.previous.get('stage')}')")
        self._clear()

    def check(self) -> bool:
        """One watchdog look. Returns True if it fired."""
        with self._lock:
            if self._done or self._fired or self._stage is None or self._limit is None:
                return False
            elapsed = self.clock() - self._entered
            if elapsed < self._limit:
                return False
            self._fired = True
            stage, skippable = self._stage, self._skippable
        prev = self.previous
        count = (int(prev.get("count", 0)) + 1) if prev.get("stage") == stage else 1
        restart = skippable or count <= MAX_RESTARTS
        self._write({"stage": stage, "skippable": skippable, "count": count,
                     "at": time.time(), "elapsed_s": round(elapsed)})
        self.on_stall(stage, elapsed, restart)
        return True

    def start(self, interval: float = 5.0) -> None:
        def _run():
            while True:
                time.sleep(interval)
                with self._lock:
                    if self._done:
                        return
                try:
                    self.check()
                except Exception as e:
                    self.log(f"[STARTUP] watchdog check failed: {e}")
        threading.Thread(target=_run, daemon=True, name="StartupWatchdog").start()


def all_thread_stacks() -> str:
    """Every thread's Python stack — what each one was doing when it stalled."""
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in sys._current_frames().items():
        out.append(f"--- thread {names.get(ident, '?')} ({ident}) ---")
        out.extend(line.rstrip() for line in traceback.format_stack(frame))
    return "\n".join(out)
