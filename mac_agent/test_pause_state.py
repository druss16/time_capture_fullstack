"""Pause / Resume state behind the menu bar's "Pause Tracking".

    python3 mac_agent/test_pause_state.py

No macOS calls: PauseState is driven by a fake clock and a temp file.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pause_state as PS  # noqa: E402


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def fresh(clock=None, path=None):
    path = path or os.path.join(tempfile.mkdtemp(), "pause.json")
    return PS.PauseState(path=path, clock=clock or Clock(), log=lambda m: None)


def test_not_paused_by_default():
    p = fresh()
    assert not p.is_paused()
    assert p.paused_since() is None


def test_timed_pause_ends_on_its_own():
    c = Clock()
    p = fresh(c)
    p.pause(15)
    assert p.is_paused()
    assert p.paused_since() == c.t
    c.advance(14 * 60)
    assert p.is_paused()
    c.advance(61)
    assert not p.is_paused(), "a 15-minute pause still running after 15 minutes"
    assert not os.path.exists(p.path), "an ended pause left its file behind"


def test_until_resumed_never_ends_on_its_own():
    c = Clock()
    p = fresh(c)
    p.pause(None)
    c.advance(3 * 24 * 3600)
    assert p.is_paused()
    assert p.status_label() == "Paused"
    p.resume()
    assert not p.is_paused()


def test_pause_survives_a_restart():
    # The agent restarts after every real sleep; the pause must not end then.
    c = Clock()
    path = os.path.join(tempfile.mkdtemp(), "pause.json")
    fresh(c, path).pause(60)
    c.advance(30 * 60)
    again = fresh(c, path)
    assert again.is_paused(), "restart silently resumed tracking"
    c.advance(31 * 60)
    assert not again.is_paused()


def test_until_resumed_survives_a_restart():
    c = Clock()
    path = os.path.join(tempfile.mkdtemp(), "pause.json")
    fresh(c, path).pause(None)
    assert fresh(c, path).is_paused()


def test_changing_the_duration_keeps_the_start():
    c = Clock()
    p = fresh(c)
    p.pause(15)
    start = p.paused_since()
    c.advance(10 * 60)
    p.pause(60)
    assert p.paused_since() == start, "the pause start moved; the dwell flush would be wrong"
    assert p.paused_until() == c.t + 3600


def test_resume_clears_the_file():
    p = fresh()
    p.pause(30)
    assert os.path.exists(p.path)
    p.resume()
    assert not os.path.exists(p.path)


def test_corrupt_file_means_not_paused():
    path = os.path.join(tempfile.mkdtemp(), "pause.json")
    with open(path, "w") as f:
        f.write("{not json")
    assert not fresh(path=path).is_paused()


def test_file_shape():
    c = Clock()
    p = fresh(c)
    p.pause(30)
    with open(p.path) as f:
        d = json.load(f)
    assert d == {"since": c.t, "until": c.t + 1800}, d


def test_menu_durations():
    assert [m for _, m in PS.DURATIONS] == [15, 30, 60, None]


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
