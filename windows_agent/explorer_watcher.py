"""
Windows Explorer Folder Watcher

Mac parity: when the user opens a folder in Explorer, feed the full path into
AIClientSwitcher so it can auto-switch the client just like NSWorkspace does
on Mac.

Design:
- Runs in its own daemon thread with its own COM apartment
- Only does expensive UIA reads when Explorer is the foreground window
- Debounces same-path events (3s window)
- Strips _GENERIC_TITLE_BLOCKLIST-style titles since we have the full path
- Falls back to Shell COM if UIA can't read the address bar
- Falls back to title parsing if both fail (worst case == current behavior)

Usage from main.py:
    from explorer_watcher import ExplorerFolderWatcher
    explorer_watcher = ExplorerFolderWatcher(ai_switcher=ai_switcher)
    explorer_watcher.start()
    # ...
    explorer_watcher.stop()  # on shutdown
"""

import os
import sys
import time
import threading
import logging
from typing import Optional, Callable

try:
    import win32gui
    import win32process
    WIN_API_AVAILABLE = True
except ImportError:
    WIN_API_AVAILABLE = False

try:
    import pythoncom
    PYTHONCOM_AVAILABLE = True
except ImportError:
    PYTHONCOM_AVAILABLE = False

# UIAutomation is the preferred path — most reliable across Win10/11
try:
    import uiautomation as uia
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False

# psutil for process name lookup (already a dependency in main.py)
try:
    import psutil
except ImportError:
    psutil = None


# Explorer window class names — these are stable across Win10/11
EXPLORER_CLASSES = {
    "CabinetWClass",   # File Explorer windows
    "ExploreWClass",   # Legacy Explorer
}

# Polling cadence — match the agent's POLL_SECONDS for consistent feel
POLL_SECONDS = 2.0

# Debounce: ignore same path within this window
DEBOUNCE_SECONDS = 3.0

# How long to wait before re-scanning the foreground after a successful read.
# Keeps CPU low when user lingers in one folder.
LINGER_BACKOFF_SECONDS = 5.0


