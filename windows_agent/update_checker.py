"""
update_checker.py — Cross-platform auto-update for TimeTracker agents.

Windows behavior in this version:
  - Silent installer download and launch
  - Removes old relaunch paths before install:
      * kills running TimeTracker processes
      * deletes scheduled tasks if present
      * removes HKCU Run key if present
  - Verifies success by waiting for installed exe mtime to change
  - Exits old agent after verified install; installer should relaunch the new one

  4

macOS behavior:
  - Preserved from existing implementation
"""

import os
import sys
import json
import time
import platform
import threading
import webbrowser
import urllib.request
import urllib.error


# How often to re-check while agent is running (seconds)
RECHECK_INTERVAL = 300  # 5 mins

# Network readiness settings
NETWORK_READY_MAX_WAIT = 30
NETWORK_READY_POLL = 3
DOWNLOAD_TIMEOUT = 120
POST_WAKE_DELAY = 15

# Track whether we recently woke from sleep
_last_wake_time = 0.0


def _log(msg: str):
    """
    Route to the main agent logger if available, else print.
    """
    try:
        import logging
        logging.getLogger("timetracker").info(msg)
    except Exception:
        print(msg, flush=True)


def notify_wake():
    """Called from main.py on_wake handler to let us know the system just woke."""
    global _last_wake_time
    _last_wake_time = time.time()


def _seconds_since_wake() -> float:
    """How long ago the system woke from sleep. Returns inf if never woke."""
    if _last_wake_time == 0.0:
        return float("inf")
    return time.time() - _last_wake_time


# ============================================================
# NETWORK READINESS
# ============================================================

def _wait_for_network(test_url: str, max_wait: int = NETWORK_READY_MAX_WAIT) -> bool:
    """
    Wait for network to be ready before attempting a download.
    Uses HEAD requests to avoid downloading anything.
    Returns True if network is reachable, False if timed out.
    """
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
    """
    Download a file with a proper socket timeout.
    Returns file size in bytes on success.
    Raises on failure.
    """
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
# EXE MTIME DETECTION + RESTART
# ============================================================

def _get_exe_mtime() -> float:
    """Get modification time of our own exe (frozen builds only)."""
    if getattr(sys, "frozen", False):
        try:
            return os.path.getmtime(sys.executable)
        except Exception:
            pass
    return 0.0


_startup_exe_mtime = _get_exe_mtime()


def _restart_into_new_exe():
    """Restart the agent using the updated exe on disk."""
    if not getattr(sys, "frozen", False):
        return

    exe_path = sys.executable
    _log(f"[UPDATE] Restarting into updated exe: {exe_path}")

    if sys.platform == "win32":
        import subprocess
        import tempfile

        pid = os.getpid()
        bat = os.path.join(tempfile.gettempdir(), "tt_restart.bat")

        with open(bat, "w") as f:
            f.write("@echo off\n")
            f.write(f'echo Waiting for old agent (PID {pid}) to exit...\n')
            f.write(":wait\n")
            f.write(f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\n')
            f.write("if not errorlevel 1 (\n")
            f.write("    timeout /t 1 /nobreak >NUL\n")
            f.write("    goto wait\n")
            f.write(")\n")
            f.write('echo Starting updated agent...\n')
            f.write(f'start "" "{exe_path}"\n')
            f.write('del "%~f0"\n')

        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)
        _log("[UPDATE] Restart script launched - exiting old process")
        os._exit(0)

    else:
        os.execv(exe_path, [exe_path])


# ============================================================
# WINDOWS HELPERS
# ============================================================

def _installed_agent_path() -> str:
    return os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "TimeTracker",
        "TimeTrackerAgent.exe",
    )


def _prepare_for_windows_update():
    """
    Remove all possible old-version relaunch paths before silent install.
    This prevents the previous agent from reappearing mid-update.
    """
    if sys.platform != "win32":
        return

    import subprocess

    CREATE_NO_WINDOW = 0x08000000

    def _run(cmd):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            if result.returncode == 0:
                _log(f"[UPDATE] OK: {' '.join(cmd)}")
            else:
                _log(
                    f"[UPDATE] WARN: {' '.join(cmd)} "
                    f"-> code={result.returncode} stdout={stdout} stderr={stderr}"
                )
        except Exception as e:
            _log(f"[UPDATE] WARN: {' '.join(cmd)} failed: {e}")

    for exe in ["TimeTracker.exe", "tt_watchdog.exe"]:
        _run(["taskkill", "/F", "/IM", exe, "/T"])

    _run(["schtasks", "/delete", "/tn", "MavOps TimeTracker", "/f"])
    _run(["schtasks", "/delete", "/tn", "TimeTrackerWatchdog", "/f"])

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, "TimeTracker")
            _log("[UPDATE] Removed HKCU Run key startup entry")
        except FileNotFoundError:
            _log("[UPDATE] HKCU Run key entry not present")
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        _log(f"[UPDATE] Failed removing HKCU Run key: {e}")


