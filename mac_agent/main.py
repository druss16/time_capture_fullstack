#!/usr/bin/env python3
"""
Mac Activity Agent (frontmost: System Events → Quartz → NSWorkspace)
- Uses System Events (most reliable) to find truly frontmost app/pid
- Falls back to Quartz (filters overlays) then NSWorkspace
- Uses AX (Accessibility) for focused window title, falls back to Quartz title
- Uses AppleScript to fetch URL/file path for common apps (with retry)
- Dwell-based posting to reduce noise; optional excludes by bundle id

ENV (all optional):
  AGENT_POST_URL=http://localhost:7123/tracker/raw-events/
  AGENT_API_KEY=...
  AGENT_POLL_SECONDS=5
  AGENT_VERBOSE=1
  AGENT_PRINT_EVERY=0
  AGENT_DISABLE_AX=0
  AGENT_MIN_DWELL_SECONDS=15
  AGENT_EXCLUDE_BUNDLES=com.apple.Terminal,com.apple.systempreferences
  MAC_AGENT_DB=~/Library/ActivityAgent/agent.sqlite3

Notes:
- Accessibility permission is required for AX titles (you enabled it).
- Automation permission prompts appear when first reading URLs/paths (approve).
- Screen Recording permission is NOT required for titles/URLs, but can help Quartz
  show window titles for some apps (Settings → Privacy & Security → Screen Recording).
"""

import os
import sys
import time
import json
import sqlite3
import platform
import subprocess
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

# ---------- Tunables via ENV ----------
POLL_SECONDS       = int(os.getenv("AGENT_POLL_SECONDS", "5"))
VERBOSE            = os.getenv("AGENT_VERBOSE", "1") == "1"
PRINT_EVERY_POLL   = os.getenv("AGENT_PRINT_EVERY", "0") == "1"
DISABLE_AX         = os.getenv("AGENT_DISABLE_AX", "0") == "1"
MIN_DWELL_SECONDS  = int(os.getenv("AGENT_MIN_DWELL_SECONDS", "15"))
DB_PATH            = os.getenv("MAC_AGENT_DB", os.path.expanduser("~/Library/ActivityAgent/agent.sqlite3"))
POST_URL           = os.getenv("AGENT_POST_URL")
API_KEY            = os.getenv("AGENT_API_KEY")
EXCLUDE_BUNDLES    = set(b.strip() for b in os.getenv("AGENT_EXCLUDE_BUNDLES", "").split(",") if b.strip())

def log(msg: str):
    if VERBOSE:
        print(msg, flush=True)

# ---------- macOS frameworks ----------
from AppKit import NSWorkspace, NSRunningApplication  # Cocoa

AX_AVAILABLE = False
if not DISABLE_AX:
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            kAXTitleAttribute,
            kAXFocusedWindowAttribute,
            kAXErrorSuccess,
        )
        AX_AVAILABLE = True
    except Exception:
        AX_AVAILABLE = False

# Quartz (window server) for fallback
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListOptionOnScreenAboveWindow,
    kCGNullWindowID,
)

