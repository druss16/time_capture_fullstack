#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tt_watchdog.py — TimeTracker External Process Watchdog
=======================================================
A tiny, separate process whose ONLY job is to make sure
TimeTrackerAgent.exe is always running.

This is the same architecture used by Chrome, Dropbox, OneDrive, and
every other enterprise app that must always be running. They don't
trust in-process watchdogs — they use a separate guardian process.

HOW IT WORKS:
  - Runs as its own Task Scheduler task (tt_watchdog_task)
  - Every 60 seconds: checks if TimeTrackerAgent.exe is running
  - If not running: starts it
  - That's it. Nothing else. Can't freeze because it does nothing else.
  - Even if the agent process is completely hung/frozen, the watchdog
    is unaffected — separate process, separate memory space.

TWO-TASK ARCHITECTURE:
  Task 1: TimeTrackerAgent  — runs the actual agent
  Task 2: TimeTrackerWatchdog — watches the agent, restarts if needed

  Neither can take down the other. If the agent freezes, the internal
  heartbeat watchdog calls os._exit(1). If that fails for any reason,
  the external watchdog sees the process is gone within 60s and restarts it.

BUILD (PyInstaller):
  pyinstaller --onefile --noconsole --name tt_watchdog tt_watchdog.py

  This produces tt_watchdog.exe (~8MB) — ship it alongside TimeTrackerAgent.exe

INSTALL:
  Called automatically by TimeTrackerAgent on startup via
  register_watchdog_task(). No manual setup needed.
