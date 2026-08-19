"""
Tests for how the watchdog starts the agent.

WHY THIS EXISTS
---------------
The watchdog now starts the agent through its scheduled task rather than by
launching the executable, so the agent inherits the task's HighestAvailable run
level instead of the watchdog's least-privilege token.

That change touches the watchdog's ONE critical job: making sure an agent is
running. The dangerous case is quiet — the agent task is registered
MultipleInstancesPolicy=IgnoreNew, so if Task Scheduler still believes an
instance is running (stale state after a kill, exactly what the watchdog exists
to recover from) it accepts the request, starts nothing, and exits zero. A
watchdog that trusted that exit code would report success while the agent
stayed down.

These pin that it falls back instead.

    python windows_agent/test_watchdog_start.py
"""
import os
import sys
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


# psutil is a Windows-agent dependency and need not exist on this host; the
# watchdog imports it at module scope.
try:
    import psutil  # noqa: F401
except ImportError:
    sys.modules['psutil'] = types.SimpleNamespace(
        process_iter=lambda *a, **k: [],
        NoSuchProcess=Exception, AccessDenied=Exception, Process=object,
    )

import subprocess as _sp  # noqa: E402
# Windows-only creationflags the watchdog passes to Popen. Absent on this host,
# and evaluating them would raise before Popen is ever reached — which would
# make the fallback look broken when it is not.
for _flag, _val in (('DETACHED_PROCESS', 0x00000008),
                    ('CREATE_NEW_PROCESS_GROUP', 0x00000200)):
    if not hasattr(_sp, _flag):
        setattr(_sp, _flag, _val)

import tt_watchdog as w  # noqa: E402


class _Result:
    def __init__(self, rc):
        self.returncode = rc
        self.stdout = self.stderr = ''


def run_case(task_rc, agent_appears, popen_raises=False):
    """Returns (result, used_task, used_popen)."""
    calls = {'task': False, 'popen': False}

    def fake_run(cmd, **kw):
        if cmd[:2] == ["schtasks", "/Run"]:
            calls['task'] = True
            if task_rc is None:
                raise OSError("schtasks missing")
            return _Result(task_rc)
        return _Result(0)

    def fake_popen(*a, **k):
        calls['popen'] = True
        if popen_raises:
            raise OSError("cannot exec")
        return object()

    w.subprocess.run, w.subprocess.Popen = fake_run, fake_popen
    w.is_agent_running = lambda: agent_appears
    w.time.sleep = lambda *_: None
    w.log = lambda *_: None
    try:
        res = w.start_agent(r"C:\x\TimeTrackerAgent.exe")
    finally:
        pass
    return res, calls['task'], calls['popen']


print("\n=== the task route is preferred ===")
ok, task, popen = run_case(task_rc=0, agent_appears=True)
check("task is tried first", task)
check("agent appeared -> reports success", ok is True)
check("...and no direct launch was needed", popen is False)

print("\n=== THE DANGEROUS CASE: task says OK but starts nothing ===")
ok, task, popen = run_case(task_rc=0, agent_appears=False)
check("does NOT trust the zero exit code", popen is True)
check("falls back to a direct launch", popen is True)
check("still reports the agent started", ok is True)

print("\n=== ordinary failures still fall back ===")
ok, task, popen = run_case(task_rc=1, agent_appears=False)
check("task missing / refused -> direct launch", popen is True and ok is True)
ok, task, popen = run_case(task_rc=None, agent_appears=False)
check("schtasks raising -> direct launch", popen is True and ok is True)

print("\n=== the agent never silently stays down ===")
ok, task, popen = run_case(task_rc=1, agent_appears=False, popen_raises=True)
check("both routes fail -> reports FAILURE so the watchdog retries", ok is False)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
