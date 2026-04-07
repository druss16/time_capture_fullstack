import os
import sys
import time
import json
import subprocess
import logging
import urllib.request
import psutil
from logging.handlers import RotatingFileHandler

AGENT_EXE_NAME     = "TimeTrackerAgent.exe"
WATCHDOG_EXE_NAME  = "tt_watchdog.exe"
CHECK_INTERVAL     = 60
STARTUP_GRACE      = 30
MAX_START_ATTEMPTS = 5
BACKOFF_SLEEP      = 300
API_BASE           = "https://timetracker-api-k375.onrender.com/api"

APPDATA   = os.environ.get("APPDATA", os.path.expanduser("~"))
LOG_DIR   = os.path.join(APPDATA, "TimeTracker", "Logs")
LOG_FILE  = os.path.join(LOG_DIR, "watchdog.log")

_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

WATCHDOG_TASK_NAME = "TimeTrackerWatchdog"
AGENT_TASK_NAME    = "TimeTrackerAgent"


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2*1024*1024, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger = logging.getLogger("tt_watchdog")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger

logger = setup_logging()

def log(msg: str):
    logger.info(msg)
    print(msg, flush=True)


def _get_device_id() -> str:
    config_path = os.path.join(
        os.path.expanduser("~"), ".timetracker", "config.json"
    )
    try:
        with open(config_path) as f:
            cfg = json.load(f)
            return cfg.get("server_device_id") or cfg.get("device_id") or ""
    except Exception:
        return ""


def check_kill_command() -> bool:
    """
    Poll backend for remote kill command.
    This is the out-of-band kill — works even when agent loop is frozen.
    """
    device_id = _get_device_id()
    if not device_id:
        return False
    try:
        url = f"{API_BASE}/watchdog/command/?device_id={device_id}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return bool(data.get("kill"))
    except Exception:
        return False


def kill_all_agent_processes():
    """Force-kill ALL TimeTrackerAgent.exe processes via psutil."""
    killed = 0
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if AGENT_EXE_NAME.lower() in (proc.info["name"] or "").lower():
                    proc.kill()
                    killed += 1
                    log(f"[WATCHDOG] Killed PID {proc.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        log(f"[WATCHDOG] Error killing processes: {e}")
    return killed


def find_agent_exe() -> str:
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(
            os.path.join(os.path.dirname(sys.executable), AGENT_EXE_NAME)
        )
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidates += [
        os.path.join(localappdata, "TimeTracker", AGENT_EXE_NAME),
        os.path.join("C:\\Program Files", "TimeTracker", AGENT_EXE_NAME),
        os.path.join("C:\\Program Files (x86)", "TimeTracker", AGENT_EXE_NAME),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def is_agent_running() -> bool:
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                if AGENT_EXE_NAME.lower() in (proc.info["name"] or "").lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        log(f"[WATCHDOG] Error checking processes: {e}")
    return False


def start_agent(agent_exe: str) -> bool:
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


def register_watchdog_task(log_fn=print):
    """
    Called by agent on startup — tries to register tasks.
    Fails silently on domain machines (GPO handles it).
    Only tries once per session.
    """
    if sys.platform != "win32":
        return
    if getattr(register_watchdog_task, '_done', False):
        return
    register_watchdog_task._done = True

    install_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, 'frozen', False)
        else os.path.join(os.environ.get("LOCALAPPDATA", ""), "TimeTracker")
    )

    for task_name, exe_name in [
        (WATCHDOG_TASK_NAME, WATCHDOG_EXE_NAME),
        (AGENT_TASK_NAME,    AGENT_EXE_NAME),
    ]:
        exe_path = os.path.join(install_dir, exe_name)
        if not os.path.exists(exe_path):
            log_fn(f"[WATCHDOG-TASK] ⚠️ {exe_name} not found — skipping")
            continue
        if _task_exists(task_name):
            log_fn(f"[WATCHDOG-TASK] ✅ {task_name} already registered")
            continue
        try:
            r = subprocess.run(
                [
                    "schtasks", "/Create",
                    "/TN", task_name,
                    "/TR", f'"{exe_path}"',
                    "/SC", "ONLOGON",
                    "/RL", "LIMITED",
                    "/F",
                ],
                capture_output=True, text=True, timeout=30,
                creationflags=_NO_WINDOW,
            )
            if r.returncode == 0:
                log_fn(f"[WATCHDOG-TASK] ✅ Registered: {task_name}")
            else:
                log_fn(f"[WATCHDOG-TASK] ⚠️ Failed: {r.stderr.strip()}")
        except Exception as e:
            log_fn(f"[WATCHDOG-TASK] ❌ Exception: {e}")


def unregister_watchdog_task(log_fn=print):
    for task in [WATCHDOG_TASK_NAME, AGENT_TASK_NAME]:
        try:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", task, "/F"],
                capture_output=True, timeout=10,
                creationflags=_NO_WINDOW,
            )
            log_fn(f"[WATCHDOG-TASK] 🗑️ Removed: {task}")
        except Exception as e:
            log_fn(f"[WATCHDOG-TASK] Failed to remove {task}: {e}")


def run_watchdog():
    log("=" * 60)
    log(f"[WATCHDOG] TimeTracker External Watchdog starting")
    log(f"[WATCHDOG] PID: {os.getpid()}, checking every {CHECK_INTERVAL}s")
    log("=" * 60)

    # Try task registration once — fails silently on domain machines
    register_watchdog_task(log_fn=log)

    agent_exe = find_agent_exe()
    if not agent_exe:
        log(f"[WATCHDOG] ⚠️ Could not find {AGENT_EXE_NAME} — will keep retrying")

    consecutive_failures = 0

    while True:
        try:
            # ── Check for remote kill command ─────────────────────────
            if check_kill_command():
                log("[WATCHDOG] 🔴 Kill command received — killing all agent processes")
                killed = kill_all_agent_processes()
                log(f"[WATCHDOG] Killed {killed} process(es) — waiting for restart")
                time.sleep(STARTUP_GRACE)

            # ── Re-find exe each loop (handles updates) ───────────────
            if not agent_exe or not os.path.exists(agent_exe):
                agent_exe = find_agent_exe()
                if not agent_exe:
                    log(f"[WATCHDOG] ⚠️ {AGENT_EXE_NAME} not found — waiting")
                    time.sleep(CHECK_INTERVAL)
                    continue

            # ── Check if agent is running ─────────────────────────────
            if is_agent_running():
                if consecutive_failures > 0:
                    log(f"[WATCHDOG] ✅ Agent is running again")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                log(f"[WATCHDOG] ⚠️ Agent NOT running (attempt {consecutive_failures})")

                if consecutive_failures >= MAX_START_ATTEMPTS:
                    log(f"[WATCHDOG] 🛑 {consecutive_failures} failed starts — backing off {BACKOFF_SLEEP}s")
                    consecutive_failures = 0
                    time.sleep(BACKOFF_SLEEP)
                    continue

                if start_agent(agent_exe):
                    log(f"[WATCHDOG] ✅ Agent started — waiting {STARTUP_GRACE}s")
                    time.sleep(STARTUP_GRACE)
                    continue

        except Exception as e:
            log(f"[WATCHDOG] ❌ Loop error: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    if "--unregister-task" in sys.argv:
        unregister_watchdog_task()
        sys.exit(0)
    run_watchdog()