def _wait_for_updated_exe(timeout: int = 150) -> bool:
    """
    Wait until the installed agent exe on disk changes mtime.
    Much better success signal than 'installer launched'.
    """
    if sys.platform != "win32":
        return False

    exe_path = _installed_agent_path()
    start = time.time()

    old_mtime = 0.0
    try:
        if os.path.exists(exe_path):
            old_mtime = os.path.getmtime(exe_path)
    except Exception:
        pass

    _log(f"[UPDATE] Watching exe for replacement: {exe_path} (old_mtime={old_mtime})")

    while time.time() - start < timeout:
        try:
            if os.path.exists(exe_path):
                new_mtime = os.path.getmtime(exe_path)
                if new_mtime > old_mtime:
                    _log(f"[UPDATE] Detected updated exe mtime: {old_mtime} -> {new_mtime}")
                    return True
        except Exception as e:
            _log(f"[UPDATE] mtime check warning: {e}")

        time.sleep(3)

    _log("[UPDATE] Timed out waiting for installed exe replacement")
    return False


# ============================================================
# UPDATE ACTIONS
# ============================================================

def _auto_update_windows(download_url: str, latest_version: str) -> bool:
    """
    Download and silently install the new Windows version.
    Returns True only if the installed exe was actually replaced.
    """
    import ctypes
    import tempfile

    update_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "TimeTracker",
        "Updates",
    )
    os.makedirs(update_dir, exist_ok=True)

    installer_path = os.path.join(
        update_dir,
        f"TimeTrackerSetup-{latest_version}.exe",
    )

    try:
        if not _wait_for_network(download_url):
            return False

        _log(f"[UPDATE] Downloading v{latest_version} installer...")
        file_size = _download_with_timeout(
            download_url,
            installer_path,
            timeout=DOWNLOAD_TIMEOUT,
        )
        _log(f"[UPDATE] Downloaded ({file_size:,} bytes) to {installer_path}")

        if file_size < 40 * 1024 * 1024:
            _log(f"[UPDATE] Download too small ({file_size} bytes) - aborting")
            _cleanup_file(installer_path)
            return False

        _prepare_for_windows_update()

        # Write flag file for watchdog to pick up and install
        flag_path = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "TimeTracker",
            "pending_update.json"
        )
        with open(flag_path, "w") as f:
            json.dump({"installer": installer_path, "version": latest_version}, f)
        _log(f"[UPDATE] ✅ Pending update flag written — watchdog will install v{latest_version}")
        return True

    except Exception as e:
        _log(f"[UPDATE] Silent install failed: {e}")
        _cleanup_file(installer_path)
        return False


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


