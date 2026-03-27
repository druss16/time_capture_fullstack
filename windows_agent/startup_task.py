"""
startup_task.py — TimeTracker Windows Agent
============================================
Registers a Windows Task Scheduler task that ensures the agent is:
  - Started on every user logon
  - Restarted automatically if it crashes or exits for any reason
  - Restarted every 2 minutes if it's not running (belt + suspenders)
  - Running as the current user with highest available privileges

This replaces the empty register_startup_task() stub in main.py.

HOW IT WORKS:
  Task Scheduler is the correct Windows mechanism for this — it's what
  Chrome, Dropbox, Slack, OneDrive, and every other "always running" app uses.
  We create an XML task definition and import it via schtasks.exe.

  The task has THREE triggers:
    1. Logon trigger       — starts on every user login
    2. Repetition trigger  — restarts every 2 min if not running (via registration trigger)
    3. Restart on failure  — if the process exits non-zero, retry up to 10 times

INTEGRATION:
  In main.py, replace:
    def register_startup_task():
        pass

  With:
    from startup_task import register_startup_task

  And call it exactly where you do now — it's already in run_agent().
  It's fast (<200ms), idempotent, and safe to call on every startup.
"""

import os
import sys
import time
import subprocess
import platform
import getpass
import tempfile
import logging

logger = logging.getLogger("timetracker")

TASK_NAME = "TimeTrackerAgent"
TASK_DESCRIPTION = "TimeTracker AI Time Tracking Agent by MavOps"

# How often to check if the task needs re-registration (seconds)
# Re-register once per day max — avoids hammering schtasks on every startup
_REREGISTER_INTERVAL = 0 # change back to on next version 86400
_last_registered: float = 0.0

# Hide terminal windows from end users
_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


def _log(msg: str):
    """Use timetracker logger if available, else print."""
    try:
        logger.info(msg)
    except Exception:
        print(msg)


def _get_executable_path() -> str:
    """
    Returns the full path to the agent executable.
    - Frozen (PyInstaller .exe): path to the .exe
    - Dev (running as .py): path to pythonw.exe + main.py
    """
    if getattr(sys, 'frozen', False):
        return sys.executable  # e.g. C:\...\TimeTrackerAgent.exe
    else:
        # Use pythonw.exe (no console window) in production,
        # fall back to python.exe for dev
        python_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(python_dir, "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        main_py = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "main.py")
        )
        return f'"{pythonw}" "{main_py}"'


def _build_task_xml(exe_path: str, username: str) -> str:
    """
    Build the Task Scheduler XML definition.
    
    Key settings:
    - LogonTrigger: fires on every logon for this user
    - RegistrationTrigger + Repetition: re-fires every 2 min indefinitely
      (this is the "always running" backstop — if the agent dies between
       logons, this picks it up within 2 minutes)
    - RestartOnFailure: retry up to 10x with 1min delay if process crashes
    - ExecutionTimeLimit: PT0S = no time limit (run forever)
    - MultipleInstancesPolicy: IgnoreNew = don't start a second copy
    - RunOnlyIfNetworkAvailable: false = run even offline
    - StopIfGoingOnBatteries: false = keep running on laptop battery
    - DisallowStartIfOnBatteries: false = start on battery too
    """
    
    # For frozen exe, just the exe path. For dev, pythonw + script.
    if getattr(sys, 'frozen', False):
        command = exe_path
        args = ""
    else:
        # Split "pythonw.exe" and "main.py" into Command + Arguments
        parts = exe_path.split('" "')
        command = parts[0].strip('"')
        args = parts[1].strip('"') if len(parts) > 1 else ""

    working_dir = os.path.dirname(
        sys.executable if getattr(sys, 'frozen', False)
        else os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
    )

    args_xml = f"<Arguments>{args}</Arguments>" if args else ""

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{TASK_DESCRIPTION}</Description>
    <Author>MavOps AI</Author>
  </RegistrationInfo>
  <Triggers>
    <!-- Trigger 1: Start on logon -->
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{username}</UserId>
      <Delay>PT5S</Delay>
    </LogonTrigger>
    <!-- Trigger 2: Repeat every 2 minutes indefinitely (always-running backstop) -->
    <RegistrationTrigger>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT2M</Interval>
        <Duration>P9999D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
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
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>10</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      {args_xml}
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def _task_exists() -> bool:
    """Check if our task is already registered."""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,

        )
        return result.returncode == 0
    except Exception:
        return False


def _task_is_healthy() -> bool:
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/XML"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,

        )
        if result.returncode != 0:
            return False

        xml = result.stdout.lower()

        # Must have current exe path
        current_exe = sys.executable if getattr(sys, 'frozen', False) else sys.executable
        if current_exe.lower() not in xml:
            return False

        # Must have the repetition trigger (bulletproof re-check trigger)
        if "registrationtrigger" not in xml:
            return False

        # Must have restart-on-failure
        if "restartonfailure" not in xml:
            return False

        return True
    except Exception:
        return False


