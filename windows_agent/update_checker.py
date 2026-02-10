"""
update_checker.py — Cross-platform forced update checker for TimeTracker agents.

Drop this file into both mac_agent/ and windows_agent/.

Usage in main.py:
    from update_checker import check_for_update_blocking
    
    # Call BEFORE starting the agent — blocks until user updates if outdated
    check_for_update_blocking(API_BASE, APP_VERSION)
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
RECHECK_INTERVAL = 3600  # 1 hour

# Track which version we already nagged about (survives restarts)
def _nag_file() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/.timetracker/.update_nagged")
    else:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "TimeTracker", ".update_nagged")

def _already_nagged(version: str) -> bool:
    """Check if we already showed the update dialog for this version."""
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
    """Record that we showed the update dialog for this version."""
    try:
        path = _nag_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"version": version, "ts": time.time()}, f)
    except Exception:
        pass

def _clear_nag():
    """Clear the nag file (called when a new version is successfully installed)."""
    try:
        path = _nag_file()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def check_version(api_base: str, current_version: str) -> dict:
    """
    Hit the backend version-check endpoint.
    Returns dict with: update_available, force, latest_version, download_url
    Returns None on network error.
    """
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
    Opens download URL in browser, then exits the app.
    Works on both Mac (Cocoa/tkinter) and Windows (tkinter).
    """
    # Try native macOS dialog first (looks better)
    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSAlert, NSAlertFirstButtonReturn, NSApp
            from AppKit import NSInformationalAlertStyle

            # Ensure NSApp exists
            NSApplication.sharedApplication()

            alert = NSAlert.alloc().init()
            alert.setMessageText_("Update Required")
            alert.setInformativeText_(
                f"TimeTracker v{latest_version} is available.\n\n"
                "You must update to continue using the app."
            )
            alert.addButtonWithTitle_("Download Update")
            alert.addButtonWithTitle_("Quit")
            alert.setAlertStyle_(NSInformationalAlertStyle)

            response = alert.runModal()

            if response == NSAlertFirstButtonReturn:
                webbrowser.open(download_url)

            # Exit either way — can't use the app
            print(f"[UPDATE] Exiting — update required to v{latest_version}")
            sys.exit(0)

        except ImportError:
            pass  # Fall through to tkinter

    # Tkinter fallback (Windows + Mac fallback)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()

        # Force it to the front
        root.attributes('-topmost', True)
        root.lift()

        result = messagebox.askokcancel(
            "Update Required",
            f"TimeTracker v{latest_version} is available.\n\n"
            "You must update to continue using the app.\n\n"
            "Click OK to download the update.",
        )

        if result:
            webbrowser.open(download_url)

        root.destroy()
        print(f"[UPDATE] Exiting — update required to v{latest_version}")
        sys.exit(0)

    except Exception as e:
        # Last resort — console only
        print(f"\n{'='*50}")
        print(f"  UPDATE REQUIRED: TimeTracker v{latest_version}")
        print(f"  Download: {download_url}")
        print(f"{'='*50}\n")
        webbrowser.open(download_url)
        sys.exit(0)


def check_for_update_blocking(api_base: str, current_version: str):
    """
    Check for updates on startup. If a forced update is available,
    show a blocking dialog and exit — the user CANNOT use the app
    until they install the new version.

    Call this BEFORE starting the agent loop.
    """
    if current_version in ("dev", "0.0.0", ""):
        print("[UPDATE] Dev build — skipping version check")
        return

    data = check_version(api_base, current_version)

    if not data:
        # Network error — let them use the app (don't block offline users)
        print("[UPDATE] Could not reach server — skipping update check")
        return

    if not data.get("update_available"):
        # Running latest version — clear any old nag file
        _clear_nag()
        return

    if data.get("force") and data.get("update_available"):
        latest = data.get("latest_version", "unknown")
        url = data.get("download_url", "https://github.com/druss16/timetracker-releases/releases/latest")

        # Already showed popup for this version — don't nag again
        if _already_nagged(latest):
            print(f"[UPDATE] Update to v{latest} available but already notified — running anyway")
            return

        print(f"[UPDATE] ⚠️ Forced update required: {current_version} → {latest}")
        _mark_nagged(latest)
        _show_blocking_dialog(latest, url)
        # _show_blocking_dialog calls sys.exit — we never get here


def start_background_checker(api_base: str, current_version: str):
    """
    Periodically re-check for updates while the agent is running.
    If a forced update drops mid-session, show the dialog and exit.

    Call this AFTER the agent starts.
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
                        continue  # Already notified, skip
                    url = data.get("download_url", "")
                    print(f"[UPDATE] ⚠️ Forced update detected mid-session: {current_version} → {latest}")
                    _mark_nagged(latest)
                    _show_blocking_dialog(latest, url)
            except Exception as e:
                print(f"[UPDATE] Background check error: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")