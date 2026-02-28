"""
update_checker.py — Cross-platform auto-update for TimeTracker agents.

Features:
  - Startup blocking check for forced updates
  - Background polling every 5 minutes
  - Silent auto-update: downloads + installs with zero user interaction (Windows)
  - Mac: AppleScript password prompt, then automatic install
  - Mtime detection: if exe on disk changes, auto-restart into new version

Drop this file into both mac_agent/ and windows_agent/.

Usage in main.py:
    from update_checker import check_for_update_blocking, start_background_checker
    
    # Call BEFORE starting the agent — blocks until user updates if outdated
    check_for_update_blocking(API_BASE, APP_VERSION)
    
    # Call AFTER starting the agent — re-checks every 5 minutes
    start_background_checker(API_BASE, APP_VERSION)
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
    print(f"[UPDATE] Restarting into updated exe: {exe_path}")
    
    if sys.platform == "win32":
        import subprocess, tempfile
        pid = os.getpid()
        bat = os.path.join(tempfile.gettempdir(), "tt_restart.bat")
        
        with open(bat, "w") as f:
            f.write(f"""@echo off
echo Waiting for old agent (PID {pid}) to exit...
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait
)
echo Starting updated agent...
start "" "{exe_path}"
del "%~f0"
""")
        
        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)  # CREATE_NO_WINDOW
        print("[UPDATE] Restart script launched — exiting old process")
        os._exit(0)
    
    else:
        # macOS: exec replaces the process in-place
        os.execv(exe_path, [exe_path])


# ============================================================
# SILENT AUTO-UPDATE (download + install)
# ============================================================

def _auto_update_windows(download_url: str, latest_version: str) -> bool:
    """Download and silently install update on Windows."""
    import subprocess, tempfile
    
    installer_path = os.path.join(tempfile.gettempdir(), f"TimeTracker-{latest_version}-Setup.exe")
    
    try:
        print(f"[UPDATE] 📥 Downloading v{latest_version}...")
        urllib.request.urlretrieve(download_url, installer_path)
        file_size = os.path.getsize(installer_path)
        print(f"[UPDATE] ✅ Downloaded ({file_size:,} bytes) to {installer_path}")
        
        # Sanity check — installer should be at least 5MB
        if file_size < 5 * 1024 * 1024:
            print(f"[UPDATE] ⚠️ Download too small ({file_size} bytes) — aborting")
            return False
        
        # Run Inno Setup installer silently
        # /VERYSILENT       = no UI at all
        # /SUPPRESSMSGBOXES = suppress any popups
        # /NORESTART        = don't reboot
        # /CLOSEAPPLICATIONS = close running TimeTracker first
        print(f"[UPDATE] 🔧 Installing v{latest_version} silently...")
        subprocess.Popen(
            [installer_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        
        # The installer will:
        # 1. Kill our process (via CloseApplications or our preinstall)
        # 2. Write new exe to disk
        # 3. Restart the agent (via postinstall or scheduled task)
        # If none of that works, the mtime detector in the next run picks it up
        print(f"[UPDATE] ✅ Installer launched — update will complete momentarily")
        return True
        
    except Exception as e:
        print(f"[UPDATE] ❌ Auto-update failed: {e}")
        # Clean up partial download
        try:
            if os.path.exists(installer_path):
                os.remove(installer_path)
        except Exception:
            pass
        return False


def _auto_update_mac(download_url: str, latest_version: str) -> bool:
    """Download and install update on macOS via AppleScript elevated installer."""
    import subprocess, tempfile
    
    pkg_path = os.path.join(tempfile.gettempdir(), f"TimeTracker-{latest_version}.pkg")
    
    try:
        print(f"[UPDATE] 📥 Downloading v{latest_version}...")
        urllib.request.urlretrieve(download_url, pkg_path)
        file_size = os.path.getsize(pkg_path)
        print(f"[UPDATE] ✅ Downloaded ({file_size:,} bytes) to {pkg_path}")
        
        # Sanity check — pkg should be at least 5MB
        if file_size < 5 * 1024 * 1024:
            print(f"[UPDATE] ⚠️ Download too small ({file_size} bytes) — aborting")
            return False
        
        # Use AppleScript to run installer with admin privileges
        # This shows a single macOS password prompt, then installs silently
        # The pkg's preinstall kills the old app, postinstall starts the new one
        print(f"[UPDATE] 🔧 Installing v{latest_version} (will prompt for password)...")
        subprocess.Popen([
            "osascript", "-e",
            f'do shell script "installer -pkg \'{pkg_path}\' -target /" with administrator privileges'
        ])
        
        print(f"[UPDATE] ✅ Installer launched — update will complete after password entry")
        return True
        
    except Exception as e:
        print(f"[UPDATE] ❌ Auto-update failed: {e}")
        try:
            if os.path.exists(pkg_path):
                os.remove(pkg_path)
        except Exception:
            pass
        return False


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
    try:
        path = _nag_file()
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                return data.get("version") == version
    except Exception:
        pass
    return False


def _mark_nagged(version: str):
    try:
        path = _nag_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"version": version, "ts": time.time()}, f)
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
    Disable the Windows scheduled task so the OLD version doesn't auto-restart
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
            print("[UPDATE] Disabled restart task during update")
        else:
            print(f"[UPDATE] Could not disable task: {result.stderr.decode(errors='ignore').strip()}")
    except Exception as e:
        print(f"[UPDATE] Failed to disable restart task: {e}")


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
    except Exception as e:
        print(f"[UPDATE] Version check failed: {e}")
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
                f'display dialog "TimeTracker v{latest_version} is available.\\n\\n'
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

            print(f"[UPDATE] Exiting — update required to v{latest_version}")
            os._exit(0)

        except Exception as e:
            print(f"[UPDATE] osascript dialog failed: {e}")
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

            print(f"[UPDATE] Exiting — update required to v{latest_version}")
            os._exit(0)

        except Exception as e:
            print(f"[UPDATE] MessageBox failed: {e}")
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
    - Regular update: start silent auto-update immediately
    """
    if current_version in ("dev", "0.0.0", ""):
        print("[UPDATE] Dev build — skipping version check")
        return

    data = check_version(api_base, current_version)

    if not data:
        print("[UPDATE] Could not reach server — skipping update check")
        return

    if not data.get("update_available"):
        _clear_nag()
        return

    latest = data.get("latest_version", "unknown")
    url = data.get("download_url", "https://github.com/druss16/timetracker-releases/releases/latest")

    if data.get("force"):
        # Forced: block and require update
        if _already_nagged(latest):
            print(f"[UPDATE] Update to v{latest} available but already notified — running anyway")
            return

        print(f"[UPDATE] ⚠️ Forced update required: {current_version} → {latest}")
        _mark_nagged(latest)
        _show_blocking_dialog(latest, url)
    
    else:
        # Non-forced: silent auto-update on startup too
        if _already_nagged(latest):
            print(f"[UPDATE] v{latest} already queued for install — skipping")
            return
        
        print(f"[UPDATE] 🔄 Auto-updating on startup: {current_version} → {latest}")
        _mark_nagged(latest)
        
        # Run in background thread so agent starts immediately
        def _bg_update():
            if sys.platform == "win32":
                _auto_update_windows(url, latest)
            elif sys.platform == "darwin":
                _auto_update_mac(url, latest)
        
        threading.Thread(target=_bg_update, daemon=True).start()


