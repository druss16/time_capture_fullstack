"""Menu-bar watchdog — notices the main (AppKit) thread freezing.

The tracking loop has mac_watchdog and startup has startup_watchdog, but the
main thread — the menu bar — had nothing. If it hangs, tracking may carry on
while the icon stops answering: Pause does nothing, Re-link does nothing, and
macOS calls the app "not responding". Nobody would know why.

A timer ON the main thread touches a heartbeat every few seconds; a
background thread checks it. Stale for longer than the threshold → on_frozen
(main.py: log every thread's stack, report 'menu_bar_frozen', restart).

The timer is scheduled in NSRunLoopCommonModes, not the default mode rumps
uses, so an open menu or a modal dialog (event-tracking / modal run-loop
modes) still ticks and never looks like a freeze. time.monotonic does not
advance while the Mac sleeps, so sleep is not a freeze either.

Plain Python except install_main_thread_timer: test_menubar_watchdog.py
drives the logic with a fake clock.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

FROZEN_AFTER_S = 120
TICK_S = 5.0


class MainThreadWatchdog:
    def __init__(self, on_frozen: Callable[[float], None],
                 threshold: float = FROZEN_AFTER_S,
                 clock: Callable[[], float] = time.monotonic):
        self.on_frozen = on_frozen
        self.threshold = threshold
        self.clock = clock
        self._last: Optional[float] = None   # None until the main thread first ticks
        self._fired = False
        self._lock = threading.Lock()

    def touch(self) -> None:
        """Called on the main thread by its timer."""
        with self._lock:
            self._last = self.clock()
            self._fired = False

    def check(self) -> bool:
        """One look from the background thread. True if it fired."""
        with self._lock:
            if self._last is None or self._fired:
                return False
            stale = self.clock() - self._last
            if stale < self.threshold:
                return False
            self._fired = True
        self.on_frozen(stale)
        return True

    def start_checker(self, interval: float = 10.0) -> None:
        def _run():
            while True:
                time.sleep(interval)
                try:
                    self.check()
                except Exception:
                    pass
        threading.Thread(target=_run, daemon=True, name="MenuBarWatchdog").start()


def install_main_thread_timer(watchdog: MainThreadWatchdog, interval: float = TICK_S):
    """Schedule the heartbeat NSTimer on the main run loop in common modes.
    Call on the main thread (the menu bar's __init__ is). Returns the timer,
    which the caller must keep a reference to."""
    from Foundation import NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer

    class _Ticker(NSObject):
        def tick_(self, _timer):
            watchdog.touch()

    ticker = _Ticker.alloc().init()
    timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
        interval, ticker, "tick:", None, True)
    NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
    watchdog.touch()
    return timer, ticker
