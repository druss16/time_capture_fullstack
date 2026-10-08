"""The startup watchdog (startup_watchdog.py).

    python3 mac_agent/test_startup_watchdog.py

No macOS calls: a fake clock and a temp file.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import startup_watchdog as SW  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make(path=None, clock=None):
    path = path or os.path.join(tempfile.mkdtemp(), "stall.json")
    fired = []
    wd = SW.StartupWatchdog(on_stall=lambda s, e, r: fired.append((s, round(e), r)),
                            path=path, clock=clock or Clock(), log=lambda m: None,
                            default_limit=120)
    return wd, fired, path


def test_a_stage_inside_its_limit_does_not_fire():
    c = Clock()
    wd, fired, _ = make(clock=c)
    wd.stage("update_check")
    c.advance(119)
    assert not wd.check() and fired == []


def test_a_stuck_stage_fires_once_with_its_name():
    c = Clock()
    wd, fired, path = make(clock=c)
    wd.stage("hello")
    c.advance(125)
    assert wd.check()
    assert not wd.check(), "fired twice for the same stall"
    assert fired == [("hello", 125, True)]
    assert os.path.exists(path)


def test_entering_the_next_stage_resets_the_clock():
    c = Clock()
    wd, fired, _ = make(clock=c)
    wd.stage("a")
    c.advance(100)
    wd.stage("b")
    c.advance(100)
    assert not wd.check()


def test_a_stage_waiting_for_a_person_is_never_timed():
    c = Clock()
    wd, fired, _ = make(clock=c)
    wd.stage("pairing", limit=None)
    c.advance(3600)
    assert not wd.check()


def test_done_stops_it_and_clears_the_record():
    c = Clock()
    wd, fired, path = make(clock=c)
    wd.stage("hello")
    c.advance(200)
    wd.check()
    wd2, fired2, _ = make(path=path, clock=c)
    wd2.done()
    assert not os.path.exists(path)
    c.advance(500)
    assert not wd2.check()


def test_a_skippable_stage_that_stalled_is_skipped_next_launch():
    c = Clock()
    wd, _, path = make(clock=c)
    wd.stage("permissions", skippable=True)
    c.advance(130)
    wd.check()
    nxt, _, _ = make(path=path, clock=c)
    assert nxt.should_skip("permissions")
    assert not nxt.should_skip("hello")


def test_an_unskippable_stage_stops_restarting_after_max():
    c = Clock()
    path = os.path.join(tempfile.mkdtemp(), "stall.json")
    restarts = []
    for _ in range(SW.MAX_RESTARTS + 2):
        wd, fired, _ = make(path=path, clock=c)
        assert not wd.should_skip("update_check")
        wd.stage("update_check")
        c.advance(130)
        wd.check()
        restarts.append(fired[0][2])
    assert restarts == [True] * SW.MAX_RESTARTS + [False, False], restarts


def test_a_different_stage_starts_the_count_again():
    c = Clock()
    path = os.path.join(tempfile.mkdtemp(), "stall.json")
    for _ in range(SW.MAX_RESTARTS):
        wd, fired, _ = make(path=path, clock=c)
        wd.stage("update_check")
        c.advance(130)
        wd.check()
    wd, fired, _ = make(path=path, clock=c)
    wd.stage("hello")
    c.advance(130)
    wd.check()
    assert fired == [("hello", 130, True)]


def test_thread_stacks_name_this_thread():
    s = SW.all_thread_stacks()
    assert "MainThread" in s and "test_thread_stacks_name_this_thread" in s


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
