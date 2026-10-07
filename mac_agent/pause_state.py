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
from typing import Callable, Optional

STATE_PATH = os.path.expanduser("~/.timetracker/pause.json")

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
        self._load()

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
        self.log(f"[PAUSE] Tracking paused "
                 f"{'for ' + str(minutes) + ' min' if minutes else 'until resumed'}")

    def resume(self) -> None:
        with self._lock:
            was = self._since is not None
            self._since = self._until = None
            self._save()
        if was:
            self.log("[PAUSE] Tracking resumed")

    def is_paused(self) -> bool:
        """True while paused. A timed pause that has run out ends here."""
        with self._lock:
            if self._since is None:
                return False
            if self._until is None or self.clock() < self._until:
                return True
            self._since = self._until = None
            self._save()
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