"""

import os
import sys
import time
import subprocess
import logging
import getpass
import platform
import tempfile
import psutil
from logging.handlers import RotatingFileHandler
from datetime import datetime
import json


# ── Config ────────────────────────────────────────────────────────────────────
AGENT_EXE_NAME     = "TimeTrackerAgent.exe"
WATCHDOG_EXE_NAME  = "tt_watchdog.exe"
CHECK_INTERVAL     = 60        # Seconds between checks
STARTUP_GRACE      = 30        # Seconds to wait after starting agent before checking again
MAX_START_ATTEMPTS = 5         # Max consecutive start attempts before backing off
BACKOFF_SLEEP      = 300       # 5 min backoff after too many failed starts

# ── Logging ───────────────────────────────────────────────────────────────────
APPDATA   = os.environ.get("APPDATA", os.path.expanduser("~"))
LOG_DIR   = os.path.join(APPDATA, "TimeTracker", "Logs")
LOG_FILE  = os.path.join(LOG_DIR, "watchdog.log")

# Hide terminal windows from end users
_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2*1024*1024, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    log = logging.getLogger("tt_watchdog")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    return log

logger = setup_logging()

def log(msg: str):
    logger.info(msg)
    # Also print so it shows in Task Scheduler history
    print(msg, flush=True)


# ── Agent detection ───────────────────────────────────────────────────────────

def find_agent_exe() -> str:
    """
    Find TimeTrackerAgent.exe path.
    - If we're a frozen exe, look in our own directory first
    - Then check common install locations
    """
    candidates = []

    # Same directory as this watchdog exe
    if getattr(sys, 'frozen', False):
        candidates.append(
            os.path.join(os.path.dirname(sys.executable), AGENT_EXE_NAME)
        )

    # Common install locations
    localappdata = os.environ.get("LOCALAPPDATA", "")
    programfiles = os.environ.get("PROGRAMFILES", "C:\\Program Files")
    programfiles_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")

    candidates += [
        os.path.join(localappdata, "TimeTracker", AGENT_EXE_NAME),
        os.path.join(programfiles, "TimeTracker", AGENT_EXE_NAME),
        os.path.join(programfiles_x86, "TimeTracker", AGENT_EXE_NAME),
        os.path.join("C:\\", "TimeTracker", AGENT_EXE_NAME),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def is_agent_running() -> bool:
    """Check if TimeTrackerAgent.exe is currently running."""
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = (proc.info.get("name") or "").lower()
                exe  = (proc.info.get("exe")  or "").lower()
                if AGENT_EXE_NAME.lower() in name or AGENT_EXE_NAME.lower() in exe:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        log(f"[WATCHDOG] Error checking processes: {e}")
    return False


def start_agent(agent_exe: str) -> bool:
    """Start the agent process."""
    try:
        log(f"[WATCHDOG] 🚀 Starting agent: {agent_exe}")
        subprocess.Popen(
            [agent_exe],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        return True
    except Exception as e:
        log(f"[WATCHDOG] ❌ Failed to start agent: {e}")
        return False


# ── Main watchdog loop ────────────────────────────────────────────────────────

def check_pending_update():
    flag_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "TimeTracker",
        "pending_update.json"
    )
    if not os.path.exists(flag_path):
        return
    try:
        with open(flag_path) as f:
            data = json.load(f)
        installer = data.get("installer")
        version = data.get("version")
        if not installer or not os.path.exists(installer):
            os.remove(flag_path)
            return
        log(f"[WATCHDOG] 🔄 Pending update to v{version} — launching installer")
        os.remove(flag_path)
        import ctypes
        log_path = os.path.join(os.environ.get("TEMP", ""), f"TimeTrackerInstall-{version}.log")
        params = f'/VERYSILENT /NORESTART /LOG="{log_path}"'
        result = ctypes.windll.shell32.ShellExecuteW(None, "open", installer, params, None, 0)
        log(f"[WATCHDOG] Installer launched (result={result}) — waiting 120s")
        time.sleep(120)
        log(f"[WATCHDOG] ✅ Update complete")
    except Exception as e:
        log(f"[WATCHDOG] ❌ Pending update failed: {e}")

def run_watchdog():
    log("=" * 60)
    log(f"[WATCHDOG] TimeTracker External Watchdog starting")
    log(f"[WATCHDOG] PID: {os.getpid()}, checking every {CHECK_INTERVAL}s")
    log("=" * 60)

    check_pending_update()  # ← ADD THIS

    agent_exe = find_agent_exe()
    if not agent_exe:
        log(f"[WATCHDOG] ❌ Could not find {AGENT_EXE_NAME} — will keep retrying")

    consecutive_failures = 0

    while True:
        try:
            # Re-find exe each loop in case of update/reinstall
            if not agent_exe or not os.path.exists(agent_exe):
                agent_exe = find_agent_exe()
                if not agent_exe:
                    log(f"[WATCHDOG] ⚠️ {AGENT_EXE_NAME} not found — waiting {CHECK_INTERVAL}s")
                    time.sleep(CHECK_INTERVAL)
                    continue

            if is_agent_running():
                # All good — reset failure counter
                if consecutive_failures > 0:
                    log(f"[WATCHDOG] ✅ Agent is running again")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                log(f"[WATCHDOG] ⚠️ Agent NOT running (attempt {consecutive_failures})")

                if consecutive_failures >= MAX_START_ATTEMPTS:
                    log(f"[WATCHDOG] 🛑 {consecutive_failures} failed attempts — backing off {BACKOFF_SLEEP}s")
                    consecutive_failures = 0
                    time.sleep(BACKOFF_SLEEP)
                    continue

                success = start_agent(agent_exe)
                if success:
                    log(f"[WATCHDOG] ✅ Agent started — waiting {STARTUP_GRACE}s")
                    time.sleep(STARTUP_GRACE)  # Give it time to initialize
                    continue

        except Exception as e:
            log(f"[WATCHDOG] ❌ Watchdog loop error: {e}")

        time.sleep(CHECK_INTERVAL)


# ── Task Scheduler registration ───────────────────────────────────────────────

WATCHDOG_TASK_NAME = "TimeTrackerWatchdog"

def _build_watchdog_task_xml(exe_path: str, username: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>TimeTracker Watchdog — ensures the agent is always running</Description>
    <Author>MavOps AI</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{username}</UserId>
      <Delay>PT10S</Delay>
    </LogonTrigger>
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
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>10</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe_path}</Command>
      <WorkingDirectory>{os.path.dirname(exe_path)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def register_watchdog_task():
    """
    Register the watchdog's OWN Task Scheduler task.
    Called by the agent on startup — self-bootstrapping.
    """
    if sys.platform != "win32":
        return

    try:
        # Find our own exe
        if getattr(sys, "frozen", False):
            watchdog_exe = os.path.join(
                os.path.dirname(sys.executable), WATCHDOG_EXE_NAME
            )
        else:
            # Dev mode — not meaningful but don't crash
            log("[WATCHDOG-TASK] Dev mode — skipping task registration")
            return

        if not os.path.exists(watchdog_exe):
            log(f"[WATCHDOG-TASK] ⚠️ {WATCHDOG_EXE_NAME} not found at {watchdog_exe} — skipping")
            return

        # Check if already registered
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", WATCHDOG_TASK_NAME],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if result.returncode == 0:
            log(f"[WATCHDOG-TASK] ✅ Watchdog task already registered")
            return

        domain   = os.environ.get("USERDOMAIN", "")
        username = getpass.getuser()
        full_user = f"{domain}\\{username}" if domain and domain.lower() != username.lower() else username

        xml = _build_watchdog_task_xml(watchdog_exe, full_user)

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False,
            encoding="utf-16", prefix="tt_wd_task_"
        )
        tmp.write(xml)
        tmp.close()

        result = subprocess.run(
            ["schtasks", "/Create", "/TN", WATCHDOG_TASK_NAME, "/XML", tmp.name, "/F"],
            capture_output=True, text=True, timeout=30,
            creationflags=_NO_WINDOW,
        )
        os.unlink(tmp.name)

        if result.returncode == 0:
            log(f"[WATCHDOG-TASK] ✅ Watchdog task registered")
        else:
            log(f"[WATCHDOG-TASK] ⚠️ Failed: {result.stderr.strip()}")

    except Exception as e:
        log(f"[WATCHDOG-TASK] ❌ Exception: {e}")


def unregister_watchdog_task():
    """Called by uninstaller."""
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", WATCHDOG_TASK_NAME, "/F"],
            capture_output=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        log(f"[WATCHDOG-TASK] 🗑️ Watchdog task removed")
    except Exception as e:
        log(f"[WATCHDOG-TASK] Failed to remove: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--unregister-task" in sys.argv:
        unregister_watchdog_task()
        sys.exit(0)
    run_watchdog()