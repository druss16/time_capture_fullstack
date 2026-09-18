"""
update_checker.py — Cross-platform auto-update for TimeTracker agents.

Windows behavior:
  - Downloads a zip of the new agent files from GitHub releases
  - Writes a bat script that extracts the zip after the agent exits
  - Bat script launches the new agent — no installer needed for updates
  - Bypasses RedirectionGuard entirely (Python writes to user-owned LocalAppData)

macOS behavior:
  - Downloads .pkg installer
  - Runs via AppleScript with admin privileges
"""

import os
import sys
import json
import time
import threading
import webbrowser
import urllib.request
import urllib.error


# How often to re-check while agent is running (seconds)
RECHECK_INTERVAL = 300  # 5 mins

# Retry backoff after a FAILED install: 60s, 120s, 240s ... capped at an hour.
# A transient locked file should cost a minute, not a release.
RETRY_BACKOFF_BASE = 60
RETRY_BACKOFF_MAX = 3600

# Network readiness settings
NETWORK_READY_MAX_WAIT = 30
NETWORK_READY_POLL = 3
DOWNLOAD_TIMEOUT = 120
POST_WAKE_DELAY = 15

_last_wake_time = 0.0


def _log(msg: str):
    try:
        import logging
        logging.getLogger("timetracker").info(msg)
    except Exception:
        print(msg, flush=True)


def notify_wake():
    global _last_wake_time
    _last_wake_time = time.time()


def _seconds_since_wake() -> float:
    if _last_wake_time == 0.0:
        return float("inf")
    return time.time() - _last_wake_time


# ============================================================
# NETWORK READINESS
# ============================================================

def _wait_for_network(test_url: str, max_wait: int = NETWORK_READY_MAX_WAIT) -> bool:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(test_url)
        ping_url = f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        ping_url = test_url

    attempts = max(1, max_wait // NETWORK_READY_POLL)
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(ping_url, method="HEAD")
            urllib.request.urlopen(req, timeout=3)
            return True
        except Exception:
            if attempt == 0:
                _log(f"[UPDATE] Waiting for network ({ping_url})...")
            time.sleep(NETWORK_READY_POLL)

    _log(f"[UPDATE] Network not ready after {max_wait}s - skipping download")
    return False


# ============================================================
# TIMEOUT-AWARE DOWNLOAD
# ============================================================

def _download_with_timeout(url: str, dest: str, timeout: int = DOWNLOAD_TIMEOUT) -> int:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
    return total


# ============================================================
# WINDOWS HELPERS
# ============================================================

def _installed_agent_path() -> str:
    return os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "TimeTracker",
        "TimeTrackerAgent.exe",
    )


def _cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ============================================================
# UPDATE ACTIONS
# ============================================================

