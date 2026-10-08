"""The menu-bar watchdog (menubar_watchdog.py).

    python3 mac_agent/test_menubar_watchdog.py

Logic only, fake clock. The NSTimer half needs AppKit and a run loop.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import menubar_watchdog as MW  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make():
    c = Clock()
    fired = []
    return MW.MainThreadWatchdog(on_frozen=lambda s: fired.append(round(s)),
                                 threshold=120, clock=c), c, fired


def test_nothing_before_the_first_tick():
    wd, c, fired = make()
    c.advance(1000)
    assert not wd.check() and fired == []


def test_ticking_main_thread_is_fine():
    wd, c, fired = make()
    for _ in range(100):
        wd.touch()
        c.advance(5)
        assert not wd.check()


def test_a_frozen_main_thread_fires_once():
    wd, c, fired = make()
    wd.touch()
    c.advance(121)
    assert wd.check()
    assert not wd.check()
    assert fired == [121]


def test_recovering_rearms_it():
    wd, c, fired = make()
    wd.touch()
    c.advance(130)
    wd.check()
    wd.touch()
    c.advance(130)
    assert wd.check()
    assert len(fired) == 2


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_") and callable(globals()[n])]
    for name in names:
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(names) - failures}/{len(names)} passed")
    sys.exit(1 if failures else 0)
