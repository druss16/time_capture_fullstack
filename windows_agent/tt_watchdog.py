"""
tt_watchdog_gpo.py — GPO-deployable watchdog registration

TWO DEPLOYMENT PATHS:
─────────────────────
Path A (Current / self-registering):
  Agent calls register_watchdog_task() on startup.
  Works fine for manual installs. Fails if agent never runs as admin.

Path B (GPO / Intune / MSI — RECOMMENDED for enterprise):
  IT drops a .xml task file into the package.
  GPO imports it via: schtasks /Create /XML watchdog_task.xml /TN TimeTrackerWatchdog
  No dependency on agent running first. Survives agent crashes before first run.

This file generates the XML for Path B and also hardens Path A.
"""

import os
import sys
import subprocess
import getpass
import tempfile
import logging

APPDATA       = os.environ.get("APPDATA", os.path.expanduser("~"))
LOCALAPPDATA  = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
_NO_WINDOW    = 0x08000000 if sys.platform == 'win32' else 0

WATCHDOG_TASK_NAME = "TimeTrackerWatchdog"
AGENT_TASK_NAME    = "TimeTrackerAgent"


def _find_exe(exe_name: str) -> str:
    """Find an exe relative to current executable or common install paths."""
    candidates = []

    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), exe_name))

    candidates += [
        os.path.join(LOCALAPPDATA, "TimeTracker", exe_name),
        os.path.join("C:\\Program Files", "TimeTracker", exe_name),
        os.path.join("C:\\Program Files (x86)", "TimeTracker", exe_name),
        os.path.join("C:\\TimeTracker", exe_name),
    ]

    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def build_watchdog_task_xml(watchdog_exe: str, username: str) -> str:
    """
    Build the Task Scheduler XML for the watchdog.

    Key settings vs the old version:
    - RegistrationTrigger fires every 2 min (catches post-crash restarts)
    - LogonTrigger for the specific user
    - ExecutionTimeLimit PT0S = no timeout (runs forever)
    - RestartOnFailure every 1 min, up to 10 times
    - MultipleInstancesPolicy = IgnoreNew (only one instance)
    """
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>TimeTracker Watchdog — ensures TimeTrackerAgent is always running</Description>
    <Author>MavOps AI</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{username}</UserId>
      <Delay>PT15S</Delay>
    </LogonTrigger>
    <RegistrationTrigger>
      <Enabled>true</Enabled>
      <Delay>PT10S</Delay>
    </RegistrationTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT2M</Interval>
        <Duration>P9999D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2024-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{username}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>6</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>10</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{watchdog_exe}</Command>
      <WorkingDirectory>{os.path.dirname(watchdog_exe)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def build_agent_task_xml(agent_exe: str, username: str) -> str:
    """
    Task XML for the agent itself — also GPO-deployable.
    Same structure as watchdog but points at TimeTrackerAgent.exe.
    """
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>TimeTracker Agent — activity tracking for CPA time billing</Description>
    <Author>MavOps AI</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{username}</UserId>
      <Delay>PT5S</Delay>
    </LogonTrigger>
    <RegistrationTrigger>
      <Enabled>true</Enabled>
      <Delay>PT5S</Delay>
    </RegistrationTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{username}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>6</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{agent_exe}</Command>
      <WorkingDirectory>{os.path.dirname(agent_exe)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def _task_exists(task_name: str) -> bool:
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def _register_task_from_xml(task_name: str, xml: str, log_fn=print) -> bool:
    """Write XML to temp file and register with schtasks."""
    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False,
            encoding="utf-16", prefix=f"tt_task_{task_name}_"
        )
        tmp.write(xml)
        tmp.close()

        r = subprocess.run(
            ["schtasks", "/Create", "/TN", task_name, "/XML", tmp.name, "/F"],
            capture_output=True, text=True, timeout=30,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            log_fn(f"[TASK] ✅ Registered: {task_name}")
            return True
        else:
            log_fn(f"[TASK] ⚠️ Failed to register {task_name}: {r.stderr.strip()}")
            return False
    except Exception as e:
        log_fn(f"[TASK] ❌ Exception registering {task_name}: {e}")
        return False
    finally:
        if tmp and os.path.exists(tmp.name):
            try:
                os.unlink(tmp.name)
            except Exception:
                pass


def export_task_xmls(output_dir: str, log_fn=print):
    """
    Export both task XMLs to output_dir for GPO/Intune packaging.

    Call this from your build script:
        python tt_watchdog_gpo.py --export C:\\build\\tasks

    IT then imports these via GPO:
        Computer Config → Preferences → Control Panel → Scheduled Tasks
        or: schtasks /Create /XML agent_task.xml /TN TimeTrackerAgent
    """
    os.makedirs(output_dir, exist_ok=True)

    # Use placeholder paths — IT will adjust or MSI sets real paths
    localappdata = "%LOCALAPPDATA%"
    agent_exe    = f"{localappdata}\\TimeTracker\\TimeTrackerAgent.exe"
    watchdog_exe = f"{localappdata}\\TimeTracker\\tt_watchdog.exe"
    username     = "%USERNAME%"  # GPO expands this per-user

    agent_xml    = build_agent_task_xml(agent_exe, username)
    watchdog_xml = build_watchdog_task_xml(watchdog_exe, username)

    agent_out    = os.path.join(output_dir, "TimeTrackerAgent_task.xml")
    watchdog_out = os.path.join(output_dir, "TimeTrackerWatchdog_task.xml")

    with open(agent_out, "w", encoding="utf-16") as f:
        f.write(agent_xml)
    with open(watchdog_out, "w", encoding="utf-16") as f:
        f.write(watchdog_xml)

    log_fn(f"[EXPORT] ✅ Agent task XML:    {agent_out}")
    log_fn(f"[EXPORT] ✅ Watchdog task XML: {watchdog_out}")
    log_fn("")
    log_fn("GPO deployment steps:")
    log_fn("  1. Add both XMLs to your GPO package")
    log_fn("  2. Computer Config → Preferences → Control Panel → Scheduled Tasks")
    log_fn("  3. New → Scheduled Task (At least Windows 7)")
    log_fn("  4. Action: Create, import XML, set 'Run only when user is logged on'")
    log_fn("  OR via PowerShell startup script:")
    log_fn("     schtasks /Create /XML TimeTrackerAgent_task.xml /TN TimeTrackerAgent /F")
    log_fn("     schtasks /Create /XML TimeTrackerWatchdog_task.xml /TN TimeTrackerWatchdog /F")

    return agent_out, watchdog_out


def register_watchdog_task(log_fn=print):
    """
    Hardened version of register_watchdog_task().
    Replaces the version in tt_watchdog.py.

    Registers BOTH the watchdog task AND the agent task — so even if
    GPO hasn't pre-deployed them, the agent bootstraps both on first run.
    """
    if sys.platform != "win32":
        return

    domain   = os.environ.get("USERDOMAIN", "")
    username = getpass.getuser()
    full_user = f"{domain}\\{username}" if domain and domain.lower() != username.lower() else username

    # ── Register watchdog task ──────────────────────────────────────────────
    watchdog_exe = _find_exe("tt_watchdog.exe")
    if not watchdog_exe:
        log_fn("[TASK] ⚠️ tt_watchdog.exe not found — skipping watchdog task registration")
    else:
        if _task_exists(WATCHDOG_TASK_NAME):
            log_fn(f"[TASK] ✅ {WATCHDOG_TASK_NAME} already registered")
        else:
            xml = build_watchdog_task_xml(watchdog_exe, full_user)
            _register_task_from_xml(WATCHDOG_TASK_NAME, xml, log_fn)

    # ── Register agent task (self-healing) ─────────────────────────────────
    # This ensures the agent itself has a Task Scheduler entry even if
    # startup_task.py failed or GPO hasn't been applied yet.
    agent_exe = _find_exe("TimeTrackerAgent.exe")
    if not agent_exe:
        log_fn("[TASK] ⚠️ TimeTrackerAgent.exe not found — skipping agent task registration")
    else:
        if _task_exists(AGENT_TASK_NAME):
            log_fn(f"[TASK] ✅ {AGENT_TASK_NAME} already registered")
        else:
            xml = build_agent_task_xml(agent_exe, full_user)
            _register_task_from_xml(AGENT_TASK_NAME, xml, log_fn)


def unregister_all_tasks(log_fn=print):
    """Called by uninstaller."""
    for task in [WATCHDOG_TASK_NAME, AGENT_TASK_NAME]:
        try:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", task, "/F"],
                capture_output=True, timeout=10,
                creationflags=_NO_WINDOW,
            )
            log_fn(f"[TASK] 🗑️ Removed: {task}")
        except Exception as e:
            log_fn(f"[TASK] Failed to remove {task}: {e}")


# ── CLI for build pipeline ────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", metavar="DIR",
                        help="Export task XMLs for GPO packaging")
    parser.add_argument("--register", action="store_true",
                        help="Register tasks on this machine now")
    parser.add_argument("--unregister", action="store_true",
                        help="Remove all TimeTracker tasks")
    args = parser.parse_args()

    if args.export:
        export_task_xmls(args.export)
    elif args.register:
        register_watchdog_task()
    elif args.unregister:
        unregister_all_tasks()
    else:
        parser.print_help()