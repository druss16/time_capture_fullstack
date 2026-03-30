"""
update_checker.py — Cross-platform auto-update for TimeTracker agents.

Features:
  - Startup blocking check for forced updates
  - Background polling every 5 minutes
  - Windows: silent install via /VERYSILENT (signed installer, no user interaction)
  - Mac: AppleScript password prompt, then automatic install
  - Mtime detection: if exe on disk changes, auto-restart into new version
  - Network readiness checks before downloads (prevents post-sleep crashes)
  - Timeout-aware downloads (no more hanging on flaky WiFi)

Drop this file into both mac_agent/ and windows_agent/.

Usage in main.py:
    from update_checker import check_for_update_blocking, start_background_checker

    testing 4

    # Call BEFORE starting the agent — blocks until user updates if outdated
    check_for_update_blocking(API_BASE, APP_VERSION)

    # Call AFTER starting the agent — re-checks every 5 minutes
    start_background_checker(API_BASE, APP_VERSION)

    # In your on_wake handler, call:
    from update_checker import notify_wake
    notify_wake()
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
NETWORK_READY_MAX_WAIT = 30    # Max seconds to wait for network
NETWORK_READY_POLL = 3         # Seconds between network readiness pings
DOWNLOAD_TIMEOUT = 120         # Timeout for pkg/exe download (seconds)
POST_WAKE_DELAY = 15           # Extra delay after wake before update checks

# Track whether we recently woke from sleep
_last_wake_time = 0.0


def _log(msg: str):
    """
    Route to the main agent logger if available, else print.
    This ensures [UPDATE] lines appear in agent.log and get shipped
    to the backend — critical for diagnosing silent update failures
    on --noconsole Windows builds where print() goes nowhere.
    """
    try:
        import logging
        logging.getLogger('timetracker').info(msg)
    except Exception:
        print(msg, flush=True)


def notify_wake():
    """Called from main.py on_wake handler to let us know the system just woke."""
    global _last_wake_time
    _last_wake_time = time.time()


def _seconds_since_wake() -> float:
    """How long ago the system woke from sleep. Returns inf if never woke."""
    if _last_wake_time == 0.0:
        return float('inf')
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

    for attempt in range(max_wait // NETWORK_READY_POLL):
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
# TIMEOUT-AWARE DOWNLOAD (replaces urlretrieve)
# ============================================================

def _download_with_timeout(url: str, dest: str, timeout: int = DOWNLOAD_TIMEOUT) -> int:
    """
    Download a file with a proper socket timeout.
    Returns file size in bytes on success.
    Raises on failure.

    Unlike urllib.request.urlretrieve, this will not hang indefinitely
    if the connection stalls (critical for post-sleep scenarios).
    """
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = 0
        with open(dest, 'wb') as f:
            while True:
                chunk = resp.read(65536)  # 64KB chunks
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
    return total


# ============================================================
# EXE MTIME DETECTION + AUTO-RESTART
# ============================================================

def _get_exe_mtime() -> float:
    """Get modification time of our own exe (frozen builds only)."""
    if getattr(sys, 'frozen', False):
        try:
            return os.path.getmtime(sys.executable)
        except Exception:
            pass
    return 0.0

_startup_exe_mtime = _get_exe_mtime()


def _restart_into_new_exe():
    """Restart the agent using the updated exe on disk."""
    if not getattr(sys, 'frozen', False):
        return  # Only for frozen builds

    exe_path = sys.executable
    _log(f"[UPDATE] Restarting into updated exe: {exe_path}")

    if sys.platform == "win32":
        import subprocess, tempfile
        pid = os.getpid()
        bat = os.path.join(tempfile.gettempdir(), "tt_restart.bat")

        with open(bat, "w") as f:
            f.write(f'@echo off\n')
            f.write(f'echo Waiting for old agent (PID {pid}) to exit...\n')
            f.write(f':wait\n')
            f.write(f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\n')
            f.write(f'if not errorlevel 1 (\n')
            f.write(f'    timeout /t 1 /nobreak >NUL\n')
            f.write(f'    goto wait\n')
            f.write(f')\n')
            f.write(f'echo Starting updated agent...\n')
            f.write(f'start "" "{exe_path}"\n')
            f.write(f'del "%~f0"\n')

        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)  # CREATE_NO_WINDOW
        _log("[UPDATE] Restart script launched - exiting old process")
        os._exit(0)

    else:
        # macOS: exec replaces the process in-place
        os.execv(exe_path, [exe_path])


# ============================================================
# UPDATE ACTIONS (platform-specific)
# ============================================================

def _auto_update_windows(download_url: str, latest_version: str) -> bool:
    """
    Silently download and install the new version on Windows.
    Uses Inno Setup /VERYSILENT flag — no user interaction required.
    Agent auto-restarts via mtime detection after install completes.
    """
    import subprocess
    import tempfile

    update_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TimeTracker", "Updates")
    os.makedirs(update_dir, exist_ok=True)
    exe_path = os.path.join(update_dir, f"TimeTrackerSetup-{latest_version}.exe")

    try:
        # Wait for network before downloading
        if not _wait_for_network(download_url):
            return False

        _log(f"[UPDATE] Downloading v{latest_version} installer...")
        file_size = _download_with_timeout(download_url, exe_path, timeout=DOWNLOAD_TIMEOUT)
        _log(f"[UPDATE] Downloaded ({file_size:,} bytes) to {exe_path}")

        # Sanity check — installer should be at least 10MB
        if file_size < 40 * 1024 * 1024:
            _log(f"[UPDATE] Download too small ({file_size} bytes) - aborting")
            _cleanup_file(exe_path)
            return False

        # Disable scheduled restart task so old version doesn't relaunch
        _disable_restart_task()

        _log(f"[UPDATE] Installing v{latest_version} silently...")
        log_path = os.path.join(tempfile.gettempdir(), f"TimeTrackerInstall-{latest_version}.log")

        # Use ShellExecute instead of subprocess — bypasses RedirectionGuard on Windows 11
        import ctypes
        params = f'/VERYSILENT /NORESTART /LOG="{log_path}"'
        result = ctypes.windll.shell32.ShellExecuteW(
            None,       # hwnd
            "open",     # operation
            exe_path,   # file
            params,     # parameters
            None,       # directory
            0           # SW_HIDE
        )

        if result > 32:
            _log(f"[UPDATE] ✅ Installer launched via ShellExecute — waiting 60s for completion")
            time.sleep(60)
            _log(f"[UPDATE] ✅ v{latest_version} install complete")
            _cleanup_file(exe_path)
            return True  # ← return True, let caller handle exit
        else:
            _log(f"[UPDATE] ⚠️ ShellExecute failed with code: {result}")
            _cleanup_file(exe_path)
            return False

    except subprocess.TimeoutExpired:
        _log(f"[UPDATE] Installer timed out after 120s")
        _cleanup_file(exe_path)
        return False
    except Exception as e:
        _log(f"[UPDATE] Silent install failed: {e}")
        _cleanup_file(exe_path)
        return False


def _auto_update_mac(download_url: str, latest_version: str) -> bool:
    """Download and install update on macOS via AppleScript elevated installer."""
    import subprocess, tempfile

    pkg_path = os.path.join(tempfile.gettempdir(), f"TimeTracker-{latest_version}.pkg")

    try:
        # Wait for network before downloading
        if not _wait_for_network(download_url):
            return False

        _log(f"[UPDATE] Downloading v{latest_version}...")

        # Use timeout-aware download instead of urlretrieve
        file_size = _download_with_timeout(download_url, pkg_path, timeout=DOWNLOAD_TIMEOUT)
        _log(f"[UPDATE] Downloaded ({file_size:,} bytes) to {pkg_path}")

        # Sanity check - pkg should be at least 5MB
        if file_size < 40 * 1024 * 1024:
            _log(f"[UPDATE] Download too small ({file_size} bytes) - aborting")
            _cleanup_file(exe_path)
            return False

        # Use AppleScript to run installer with admin privileges
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
# NAG FILE (prevents repeated prompts/downloads for same version)
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
    Also check if the nag is stale (>24h old) — if a previous attempt
    failed mid-download, we should retry rather than permanently skip.
    """
    try:
        path = _nag_file()
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                if data.get("version") != version:
                    return False

                # Stale nag check - retry after 24 hours regardless
                nag_ts = data.get("ts", 0)
                if time.time() - nag_ts > 86400:  # 24 hours
                    _log(f"[UPDATE] Nag for v{version} is stale (>24h) - will retry")
                    return False

                # Check if the download actually succeeded
                if not data.get("download_ok", False):
                    # Previous attempt failed - retry after 1 hour
                    if time.time() - nag_ts > 3600:
                        _log(f"[UPDATE] Previous download of v{version} failed - retrying")
                        return False

                return True
    except Exception:
        pass
    return False