# ============================================================
# BACKGROUND CHECKER (runs every 5 minutes while agent is alive)
# ============================================================

def start_background_checker(api_base: str, current_version: str):
    """
    Periodically re-check for updates while the agent is running.
    
    Three update paths:
      1. Mtime detection — exe on disk changed (installer already ran) → restart
      2. Forced update — block with dialog, exit
      3. Silent auto-update — download + install with zero UI (Windows)
    """
    if current_version in ("dev", "0.0.0", ""):
        return

    def _loop():
        while True:
            time.sleep(RECHECK_INTERVAL)
            
            # ── Path 1: Mtime detection (installer already ran while we were running) ──
            if _startup_exe_mtime > 0:
                current_mtime = _get_exe_mtime()
                if current_mtime > _startup_exe_mtime:
                    print(f"[UPDATE] Exe on disk changed ({_startup_exe_mtime} → {current_mtime}) — restarting")
                    _restart_into_new_exe()
            
            try:
                data = check_version(api_base, current_version)
                
                if not data or not data.get("update_available"):
                    continue
                
                latest = data.get("latest_version", "unknown")
                url = data.get("download_url", "")
                
                if not url:
                    continue
                
                # Already handled this version
                if _already_nagged(latest):
                    continue
                
                # ── Path 2: Forced update — block with dialog ──
                if data.get("force"):
                    print(f"[UPDATE] ⚠️ Forced update detected mid-session: {current_version} → {latest}")
                    _mark_nagged(latest)
                    _show_blocking_dialog(latest, url)
                
                # ── Path 3: Silent auto-update ──
                else:
                    print(f"[UPDATE] 🔄 Auto-updating: {current_version} → {latest}")
                    _mark_nagged(latest)
                    
                    if sys.platform == "win32":
                        _auto_update_windows(url, latest)
                    elif sys.platform == "darwin":
                        _auto_update_mac(url, latest)
                    
            except Exception as e:
                print(f"[UPDATE] Background check error: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")