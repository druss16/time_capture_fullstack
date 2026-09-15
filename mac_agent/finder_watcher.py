"""
Finder Folder Watcher — the Mac counterpart of windows_agent/explorer_watcher.py.

When the user opens a folder in Finder, feed the full POSIX path into
AIClientSwitcher so it can attribute the time, exactly as the Windows agent
does when Explorer's address bar changes.

Why this exists at all: a Finder window's *title* is only the folder's leaf
name — "2024 1040" — which names no client. Its *path* is
"/Users/dan/Clients/Varacchi/2024 1040", which names one unambiguously. The
window title is all the tracking loop ever saw, so browsing a client's folder
produced no client signal on Mac.

Design (mirrors the Windows watcher):
- Runs in its own daemon thread
- Only asks Finder for a path when Finder is frontmost
- Debounces the same path (3s window)
- Never raises into the caller; a failure degrades to today's behavior

Usage from main.py:
    from finder_watcher import FinderFolderWatcher
    finder_watcher = FinderFolderWatcher(ai_switcher=ai_switcher, log_fn=log)
    finder_watcher.start()
    # ...
    finder_watcher.stop()  # on shutdown
"""

import os
import subprocess
import threading
import time
from typing import Callable, Optional

try:
    from AppKit import NSWorkspace
    NSWORKSPACE_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    NSWORKSPACE_AVAILABLE = False

FINDER_BUNDLE_ID = "com.apple.finder"

# Polling cadence — matches the agent's POLL_SECONDS for a consistent feel.
POLL_SECONDS = 2.0

# Ignore the same path within this window.
DEBOUNCE_SECONDS = 3.0

# osascript is a subprocess; never let a wedged one hold the thread.
OSASCRIPT_TIMEOUT = 3.0

# Finder's front window as a POSIX path. `target of front window` covers a
# normal browsing window; the error branch covers the desktop, a search
# results window, and the Trash, none of which name a place on disk we can
# attribute. Returns "" rather than raising so the caller reads one thing.
_FRONT_FOLDER_SCRIPT = '''
tell application "Finder"
    try
        if (count of Finder windows) is 0 then return ""
        set theTarget to target of front Finder window
        return POSIX path of (theTarget as alias)
    on error
        return ""
    end try
end tell
'''

# Folders that are a place rather than a client's work. Browsing your own
# Downloads folder should not attribute time to a client who happens to be
# called Downloads, and more importantly should not overwrite the client the
# user was actually on.
_NOISE_PATHS = {
    "/", "/applications", "/library", "/system", "/users", "/volumes",
    "/private", "/tmp", "/var", "/usr", "/opt",
}

_NOISE_LEAF_NAMES = {
    "desktop", "documents", "downloads", "pictures", "music", "movies",
    "public", "library", "applications", "home", "icloud drive",
    "dropbox", "onedrive", "google drive", "box", "recents", "trash",
}


class FinderFolderWatcher:
    """Watches the frontmost Finder window and feeds paths to AIClientSwitcher."""

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if not self.enabled:
            self.log("[FINDER] Disabled by config — not starting watcher")
            return
        if self.ai_switcher is None:
            self.log("[FINDER] No AI switcher provided — watcher disabled")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="FinderFolderWatcher"
        )
        self._thread.start()
        method = "NSWorkspace" if NSWORKSPACE_AVAILABLE else "osascript-only"
        self.log(
            f"[FINDER] ✅ Folder watcher started "
            f"(frontmost={method}, poll={self.poll_seconds}s)"
        )

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------
    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                # Never let an exception kill the watcher thread.
                self.log(f"[FINDER] Tick error: {e}")
            self._stop_event.wait(self.poll_seconds)

    def _tick(self):
        if not self._finder_is_frontmost():
            return

        path = self._read_front_folder()
        if not path:
            return

        path = path.rstrip("/") or "/"

        if self._is_noise(path):
            return

        now = time.time()
        if path == self._last_path and (now - self._last_path_at) < DEBOUNCE_SECONDS:
            return

        self._last_path = path
        self._last_path_at = now
        self._dispatch_path(path)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def _finder_is_frontmost(self) -> bool:
        """Is Finder the frontmost app? Cheap gate before the osascript call."""
        if not NSWORKSPACE_AVAILABLE:
            # Without NSWorkspace we cannot gate cheaply. Asking Finder for its
            # front window while another app is frontmost is harmless — Finder
            # answers about its own window either way — but it costs a
            # subprocess every poll, so say so once and carry on.
            return True
        try:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return False
            return str(app.bundleIdentifier() or "") == FINDER_BUNDLE_ID
        except Exception as e:
            self.log(f"[FINDER] frontmost check failed: {e}")
            return False

    def _read_front_folder(self) -> Optional[str]:
        """Ask Finder for its front window's folder as a POSIX path."""
        try:
            result = subprocess.run(
                ["osascript", "-e", _FRONT_FOLDER_SCRIPT],
                capture_output=True,
                text=True,
                timeout=OSASCRIPT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            self.log("[FINDER] osascript timed out reading front window")
            return None
        except Exception as e:
            self.log(f"[FINDER] osascript failed: {e}")
            return None

        if result.returncode != 0:
            return None
        return (result.stdout or "").strip() or None

    # ------------------------------------------------------------------
    # Filtering + dispatch
    # ------------------------------------------------------------------
    @staticmethod
    def _is_noise(path: str) -> bool:
        """Is this a place rather than a client's work?"""
        low = path.lower()
        if low in _NOISE_PATHS:
            return True
        leaf = os.path.basename(path)
        if leaf.lower() in _NOISE_LEAF_NAMES:
            return True
        # The user's own home folder: /Users/<name> and nothing below it.
        parts = [p for p in low.split("/") if p]
        if len(parts) == 2 and parts[0] == "users":
            return True
        return False

    def _dispatch_path(self, path: str):
        """Feed the path into the AI switcher, mirroring on_window_change()."""
        try:
            folder_name = os.path.basename(path) or path
            self.log(f"[FINDER] Folder open detected: {folder_name}  (path={path})")

            # Synthesize the window change the switcher already knows how to
            # handle. The full path goes into BOTH title (client codes live in
            # folder names, and the regex tier reads the title) and file_path
            # (for the path-aware tiers) — same as the Windows watcher.
            #
            # exe_name is the Finder bundle id, so an org routing rule written
            # against exe_family=finder applies here.
            self.ai_switcher.on_window_change(
                app_name="Finder",
                exe_name=FINDER_BUNDLE_ID,
                title=path,
                url=None,
                file_path=path,
            )
        except Exception as e:
            self.log(f"[FINDER] Dispatch error: {e}")