# ---------- Storage ----------
def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS raw_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            app_name TEXT,
            bundle_id TEXT,
            window_title TEXT,
            url TEXT,
            file_path TEXT,
            user TEXT,
            hostname TEXT,
            posted INTEGER DEFAULT 0
        )"""
    )
    conn.commit()
    return conn

# ---------- AppleScript helpers ----------
def osa(script: str) -> str:
    try:
        out = subprocess.check_output(["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL).strip()
        return out
    except Exception:
        return ""

def osa_retry(script: str, tries: int = 2, delay: float = 0.15) -> str:
    """Run AppleScript with one quick retry (helps during active window switches)."""
    for _ in range(tries):
        out = osa(script)
        if out:
            return out
        time.sleep(delay)
    return ""

# 1) PRIMARY: System Events (most reliable frontmost)
def get_frontmost_via_system_events() -> Optional[Tuple[str, int]]:
    # returns (process_name, pid) or None
    s = (
        'tell application "System Events" to try\n'
        'set p to first process whose frontmost is true\n'
        'return (name of p as text) & "|" & (unix id of p as text)\n'
        'on error\nreturn ""\nend try'
    )
    out = osa(s)
    if "|" in out:
        name, pid = out.split("|", 1)
        try:
            return name, int(pid)
        except ValueError:
            return None
    return None

# 2) FALLBACK: Quartz (filter overlays & weird layers)
_OVERLAY_OWNERS = {
    "Window Server", "Control Center", "Notification Center", "Dock",
    "Spotlight", "ScreenSaverEngine", "PowerChime", "Creative Cloud",
    "Adobe CEF Helper", "Adobe Desktop Service"
}
def get_frontmost_via_quartz() -> Optional[Tuple[str, int, Optional[str]]]:
    """
    Returns (owner_name, pid, quartz_window_title) for the best candidate.
    We filter to layer 0 (normal windows), visible, non-overlay owners.
    """
    try:
        opts = kCGWindowListOptionOnScreenOnly | kCGWindowListOptionOnScreenAboveWindow
        info = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) or []
        if not info:
            return None

        # pick first "normal" window
        for w in info:
            owner = w.get("kCGWindowOwnerName") or ""
            if owner in _OVERLAY_OWNERS:
                continue
            layer = int(w.get("kCGWindowLayer") or 0)
            if layer != 0:
                continue
            alpha = float(w.get("kCGWindowAlpha") or 1.0)
            if alpha <= 0.01:
                continue
            pid = int(w.get("kCGWindowOwnerPID") or 0)
            title = w.get("kCGWindowName") or None
            return (str(owner), pid, title)
        # as last resort, return top entry anyway
        top = info[0]
        return (str(top.get("kCGWindowOwnerName") or ""), int(top.get("kCGWindowOwnerPID") or 0), top.get("kCGWindowName") or None)
    except Exception:
        return None

# 3) LAST RESORT: NSWorkspace
def get_frontmost_via_nsworkspace() -> Optional[Tuple[str, int]]:
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not app:
            return None
        return (str(app.localizedName() or ""), int(app.processIdentifier()))
    except Exception:
        return None

# Unified frontmost: returns (app_name, bundle_id, pid, fallback_title)
def get_frontmost_app() -> Optional[Tuple[str, str, int, Optional[str]]]:
    # Try System Events
    se = get_frontmost_via_system_events()
    if se:
        name, pid = se
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        return (name, bid, pid, None)

    # Try Quartz
    q = get_frontmost_via_quartz()
    if q:
        name, pid, qtitle = q
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        return (name, bid, pid, qtitle)

    # Try NSWorkspace
    ws = get_frontmost_via_nsworkspace()
    if ws:
        name, pid = ws
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        return (name, bid, pid, None)

    return None

# ---------- AX title ----------
def _ax_ok(code: int) -> bool:
    try:
        return code == 0 or code == kAXErrorSuccess
    except Exception:
        return False

def get_window_title_via_ax(pid: int) -> Optional[str]:
    if not AX_AVAILABLE:
        return None
    try:
        app_ref = AXUIElementCreateApplication(pid)
        try:
            err, window = AXUIElementCopyAttributeValue(app_ref, kAXFocusedWindowAttribute, None)
        except Exception:
            window = AXUIElementCopyAttributeValue(app_ref, kAXFocusedWindowAttribute)
            err = 0 if window else 1
        if not _ax_ok(err) or window is None:
            return None
        try:
            err2, title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute, None)
        except Exception:
            title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute)
            err2 = 0 if title else 1
        if not _ax_ok(err2):
            return None
        return str(title) if title else None
    except Exception as e:
        log(f"[WARN] AX read failed: {e}")
        return None

# ---------- URL/path via AppleScript (with retry) ----------
def try_get_url_or_path(bundle_id: str) -> Dict[str, Optional[str]]:
    # Safari
    if bundle_id == "com.apple.Safari":
        url = osa_retry(
            'tell application "Safari" to try\n'
            'set u to URL of current tab of front window\n'
            'return u\non error\nreturn ""\nend try'
        )
        return {"url": url or None, "file_path": None}

    # Chrome (stable/canary)
    if bundle_id in ("com.google.Chrome", "com.google.Chrome.canary"):
        url = osa_retry(
            'tell application "Google Chrome" to try\n'
            'set u to URL of active tab of front window\n'
            'return u\non error\nreturn ""\nend try'
        )
        return {"url": url or None, "file_path": None}

    # Brave
    if bundle_id == "com.brave.Browser":
        url = osa_retry(
            'tell application "Brave Browser" to try\n'
            'set u to URL of active tab of front window\n'
            'return u\non error\nreturn ""\nend try'
        )
        return {"url": url or None, "file_path": None}

    # Preview
    if bundle_id == "com.apple.Preview":
        path = osa_retry(
            'tell application "Preview" to try\n'
            'set theDoc to document 1\n'
            'set p to path of theDoc\n'
            'POSIX path of p\n'
            'on error\nreturn ""\nend try'
        )
        return {"url": None, "file_path": path or None}

    # Excel
    if bundle_id == "com.microsoft.Excel":
        path = osa_retry(
            'tell application "Microsoft Excel" to try\n'
            'if not (exists active workbook) then return ""\n'
            'set p to (full name of active workbook)\n'
            'return POSIX path of p\n'
            'on error\nreturn ""\nend try'
        )
        return {"url": None, "file_path": path or None}

    # Sublime Text (v4/v3)
    if bundle_id in ("com.sublimetext.4", "com.sublimetext.3"):
        path = osa_retry(
            'tell application "Sublime Text" to try\n'
            'if not (exists window 1) then return ""\n'
            'set theDoc to document of window 1\n'
            'if theDoc is missing value then return ""\n'
            'set p to (path of theDoc)\n'
            'return POSIX path of p\n'
            'on error\nreturn ""\nend try'
        )
        return {"url": None, "file_path": path or None}

    return {"url": None, "file_path": None}

# ---------- Posting ----------
def post_event_async(event: dict):
    if not POST_URL:
        return
    def _run():
        try:
            import urllib.request
            req = urllib.request.Request(POST_URL, data=json.dumps(event).encode("utf-8"), method="POST")
            req.add_header("Content-Type", "application/json")
            if API_KEY:
                req.add_header("Authorization", f"Bearer {API_KEY}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                _ = resp.read()
            log(f"[POSTED] {POST_URL}")
        except Exception as e:
            log(f"[POST ERROR] {e}")
    threading.Thread(target=_run, daemon=True).start()

def write_event(conn, cur, user: str, hostname: str, sig):
    app_name, bundle_id, title, url, fpath = sig
    ts = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO raw_events (ts_utc, app_name, bundle_id, window_title, url, file_path, user, hostname) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, app_name, bundle_id, title or "", url, fpath, user, hostname),
    )
    conn.commit()
    post_event_async({
        "ts_utc": ts, "app_name": app_name, "bundle_id": bundle_id,
        "window_title": title or "", "url": url, "file_path": fpath,
        "user": user, "hostname": hostname,
    })
    log(f"[EVENT] dwell-finalized • {app_name} • {title or '(no title)'} • url={url or '-'} • path={fpath or '-'}")

# ---------- Main ----------
def main():
    # live logs
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    log("=== Mac Activity Agent starting… (Ctrl+C to stop) ===")
    log(f"DB_PATH={DB_PATH}")
    log(f"POST_URL={POST_URL or '(disabled)'}")
    log(f"AX_AVAILABLE={AX_AVAILABLE} (set AGENT_DISABLE_AX=1 to skip)")
    log(f"POLL_SECONDS={POLL_SECONDS}, MIN_DWELL_SECONDS={MIN_DWELL_SECONDS}")
    log(f"VERBOSE={VERBOSE}, PRINT_EVERY_POLL={PRINT_EVERY_POLL}")
    if EXCLUDE_BUNDLES:
        log(f"EXCLUDE_BUNDLES={sorted(EXCLUDE_BUNDLES)}")
    log("[NOTE] On first URL read, macOS may prompt to allow Terminal to control Safari/Chrome (Automation).")
    log("[TIP] Screen Recording is optional; enabling it can improve Quartz window titles.")

    conn = ensure_db()
    cur = conn.cursor()
    user = os.getenv("USER") or "unknown"
    hostname = platform.node()

    current_sig = None
    dwell_start = None

    while True:
        try:
            # unified frontmost detection
            front = get_frontmost_app()
            if not front:
                if PRINT_EVERY_POLL:
                    log("[POLL] No frontmost")
                time.sleep(POLL_SECONDS)
                continue

            app_name, bundle_id, pid, fallback_title = front

            # excludes
            if bundle_id in EXCLUDE_BUNDLES:
                if PRINT_EVERY_POLL:
                    log(f"[POLL] Excluded bundle: {bundle_id}")
                if current_sig and dwell_start:
                    dwell = time.time() - dwell_start
                    if dwell >= MIN_DWELL_SECONDS:
                        write_event(conn, cur, user, hostname, current_sig)
                current_sig = None
                dwell_start = None
                time.sleep(POLL_SECONDS)
                continue

            # title via AX, else Quartz fallback title
            title_ax = get_window_title_via_ax(pid) or ""
            title = title_ax or (fallback_title or "")

            # URL/path via OSA for known apps (with retry)
            extras = try_get_url_or_path(bundle_id)
            url, fpath = extras.get("url"), extras.get("file_path")

            sig = (app_name, bundle_id, title, url, fpath)

            if sig != current_sig:
                if current_sig and dwell_start:
                    dwell = time.time() - dwell_start
                    if dwell >= MIN_DWELL_SECONDS:
                        write_event(conn, cur, user, hostname, current_sig)
                    else:
                        log(f"[SKIP] dwell too short ({int(dwell)}s) for {current_sig[0]}")
                current_sig = sig
                dwell_start = time.time()
                log(f"[FOCUS] {app_name} • {title or '(no title)'} • url={url or '-'} • path={fpath or '-'}")
            else:
                if PRINT_EVERY_POLL:
                    log(f"[POLL] dwelling {int(time.time()-dwell_start)}s • {app_name}")

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log("=== Stopping (Ctrl+C) ===")
            if current_sig and dwell_start:
                dwell = time.time() - dwell_start
                if dwell >= MIN_DWELL_SECONDS:
                    write_event(conn, cur, user, hostname, current_sig)
            break
        except Exception as e:
            log(f"[LOOP ERROR] {e}")
            time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
