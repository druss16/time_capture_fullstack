"""
update_checker.py — Cross-platform forced update checker for TimeTracker agents.

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


def _disable_restart_task():
    """
    Disable the Windows scheduled task so the OLD version doesn't auto-restart
    after os._exit(0) during an update. The installer re-creates the task
    in ssPostInstall, so it will be re-enabled after the new version installs.
    """
    if sys.platform == "darwin":
        return  # Mac uses launchd, not schtasks

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


def _show_blocking_dialog(latest_version: str, download_url: str):
    """
    Show a modal dialog that blocks the app until user clicks Update.
    Uses OS-native methods that work from ANY thread (including daemon threads).
    """

    if sys.platform == "darwin":
        # osascript works from any thread — spawns its own process
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
        # Windows: ctypes MessageBox is thread-safe
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

            # Disable scheduled task so old version doesn't restart and wipe config.
            # The installer re-creates the task after the new version installs.
            _disable_restart_task()

            print(f"[UPDATE] Exiting — update required to v{latest_version}")
            os._exit(0)

        except Exception as e:
            print(f"[UPDATE] MessageBox failed: {e}")
            _disable_restart_task()
            webbrowser.open(download_url)
            os._exit(0)


def check_for_update_blocking(api_base: str, current_version: str):
    """
    Check for updates on startup. If a forced update is available,
    show a blocking dialog and exit.
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

    if data.get("force") and data.get("update_available"):
        latest = data.get("latest_version", "unknown")
        url = data.get("download_url", "https://github.com/druss16/timetracker-releases/releases/latest")

        if _already_nagged(latest):
            print(f"[UPDATE] Update to v{latest} available but already notified — running anyway")
            return

        print(f"[UPDATE] ⚠️ Forced update required: {current_version} → {latest}")
        _mark_nagged(latest)
        _show_blocking_dialog(latest, url)


def start_background_checker(api_base: str, current_version: str):
    """
    Periodically re-check for updates while the agent is running.
    If a forced update drops mid-session, show the dialog and exit.
    """
    if current_version in ("dev", "0.0.0", ""):
        return

    def _loop():
        while True:
            time.sleep(RECHECK_INTERVAL)
            try:
                data = check_version(api_base, current_version)
                if data and data.get("force") and data.get("update_available"):
                    latest = data.get("latest_version", "unknown")
                    if _already_nagged(latest):
                        continue
                    url = data.get("download_url", "")
                    print(f"[UPDATE] ⚠️ Forced update detected mid-session: {current_version} → {latest}")
                    _mark_nagged(latest)
                    _show_blocking_dialog(latest, url)
            except Exception as e:
                print(f"[UPDATE] Background check error: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")