class ExplorerFolderWatcher:
    """Watches the foreground Explorer window and feeds paths to AIClientSwitcher."""

    def __init__(
        self,
        ai_switcher,
        log_fn: Optional[Callable[[str], None]] = None,
        poll_seconds: float = POLL_SECONDS,
        enabled: bool = True,
    ):
        self.ai_switcher = ai_switcher
        self.log = log_fn or (lambda msg: print(msg, flush=True))
        self.poll_seconds = poll_seconds
        self.enabled = enabled

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Debounce state
        self._last_path: Optional[str] = None
        self._last_path_at: float = 0.0
        self._last_hwnd: Optional[int] = None
        self._last_read_at: float = 0.0

        # Capability flags determined at startup
        self._can_use_uia = UIA_AVAILABLE and PYTHONCOM_AVAILABLE
        self._can_use_shell = PYTHONCOM_AVAILABLE  # Shell.Application is always there

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if not self.enabled:
            self.log("[EXPLORER] Disabled by config — not starting watcher")
            return
        if not WIN_API_AVAILABLE:
            self.log("[EXPLORER] pywin32 not available — Explorer watcher disabled")
            return
        if not (self._can_use_uia or self._can_use_shell):
            self.log("[EXPLORER] Neither UIA nor Shell COM available — watcher disabled")
            return
        if self.ai_switcher is None:
            self.log("[EXPLORER] No AI switcher provided — watcher disabled")
            return

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ExplorerFolderWatcher"
        )
        self._thread.start()
        method = "UIA" if self._can_use_uia else "Shell COM"
        self.log(f"[EXPLORER] ✅ Folder watcher started (method={method}, poll={self.poll_seconds}s)")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _run(self):
        # Each thread that touches COM needs its own apartment.
        # We use STA (single-threaded apartment) — required for UIA.
        com_initialized = False
        if PYTHONCOM_AVAILABLE:
            try:
                pythoncom.CoInitialize()
                com_initialized = True
            except Exception as e:
                self.log(f"[EXPLORER] CoInitialize failed: {e}")

        try:
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except Exception as e:
                    # Never let an exception kill the watcher thread
                    self.log(f"[EXPLORER] Tick error: {e}")

                # Sleep in small chunks so stop() responds quickly
                self._stop_event.wait(self.poll_seconds)
        finally:
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _tick(self):
        """One iteration: check if Explorer is foreground, read its path, dispatch."""
        hwnd = self._foreground_explorer_hwnd()
        if not hwnd:
            return

        # Linger backoff — if we just read this same window, don't hammer it
        now = time.time()
        if (
            hwnd == self._last_hwnd
            and (now - self._last_read_at) < LINGER_BACKOFF_SECONDS
        ):
            return

        path = self._read_explorer_path(hwnd)
        self._last_hwnd = hwnd
        self._last_read_at = now

        if not path:
            return

        # Debounce: same path within DEBOUNCE_SECONDS → skip
        if path == self._last_path and (now - self._last_path_at) < DEBOUNCE_SECONDS:
            return

        self._last_path = path
        self._last_path_at = now

        self._dispatch_path(path)

    # ------------------------------------------------------------------
    # Foreground detection
    # ------------------------------------------------------------------
    def _foreground_explorer_hwnd(self) -> Optional[int]:
        """Return hwnd if foreground window is an Explorer window, else None."""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None

            cls = win32gui.GetClassName(hwnd)
            if cls not in EXPLORER_CLASSES:
                return None

            # Extra safety: confirm the process is explorer.exe.
            # CabinetWClass *should* always be explorer.exe, but some shell
            # replacements (like Directory Opus) reuse the class.
            if psutil:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc_name = psutil.Process(pid).name().lower()
                    if proc_name != "explorer.exe":
                        return None
                except Exception:
                    pass

            return hwnd
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Path extraction — try UIA first, fall back to Shell COM, then title
    # ------------------------------------------------------------------
    def _read_explorer_path(self, hwnd: int) -> Optional[str]:
        # 1. UIA address bar — most reliable
        if self._can_use_uia:
            path = self._read_via_uia(hwnd)
            if path:
                return path

        # 2. Shell.Application enumeration — works on older Windows
        if self._can_use_shell:
            path = self._read_via_shell(hwnd)
            if path:
                return path

        # 3. Last resort: window title (current behavior, no improvement)
        try:
            title = win32gui.GetWindowText(hwnd)
            if title and title.strip():
                return title.strip()
        except Exception:
            pass

        return None

    def _read_via_uia(self, hwnd: int) -> Optional[str]:
        """Read the Explorer address bar via UI Automation.

        The address bar in modern Explorer is a ToolBar with AutomationId
        'TitleBar' or similar. Most reliable approach is to grab the window
        and look for an Edit/Document control whose value is a path.
        """
        try:
            # ControlFromHandle is the lightweight entry point — doesn't walk
            # the whole desktop tree
            window = uia.ControlFromHandle(hwnd)
            if not window:
                return None

            # Win11: address bar exposes its full path through the
            # 'Address' or 'Address: ...' edit control.
            # Win10: similar, but the control name is localized.
            #
            # The most portable approach is to look for any EditControl
            # whose value looks like a filesystem path.
            edit = window.EditControl(searchDepth=12)
            if edit and edit.Exists(0, 0):
                try:
                    pattern = edit.GetValuePattern()
                    if pattern:
                        value = pattern.Value
                        if value and self._looks_like_path(value):
                            return value
                except Exception:
                    pass

            # Fallback: walk all Edit controls (some Win11 builds nest them deeper)
            for edit_ctrl in window.GetChildren():
                try:
                    if edit_ctrl.ControlTypeName == "EditControl":
                        pattern = edit_ctrl.GetValuePattern()
                        if pattern and pattern.Value:
                            value = pattern.Value
                            if self._looks_like_path(value):
                                return value
                except Exception:
                    continue

        except Exception as e:
            # Don't log every UIA failure — too noisy
            pass

        return None

    def _read_via_shell(self, hwnd: int) -> Optional[str]:
        """Fallback: enumerate Shell windows and match by hwnd.

        Uses Shell.Application.Windows() — historically prone to deadlocks
        if the main thread also touches COM, but we're on a dedicated STA
        thread so this is safe.
        """
        try:
            from win32com.client import Dispatch

            shell = Dispatch("Shell.Application")
            windows = shell.Windows()

            for i in range(windows.Count):
                try:
                    win = windows.Item(i)
                    if win is None:
                        continue
                    if int(win.HWND) != int(hwnd):
                        continue

                    # LocationURL gives us a file:// URL — convert to path
                    location_url = getattr(win, "LocationURL", None)
                    if location_url:
                        path = self._url_to_path(location_url)
                        if path:
                            return path

                    # Some special folders only expose LocationName
                    location_name = getattr(win, "LocationName", None)
                    if location_name:
                        return location_name
                except Exception:
                    continue
        except Exception as e:
            self.log(f"[EXPLORER] Shell COM read failed: {e}")

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _looks_like_path(s: str) -> bool:
        """Heuristic: does this string look like a filesystem path?"""
        if not s or len(s) < 2:
            return False
        s = s.strip()
        # Drive letter
        if len(s) >= 2 and s[1] == ":":
            return True
        # UNC
        if s.startswith("\\\\"):
            return True
        # Forward-slash path (rare in Explorer but possible)
        if s.startswith("/"):
            return True
        return False

    @staticmethod
    def _url_to_path(url: str) -> Optional[str]:
        """Convert a file:// URL to a Windows path."""
        try:
            from urllib.parse import unquote, urlparse
            parsed = urlparse(url)
            if parsed.scheme != "file":
                return None
            # file:///C:/path → /C:/path → C:/path
            path = unquote(parsed.path)
            if path.startswith("/") and len(path) > 2 and path[2] == ":":
                path = path[1:]
            return path.replace("/", "\\")
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Dispatch into AIClientSwitcher
    # ------------------------------------------------------------------
    def _dispatch_path(self, path: str):
        """Feed the path into the AI switcher, mirroring on_window_change()."""
        try:
            folder_name = os.path.basename(path.rstrip("\\/")) or path

            self.log(f"[EXPLORER] Folder open detected: {folder_name}  (path={path})")

            # We synthesize a "window change" event the switcher already knows
            # how to handle. The full path goes into both window_title (for
            # the regex tier — client codes often appear in folder names) AND
            # file_path (for any path-aware logic in the AI tier).
            #
            # app_name="Explorer" / exe_name="explorer.exe" lets the switcher
            # apply any Explorer-specific routing rules from sync.routing_rules.
            self.ai_switcher.on_window_change(
                app_name="Explorer",
                exe_name="explorer.exe",
                title=path,
                url=None,
                file_path=path,
            )
        except Exception as e:
            self.log(f"[EXPLORER] Dispatch error: {e}")