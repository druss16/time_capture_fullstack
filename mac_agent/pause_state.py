"""User pause / resume for the Mac agent.

The person picks "Pause Tracking" in the menu bar; until they resume (or the
chosen time runs out) the tracking loop records nothing. The menu bar and the
tracking loop run in the same process and both read this module.

The pause is SAVED TO DISK. The agent restarts itself after every real sleep
(main.py on_wake → os._exit(1) → LaunchAgent), so a pause held only in memory
would silently end the first time the lid closed — and someone who paused for
privacy would be tracked again without knowing it.

Plain Python, no macOS calls: test_pause_state.py drives it with a fake clock.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

STATE_PATH = os.path.expanduser("~/.timetracker/pause.json")
# Pauses not yet confirmed by the server (POST /api/agent/pauses/), kept on
# disk so a pause taken offline, or before a restart, still reaches Reports.
OUTBOX_NAME = "pause_outbox.json"

# Menu choices: (label, minutes). None = until the person resumes.
DURATIONS = (
    ("15 minutes", 15),
    ("30 minutes", 30),
    ("1 hour", 60),
    ("Until I resume", None),
)


class PauseState:
    def __init__(self, path: str = STATE_PATH, clock: Callable[[], float] = time.time,
                 log: Callable[[str], None] = print):
        self.path = path
        self.clock = clock
        self.log = log
        self._lock = threading.Lock()
        self._since: Optional[float] = None   # epoch the pause began; None = not paused
        self._until: Optional[float] = None   # epoch it ends; None = until resumed
        self.outbox_path = os.path.join(os.path.dirname(path), OUTBOX_NAME)
        # {str(started_at): {"started_at", "ended_at", "planned_until"}} — epochs
        self._outbox: Dict[str, dict] = {}
        # Called (no args) after the outbox changes, to wake the sender.
        self.on_change: Optional[Callable[[], None]] = None
        self._load()
        self._load_outbox()

    # ---- persistence -------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path) as f:
                d = json.load(f)
            since = d.get("since")
            if since is not None:
                self._since = float(since)
                until = d.get("until")
                self._until = float(until) if until is not None else None
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log(f"[PAUSE] could not read {self.path}: {e} — not paused")

    def _save(self) -> None:
        try:
            if self._since is None:
                if os.path.exists(self.path):
                    os.remove(self.path)
                return
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"since": self._since, "until": self._until}, f)
            os.replace(tmp, self.path)
        except Exception as e:
            self.log(f"[PAUSE] could not save {self.path}: {e}")

    # ---- report outbox -----------------------------------------------------
    def _load_outbox(self) -> None:
        try:
            with open(self.outbox_path) as f:
                d = json.load(f)
            if isinstance(d, dict):
                self._outbox = {k: v for k, v in d.items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log(f"[PAUSE] could not read {self.outbox_path}: {e}")

    def _save_outbox(self) -> None:
        try:
            if not self._outbox:
                if os.path.exists(self.outbox_path):
                    os.remove(self.outbox_path)
                return
            os.makedirs(os.path.dirname(self.outbox_path), exist_ok=True)
            tmp = self.outbox_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._outbox, f)
            os.replace(tmp, self.outbox_path)
        except Exception as e:
            self.log(f"[PAUSE] could not save {self.outbox_path}: {e}")

    def _queue(self, since: float, ended: Optional[float], until: Optional[float]) -> None:
        """Lock held. The latest state of one pause replaces any unsent one."""
        self._outbox[repr(since)] = {"started_at": since, "ended_at": ended,
                                     "planned_until": until}
        self._save_outbox()

    def _changed(self) -> None:
        cb = self.on_change
        if cb:
            try:
                cb()
            except Exception:
                pass

    def pending_reports(self) -> List[dict]:
        """Copies of every pause the server has not confirmed yet."""
        with self._lock:
            return [dict(r) for r in self._outbox.values()]

    def mark_reported(self, sent: List[dict]) -> None:
        """Drop what the server confirmed — unless that pause changed again
        while the post was in flight (then the newer state is still owed)."""
        with self._lock:
            for r in sent:
                key = repr(r.get("started_at"))
                if self._outbox.get(key) == r:
                    del self._outbox[key]
            self._save_outbox()

    # ---- the API -----------------------------------------------------------
    def pause(self, minutes: Optional[int] = None) -> None:
        """Pause now, for `minutes`, or until resume() when None. Pausing
        while already paused changes how long, keeping the original start."""
        with self._lock:
            now = self.clock()
            if self._since is None:
                self._since = now
            self._until = now + minutes * 60 if minutes else None
            self._save()
            self._queue(self._since, None, self._until)
        self._changed()
        self.log(f"[PAUSE] Tracking paused "
                 f"{'for ' + str(minutes) + ' min' if minutes else 'until resumed'}")

    def resume(self) -> None:
        with self._lock:
            was = self._since is not None
            if was:
                self._queue(self._since, self.clock(), self._until)
            self._since = self._until = None
            self._save()
        if was:
            self._changed()
            self.log("[PAUSE] Tracking resumed")

    def is_paused(self) -> bool:
        """True while paused. A timed pause that has run out ends here."""
        with self._lock:
            if self._since is None:
                return False
            if self._until is None or self.clock() < self._until:
                return True
            # It ended when it was set to, not when someone noticed.
            self._queue(self._since, self._until, self._until)
            self._since = self._until = None
            self._save()
        self._changed()
        self.log("[PAUSE] Pause time is up — tracking resumed")
        return False

    def paused_since(self) -> Optional[float]:
        with self._lock:
            return self._since

    def paused_until(self) -> Optional[float]:
        with self._lock:
            return self._until

    def status_label(self) -> str:
        """For the menu: 'Paused until 3:45 PM' or 'Paused'."""
        until = self.paused_until()
        if until is None:
            return "Paused"
        return "Paused until " + datetime.fromtimestamp(until).strftime("%-I:%M %p")


_shared: Optional[PauseState] = None
_shared_lock = threading.Lock()


def shared(log: Callable[[str], None] = print) -> PauseState:
    """The one PauseState the menu bar and the tracking loop share."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = PauseState(log=log)
        return _shared