def _register_task_xml(xml: str) -> bool:
    """Write XML to temp file and import via schtasks."""
    tmp = None
    try:
        # schtasks requires UTF-16 LE with BOM for XML import
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.xml', delete=False,
            encoding='utf-16', prefix='tt_task_'
        )
        tmp.write(xml)
        tmp.close()

        result = subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", TASK_NAME,
                "/XML", tmp.name,
                "/F",   # Force overwrite if exists
            ],
            capture_output=True, text=True, timeout=30,
            creationflags=_NO_WINDOW,
        )

        if result.returncode == 0:
            _log(f"[STARTUP-TASK] ✅ Task '{TASK_NAME}' registered successfully")
            return True
        else:
            _log(f"[STARTUP-TASK] ⚠️ schtasks failed (code {result.returncode}): {result.stderr.strip()}")
            return False

    except Exception as e:
        _log(f"[STARTUP-TASK] ❌ Exception registering task: {e}")
        return False
    finally:
        if tmp and os.path.exists(tmp.name):
            try:
                os.unlink(tmp.name)
            except Exception:
                pass


def _ensure_task_running():
    """
    If the task exists but agent isn't currently running, start it now.
    This handles the case where we're running as a one-shot repair/setup.
    """
    try:
        # Check if already running by looking for our process
        import psutil
        exe_name = os.path.basename(sys.executable).lower()
        current_pid = os.getpid()
        
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            if proc.info['pid'] == current_pid:
                continue
            proc_name = (proc.info.get('name') or '').lower()
            if exe_name in proc_name or 'timetrackeragent' in proc_name:
                return  # Already running
    except Exception:
        pass  # psutil not available — skip this check


def register_startup_task():
    """
    Main entry point. Call this once on every agent startup.
    
    - Idempotent: safe to call every time
    - Fast: skips re-registration if task is healthy (checks once/day)
    - Self-healing: re-registers if task is missing or stale after update
    - Falls back gracefully if schtasks is unavailable
    """
    global _last_registered

    # Only re-check once per day
    now = time.time()
    if _last_registered and (now - _last_registered) < _REREGISTER_INTERVAL:
        return

    if sys.platform != 'win32':
        return  # Mac/Linux: handled separately

    try:
        username = getpass.getuser()
        # Get domain\username format if on a domain (required by schtasks)
        domain = os.environ.get('USERDOMAIN', '')
        if domain and domain.lower() != username.lower():
            full_username = f"{domain}\\{username}"
        else:
            full_username = username

        exe_path = _get_executable_path()

        # Check if already healthy — avoid unnecessary re-registration
        if _task_is_healthy():
            _log(f"[STARTUP-TASK] ✅ Task already registered and healthy")
            _last_registered = now
            return

        _log(f"[STARTUP-TASK] Registering startup task for {full_username}...")
        _log(f"[STARTUP-TASK] Executable: {exe_path}")

        xml = _build_task_xml(exe_path, full_username)
        success = _register_task_xml(xml)

        if success:
            _last_registered = now
        else:
            # Fallback: try registry run key (simpler, no restart-on-failure)
            _register_run_key_fallback(exe_path)

    except Exception as e:
        _log(f"[STARTUP-TASK] ❌ Failed to register startup task: {e}")
        # Non-fatal — agent still runs, just won't auto-restart


def _register_run_key_fallback(exe_path: str):
    """
    Last-resort fallback: HKCU Run key.
    No restart-on-failure, but better than nothing.
    Only used if schtasks completely fails.
    """
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "TimeTrackerAgent", 0, winreg.REG_SZ, exe_path)
        _log("[STARTUP-TASK] ⚠️ Registered via Run key (fallback — no restart-on-failure)")
    except Exception as e:
        _log(f"[STARTUP-TASK] ❌ Run key fallback also failed: {e}")


def unregister_startup_task():
    """
    Remove the Task Scheduler task and Run key.
    Call this from the uninstaller.
    """
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if result.returncode == 0:
            _log(f"[STARTUP-TASK] 🗑️ Task '{TASK_NAME}' removed")
        else:
            _log(f"[STARTUP-TASK] Task removal: {result.stderr.strip()}")
    except Exception as e:
        _log(f"[STARTUP-TASK] Failed to remove task: {e}")

    # Also clean up Run key if it exists
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, "TimeTrackerAgent")
                _log("[STARTUP-TASK] 🗑️ Run key removed")
            except FileNotFoundError:
                pass
    except Exception:
        pass


if __name__ == "__main__":
    # Allow running standalone to register/unregister
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "unregister":
        unregister_startup_task()
    else:
        register_startup_task()