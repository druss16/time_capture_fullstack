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
    Download zip of new agent files and extract via bat script after agent exits.
    No installer involved — writes directly to user-owned LocalAppData.
    """
    import subprocess
    import tempfile

    if not zip_url:
        _log("[UPDATE] No zip_url provided — cannot update")
        return False

    update_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TimeTracker", "Updates")
    os.makedirs(update_dir, exist_ok=True)
    zip_path = os.path.join(update_dir, f"TimeTrackerAgent-{latest_version}.zip")
    install_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TimeTracker")

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

        # Can't extract while agent is running — files are locked.
        # Bat script waits 3s for agent to exit, extracts zip, launches new agent.
        new_exe = _installed_agent_path()
        bat = os.path.join(tempfile.gettempdir(), "tt_update.bat")
        with open(bat, "w") as f:
            f.write("@echo off\n")
            f.write("timeout /t 3 /nobreak >NUL\n")
            # Kill watchdog before replacing files
            f.write("taskkill /F /IM tt_watchdog.exe 2>nul\n")
            f.write("taskkill /F /IM TimeTrackerAgent.exe 2>nul\n")
            f.write("timeout /t 2 /nobreak >NUL\n")
            # Extract new files
            f.write(f'powershell -Command "Expand-Archive -Path \\"{zip_path}\\" -DestinationPath \\"{install_dir}\\" -Force"\n')
            f.write(f'del "{zip_path}"\n')
            # Start watchdog — it will start the agent
            f.write(f'start "" "{os.path.join(install_dir, "tt_watchdog.exe")}"\n')
            f.write('del "%~f0"\n')

        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)
        _log(f"[UPDATE] ✅ Update bat launched — exiting old agent")
        return True

    except Exception as e:
        _log(f"[UPDATE] Zip update failed: {e}")
        _cleanup_file(zip_path)
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
    try:
        path = _nag_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"version": version, "ts": time.time(), "download_ok": download_ok}, f)
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
                    _log("[UPDATE] Download/install failed - will retry later")

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
                        _log("[UPDATE] Download/install failed - will retry next cycle")

            except Exception as e:
                _log(f"[UPDATE] Background check error (non-fatal): {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    _log(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")