def _auto_update_windows(download_url: str, latest_version: str, zip_url: str = None) -> bool:
    """
    Download the new agent and hand extraction to a detached PowerShell script.

    WHY THIS IS NOT A THREE-LINE BAT ANY MORE
    -----------------------------------------
    It used to be: sleep 3, taskkill, sleep 2, Expand-Archive, start watchdog.
    Two fixed sleeps standing in for "the agent has exited" and "extraction
    finished". A 37 MB / 1057-file archive does not extract in the gap between
    them, and the field log of the 1.9.3 -> 1.9.4 update shows exactly what that
    costs:

        13:34:55  Update bat launched - exiting old agent
        13:35:04  (agent restarts - STILL 1.9.3)
        13:35:08  Nag says installed but still on 1.9.3 - retrying
        13:35:12  Zip update failed: [Errno 13] Permission denied: ...-1.9.4.zip

    Expand-Archive was still running and still holding the zip when the
    scheduled task restarted the old agent, which then tried to re-download on
    top of the file its own updater had open. The update silently did not
    happen, and the retry could not happen either.

    Three things fix it, and all three matter:
      * the zip path is unique per attempt, so a retry can never collide with an
        extraction still in flight;
      * the updater WAITS for the processes to actually exit and RETRIES the
        extraction, instead of assuming five seconds was enough;
      * it kills anything that got started during the extraction before
        restarting, because the scheduled task does not know an update is
        running.

    It also verifies the version on disk afterwards and writes its own log, so
    the next failure says what happened instead of looking like a version number
    that will not move.
    """
    import subprocess
    import tempfile

    if not zip_url:
        _log("[UPDATE] No zip_url provided — cannot update")
        return False

    local = os.environ.get("LOCALAPPDATA", "")
    install_dir = os.path.join(local, "TimeTracker")
    update_dir = os.path.join(install_dir, "Updates")
    log_dir = os.path.join(install_dir, "Logs")
    os.makedirs(update_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    # Unique per attempt. The old fixed name is precisely what produced
    # [Errno 13]: a second attempt reopened the file the first attempt's
    # Expand-Archive still had open.
    stamp = f"{os.getpid()}-{int(time.time())}"
    zip_path = os.path.join(update_dir, f"TimeTrackerAgent-{latest_version}-{stamp}.zip")
    update_log = os.path.join(log_dir, "update.log")

    try:
        if not _wait_for_network(zip_url):
            return False

        _log(f"[UPDATE] Downloading v{latest_version} zip...")
        file_size = _download_with_timeout(zip_url, zip_path, timeout=DOWNLOAD_TIMEOUT)
        _log(f"[UPDATE] Downloaded ({file_size:,} bytes) to {zip_path}")

        if file_size < 10 * 1024 * 1024:
            _log(f"[UPDATE] Download too small ({file_size} bytes) - aborting")
            _cleanup_file(zip_path)
            return False

        watchdog = os.path.join(install_dir, "tt_watchdog.exe")
        ps1 = os.path.join(tempfile.gettempdir(), f"tt_update-{stamp}.ps1")
        with open(ps1, "w", encoding="utf-8") as f:
            f.write(_UPDATER_PS1)

        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1,
             "-Zip", zip_path, "-InstallDir", install_dir,
             "-Watchdog", watchdog, "-Version", latest_version, "-LogFile", update_log],
            creationflags=0x08000000,
        )
        _log(f"[UPDATE] Updater launched (log: {update_log}) — exiting old agent")
        return True

    except Exception as e:
        _log(f"[UPDATE] Zip update failed: {e}")
        _cleanup_file(zip_path)
        return False


# The detached updater. Runs after the agent exits, so nothing here may assume
# the agent is alive — it logs to its own file and is the only account of what
# happened if the version does not change.
_UPDATER_PS1 = r"""
param(
  [Parameter(Mandatory=$true)][string]$Zip,
  [Parameter(Mandatory=$true)][string]$InstallDir,
  [Parameter(Mandatory=$true)][string]$Watchdog,
  [Parameter(Mandatory=$true)][string]$Version,
  [Parameter(Mandatory=$true)][string]$LogFile
)

function W($m) {
  try { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" |
        Out-File -FilePath $LogFile -Append -Encoding utf8 } catch {}
}

function Stop-Agent {
  foreach ($n in @('TimeTrackerAgent','tt_watchdog')) {
    Get-Process -Name $n -ErrorAction SilentlyContinue |
      Stop-Process -Force -ErrorAction SilentlyContinue
  }
}

W "=== update to v$Version starting (zip: $Zip)"

# 1. Stop the agent and WAIT for it to really be gone. The old bat slept two
#    seconds and hoped; a locked file is what made the extraction fail.
Stop-Agent
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
  $alive = @(Get-Process -Name 'TimeTrackerAgent','tt_watchdog' -ErrorAction SilentlyContinue)
  if ($alive.Count -eq 0) { break }
  Start-Sleep -Milliseconds 500
}
$alive = @(Get-Process -Name 'TimeTrackerAgent','tt_watchdog' -ErrorAction SilentlyContinue)
W ("processes still alive after wait: " + $alive.Count)

# 2. Extract, retrying. A transient lock should cost seconds, not a whole
#    release.
$ok = $false
for ($i = 1; $i -le 5; $i++) {
  try {
    Expand-Archive -LiteralPath $Zip -DestinationPath $InstallDir -Force -ErrorAction Stop
    $ok = $true
    W "extraction succeeded on attempt $i"
    break
  } catch {
    W "extraction attempt $i failed: $($_.Exception.Message)"
    Stop-Agent
    Start-Sleep -Seconds 3
  }
}

# 3. Say what is actually on disk now. A silent wrong version is the whole
#    reason this script exists.
$vf = Join-Path $InstallDir '_internal\version.py'
if (Test-Path $vf) {
  $line = (Get-Content $vf | Where-Object { $_ -match 'APP_VERSION' }) -join ' '
  W "on disk after extraction: $line"
  if ($line -notmatch [regex]::Escape($Version)) {
    W "WARNING: expected v$Version on disk and did not find it"
  }
} else {
  W "WARNING: $vf missing after extraction"
}

if ($ok) {
  Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
} else {
  W "EXTRACTION FAILED - previous install left in place, zip kept for diagnosis"
}

# 4. The scheduled task does not know an update is running and may have started
#    the OLD agent while we extracted. Kill whatever is there, then start clean,
#    or the machine keeps running the version we just replaced.
Stop-Agent
Start-Sleep -Milliseconds 500
try {
  Start-Process -FilePath $Watchdog -ErrorAction Stop
  W "watchdog restarted"
} catch {
  W "could not start watchdog: $($_.Exception.Message)"
}

# Old zips from earlier attempts pile up at ~37 MB each.
try {
  Get-ChildItem (Join-Path $InstallDir 'Updates') -Filter 'TimeTrackerAgent-*.zip' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-1) } |
    Remove-Item -Force -ErrorAction SilentlyContinue
} catch {}

W "=== update finished (extracted=$ok)"
try { Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue } catch {}
"""


