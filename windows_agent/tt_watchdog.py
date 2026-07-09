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

# ── Crash-loop self-heal ──────────────────────────────────────────────
# A plain restart cannot fix a bad *build* (e.g. an import-time crash) — it
# just relaunches the same broken exe forever. When the agent dies almost
# immediately after we start it, repeatedly, the watchdog stops restarting and
# instead tries to REPLACE the build. The watchdog is the right place for this:
# it is the process that does NOT crash, so it can cure one that does.
CRASH_WINDOW         = 45     # agent must survive at least this long, or it's a "fast crash"
CRASH_LOOP_THRESHOLD = 3      # this many fast crashes ⇒ bad build ⇒ attempt self-heal
SELF_HEAL_THROTTLE   = 1800   # at most one self-heal update attempt per 30 min

# ── Frozen-agent detection ────────────────────────────────────────────
# The agent stamps APPDATA/TimeTracker/agent.heartbeat from its in-process
# watchdog loop (~every 30s). If the process EXISTS but that stamp is stale, the
# whole process is wedged (classic sleep/wake hard freeze) — the case a plain
# "is the process there?" check misses. We kill the zombie so it gets restarted.
HEARTBEAT_FILE  = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "TimeTracker", "agent.heartbeat"
)
HEARTBEAT_STALE = 300         # no stamp for this long (with process alive) ⇒ frozen

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


def agent_heartbeat_age():
    """Seconds since the agent last stamped its disk heartbeat. Returns None if
    there's no readable stamp (older build that doesn't write one, or not written
    yet) — treated as 'unknown', i.e. NOT frozen, so we never kill an agent that
    simply doesn't pulse."""
    try:
        with open(HEARTBEAT_FILE) as f:
            ts = float(f.read().strip())
        return max(0.0, time.time() - ts)
    except Exception:
        return None


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


# Self-reviving watchdog task: starts at logon, re-checks every 5 min (so it
# comes back if it ever exits mid-session), and Task Scheduler restarts it every
# minute if it crashes. This is the SAME robust definition the GPO script uses —
# now applied on every machine, so staying alive no longer depends on GPO.
_WATCHDOG_TASK_XML = '''<?xml version="1.0"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>MavOps TimeTracker Watchdog - keeps the agent alive and self-heals bad builds</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><Delay>PT10S</Delay></LogonTrigger>
    <TimeTrigger>
      <Repetition><Interval>PT5M</Interval><Duration>P9999D</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <Enabled>true</Enabled><StartBoundary>2024-01-01T00:00:00</StartBoundary>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions>
    <Exec><Command>{exe_path}</Command></Exec>
  </Actions>
</Task>'''


def _register_robust_watchdog_task(exe_path: str, log_fn=print) -> bool:
    """Register the watchdog as a self-reviving Scheduled Task via XML.
    Uses /F so an existing WEAK (onlogon-only) task from an older build is
    UPGRADED in place. Best-effort: on a domain box where the user lacks rights
    to overwrite a GPO-owned task, this fails harmlessly (GPO's task — already
    robust — stays)."""
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "tt_watchdog_task.xml")
    try:
        # schtasks /Create /XML requires UTF-16LE with a BOM. A UTF-8 BOM
        # (utf-8-sig) is rejected with "The task XML is malformed. (1,2):
        # incorrect document syntax". Python's "utf-16" writes UTF-16LE+BOM.
        with open(tmp, "w", encoding="utf-16") as f:
            f.write(_WATCHDOG_TASK_XML.format(exe_path=exe_path))
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", WATCHDOG_TASK_NAME, "/XML", tmp, "/F"],
            capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            log_fn("[WATCHDOG-TASK] ✅ Watchdog task registered (repetition + restart-on-failure)")
            return True
        log_fn(f"[WATCHDOG-TASK] ⚠️ Robust register failed: {r.stderr.strip()}")
        return False
    except Exception as e:
        log_fn(f"[WATCHDOG-TASK] ❌ Robust register exception: {e}")
        return False
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def register_watchdog_task(log_fn=print):
    """
    Called by agent/watchdog on startup — registers the Scheduled Tasks.
    Only tries once per session.

    Watchdog task: robust XML (self-reviving) — always (re)applied so older
    machines with the weak onlogon-only task get upgraded. Agent task: a simple
    onlogon fallback; the watchdog is the primary supervisor.
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

    # Watchdog task — robust, always (re)applied to upgrade older weak tasks.
    # No separate agent task: the watchdog itself keeps the agent alive, and the
    # installer already creates a "MavOps TimeTracker" logon task for the agent.
    # (The old agent-task registration only produced a redundant "Access is
    # denied" and added nothing.)
    wd_exe = os.path.join(install_dir, WATCHDOG_EXE_NAME)
    if os.path.exists(wd_exe):
        _register_robust_watchdog_task(wd_exe, log_fn=log_fn)
    else:
        log_fn(f"[WATCHDOG-TASK] ⚠️ {WATCHDOG_EXE_NAME} not found — skipping")


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


def _acquire_singleton():
    """Ensure only ONE watchdog worker runs, no matter how many launch sources
    fire (Scheduled Task + HKCU Run key + agent mutual-supervision). A named
    mutex enforces it: the first worker holds it; later ones see it already
    exists and bow out. The --onefile bootloader never runs this code, so this
    counts real workers, not bootloader parents. Returns the mutex handle to
    keep alive for the process lifetime, or None if another worker already owns
    it (caller should exit)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\TimeTrackerWatchdogSingleton")
        if not handle:
            return True  # couldn't create the mutex — don't block startup
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return None  # another worker already holds it
        return handle
    except Exception:
        return True      # on any error, never block the watchdog from starting


