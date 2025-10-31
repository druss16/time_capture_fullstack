#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mac Activity Agent with:
- PID file + CLI (start|stop|status)
- Admin kill-switch via /api/agent/control/?user=&host=
- One-time "hello" handshake to auto-provision user in Django (/api/agents/hello/)
- Identity headers on every POST (X-Agent-User, X-Agent-Host)
- Context bus for structured hints
"""

import os
import sys
import time
import json
import sqlite3
import platform
import subprocess
import threading
import signal
import uuid
import getpass
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

# ---------------- Config ----------------
CONFIG_FILE = os.path.expanduser("~/.timetracker/config.json")
PID_FILE    = os.path.expanduser("~/Library/ActivityAgent/agent.pid")
DB_PATH_DEFAULT = os.path.expanduser("~/Library/ActivityAgent/agent.sqlite3")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load {CONFIG_FILE}: {e}")
    return {}

config = load_config()

# Tunables (config then env then defaults)
def _get(name, default=None, env=None):
    if name in config: return config[name]
    if env and os.getenv(env) is not None: return os.getenv(env)
    return default

POST_URL          = _get("api_url", os.getenv("AGENT_POST_URL")) or "http://localhost:7123/api/raw-events/"
API_KEY           = _get("api_key", os.getenv("AGENT_API_KEY"))
POLL_SECONDS      = int(_get("poll_seconds", _get("AGENT_POLL_SECONDS", 5, "AGENT_POLL_SECONDS")) or 5)
MIN_DWELL_SECONDS = int(_get("min_dwell_seconds", _get("AGENT_MIN_DWELL_SECONDS", 15, "AGENT_MIN_DWELL_SECONDS")) or 15)
VERBOSE           = bool(_get("verbose", os.getenv("AGENT_VERBOSE") == "1"))
PRINT_EVERY_POLL  = bool(_get("print_every", os.getenv("AGENT_PRINT_EVERY") == "1"))
DISABLE_AX        = bool(_get("disable_ax", os.getenv("AGENT_DISABLE_AX") == "1"))
EXCLUDE_BUNDLES   = set(_get("exclude_bundles", os.getenv("AGENT_EXCLUDE_BUNDLES", "").split(",")) or [])
DB_PATH           = _get("db_path", os.getenv("MAC_AGENT_DB")) or DB_PATH_DEFAULT
CONTEXT_PORT      = int(_get("context_port", os.getenv("AGENT_CONTEXT_PORT")) or 7321)

# New: hello + control endpoints
HELLO_URL         = _get("agent_hello_url", None) or "http://localhost:7123/api/agents/hello/"
CONTROL_URL       = _get("agent_control_url", None) or "http://localhost:7123/api/agent/control/"
CONTROL_POLL_S    = int(_get("agent_control_poll_seconds", 10))

APP_VERSION     = _get("app_version", os.getenv("AGENT_APP_VERSION")) or "1.0.0"
DEVICE_ID_FILE  = _get("device_id_file", os.path.expanduser("~/.mavops_device_id"))

# ---------------- Logging ----------------
def log(msg: str):
    if VERBOSE:
        print(msg, flush=True)

# ---------------- Context bus ----------------
from http.server import BaseHTTPRequestHandler, HTTPServer
_CONTEXT: Dict[str, dict] = {}
class _CtxHandler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_POST(self):
        if self.path != "/context":
            self.send_response(404); self.end_headers(); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw or b"{}")
            src = (data.get("source") or "unknown").lower()
            _CONTEXT[src] = data
            self.send_response(200); self.end_headers()
        except Exception:
            self.send_response(400); self.end_headers()

def start_context_bus(port: int):
    srv = HTTPServer(("127.0.0.1", port), _CtxHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log(f"[CTX] Listening on http://127.0.0.1:{port}/context")
    return srv

def snapshot_ctx() -> dict:
    try:
        return json.loads(json.dumps(_CONTEXT))
    except Exception:
        return {}

# ---------------- macOS frameworks ----------------
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

from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListOptionOnScreenAboveWindow,
    kCGNullWindowID,
)

# ---------------- DB ----------------
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

# ---------------- AppleScript helpers ----------------
def osa(script: str) -> str:
    try:
        out = subprocess.check_output(["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL).strip()
        return out
    except Exception:
        return ""

def osa_retry(script: str, tries: int = 2, delay: float = 0.15) -> str:
    for _ in range(tries):
        out = osa(script)
        if out:
            return out
        time.sleep(delay)
    return ""

# Frontmost via System Events
def get_frontmost_via_system_events() -> Optional[Tuple[str, int]]:
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

_OVERLAY_OWNERS = {
    "Window Server", "Control Center", "Notification Center", "Dock",
    "Spotlight", "ScreenSaverEngine", "PowerChime", "Creative Cloud",
    "Adobe CEF Helper", "Adobe Desktop Service"
}
def get_frontmost_via_quartz() -> Optional[Tuple[str, int, Optional[str]]]:
    try:
        opts = kCGWindowListOptionOnScreenOnly | kCGWindowListOptionOnScreenAboveWindow
        info = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) or []
        if not info: return None
        for w in info:
            owner = w.get("kCGWindowOwnerName") or ""
            if owner in _OVERLAY_OWNERS: continue
            layer = int(w.get("kCGWindowLayer") or 0)
            if layer != 0: continue
            alpha = float(w.get("kCGWindowAlpha") or 1.0)
            if alpha <= 0.01: continue
            pid = int(w.get("kCGWindowOwnerPID") or 0)
            title = w.get("kCGWindowName") or None
            return (str(owner), pid, title)
        top = info[0]
        return (str(top.get("kCGWindowOwnerName") or ""), int(top.get("kCGWindowOwnerPID") or 0), top.get("kCGWindowName") or None)
    except Exception:
        return None

def get_frontmost_via_nsworkspace() -> Optional[Tuple[str, int]]:
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not app: return None
        return (str(app.localizedName() or ""), int(app.processIdentifier()))
    except Exception:
        return None

def get_frontmost_app() -> Optional[Tuple[str, str, int, Optional[str]]]:
    se = get_frontmost_via_system_events()
    if se:
        name, pid = se
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        return (name, bid, pid, None)

    q = get_frontmost_via_quartz()
    if q:
        name, pid, qtitle = q
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        return (name, bid, pid, qtitle)

    ws = get_frontmost_via_nsworkspace()
    if ws:
        name, pid = ws
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        return (name, bid, pid, None)

    return None

def _ax_ok(code: int) -> bool:
    try:
        return code == 0 or code == kAXErrorSuccess
    except Exception:
        return False

def get_window_title_via_ax(pid: int) -> Optional[str]:
    if not AX_AVAILABLE: return None
    try:
        app_ref = AXUIElementCreateApplication(pid)
        try:
            err, window = AXUIElementCopyAttributeValue(app_ref, kAXFocusedWindowAttribute, None)
        except Exception:
            window = AXUIElementCopyAttributeValue(app_ref, kAXFocusedWindowAttribute); err = 0 if window else 1
        if not _ax_ok(err) or window is None: return None
        try:
            err2, title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute, None)
        except Exception:
            title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute); err2 = 0 if title else 1
        if not _ax_ok(err2): return None
        return str(title) if title else None
    except Exception as e:
        log(f"[WARN] AX read failed: {e}")
        return None

def try_get_url_or_path(bundle_id: str) -> Dict[str, Optional[str]]:
    # Safari
    if bundle_id == "com.apple.Safari":
        url = osa_retry('tell application "Safari" to try\nset u to URL of current tab of front window\nreturn u\non error\nreturn ""\nend try')
        return {"url": url or None, "file_path": None}
    # Chrome
    if bundle_id in ("com.google.Chrome", "com.google.Chrome.canary"):
        url = osa_retry('tell application "Google Chrome" to try\nset u to URL of active tab of front window\nreturn u\non error\nreturn ""\nend try')
        return {"url": url or None, "file_path": None}
    # Brave
    if bundle_id == "com.brave.Browser":
        url = osa_retry('tell application "Brave Browser" to try\nset u to URL of active tab of front window\nreturn u\non error\nreturn ""\nend try')
        return {"url": url or None, "file_path": None}
    # Preview
    if bundle_id == "com.apple.Preview":
        path = osa_retry('tell application "Preview" to try\nset theDoc to document 1\nset p to path of theDoc\nPOSIX path of p\non error\nreturn ""\nend try')
        return {"url": None, "file_path": path or None}
    # Excel
    if bundle_id == "com.microsoft.Excel":
        path = osa_retry('tell application "Microsoft Excel" to try\nif not (exists active workbook) then return ""\nset p to (full name of active workbook)\nreturn POSIX path of p\non error\nreturn ""\nend try')
        return {"url": None, "file_path": path or None}
    # Sublime
    if bundle_id in ("com.sublimetext.4", "com.sublimetext.3"):
        path = osa_retry('tell application "Sublime Text" to try\nif not (exists window 1) then return ""\nset theDoc to document of window 1\nif theDoc is missing value then return ""\nset p to (path of theDoc)\nreturn POSIX path of p\non error\nreturn ""\nend try')
        return {"url": None, "file_path": path or None}
    return {"url": None, "file_path": None}

# ---------------- PID utils ----------------
def write_pid():
    try:
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log(f"[WARN] Could not write PID file: {e}")

def remove_pid():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

def read_pid():
    if not os.path.exists(PID_FILE): return None
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None

# ---------------- Networking helpers ----------------
def http_post_json(url: str, payload: dict, headers: dict, timeout=5):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    for k,v in headers.items(): req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def http_get_json(url: str, headers: dict, timeout=5) -> dict:
    import urllib.request, urllib.error
    req = urllib.request.Request(url, method="GET")
    for k,v in headers.items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        log(f"[CTRL] HTTP {e.code} from control")
        return {}
    except Exception as e:
        log(f"[CTRL] get error: {e}")
        return {}

def get_device_id() -> str:
    try:
        if os.path.exists(DEVICE_ID_FILE):
            with open(DEVICE_ID_FILE, "r") as f:
                did = f.read().strip()
                if did:
                    return did
        did = str(uuid.uuid4())
        os.makedirs(os.path.dirname(DEVICE_ID_FILE), exist_ok=True)
        with open(DEVICE_ID_FILE, "w") as f:
            f.write(did)
        return did
    except Exception:
        # fall back to a transient id if the file write fails
        return str(uuid.uuid4())

def get_os_username() -> str:
    # launchd contexts sometimes break os.getlogin(); try multiple sources
    for fn in (
        lambda: os.getlogin(),
        lambda: getpass.getuser(),
        lambda: os.environ.get("LOGNAME"),
        lambda: os.environ.get("USER"),
        lambda: os.environ.get("USERNAME"),
    ):
        try:
            v = fn()
            if v:
                return str(v)
        except Exception:
            pass
    return "unknown"

# ---------------- Handshake & control ----------------
SERVER_USER_ID = None

def hello(server_url: str, user: str, host: str, device_id: str):
    global SERVER_USER_ID
    headers = {
        "Content-Type": "application/json",
        "X-Agent-User": user,
        "X-Agent-Host": host,
        "X-Agent-Platform": platform.platform(),
        "X-Agent-Version": APP_VERSION,
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = {
        # JSON body fallback used by your agents_hello view
        "user": user,
        "hostname": host,
        "app_version": APP_VERSION,
        "device_id": device_id,
    }
    try:
        raw = http_post_json(server_url, payload, headers)
        data = json.loads(raw or b"{}")
        SERVER_USER_ID = data.get("user_id")
        log(f"[HELLO] Registered with server: user_id={SERVER_USER_ID}")
    except Exception as e:
        log(f"[HELLO] failed: {e}")

_last_control_check = 0.0
def should_stop(control_url: str, user: str, host: str) -> bool:
    global _last_control_check
    now = time.time()
    if now - _last_control_check < CONTROL_POLL_S:
        return False
    _last_control_check = now
    qs = f"?user={user}&host={host}"
    headers = {"Accept": "application/json", "X-Agent-User": user, "X-Agent-Host": host}
    if API_KEY: headers["Authorization"] = f"Bearer {API_KEY}"
    data = http_get_json(control_url + qs, headers)
    stop = bool(data.get("stop"))
    if stop:
        log(f"[CTRL] Stop received from server: reason={data.get('reason','')}")
    return stop

# ---------------- Posting ----------------
def post_event_async(event: dict):
    if not POST_URL:
        return
    def _run():
        try:
            import urllib.request
            req = urllib.request.Request(POST_URL, data=json.dumps(event).encode("utf-8"), method="POST")
            req.add_header("Content-Type", "application/json")
            # Identity headers
            req.add_header("X-Agent-User", event.get("user", "unknown"))
            req.add_header("X-Agent-Host", event.get("hostname", "unknown"))
            req.add_header("X-Agent-Platform", platform.platform())
            req.add_header("X-Agent-Version", APP_VERSION)
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

    payload = {
        "ts_utc": ts,
        "app_name": app_name,
        "bundle_id": bundle_id,
        "window_title": title or "",
        "url": url,
        "file_path": fpath,
        "user": user,
        "hostname": hostname,
        "server_user_id": SERVER_USER_ID,   # handy for backend mapping
        "device_id": get_device_id(),  # include stable device id with each event
        "ctx": snapshot_ctx(),
    }
    post_event_async(payload)
    log(f"[EVENT] dwell-finalized • {app_name} • {title or '(no title)'} • url={url or '-'} • path={fpath or '-'}")

# ---------------- Main loop ----------------
def run_agent():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    start_context_bus(CONTEXT_PORT)

    log("=== Mac Activity Agent starting… (Ctrl+C to stop) ===")
    if os.path.exists(CONFIG_FILE): log(f"CONFIG={CONFIG_FILE} (loaded)")
    else: log(f"CONFIG={CONFIG_FILE} (not found, using ENV)")

    log(f"DB_PATH={DB_PATH}")
    log(f"POST_URL={POST_URL or '(disabled)'}")
    log(f"HELLO_URL={HELLO_URL}")
    log(f"CONTROL_URL={CONTROL_URL} (poll {CONTROL_POLL_S}s)")
    log(f"AX_AVAILABLE={AX_AVAILABLE}")
    log(f"POLL_SECONDS={POLL_SECONDS}, MIN_DWELL_SECONDS={MIN_DWELL_SECONDS}")
    if EXCLUDE_BUNDLES: log(f"EXCLUDE_BUNDLES={sorted([b for b in EXCLUDE_BUNDLES if b])}")

    conn = ensure_db()
    cur = conn.cursor()
    user = get_os_username()
    hostname = platform.node()
    device_id = get_device_id()

    # PID file
    write_pid()

    # Server handshake (auto-provision user)
    hello(HELLO_URL, user, hostname, device_id)

    current_sig = None
    dwell_start = None

    try:
        while True:
            # admin kill-switch
            if should_stop(CONTROL_URL, user, hostname):
                log("[CTRL] Stopping agent per admin request.")
                break

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
                    log(f"[POLL] Excluded: {bundle_id}")
                if current_sig and dwell_start:
                    dwell = time.time() - dwell_start
                    if dwell >= MIN_DWELL_SECONDS:
                        write_event(conn, cur, user, hostname, current_sig)
                current_sig = None
                dwell_start = None
                time.sleep(POLL_SECONDS)
                continue

            # title
            title_ax = get_window_title_via_ax(pid) or ""
            title = title_ax or (fallback_title or "")

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
    finally:
        remove_pid()

# ---------------- CLI ----------------
def cmd_status():
    pid = read_pid()
    if not pid:
        print("Agent status: not running")
        return
    try:
        os.kill(pid, 0)
        print(f"Agent status: running (PID {pid})")
    except ProcessLookupError:
        print("Agent status: stale pid file, removing…")
        remove_pid()

def cmd_stop():
    pid = read_pid()
    if not pid:
        print("No PID file — agent not running?")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"🛑 Stopped agent (PID {pid})")
        remove_pid()
    except ProcessLookupError:
        print("Process not found — removing stale PID file.")
        remove_pid()
    except Exception as e:
        print(f"Error stopping agent: {e}")

def main():
    if len(sys.argv) >= 2:
        sub = sys.argv[1].lower()
        if sub in ("stop", "kill"):
            return cmd_stop()
        if sub in ("status",):
            return cmd_status()
        if sub in ("start", "run"):
            # start in foreground
            return run_agent()
        if sub in ("start-bg", "daemon"):
            # background
            if read_pid():
                print("Already running. Use `main.py status`.")
                return
            pid = os.fork()
            if pid > 0:
                print("Started agent in background.")
                return
            # child
            os.setsid()
            run_agent()
            return
        print("Usage: main.py [start|start-bg|stop|status]")
        return
    # default: foreground start
    run_agent()

if __name__ == "__main__":
    main()