def _auto_update_mac(download_url: str, latest_version: str) -> bool:
    """Download and install update on macOS via AppleScript elevated installer."""
    import subprocess
    import tempfile

    pkg_path = os.path.join(tempfile.gettempdir(), f"TimeTracker-{latest_version}.pkg")

    try:
        if not _wait_for_network(download_url):
            return False

        _log(f"[UPDATE] Downloading v{latest_version}...")
        file_size = _download_with_timeout(download_url, pkg_path, timeout=DOWNLOAD_TIMEOUT)
        _log(f"[UPDATE] Downloaded ({file_size:,} bytes) to {pkg_path}")

        if file_size < 40 * 1024 * 1024:
            _log(f"[UPDATE] Download too small ({file_size} bytes) - aborting")
            _cleanup_file(pkg_path)
            return False

        _log(f"[UPDATE] Installing v{latest_version} (will prompt for password)...")
        install_script = (
            f'do shell script "installer -pkg '
            f"'{pkg_path}'"
            f' -target /" with administrator privileges with prompt '
            f'"TimeTracker needs to install an update (v{latest_version}).'
            f'\\\\n\\\\nEnter your password to continue."'
        )
        subprocess.Popen(["osascript", "-e", install_script])
        _log(f"[UPDATE] Installer launched - update will complete after password entry")
        return True

    except Exception as e:
        _log(f"[UPDATE] Auto-update failed: {e}")
        _cleanup_file(pkg_path)
        return False


# ============================================================
# NAG FILE
# ============================================================

def _nag_file() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/.timetracker/.update_nagged")
    else:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "TimeTracker", ".update_nagged")


def _already_nagged(version: str) -> bool:
    try:
        path = _nag_file()
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                if data.get("version") != version:
                    return False
                # If download succeeded but we're still on old version, retry
                if data.get("download_ok"):
                    try:
                        from version import APP_VERSION
                        if APP_VERSION != version:
                            _log(f"[UPDATE] Nag says installed but still on {APP_VERSION} — retrying")
                            return False
                    except Exception:
                        pass
                nag_ts = data.get("ts", 0)
                if time.time() - nag_ts > 86400:
                    return False
                if not data.get("download_ok"):
                    # Progressive, not a flat hour. This branch used to sit out
                    # 3600s after ANY failure — including one transient locked
                    # file — while logging "will retry next cycle", which was
                    # not what it did. A machine could therefore sit on the old
                    # version for an hour with one misleading line to explain it.
                    attempts = int(data.get("attempts", 1) or 1)
                    backoff = min(RETRY_BACKOFF_BASE * (2 ** max(0, attempts - 1)),
                                  RETRY_BACKOFF_MAX)
                    if time.time() - nag_ts > backoff:
                        return False
                return True
    except Exception:
        pass
    return False


