#!/usr/bin/env python3
"""
The notification switch: off by default, and genuinely restorable.

Every banner this agent can raise goes out through one of five calls to
UNUserNotificationCenter, spread across three files:

    notifications.py        _send_notification        (7 nag types)
    ai_client_switcher.py   _notify_switch            (every client switch)
    main.py                 show_subscription_inactive_notification
    main.py                 notify_nudge              (MavOps yes/no prompt)
    main.py                 check_startup_timesheet   (at every launch)

All five now consult `notifications_enabled()`, which defaults to False. This
pins that default, pins the two ways back on, and pins that a broken or absent
config fails CLOSED rather than open.

The audit at the bottom is the part that matters most over time: it re-derives
the list of delivery calls from the source and fails if a new one appears
without a guard, so the next notification someone adds cannot quietly reopen
the thing this turned off.

Run:
    python3 test_notification_switch.py          (needs pyobjc)

Exits non-zero if any assertion fails.
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


print("notification switch:")

try:
    import notifications as N
except Exception as e:                       # pyobjc missing
    print(f"  SKIP  notifications module unavailable ({type(e).__name__}: {e})")
    print("\n  0 passed, 0 failed, 1 skipped")
    sys.exit(0)

_real_cfg = N._NOTIF_CONFIG_FILE
os.environ.pop("AGENT_NOTIF_ENABLED", None)

# --- the default ---------------------------------------------------------
N._NOTIF_CONFIG_FILE = "/nonexistent/timetracker/config.json"
check("default is OFF, with no config and no env",
      N.notifications_enabled() is False)

# --- the way back on -----------------------------------------------------
env_cases = [("1", True), ("true", True), ("TRUE", True), ("yes", True),
             ("on", True), ("0", False), ("false", False), ("", False)]
env_ok = True
for val, want in env_cases:
    os.environ["AGENT_NOTIF_ENABLED"] = val
    if N.notifications_enabled() is not want:
        env_ok = False
        print(f"        (AGENT_NOTIF_ENABLED={val!r} gave "
              f"{N.notifications_enabled()}, wanted {want})")
os.environ.pop("AGENT_NOTIF_ENABLED", None)
check("AGENT_NOTIF_ENABLED is read, and understands 1/true/yes/on", env_ok)

_dir = tempfile.mkdtemp()
cfg = os.path.join(_dir, "config.json")
N._NOTIF_CONFIG_FILE = cfg
cfg_ok = True
for value, want in [(True, True), (False, False), ("true", True), ("no", False)]:
    with open(cfg, "w") as fh:
        json.dump({"notifications_enabled": value}, fh)
    if N.notifications_enabled() is not want:
        cfg_ok = False
        print(f"        (config {value!r} gave {N.notifications_enabled()}, "
              f"wanted {want})")
check("config.json notifications_enabled turns them on and off", cfg_ok)

with open(cfg, "w") as fh:
    json.dump({"notifications_enabled": False}, fh)
os.environ["AGENT_NOTIF_ENABLED"] = "1"
check("env beats config, so a banner can be forced without editing files",
      N.notifications_enabled() is True)
os.environ.pop("AGENT_NOTIF_ENABLED", None)

# --- failing closed ------------------------------------------------------
with open(cfg, "w") as fh:
    json.dump({"something_else": 1}, fh)
check("a config without the key stays OFF",
      N.notifications_enabled() is False)

with open(cfg, "w") as fh:
    fh.write("{ not valid json")
check("a corrupt config stays OFF (fails closed, not open)",
      N.notifications_enabled() is False)

# --- the central send path -----------------------------------------------
N._NOTIF_CONFIG_FILE = "/nonexistent/timetracker/config.json"
mgr = N.ClientNotificationManager.__new__(N.ClientNotificationManager)
throttle_calls = []
mgr._can_send_notification = lambda *a, **k: (throttle_calls.append(1) or True)
result = N.ClientNotificationManager._send_notification(
    mgr, notif_type=N.NotificationType.PERIODIC_CHECKIN, title="t", body="b")
check("_send_notification refuses while disabled", result is False)
check("...and refuses BEFORE the throttle, so a silent agent burns no quota "
      "and records no 'last notification' it never sent",
      throttle_calls == [])

# --- the audit: no unguarded delivery path may exist ---------------------
# Re-derived from source so a NEW notification added later, without a guard,
# fails here rather than quietly reopening what this change turned off.
_here = os.path.dirname(os.path.abspath(__file__))
_GUARD = re.compile(r"NOTIF_ENABLED|notifications_enabled\(\)|notify_on_switch")
unguarded = []
for fname in ("main.py", "notifications.py", "ai_client_switcher.py"):
    path = os.path.join(_here, fname)
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        continue
    for i, line in enumerate(lines):
        if "addNotificationRequest_withCompletionHandler_" not in line:
            continue
        # Look back over the enclosing function for a guard.
        window = "\n".join(lines[max(0, i - 80):i + 1])
        if not _GUARD.search(window):
            unguarded.append(f"{fname}:{i + 1}")

check("every banner-delivery call sits behind the switch"
      + (f" (unguarded: {', '.join(unguarded)})" if unguarded else ""),
      not unguarded)

N._NOTIF_CONFIG_FILE = _real_cfg
print(f"\n  {_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
