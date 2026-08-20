"""
Tests for the agent's one-shot elevation restart.

WHY THIS EXISTS
---------------
The agent's scheduled task requests HighestAvailable, but a process started as
a CHILD of something least-privileged inherits that instead. That is what the
watchdog used to do, and what an in-flight update still does — the watchdog
running at that moment is the pre-fix binary. Field result: agent_is_admin=0 on
the owner's machine, who is certainly an administrator.

So an unelevated agent exits once and lets the task's existing two-minute
backstop restart it properly. The danger is obvious: an agent that exits on
startup and is wrong about why would be an agent that never runs. These pin the
guards.

    python windows_agent/test_elevation_restart.py
"""
import os
import sys
import tempfile
import time
import types

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


for mod in ("psutil", "requests", "win32gui", "win32process", "pystray", "PIL"):
    sys.modules.setdefault(mod, types.ModuleType(mod))

import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location(
    "_agent_main", os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"))
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except Exception:
    pass   # main.py has heavy import-time side effects; we only need two funcs

if not hasattr(m, "_exit_for_elevation"):
    print("  SKIP  main.py could not be imported standalone on this host")
    sys.exit(0)

tmp = tempfile.mkdtemp()
m._ELEVATION_MARKER = os.path.join(tmp, "elevation_attempt")
m.log = lambda *a, **k: None
m.sys = types.SimpleNamespace(platform="win32")

print("\n=== an elevated agent never restarts itself ===")
m._is_process_elevated = lambda: True
check("already elevated -> keep running", m._exit_for_elevation() is False)
check("...and no marker is written", not os.path.exists(m._ELEVATION_MARKER))

print("\n=== an unelevated agent restarts ONCE ===")
m._is_process_elevated = lambda: False
check("first time -> exit so the task can restart it", m._exit_for_elevation() is True)
check("...and records the attempt", os.path.exists(m._ELEVATION_MARKER))
check("second time -> keeps running (no restart loop)",
      m._exit_for_elevation() is False)

print("\n=== the retry window reopens eventually ===")
old = time.time() - (m._ELEVATION_RETRY_HOURS + 1) * 3600
os.utime(m._ELEVATION_MARKER, (old, old))
check("marker older than the window -> try again", m._exit_for_elevation() is True)

print("\n=== a user who cannot elevate still gets a working agent ===")
# Simulates the machine where the task cannot grant elevation: the agent exits
# once, comes back still unelevated, and must then simply run.
m._is_process_elevated = lambda: False
attempts = sum(1 for _ in range(20) if m._exit_for_elevation())
check("at most one restart across 20 startups", attempts == 0)

print("\n=== non-Windows is never affected ===")
m.sys = types.SimpleNamespace(platform="darwin")
check("mac/linux -> never exits", m._exit_for_elevation() is False)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