def _cleanup_file(path: str):
    """Safely remove a partial/failed download."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


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
    """
    Check if we already attempted this version.
    Also check if the nag is stale (>24h old).
    """
    try:
        path = _nag_file()
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                if data.get("version") != version:
                    return False

                nag_ts = data.get("ts", 0)
                if time.time() - nag_ts > 86400:
                    _log(f"[UPDATE] Nag for v{version} is stale (>24h) - will retry")
                    return False

                if not data.get("download_ok", False):
                    if time.time() - nag_ts > 3600:
                        _log(f"[UPDATE] Previous download of v{version} failed - retrying")
                        return False

                return True
    except Exception:
        pass
    return False


def _mark_nagged(version: str, download_ok: bool = False):
    """Mark that we have attempted this version."""
    try:
        path = _nag_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({
                "version": version,
                "ts": time.time(),
                "download_ok": download_ok,
            }, f)
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
    """
    Check for available updates. Returns None on any failure.
    """
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
# FORCED UPDATE DIALOG (blocking)
# ============================================================

def _show_blocking_dialog(latest_version: str, download_url: str):
    """
    Show a modal dialog that blocks the app until user clicks Update.
    """
    if sys.platform == "darwin":
        try:
            import subprocess
            script = (
                f'display dialog "TimeTracker v{latest_version} is available.\\\\n\\\\n'
                f'You must update to continue." '
                f'buttons {{"Quit", "Download Update"}} default button "Download Update" '
                f'with title "Update Required" with icon caution'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=300
            )
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
            MB_OKCANCEL = 0x01
            MB_ICONWARNING = 0x30
            MB_TOPMOST = 0x40000
            MB_SETFOREGROUND = 0x10000

            result = ctypes.windll.user32.MessageBoxW(
                0,
                f"TimeTracker v{latest_version} is available.\n\n"
                "You must update to continue using the app.\n\n"
                "Click OK to download the update.",
                "Update Required",
                MB_OKCANCEL | MB_ICONWARNING | MB_TOPMOST | MB_SETFOREGROUND
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
    """
    Check for updates on startup.
    - Forced update: silent install on Windows, blocking dialog on Mac
    - Regular update: silent background install
    """
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

        _log(f"[UPDATE] Update available: v{current_version} → v{latest} (force={data.get('force', False)})")

        if data.get("force"):
            if _already_nagged(latest):
                _log(f"[UPDATE] Update to v{latest} available but already notified - running anyway")
                return

            _log(f"[UPDATE] Forced update required: {current_version} -> {latest}")
            _mark_nagged(latest, download_ok=False)

            if sys.platform == "win32":
                def _bg_forced():
                    success = _auto_update_windows(url, latest)
                    if success:
                        _mark_nagged(latest, download_ok=True)
                        _log(f"[UPDATE] ✅ Forced update to v{latest} installed — exiting old agent")
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
                        success = _auto_update_windows(url, latest)
                    elif sys.platform == "darwin":
                        success = _auto_update_mac(url, latest)
                except Exception as e:
                    _log(f"[UPDATE] Background update failed: {e}")
                    success = False

                if success:
                    _mark_nagged(latest, download_ok=True)
                    if sys.platform == "win32":
                        _log(f"[UPDATE] ✅ v{latest} install verified — exiting old agent")
                        os._exit(0)
                    else:
                        _log(f"[UPDATE] ✅ v{latest} install complete — will restart on next mtime check")
                else:
                    _log("[UPDATE] Download/install failed - will retry later")

            threading.Thread(target=_bg_update, daemon=True).start()

    except Exception as e:
        _log(f"[UPDATE] Startup update check failed (non-fatal): {e}")
        return


# ============================================================
# BACKGROUND CHECKER
# ============================================================

def start_background_checker(api_base: str, current_version: str):
    """
    Periodically re-check for updates while the agent is running.
    """
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

            if _startup_exe_mtime > 0:
                try:
                    current_mtime = _get_exe_mtime()
                    if current_mtime > _startup_exe_mtime:
                        _log(f"[UPDATE] Exe on disk changed ({_startup_exe_mtime} -> {current_mtime}) - restarting")
                        _restart_into_new_exe()
                except Exception as e:
                    _log(f"[UPDATE] Mtime check error: {e}")

            try:
                data = check_version(api_base, current_version)

                if not data or not data.get("update_available"):
                    continue

                latest = data.get("latest_version", "unknown")
                url = data.get("download_url", "")

                if not url:
                    continue

                if _already_nagged(latest):
                    continue

                _log(
                    f"[UPDATE] Background check: update available "
                    f"v{current_version} → v{latest} (force={data.get('force', False)})"
                )

                if data.get("force"):
                    _log(f"[UPDATE] Forced update detected mid-session: {current_version} -> {latest}")
                    _mark_nagged(latest, download_ok=False)
                    if sys.platform == "win32":
                        success = _auto_update_windows(url, latest)
                        if success:
                            _mark_nagged(latest, download_ok=True)
                            _log(f"[UPDATE] ✅ Forced update to v{latest} installed — exiting old agent")
                            os._exit(0)
                    else:
                        _show_blocking_dialog(latest, url)

                else:
                    _log(f"[UPDATE] Starting background install of v{latest}...")
                    _mark_nagged(latest, download_ok=False)

                    success = False
                    try:
                        if sys.platform == "win32":
                            success = _auto_update_windows(url, latest)
                        elif sys.platform == "darwin":
                            success = _auto_update_mac(url, latest)
                    except Exception as e:
                        _log(f"[UPDATE] Auto-update error: {e}")
                        success = False

                    if success:
                        _mark_nagged(latest, download_ok=True)
                        if sys.platform == "win32":
                            _log(f"[UPDATE] ✅ v{latest} installed and verified — exiting old agent")
                            os._exit(0)
                        else:
                            _log(f"[UPDATE] ✅ v{latest} installed — launching new agent and exiting")
                    else:
                        _log("[UPDATE] Download/install failed - will retry next cycle")

            except Exception as e:
                _log(f"[UPDATE] Background check error (non-fatal): {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    _log(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")