def _install_runkey():
    """Add an HKCU Run entry so the watchdog starts at logon WITHOUT admin.

    This is the no-admin fallback for locked-down machines where schtasks needs
    elevation the standard user doesn't have. HKCU is the user's own registry
    hive — writable without elevation — so this always succeeds where the
    Scheduled Task can't be created. Best-effort; never raises."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        install_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.join(os.environ.get("LOCALAPPDATA", ""), "TimeTracker")
        )
        exe = os.path.join(install_dir, WATCHDOG_EXE_NAME)
        if not os.path.exists(exe):
            return
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        try:
            winreg.SetValueEx(key, WATCHDOG_TASK_NAME, 0, winreg.REG_SZ, f'"{exe}"')
            log("[WATCHDOG] ✅ HKCU Run entry ensured (no-admin logon start)")
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        log(f"[WATCHDOG] HKCU Run install failed (non-fatal): {e}")


def _installed_version() -> str:
    """The shipped version. Agent + watchdog ship together in one zip, so the
    watchdog's own version equals the (crashing) agent's version."""
    try:
        from version import APP_VERSION
        return APP_VERSION
    except Exception:
        return "dev"


def report_crash_loop(version: str, crashes: int):
    """Best-effort telemetry so a crash-looping fleet surfaces from monitoring
    instead of user complaints. Harmless no-op if the endpoint doesn't exist."""
    device_id = _get_device_id()
    if not device_id:
        return
    try:
        payload = json.dumps({
            "device_id":    device_id,
            "version":      version,
            "fast_crashes": crashes,
            "component":    AGENT_EXE_NAME,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/watchdog/crash-report/",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        log(f"[WATCHDOG] 📡 Reported crash-loop (v{version}, {crashes} fast crashes)")
    except Exception:
        # Endpoint may not exist yet — telemetry never blocks recovery.
        pass


def try_self_heal_update() -> bool:
    """Crash-loop cure: ask the backend for the latest build and, if newer,
    download + replace the crashing agent. Reuses the tested updater. Runs in
    the watchdog (the process that does NOT crash), so a broken agent build can
    be replaced with zero user action. Returns True if an update was launched."""
    version = _installed_version()
    if version in ("dev", "0.0.0", ""):
        log("[WATCHDOG] Self-heal skipped — dev/unknown build")
        return False
    try:
        from update_checker import check_version, _auto_update_windows
    except Exception as e:
        log(f"[WATCHDOG] Self-heal unavailable (update_checker import failed): {e}")
        return False
    try:
        data = check_version(API_BASE, version)
        if not data or not data.get("update_available"):
            log(f"[WATCHDOG] Self-heal: server reports no newer build than v{version}")
            return False
        latest  = data.get("latest_version", "unknown")
        url     = data.get("download_url", "")
        zip_url = data.get("zip_url", "")
        if not zip_url:
            log("[WATCHDOG] Self-heal: server gave no zip_url — cannot replace")
            return False
        log(f"[WATCHDOG] 🩹 Self-heal: replacing crashing v{version} with v{latest}")
        return _auto_update_windows(url, latest, zip_url=zip_url)
    except Exception as e:
        log(f"[WATCHDOG] Self-heal update failed: {e}")
        return False


def run_watchdog():
    # Singleton guard FIRST — a duplicate instance exits before doing anything,
    # so the task + run key + mutual supervision can't stack up watchdogs.
    _singleton = _acquire_singleton()
    if _singleton is None:
        log("[WATCHDOG] 🚦 Another watchdog is already running — exiting (singleton guard)")
        return

    log("=" * 60)
    log(f"[WATCHDOG] TimeTracker External Watchdog starting")
    log(f"[WATCHDOG] PID: {os.getpid()}, checking every {CHECK_INTERVAL}s")
    log("=" * 60)

    # Two logon-start paths, tried in order of strength:
    #   1. Scheduled Task — self-reviving (restart-on-failure), but needs
    #      elevation/GPO, so it silently fails on locked-down standard-user boxes.
    #   2. HKCU Run key — no admin ever, always works, but logon-start only.
    # Managed machines get #1; locked-down self-installs fall back to #2 (plus
    # the agent's mutual supervision for mid-session revival).
    register_watchdog_task(log_fn=log)
    _install_runkey()

    agent_exe = find_agent_exe()
    if not agent_exe:
        log(f"[WATCHDOG] ⚠️ Could not find {AGENT_EXE_NAME} — will keep retrying")

    consecutive_failures = 0    # can't-start-at-all counter
    fast_crashes         = 0    # agent starts then dies quickly ⇒ bad build
    last_start_time      = 0.0  # when the watchdog last launched the agent
    last_heal_attempt    = 0.0  # throttles self-heal update attempts

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

            # ── Agent process exists ──────────────────────────────────
            if is_agent_running():
                # Present but not pulsing? Whole-process freeze (sleep/wake) —
                # the in-process watchdog is wedged too, so kill it here and let
                # the not-running path below relaunch a fresh one. No human needed.
                hb = agent_heartbeat_age()
                if hb is not None and hb > HEARTBEAT_STALE:
                    log(f"[WATCHDOG] 🥶 Agent present but heartbeat stale ({int(hb)}s > {HEARTBEAT_STALE}s) — killing frozen agent")
                    kill_all_agent_processes()
                    fast_crashes = 0            # a freeze is not a build crash
                    time.sleep(3)
                    continue

                # Only "healthy" once it has survived past the crash window;
                # then clear crash counters so a later stop starts fresh.
                if last_start_time and (time.time() - last_start_time) >= CRASH_WINDOW:
                    if fast_crashes or consecutive_failures:
                        log("[WATCHDOG] ✅ Agent stable — clearing crash counters")
                    fast_crashes = 0
                    consecutive_failures = 0
                time.sleep(CHECK_INTERVAL)
                continue

            # ── Agent is NOT running ──────────────────────────────────
            # Did it die shortly after we launched it? That's a crash (bad
            # build), not a normal stop.
            if last_start_time and (time.time() - last_start_time) < CRASH_WINDOW:
                fast_crashes += 1
                log(f"[WATCHDOG] 💥 Agent died {int(time.time() - last_start_time)}s "
                    f"after start — fast crash #{fast_crashes}")

            # ── Crash loop ⇒ restarting won't help. REPLACE the build. ─
            if fast_crashes >= CRASH_LOOP_THRESHOLD:
                ver = _installed_version()
                log(f"[WATCHDOG] 🔁 Crash loop detected (v{ver}) — a restart can't fix a bad build")
                report_crash_loop(ver, fast_crashes)
                now = time.time()
                if now - last_heal_attempt >= SELF_HEAL_THROTTLE:
                    last_heal_attempt = now
                    if try_self_heal_update():
                        log("[WATCHDOG] 🩹 Update launched — exiting so the updater can swap files")
                        return  # updater's bat kills + relaunches the new watchdog
                else:
                    log("[WATCHDOG] Self-heal throttled — waiting before next attempt")
                log(f"[WATCHDOG] Backing off {BACKOFF_SLEEP}s")
                fast_crashes = 0
                time.sleep(BACKOFF_SLEEP)
                continue

            # ── Otherwise: normal "not running" → (re)start it ────────
            consecutive_failures += 1
            log(f"[WATCHDOG] ⚠️ Agent NOT running (attempt {consecutive_failures})")

            if consecutive_failures >= MAX_START_ATTEMPTS:
                log(f"[WATCHDOG] 🛑 {consecutive_failures} failed starts — backing off {BACKOFF_SLEEP}s")
                consecutive_failures = 0
                time.sleep(BACKOFF_SLEEP)
                continue

            if start_agent(agent_exe):
                last_start_time = time.time()
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