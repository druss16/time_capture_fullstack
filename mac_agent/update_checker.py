"""
update_checker.py — Cross-platform auto-update for TimeTracker agents.

Features:
  - Startup blocking check for forced updates
  - Background polling every 5 minutes
  - Windows: zip download + bat script extraction (bypasses RedirectionGuard)
  - Mac: replaces its own bundle with no password when the user owns it
    (installs from v1.9.11 on); otherwise an admin-prompted pkg install
  - Network readiness checks before downloads (prevents post-sleep crashes)
  - Timeout-aware downloads (no more hanging on flaky WiFi)

Drop this file into both mac_agent/ and windows_agent/.

Usage in main.py:
    from update_checker import check_for_update_blocking, start_background_checker

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
DOWNLOAD_TIMEOUT = 120         # Timeout for pkg/zip download (seconds)
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
# UPDATE ACTIONS (platform-specific)
# ============================================================

def _auto_update_windows(download_url: str, latest_version: str, zip_url: str = None) -> bool:
    """
    Silently download and install the new version on Windows.

    Uses zip extraction via a bat script to bypass Windows 11 RedirectionGuard
    (which blocks child-process installers). Flow:
      1. Download TimeTrackerAgent-X.X.X.zip from GitHub releases
      2. Write a bat script to %TEMP%\tt_update.bat
      3. Return True — caller does os._exit(0)
      4. Bat script waits for agent to exit, then PowerShell-extracts the zip
      5. Bat script launches new TimeTrackerAgent.exe

    zip_url is provided by the backend version-check response.
    Mac always receives zip_url=None and never calls this function.
    """
    import subprocess
    import tempfile

    if not zip_url:
        _log("[UPDATE] Windows update requires zip_url but none provided - skipping")
        return False

    zip_path = os.path.join(tempfile.gettempdir(), f"TimeTrackerAgent-{latest_version}.zip")
    install_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TimeTracker")

    try:
        # Wait for network before downloading
        if not _wait_for_network(zip_url):
            return False

        _log(f"[UPDATE] Downloading v{latest_version} zip...")
        file_size = _download_with_timeout(zip_url, zip_path, timeout=DOWNLOAD_TIMEOUT)
        _log(f"[UPDATE] Downloaded ({file_size:,} bytes) to {zip_path}")

        # Sanity check — zip should be at least 1MB
        if file_size < 1 * 1024 * 1024:
            _log(f"[UPDATE] Download too small ({file_size} bytes) - aborting")
            _cleanup_file(zip_path)
            return False

        # Write bat script — runs after we exit
        bat_path = os.path.join(tempfile.gettempdir(), "tt_update.bat")
        exe_path = os.path.join(install_dir, "TimeTrackerAgent.exe")

        with open(bat_path, "w") as f:
            f.write("@echo off\n")
            f.write("echo Waiting for TimeTracker agent to exit...\n")
            f.write("timeout /t 3 /nobreak >NUL\n")
            f.write(f'powershell -Command "Expand-Archive -Path \'"{zip_path}"\' '
                    f'-DestinationPath \'"{install_dir}"\' -Force"\n')
            f.write(f'start "" "{exe_path}"\n')
            f.write("del \"%~f0\"\n")

        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )

        _log(f"[UPDATE] ✅ Bat script launched — exiting for update")
        return True

    except Exception as e:
        _log(f"[UPDATE] Windows zip update failed: {e}")
        _cleanup_file(zip_path)
        return False


# ============================================================
# MAC: UPDATE WITHOUT AN ADMIN PASSWORD
# ============================================================
#
# An update needed an admin password only because installer(8) writes into
# /Applications/TimeTracker.app, which the pkg leaves owned by root. A Standard
# user could never approve it, so their Mac froze on whatever version it was
# installed with. The postinstall now hands the bundle to the person who
# installed it — the same ownership a drag-installed app has — and from then
# on the agent replaces its own Contents:
#
#   1. download the same signed, notarized TimeTracker.pkg;
#   2. `pkgutil --expand-full` it (no root needed) and take Payload/*.app;
#   3. refuse unless the pkg AND the app are signed by the SAME Apple team as
#      the running copy, and the app is TimeTracker and passes a strict check;
#   4. copy the new Contents into a staging dir on the same volume, then a
#      detached helper waits for this process to exit, swaps Contents with two
#      renames (rolling back if the second fails), and relaunches the agent.
#
# Anything outside that — a root-owned bundle from an older install, a
# signature mismatch, a previous swap that failed for this version — falls
# back to the admin-prompt install below, so nothing is worse than before.
# The root-only parts of the pkg (browser-extension drop files, the staged
# profile) are identical across versions and are not redone here.

_MAC_LABEL = "com.mavops.timetracker"
_MAC_BUNDLE_ID = "TimeTracker"
_MAC_STAGE_ROOT = os.path.expanduser("~/Library/Caches/TimeTracker/update")
_MAC_SWAP_LOG = os.path.expanduser("~/Library/Logs/TimeTracker/update-swap.log")
# Exit code for "restarting into an update". The LaunchAgent relaunches us on
# any exit (KeepAlive=true since v1.9.14; non-zero also covered the older
# SuccessfulExit=false plist), so the agent comes back even if the helper dies.
_MAC_UPDATE_EXIT_CODE = 3


def _mac_running_bundle():
    """/Applications/TimeTracker.app (or wherever we run from), or None."""
    if not getattr(sys, "frozen", False):
        return None
    contents = os.path.dirname(os.path.dirname(os.path.realpath(sys.executable)))
    bundle = os.path.dirname(contents)
    if os.path.basename(contents) != "Contents" or not bundle.endswith(".app"):
        return None
    return bundle


def _mac_owns_bundle(bundle: str) -> bool:
    """We can swap Contents only if we own the bundle and everything in it."""
    uid = os.getuid()
    try:
        for root, dirs, _files in os.walk(bundle):
            if os.lstat(root).st_uid != uid or not os.access(root, os.W_OK):
                return False
        return True
    except OSError:
        return False


def _mac_team_id(signature_output: str) -> str:
    """TeamIdentifier from `codesign -dv`, or the (TEAMID) of a Developer ID
    certificate line from `pkgutil --check-signature`."""
    import re
    m = re.search(r"TeamIdentifier=([A-Z0-9]{10})\b", signature_output)
    if m:
        return m.group(1)
    m = re.search(r"Developer ID \w+: .*\(([A-Z0-9]{10})\)", signature_output)
    return m.group(1) if m else ""


def _mac_codesign_info(path: str) -> str:
    import subprocess
    r = subprocess.run(["codesign", "-dv", "--verbose=2", path],
                       capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


def _mac_swap_failed_before(version: str) -> bool:
    try:
        with open(_MAC_SWAP_LOG) as f:
            return f"SWAP FAILED {version}" in f.read()
    except OSError:
        return False


_MAC_SWAP_HELPER = r'''#!/bin/bash
# Written by update_checker._mac_self_update. Swaps TimeTracker.app/Contents
# once the old agent has exited, then relaunches it.
BUNDLE="$1"; STAGE="$2"; PID="$3"; VERSION="$4"; LABEL="$5"
exec >>"$6" 2>&1
echo "== $(date) swap to $VERSION: waiting for pid $PID"
for _ in $(seq 1 300); do kill -0 "$PID" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$PID" 2>/dev/null; then
    echo "SWAP FAILED $VERSION (agent still running after 30s)"
    rm -rf "$STAGE"
    exit 1
fi
if mv "$BUNDLE/Contents" "$STAGE/Contents.old"; then
    if mv "$STAGE/Contents" "$BUNDLE/Contents"; then
        echo "swapped in $VERSION"
        rm -rf "$STAGE/Contents.old"
    else
        mv "$STAGE/Contents.old" "$BUNDLE/Contents"
        echo "SWAP FAILED $VERSION (rolled back)"
    fi
else
    echo "SWAP FAILED $VERSION (could not move old Contents)"
fi
# Keep the LaunchAgent in step with the version now installed.
SRC="$BUNDLE/Contents/Resources/$LABEL.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
if [ -f "$SRC" ] && ! cmp -s "$SRC" "$DST"; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
    cp "$SRC" "$DST" && launchctl bootstrap "gui/$(id -u)" "$DST"
    echo "LaunchAgent refreshed"
else
    launchctl kickstart "gui/$(id -u)/$LABEL" 2>/dev/null
fi
rm -rf "$STAGE"
echo "done"
'''


def _mac_self_update(pkg_path: str, latest_version: str) -> bool:
    """Install `pkg_path` over the running bundle without admin rights.

    Returns False (caller falls back to the admin installer) whenever a check
    fails. On success it does not return: the helper is launched and this
    process exits so the helper can swap Contents underneath it.
    """
    import shutil, subprocess

    bundle = _mac_running_bundle()
    if not bundle:
        _log("[UPDATE] Not running from an app bundle - no self-update")
        return False
    if not _mac_owns_bundle(bundle):
        _log(f"[UPDATE] {bundle} is not owned by this user (installed by an "
             "older pkg) - needs the admin installer this once")
        return False
    if _mac_swap_failed_before(latest_version):
        _log(f"[UPDATE] A swap to v{latest_version} failed before - using the admin installer")
        return False

    running_team = _mac_team_id(_mac_codesign_info(bundle))
    if not running_team:
        _log("[UPDATE] Running copy has no Team ID - refusing self-update")
        return False

    pkg_sig = subprocess.run(["pkgutil", "--check-signature", pkg_path],
                             capture_output=True, text=True, timeout=60)
    if pkg_sig.returncode != 0 or _mac_team_id(pkg_sig.stdout) != running_team:
        _log(f"[UPDATE] Package signature does not match team {running_team} - refusing")
        return False

    stage = os.path.join(_MAC_STAGE_ROOT, latest_version)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    expanded = os.path.join(stage, "expanded")
    try:
        r = subprocess.run(["pkgutil", "--expand-full", pkg_path, expanded],
                           capture_output=True, text=True, timeout=300)
        new_app = os.path.join(expanded, "Payload", os.path.basename(bundle))
        if r.returncode != 0 or not os.path.isdir(os.path.join(new_app, "Contents")):
            _log(f"[UPDATE] Could not expand the package: {r.stderr.strip()[:200]}")
            return False

        info = _mac_codesign_info(new_app)
        if (_mac_team_id(info) != running_team
                or f"Identifier={_MAC_BUNDLE_ID}\n" not in info + "\n"):
            _log("[UPDATE] New app is not TimeTracker signed by our team - refusing")
            return False
        strict = subprocess.run(["codesign", "--verify", "--deep", "--strict", new_app],
                                capture_output=True, text=True, timeout=300)
        if strict.returncode != 0:
            _log(f"[UPDATE] New app fails signature check: {strict.stderr.strip()[:200]}")
            return False

        # The swap is two renames, so the staging dir must share a volume with
        # the bundle; ditto preserves the symlinks and signatures PyInstaller
        # bundles depend on.
        if os.stat(stage).st_dev != os.stat(bundle).st_dev:
            _log("[UPDATE] Staging dir is on another volume - using the admin installer")
            return False
        staged_contents = os.path.join(stage, "Contents")
        subprocess.run(["ditto", os.path.join(new_app, "Contents"), staged_contents],
                       check=True, capture_output=True, timeout=300)
        shutil.rmtree(expanded, ignore_errors=True)

        helper = os.path.join(stage, "swap.sh")
        with open(helper, "w") as f:
            f.write(_MAC_SWAP_HELPER)
        os.chmod(helper, 0o755)
        os.makedirs(os.path.dirname(_MAC_SWAP_LOG), exist_ok=True)
        # A new session, so launchd's clean-up of our process group when we
        # exit cannot take the helper with it.
        subprocess.Popen(
            ["/bin/bash", helper, bundle, stage, str(os.getpid()),
             latest_version, _MAC_LABEL, _MAC_SWAP_LOG],
            start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        )
    except Exception as e:
        _log(f"[UPDATE] Self-update staging failed: {e}")
        shutil.rmtree(stage, ignore_errors=True)
        return False

    _cleanup_file(pkg_path)
    _log(f"[UPDATE] ✅ v{latest_version} staged - restarting into it (no password needed)")
    os._exit(_MAC_UPDATE_EXIT_CODE)


def _download_mac_pkg(download_url: str, latest_version: str):
    """Download the release pkg to a temp path; None on any failure."""
    import tempfile

    pkg_path = os.path.join(tempfile.gettempdir(), f"TimeTracker-{latest_version}.pkg")
    try:
        # Wait for network before downloading
        if not _wait_for_network(download_url):
            return None

        _log(f"[UPDATE] Downloading v{latest_version}...")

        # Use timeout-aware download instead of urlretrieve
        file_size = _download_with_timeout(download_url, pkg_path, timeout=DOWNLOAD_TIMEOUT)
        _log(f"[UPDATE] Downloaded ({file_size:,} bytes) to {pkg_path}")

        # Sanity check - pkg should be at least 5MB
        if file_size < 5 * 1024 * 1024:
            _log(f"[UPDATE] Download too small ({file_size} bytes) - aborting")
            _cleanup_file(pkg_path)
            return None
        return pkg_path
    except Exception as e:
        _log(f"[UPDATE] Download failed: {e}")
        _cleanup_file(pkg_path)
        return None


def _auto_update_mac(download_url: str, latest_version: str) -> bool:
    """Download and install an update on macOS.

    Tries the no-password self-update first; falls back to installer(8) behind
    an AppleScript admin prompt when the bundle isn't ours to replace.
    """
    import subprocess

    pkg_path = _download_mac_pkg(download_url, latest_version)
    if not pkg_path:
        return False

    try:
        # No password needed when the bundle is ours to replace. On success
        # this exits the process; on any refusal it returns False.
        _mac_self_update(pkg_path, latest_version)

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

                # The download finished but we are STILL on the old version,
                # so the install never happened — a downloaded-but-uninstalled
                # update would otherwise sit there forever, the nag file
                # insisting the job was done. Retry it.
                if data.get("download_ok"):
                    try:
                        from version import APP_VERSION
                        if APP_VERSION != version:
                            _log(f"[UPDATE] Nag says installed but still on "
                                 f"{APP_VERSION} — retrying")
                            return False
                    except Exception:
                        pass

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


def _forced_update_mac(download_url: str, latest_version: str):
    """A forced update installs in place when the bundle is ours (the
    self-update exits into the new version); otherwise the old behaviour — a
    blocking dialog that sends the person to the download — is all there is,
    since a Standard user cannot complete the admin installer anyway."""
    bundle = _mac_running_bundle()
    if bundle and _mac_owns_bundle(bundle):
        pkg_path = _download_mac_pkg(download_url, latest_version)
        if pkg_path:
            _mac_self_update(pkg_path, latest_version)  # exits on success
            _cleanup_file(pkg_path)
    _show_blocking_dialog(latest_version, download_url)


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
        zip_url = data.get("zip_url", "")  # Windows only; Mac always receives None/""

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
                    success = _auto_update_windows(url, latest, zip_url=zip_url)
                    if success:
                        _mark_nagged(latest, download_ok=True)
                        os._exit(0)
                threading.Thread(target=_bg_forced, daemon=True).start()
            else:
                _forced_update_mac(url, latest)

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
                        success = _auto_update_windows(url, latest, zip_url=zip_url)
                    elif sys.platform == "darwin":
                        success = _auto_update_mac(url, latest)
                except Exception as e:
                    _log(f"[UPDATE] Background update failed: {e}")
                    success = False

                if success:
                    _mark_nagged(latest, download_ok=True)
                    if sys.platform == "win32":
                        _log(f"[UPDATE] ✅ v{latest} bat script launched — exiting")
                        os._exit(0)
                    else:
                        _log(f"[UPDATE] ✅ v{latest} installer launched")
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

    Two update paths:
      1. Forced update — silent zip install on Windows, dialog on Mac
      2. Silent background install

    Post-wake delay prevents crashes when WiFi is not reconnected yet.
    All download paths check network readiness first.
    mark_nagged only set to download_ok=True AFTER successful handling.

    Note: mtime detection removed — the zip-based Windows update flow
    handles restarts via os._exit(0) + bat script, not mtime polling.
    Mac restarts are handled by LaunchAgent after pkg install.
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

            try:
                data = check_version(api_base, current_version)

                if not data or not data.get("update_available"):
                    continue

                latest = data.get("latest_version", "unknown")
                url = data.get("download_url", "")
                zip_url = data.get("zip_url", "")  # Windows only; Mac always receives None/""

                if not url:
                    continue

                # Already handled this version (and download succeeded)
                if _already_nagged(latest):
                    continue

                _log(f"[UPDATE] Background check: update available v{current_version} → v{latest} "
                     f"(force={data.get('force', False)})")

                # -- Forced update — silent on Windows, dialog on Mac --
                if data.get("force"):
                    _log(f"[UPDATE] Forced update detected mid-session: "
                         f"{current_version} -> {latest}")
                    _mark_nagged(latest, download_ok=False)
                    if sys.platform == "win32":
                        success = _auto_update_windows(url, latest, zip_url=zip_url)
                        if success:
                            _mark_nagged(latest, download_ok=True)
                            os._exit(0)
                    else:
                        _forced_update_mac(url, latest)

                # -- Silent background install --
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
                            _log(f"[UPDATE] ✅ v{latest} bat script launched — exiting")
                            os._exit(0)
                        else:
                            _log(f"[UPDATE] ✅ v{latest} installer launched")
                    else:
                        # Don't permanently skip - will retry next cycle
                        _log("[UPDATE] Download/install failed - will retry next cycle")

            except Exception as e:
                # Never let an update check crash the background thread
                _log(f"[UPDATE] Background check error (non-fatal): {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    _log(f"[UPDATE] Background checker running (every {RECHECK_INTERVAL}s)")