def _mark_nagged(version: str, download_ok: bool = False):
    """
    Record an attempt. `attempts` drives the retry backoff, and only counts
    consecutive failures for the SAME version — a new version starts fresh,
    because a release that failed says nothing about the next one.
    """
    try:
        path = _nag_file()
        attempts = 0
        if not download_ok:
            try:
                with open(path) as f:
                    prev = json.load(f)
                if prev.get("version") == version and not prev.get("download_ok"):
                    attempts = int(prev.get("attempts", 0) or 0)
            except Exception:
                attempts = 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"version": version, "ts": time.time(),
                       "download_ok": download_ok,
                       "attempts": attempts + (0 if download_ok else 1)}, f)
    except Exception:
        pass


def _clear_nag():
    try:
        path = _nag_file()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ============================================================
# VERSION CHECK
# ============================================================

def check_version(api_base: str, current_version: str) -> dict:
    plat = "macos" if sys.platform == "darwin" else "windows"
    url = f"{api_base}/agent/version-check/?version={current_version}&platform={plat}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        _log(f"[UPDATE] Version check failed (network): {e}")
        return None
    except Exception as e:
        _log(f"[UPDATE] Version check failed: {e}")
        return None


# ============================================================
# FORCED UPDATE DIALOG
# ============================================================

def _show_blocking_dialog(latest_version: str, download_url: str):
    if sys.platform == "darwin":
        try:
            import subprocess
            script = (
                f'display dialog "TimeTracker v{latest_version} is available.\\\\n\\\\n'
                f'You must update to continue." '
                f'buttons {{"Quit", "Download Update"}} default button "Download Update" '
                f'with title "Update Required" with icon caution'
            )
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
            if "Download Update" in result.stdout:
                webbrowser.open(download_url)
            _log(f"[UPDATE] Exiting - update required to v{latest_version}")
            os._exit(0)
        except Exception as e:
            _log(f"[UPDATE] osascript dialog failed: {e}")
            webbrowser.open(download_url)
            os._exit(0)
    else:
        try:
            import ctypes
            result = ctypes.windll.user32.MessageBoxW(
                0,
                f"TimeTracker v{latest_version} is available.\n\nYou must update to continue.\n\nClick OK to download.",
                "Update Required",
                0x01 | 0x30 | 0x40000 | 0x10000
            )
            if result == 1:
                webbrowser.open(download_url)
            _log(f"[UPDATE] Exiting - update required to v{latest_version}")
            os._exit(0)
        except Exception as e:
            _log(f"[UPDATE] MessageBox failed: {e}")
            webbrowser.open(download_url)
            os._exit(0)


# ============================================================
# STARTUP CHECK
# ============================================================