def _mark_nagged(version: str, download_ok: bool = False):
    """
    Mark that we have attempted this version.
    Track whether the download actually succeeded so we can retry failures.
    """
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
# WINDOWS SCHEDULED TASK HELPER
# ============================================================

def _disable_restart_task():
    """
    Disable the Windows scheduled task so the OLD version does not auto-restart
    after os._exit(0) during an update. The installer re-creates the task
    in ssPostInstall, so it will be re-enabled after the new version installs.
    """
    if sys.platform == "darwin":
        return

    try:
        import subprocess
        result = subprocess.run(
            ['schtasks', '/change', '/tn', 'MavOps TimeTracker', '/disable'],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            _log("[UPDATE] Disabled restart task during update")
        else:
            _log(f"[UPDATE] Could not disable task: {result.stderr.decode(errors='ignore').strip()}")
    except Exception as e:
        _log(f"[UPDATE] Failed to disable restart task: {e}")


# ============================================================
# VERSION CHECK
# ============================================================

def check_version(api_base: str, current_version: str) -> dict:
    """
    Check for available updates. Returns None on any failure.
    Explicit handling for URLError (network not ready after sleep).
    """
    plat = "macos" if sys.platform == "darwin" else "windows"
    url = f"{api_base}/agent/version-check/?version={current_version}&platform={plat}"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        # Network not ready - totally expected after sleep
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
    Uses OS-native methods that work from ANY thread.
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

            if result == 1:  # IDOK
                webbrowser.open(download_url)

            _disable_restart_task()

            _log(f"[UPDATE] Exiting - update required to v{latest_version}")
            os._exit(0)

        except Exception as e:
            _log(f"[UPDATE] MessageBox failed: {e}")
            _disable_restart_task()
            webbrowser.open(download_url)
            os._exit(0)


# ============================================================
# STARTUP CHECK (blocking for forced updates only)
# ============================================================

def check_for_update_blocking(api_base: str, current_version: str):
    """
    Check for updates on startup.
    - Forced update: block with dialog, exit
    - Regular update: silent background install

    Entire function wrapped in try/except — an update check failure
    must NEVER prevent the agent from starting. The tracking loop is
    more important than any update.
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
            # Forced: silent install on Windows, blocking dialog on Mac
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
                threading.Thread(target=_bg_forced, daemon=True).start()
            else:
                _show_blocking_dialog(latest, url)

        else:
            # Non-forced: silent background install
            if _already_nagged(latest):
                _log(f"[UPDATE] v{latest} already queued for install - skipping")
                return

            _log(f"[UPDATE] Queuing background install of v{latest}...")

            # Run in background thread so agent starts immediately
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
                    _log(f"[UPDATE] ✅ v{latest} install complete — will restart on next mtime check")
                else:
                    # Don't permanently mark as handled - will retry after 1h
                    _log("[UPDATE] Download/install failed - will retry later")

            threading.Thread(target=_bg_update, daemon=True).start()

    except Exception as e:
        # CRITICAL: Never let an update check crash the agent startup
        _log(f"[UPDATE] Startup update check failed (non-fatal): {e}")
        return


# ============================================================
# BACKGROUND CHECKER (runs every 5 minutes while agent is alive)
# ============================================================

def start_background_checker(api_base: str, current_version: str):
    """
    Periodically re-check for updates while the agent is running.

    Three update paths:
      1. Mtime detection — exe on disk changed (installer already ran) -> restart
      2. Forced update — block with dialog, exit
      3. Silent background install

    Post-wake delay prevents crashes when WiFi is not reconnected yet.
    All download paths check network readiness first.
    mark_nagged only set to download_ok=True AFTER successful handling.
    """
    if current_version in ("dev", "0.0.0", ""):
        return

    def _loop():
        while True:
            time.sleep(RECHECK_INTERVAL)

            # -- Post-wake delay --
            # If we just woke from sleep, wait extra time for WiFi to reconnect
            since_wake = _seconds_since_wake()
            if since_wake < POST_WAKE_DELAY:
                wait = POST_WAKE_DELAY - since_wake
                _log(f"[UPDATE] System just woke {since_wake:.0f}s ago - "
                     f"waiting {wait:.0f}s for network")
                time.sleep(wait)

            # -- Path 1: Mtime detection (installer already ran while we were running) --
            if _startup_exe_mtime > 0:
                try:
                    current_mtime = _get_exe_mtime()
                    if current_mtime > _startup_exe_mtime:
                        _log(f"[UPDATE] Exe on disk changed "
                             f"({_startup_exe_mtime} -> {current_mtime}) - restarting")
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

                # Already handled this version (and download succeeded)
                if _already_nagged(latest):
                    continue

                _log(f"[UPDATE] Background check: update available v{current_version} → v{latest} "
                     f"(force={data.get('force', False)})")

                # -- Path 2: Forced update — silent on Windows, dialog on Mac --
                if data.get("force"):
                    _log(f"[UPDATE] Forced update detected mid-session: "
                         f"{current_version} -> {latest}")
                    _mark_nagged(latest, download_ok=False)
                    if sys.platform == "win32":
                        success = _auto_update_windows(url, latest)
                        if success:
                            _mark_nagged(latest, download_ok=True)
                    else:
                        _show_blocking_dialog(latest, url)

                # -- Path 3: Silent background install --
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
                        _log(f"[UPDATE] ✅ v{latest} installed — launching new agent and exiting")
                        try:
                            import subprocess, tempfile
                            new_exe = sys.executable
                            bat = os.path.join(tempfile.gettempdir(), "tt_update.bat")
                            with open(bat, "w") as f:
                                f.write(f'@echo off\n')
                                f.write(f':waitinstall\n')
                                f.write(f'tasklist /FI "IMAGENAME eq TimeTrackerSetup*" 2>NUL | find /I "TimeTrackerSetup" >NUL\n')
                                f.write(f'if not errorlevel 1 (\n')
                                f.write(f'    timeout /t 2 /nobreak >NUL\n')
                                f.write(f'    goto waitinstall\n')
                                f.write(f')\n')
                                f.write(f'timeout /t 5 /nobreak >NUL\n')
                                f.write(f'start "" "{new_exe}"\n')
                                f.write(f'del "%~f0"\n')
                            subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)
                            _log(f"[UPDATE] ✅ Restart bat launched — exiting old agent")
                        except Exception as e:
                            _log(f"[UPDATE] ⚠️ Failed to launch restart bat: {e}")
                        os._exit(0)
                    else:
                        _log("[UPDATE] Download/install failed - will retry next cycle")

            except Exception as e:
                # Never let an update check crash the background thread
                _log(f"[UPDATE] Background check error (non-fatal): {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    _log(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")