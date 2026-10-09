"""MavOps' remote Accessibility switch and the self-rollback trial.

    python3 mac_agent/test_ax_switch.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ax_switch as A  # noqa: E402

T0 = 1_000_000.0


def test_on_clears_disable_ax_restarts_and_starts_a_trial():
    cfg = {"disable_ax": True}
    assert A.apply_remote(cfg, "on", "1", T0) is True
    assert "disable_ax" not in cfg
    assert cfg["ax_trial"] == {"started": T0, "launches": 0}
    assert cfg["ax_switch_applied"] == "1"


def test_same_id_is_acted_on_once():
    cfg = {"disable_ax": True}
    A.apply_remote(cfg, "on", "1", T0)
    cfg["disable_ax"] = True          # e.g. the trial rolled it back
    assert A.apply_remote(cfg, "on", "1", T0 + 30) is False
    assert cfg["disable_ax"] is True, "a rollback must not be undone by the next poll"


def test_on_when_already_on_needs_no_restart():
    cfg = {}
    assert A.apply_remote(cfg, "on", "1", T0) is False
    assert "ax_trial" not in cfg


def test_off_sets_disable_ax_and_restarts_only_if_it_was_on():
    cfg = {"ax_trial": {"started": T0, "launches": 1}}
    assert A.apply_remote(cfg, "off", "2", T0) is True
    assert cfg["disable_ax"] is True and "ax_trial" not in cfg
    assert A.apply_remote(cfg, "off", "3", T0) is False


def test_garbage_is_ignored():
    cfg = {"disable_ax": True}
    for state, sid in (("maybe", "1"), ("on", ""), ("on", None), ("on", 5)):
        assert A.apply_remote(cfg, state, sid, T0) is False
    assert cfg == {"disable_ax": True}


def test_two_freezes_in_the_trial_roll_back():
    cfg = {"disable_ax": True}
    A.apply_remote(cfg, "on", "1", T0)
    assert A.on_launch(cfg, T0 + 5) == "trial"        # the switch's own restart
    assert "disable_ax" not in cfg
    assert A.on_launch(cfg, T0 + 100) == "trial"      # freeze 1
    assert A.on_launch(cfg, T0 + 200) == "rolled_back"  # freeze 2
    assert cfg["disable_ax"] is True
    assert cfg["ax_rolled_back"] == T0 + 200
    assert "ax_trial" not in cfg
    assert A.on_launch(cfg, T0 + 300) == "none"


def test_one_freeze_is_tolerated_and_the_trial_passes():
    cfg = {"disable_ax": True}
    A.apply_remote(cfg, "on", "1", T0)
    assert A.on_launch(cfg, T0 + 5) == "trial"
    assert A.on_launch(cfg, T0 + 100) == "trial"
    assert A.finish_trial(cfg, T0 + 300) is False     # still inside
    assert A.finish_trial(cfg, T0 + A.TRIAL_S + 1) is True
    assert "ax_trial" not in cfg and "disable_ax" not in cfg
    assert A.on_launch(cfg, T0 + A.TRIAL_S + 50) == "none"


def test_a_restart_after_the_window_ends_the_trial_without_counting():
    cfg = {"ax_trial": {"started": T0, "launches": 2}}
    assert A.on_launch(cfg, T0 + A.TRIAL_S + 1) == "passed"
    assert "disable_ax" not in cfg and "ax_trial" not in cfg


def test_try_again_after_a_rollback_clears_the_flag():
    cfg = {"disable_ax": True, "ax_rolled_back": T0, "ax_switch_applied": "1"}
    assert A.apply_remote(cfg, "on", "2", T0 + 900) is True
    assert "ax_rolled_back" not in cfg and "disable_ax" not in cfg


def test_corrupt_trial_is_dropped():
    cfg = {"ax_trial": "lol"}
    assert A.on_launch(cfg, T0) == "passed"
    assert "ax_trial" not in cfg


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