def check_for_update_blocking(api_base: str, current_version: str):
    if current_version in ("dev", "0.0.0", ""):
        _log("[UPDATE] Dev build - skipping version check")
        return

    try:
        data = check_version(api_base, current_version)

        if not data:
            _log("[UPDATE] Could not reach server - skipping update check")
            return

        if not data.get("update_available"):
            _log(f"[UPDATE] Up to date (v{current_version})")
            _clear_nag()
            return

        latest = data.get("latest_version", "unknown")
        url = data.get("download_url", "https://github.com/druss16/timetracker-releases/releases/latest")
        zip_url = data.get("zip_url", "")

        _log(f"[UPDATE] Update available: v{current_version} → v{latest} (force={data.get('force', False)})")

        if data.get("force"):
            if _already_nagged(latest):
                _log(f"[UPDATE] Update to v{latest} available but already notified - running anyway")
                return

            _log(f"[UPDATE] Forced update required: {current_version} -> {latest}")
            _mark_nagged(latest, download_ok=False)

            if sys.platform == "win32":
                def _bg_forced():
                    success = _auto_update_windows(url, latest, zip_url=zip_url)
                    if success:
                        _mark_nagged(latest, download_ok=True)
                        _log(f"[UPDATE] ✅ Forced update to v{latest} — exiting old agent")
                        os._exit(0)
                threading.Thread(target=_bg_forced, daemon=True).start()
            else:
                _show_blocking_dialog(latest, url)

        else:
            if _already_nagged(latest):
                _log(f"[UPDATE] v{latest} already queued for install - skipping")
                return

            _log(f"[UPDATE] Queuing background install of v{latest}...")

            def _bg_update():
                _mark_nagged(latest, download_ok=False)
                success = False
                try:
                    if sys.platform == "win32":
                        success = _auto_update_windows(url, latest, zip_url=zip_url)
                    elif sys.platform == "darwin":
                        success = _auto_update_mac(url, latest)
                except Exception as e:
                    _log(f"[UPDATE] Background update failed: {e}")

                if success:
                    _mark_nagged(latest, download_ok=True)
                    if sys.platform == "win32":
                        _log(f"[UPDATE] ✅ v{latest} installed — exiting old agent")
                        os._exit(0)
                    else:
                        _log(f"[UPDATE] ✅ v{latest} install complete — will restart on next mtime check")
                else:
                    _log("[UPDATE] Download/install failed — backing off, see "
                         "Logs/update.log for what the updater saw")

            threading.Thread(target=_bg_update, daemon=True).start()

    except Exception as e:
        _log(f"[UPDATE] Startup update check failed (non-fatal): {e}")
        return


# ============================================================
# BACKGROUND CHECKER
# ============================================================

def start_background_checker(api_base: str, current_version: str):
    if current_version in ("dev", "0.0.0", ""):
        return

    def _loop():
        while True:
            time.sleep(RECHECK_INTERVAL)

            since_wake = _seconds_since_wake()
            if since_wake < POST_WAKE_DELAY:
                wait = POST_WAKE_DELAY - since_wake
                _log(f"[UPDATE] System just woke {since_wake:.0f}s ago - waiting {wait:.0f}s for network")
                time.sleep(wait)

            try:
                data = check_version(api_base, current_version)

                if not data or not data.get("update_available"):
                    continue

                latest = data.get("latest_version", "unknown")
                url = data.get("download_url", "")
                zip_url = data.get("zip_url", "")

                if not url:
                    continue

                if _already_nagged(latest):
                    continue

                _log(f"[UPDATE] Background check: update available v{current_version} → v{latest} (force={data.get('force', False)})")

                if data.get("force"):
                    _log(f"[UPDATE] Forced update detected mid-session: {current_version} -> {latest}")
                    _mark_nagged(latest, download_ok=False)
                    if sys.platform == "win32":
                        success = _auto_update_windows(url, latest, zip_url=zip_url)
                        if success:
                            _mark_nagged(latest, download_ok=True)
                            _log(f"[UPDATE] ✅ Forced update to v{latest} — exiting old agent")
                            os._exit(0)
                    else:
                        _show_blocking_dialog(latest, url)

                else:
                    _log(f"[UPDATE] Starting background install of v{latest}...")
                    _mark_nagged(latest, download_ok=False)

                    success = False
                    try:
                        if sys.platform == "win32":
                            success = _auto_update_windows(url, latest, zip_url=zip_url)
                        elif sys.platform == "darwin":
                            success = _auto_update_mac(url, latest)
                    except Exception as e:
                        _log(f"[UPDATE] Auto-update error: {e}")
                        success = False

                    if success:
                        _mark_nagged(latest, download_ok=True)
                        if sys.platform == "win32":
                            _log(f"[UPDATE] ✅ v{latest} installed — exiting old agent")
                            os._exit(0)
                        else:
                            _log(f"[UPDATE] ✅ v{latest} installed — will restart on next mtime check")
                    else:
                        _log("[UPDATE] Download/install failed — backing off, see "
                             "Logs/update.log for what the updater saw")

            except Exception as e:
                _log(f"[UPDATE] Background check error (non-fatal): {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    _log(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")