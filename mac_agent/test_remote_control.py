#!/usr/bin/env python3
"""
MavOps → Devices "Request logs" / "Restart" on the Mac agent.

Pins the decision in remote_control.py, and audits main.py so should_stop()
keeps routing the control response through it — the Mac agent once read
neither key and both buttons were silent no-ops.

Run:
    python3 test_remote_control.py          (no pyobjc needed)

Exits non-zero if any assertion fails.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import remote_control as rc

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


print("remote control decisions:")
a = rc.control_actions({"stop": False, "ship_logs": False, "restart": False}, 1)
check("nothing asked → nothing done", a == (False, None))
check("empty / failed response → nothing done", rc.control_actions({}, 1) == (False, None))
check("None response → nothing done", rc.control_actions(None, 1) == (False, None))
check("older server without the keys → nothing done",
      rc.control_actions({"stop": False, "reason": ""}, 1) == (False, None))
check("ship_logs → ship", rc.control_actions({"ship_logs": True}, 1).ship_logs is True)
check("ship_logs ships even outside launchd",
      rc.control_actions({"ship_logs": True}, 4242).ship_logs is True)
check("restart under launchd → exit", rc.control_actions({"restart": True}, 1).restart == "exit")
check("restart from a terminal → refuse",
      rc.control_actions({"restart": True}, 4242).restart == "refuse")
both = rc.control_actions({"ship_logs": True, "restart": True}, 1)
check("both at once → both", both == (True, "exit"))
check("restart exit code is non-zero (KeepAlive relaunches)", rc.RESTART_EXIT_CODE != 0)

print("main.py wiring:")
src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
m = re.search(r"\ndef should_stop\(.*?(?=\ndef )", src, re.S)
body = m.group(0) if m else ""
check("should_stop exists", bool(body))
check("should_stop consults remote_control.control_actions",
      "remote_control.control_actions(data, os.getppid())" in body)
check("log ship runs on a background thread with the mavops trigger",
      "threading.Thread(" in body and '"trigger": "mavops_request"' in body
      and "target=ship_logs_to_backend" in body)
check("restart exits with RESTART_EXIT_CODE",
      "os._exit(remote_control.RESTART_EXIT_CODE)" in body)

print("bundling:")
spec = open(os.path.join(HERE, "TimeTracker.spec"), encoding="utf-8").read()
wf = open(os.path.join(HERE, "..", ".github", "workflows", "release.yml"), encoding="utf-8").read()
check("TimeTracker.spec datas", "('remote_control.py', '.')" in spec)
check("TimeTracker.spec hiddenimports", "'remote_control'," in spec)
check("release.yml --add-data", '--add-data "remote_control.py:."' in wf)
check("release.yml --hidden-import", "--hidden-import=remote_control " in wf)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
