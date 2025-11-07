#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mac Activity Agent with device pairing:

- One-time "pair" to exchange a short code for a persistent device api_key
- Authorization: DeviceKey <api_key> on every POST/GET
- /api/agents/hello2/ heartbeat auto-provisions user/device
- PID file + context bus + admin kill-switch
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

from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListOptionOnScreenAboveWindow,
    kCGNullWindowID,
    # NEW:
    CGEventSourceSecondsSinceLastEventType,
    kCGEventSourceStateCombinedSessionState,
    kCGEventMouseMoved,
)

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

def save_config(cfg: dict):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save {CONFIG_FILE}: {e}")

config = load_config()

# Tunables (config then env then defaults)
def _get(name, default=None, env=None):
    if name in config: return config[name]
    if env and os.getenv(env) is not None: return os.getenv(env)
    return default

# Core API base (dev default -> localhost)
API_BASE = (_get("api_base", os.getenv("AGENT_API_BASE")) or "http://localhost:7123/api").rstrip("/")

# Derived endpoints (can be overridden in config if you want)
POST_URL    = _get("post_url", None) or f"{API_BASE}/raw-events/"
HELLO_URL   = _get("hello_url", None) or f"{API_BASE}/agents/hello2/"
CONTROL_URL = _get("control_url", None) or f"{API_BASE}/agent/control/"
PAIR_CLAIM  = _get("pair_claim_url", None) or f"{API_BASE}/agents/pair/claim/"

# Auth/device settings
API_KEY           = _get("api_key", os.getenv("AGENT_API_KEY"))  # stored after pairing
APP_VERSION       = _get("app_version", os.getenv("AGENT_APP_VERSION")) or "1.0.0"
DEVICE_ID_FILE    = _get("device_id_file", os.path.expanduser("~/.mavops_device_id"))

# Runtime tunables
POLL_SECONDS      = int(_get("poll_seconds", _get("AGENT_POLL_SECONDS", 5, "AGENT_POLL_SECONDS")) or 5)
MIN_DWELL_SECONDS = int(_get("min_dwell_seconds", _get("AGENT_MIN_DWELL_SECONDS", 15, "AGENT_MIN_DWELL_SECONDS")) or 15)
VERBOSE           = bool(_get("verbose", os.getenv("AGENT_VERBOSE") == "1"))
PRINT_EVERY_POLL  = bool(_get("print_every", os.getenv("AGENT_PRINT_EVERY") == "1"))
DISABLE_AX        = bool(_get("disable_ax", os.getenv("AGENT_DISABLE_AX") == "1"))
EXCLUDE_BUNDLES   = set(_get("exclude_bundles", os.getenv("AGENT_EXCLUDE_BUNDLES", "").split(",")) or [])
DB_PATH           = _get("db_path", os.getenv("MAC_AGENT_DB")) or DB_PATH_DEFAULT
CONTEXT_PORT      = int(_get("context_port", os.getenv("AGENT_CONTEXT_PORT")) or 7321)
CONTROL_POLL_S    = int(_get("agent_control_poll_seconds", 10))

# Optional: preset pair_code for headless pairing (config/env)
PAIR_CODE = _get("pair_code", os.getenv("AGENT_PAIR_CODE"))

# Runtime tunables
POLL_SECONDS      = int(_get("poll_seconds", _get("AGENT_POLL_SECONDS", 5, "AGENT_POLL_SECONDS")) or 5)
MIN_DWELL_SECONDS = int(_get("min_dwell_seconds", _get("AGENT_MIN_DWELL_SECONDS", 15, "AGENT_MIN_DWELL_SECONDS")) or 15)
# NEW: mouse idle threshold (seconds) before pausing tracking
MOUSE_IDLE_PAUSE_S = int(_get("mouse_idle_pause_seconds", os.getenv("AGENT_MOUSE_IDLE_PAUSE_SECONDS") or 20))

IDLE_SIG = ("Idle", "__idle__", "Idle/Uncategorized", None, None)

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

# ------------- Mouse Idle --------------
def mouse_idle_seconds() -> float:
    """
    Returns seconds since the last mouse move at the session level.
    Uses Quartz CGEventSourceSecondsSinceLastEventType.
    """
    try:
        return float(CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateCombinedSessionState,
            kCGEventMouseMoved
        ))
    except Exception:
        # If Quartz errors for any reason, pretend there is no idle time.
        return 0.0

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
def api_headers(user: str, host: str) -> dict:
    h = {
        "Content-Type": "application/json",
        "X-Agent-Host": host,
        "X-Agent-Platform": platform.platform(),
        "X-Agent-Version": APP_VERSION,
        "Authorization": f"DeviceKey {config.get('api_key') or API_KEY}"
    }
    return h

def http_post_json(url: str, payload: dict, headers: dict, timeout=6):
    import urllib.request, urllib.error, json as _json
    req = urllib.request.Request(url, data=_json.dumps(payload).encode("utf-8"), method="POST")
    for k,v in headers.items(): req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def http_get_json(url: str, headers: dict, timeout=6) -> dict:
    import urllib.request, urllib.error, json as _json
    req = urllib.request.Request(url, method="GET")
    for k,v in headers.items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return _json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", errors="ignore")
        except: pass
        log(f"[CTRL] HTTP {e.code} from control: {body[:200]}")
        return {}
    except Exception as e:
        log(f"[CTRL] get error: {e}")
        return {}

# ---------------- Device identity ----------------
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
        return str(uuid.uuid4())

def get_os_username() -> str:
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

# ---------------- Pairing ----------------
_pair_lock = threading.Lock()

def _claim_pair(code: str, hostname: str) -> Optional[str]:
    payload = {
        "code": code.strip().upper(),
        "hostname": hostname,
        "platform": "macOS",
        "version": APP_VERSION,
        "device_id": get_device_id(),
    }
    try:
        raw = http_post_json(PAIR_CLAIM, payload, {"Content-Type": "application/json"})
        data = json.loads(raw or b"{}")
        key = data.get("api_key")
        if key:
            config["api_key"] = key
            # clear one-off pair_code if present
            if "pair_code" in config: del config["pair_code"]
            save_config(config)
            print("✅ Device paired; key saved.")
            return key
        else:
            print("❌ Pair claim response missing api_key.")
            return None
    except Exception as e:
        print(f"❌ Pair claim failed: {e}")
        return None

def ensure_api_key_interactive(hostname: str):
    """Ensure we have an API key; prompt for code if running in a TTY and key missing."""
    global API_KEY
    key = config.get("api_key") or API_KEY
    if key:
        return key
    # headless pre-provided code
    if PAIR_CODE:
        with _pair_lock:
            key = _claim_pair(PAIR_CODE, hostname)
            API_KEY = key
            return key

    # Interactive prompt (only if a real TTY)
    if sys.stdin.isatty():
        print("\n🧩 Enter pairing code from the web app to link this device:")
        code = input("> ").strip()
        if code:
            with _pair_lock:
                key = _claim_pair(code, hostname)
                API_KEY = key
                return key
    print("⚠️ No api_key configured; set AGENT_API_KEY, or add 'pair_code' to config.json, or run interactively.")
    return None

def drop_api_key():
    """Remove bad key so we can re-pair on next cycle."""
    if "api_key" in config:
        del config["api_key"]
        save_config(config)
    # keep global in sync
    global API_KEY
    API_KEY = None

# ---------------- Handshake & control ----------------
SERVER_USER_ID = None

def hello(server_url: str, user: str, host: str, device_id: str):
    """Hello using DeviceKey (no need to pass username if device is linked)."""
    global SERVER_USER_ID
    headers = api_headers(user, host)
    payload = {
        "hostname": host,
        "app_version": APP_VERSION,
        "device_id": device_id,
        # user is inferred from DeviceKey server-side; we also include a hint:
        "os_username": user,
    }
    try:
        raw = http_post_json(server_url, payload, headers)
        data = json.loads(raw or b"{}")
        SERVER_USER_ID = data.get("user_id")
        log(f"[HELLO] Registered with server: user_id={SERVER_USER_ID}")
        return True
    except Exception as e:
        log(f"[HELLO] failed: {e}")
        return False

_last_control_check = 0.0
def should_stop(control_url: str, user: str, host: str) -> bool:
    global _last_control_check
    now = time.time()
    if now - _last_control_check < CONTROL_POLL_S:
        return False
    _last_control_check = now
    qs = f"?host={host}"  # user inferred by DeviceKey; host still distinguishes per-machine control
    headers = api_headers(user, host)
    data = http_get_json(control_url + qs, headers)
    stop = bool(data.get("stop"))
    if stop:
        log(f"[CTRL] Stop received from server: reason={data.get('reason','')}")
    return stop

# ---------------- Posting ----------------
def post_event_async(event: dict, user: str, host: str):
    if not POST_URL:
        return
    def _run():
        import urllib.request, urllib.error, json as _json
        headers = api_headers(user, host)
        try:
            req = urllib.request.Request(POST_URL, data=_json.dumps(event).encode("utf-8"), method="POST")
            for k, v in headers.items(): req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=6) as resp:
                _ = resp.read()
            log(f"[POSTED] {POST_URL}")
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode("utf-8", errors="ignore")
            except: pass
            log(f"[POST ERROR] HTTP {e.code}: {body[:200]}")
            # If unauthorized, drop key to trigger re-pair on next loop
            if e.code in (401, 403):
                log("[AUTH] Device key rejected — will re-pair.")
                drop_api_key()
        except Exception as e:
            log(f"[POST ERROR] {e}")
    threading.Thread(target=_run, daemon=True).start()

# change signature
def write_event(conn, cur, user: str, hostname: str, sig, ts_override: float | None = None):
    app_name, bundle_id, title, url, fpath = sig

    # use override if provided, otherwise now()
    if ts_override is not None:
        ts_dt = datetime.fromtimestamp(ts_override, tz=timezone.utc)
    else:
        ts_dt = datetime.now(timezone.utc)
    ts_iso = ts_dt.isoformat()

    cur.execute(
        "INSERT INTO raw_events (ts_utc, app_name, bundle_id, window_title, url, file_path, user, hostname) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts_iso, app_name, bundle_id, title or "", url, fpath, user, hostname),
    )
    conn.commit()

    payload = {
        "ts_utc": ts_iso,
        "app_name": app_name,
        "bundle_id": bundle_id,
        "window_title": title or "",
        "url": url,
        "file_path": fpath,
        "hostname": hostname,
        "server_user_id": SERVER_USER_ID,
        "device_id": get_device_id(),
        "ctx": snapshot_ctx(),
    }
    post_event_async(payload, user, hostname)
    log(f"[EVENT] dwell-finalized • {app_name} • {title or '(no title)'} • url={url or '-'} • path={fpath or '-'} at {ts_iso}")
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
    log(f"API_BASE={API_BASE}")
    log(f"POST_URL={POST_URL}")
    log(f"HELLO_URL={HELLO_URL}")
    log(f"CONTROL_URL={CONTROL_URL} (poll {CONTROL_POLL_S}s)")
    log(f"AX_AVAILABLE={AX_AVAILABLE}")
    log(f"POLL_SECONDS={POLL_SECONDS}, MIN_DWELL_SECONDS={MIN_DWELL_SECONDS}")
    if EXCLUDE_BUNDLES: log(f"EXCLUDE_BUNDLES={sorted([b for b in EXCLUDE_BUNDLES if b])}")

    conn = ensure_db()
    cur = conn.cursor()
    os_user = get_os_username()
    hostname = platform.node()
    device_id = get_device_id()

    # PID file
    write_pid()

    # Ensure we have a device key (pair if needed)
    key = config.get("api_key") or API_KEY
    if not key:
        key = ensure_api_key_interactive(hostname)
        if not key:
            print("Exiting: no device key configured.")
            remove_pid()
            return

    # Hello (with key)
    if not hello(HELLO_URL, os_user, hostname, device_id):
        # If hello failed due to auth, drop key and try pairing once
        log("[HELLO] Attempting re-pair after hello failure.")
        drop_api_key()
        key = ensure_api_key_interactive(hostname)
        if not key or not hello(HELLO_URL, os_user, hostname, device_id):
            print("Exiting: hello failed.")
            remove_pid()
            return

    current_sig = None
    dwell_start = None
    paused = False  # NEW

    try:
        while True:
            # admin kill-switch
            if should_stop(CONTROL_URL, os_user, hostname):
                log("[CTRL] Stopping agent per admin request.")
                break

            # --- NEW: mouse idle pause ---
            # --- NEW: idle → record as its own dwell ("Uncategorized - Idle") ---
            idle = mouse_idle_seconds()

            if idle >= MOUSE_IDLE_PAUSE_S:
                # If we're not already in an idle dwell, transition INTO idle now.
                if current_sig != IDLE_SIG:
                    # Finalize the active dwell up to the moment idle crossed the threshold,
                    # so we don't over-count active time during idle.
                    if current_sig and dwell_start:
                        now = time.time()
                        effective_end = now - max(0.0, idle - MOUSE_IDLE_PAUSE_S)
                        dwell = effective_end - dwell_start
                        if dwell >= MIN_DWELL_SECONDS:
                            write_event(conn, cur, os_user, hostname, current_sig)
                        else:
                            log(f"[SKIP] dwell too short ({int(dwell)}s) before idle for {current_sig[0]}")

                    # Start an idle dwell beginning at the threshold boundary
                    # (we approximate by starting now; most workflows don't need backdating)
                    current_sig = IDLE_SIG
                    dwell_start = time.time() - min(idle, MOUSE_IDLE_PAUSE_S)  # small nudge so idle has length
                    log(f"[IDLE] Entered idle (mouse idle {int(idle)}s ≥ {MOUSE_IDLE_PAUSE_S}s)")
                
                # Remain in idle; do not attempt normal frontmost tracking until mouse moves again
                time.sleep(POLL_SECONDS)
                
            else:
                # Mouse moved. If we WERE in idle, finalize the idle dwell.
                if current_sig == IDLE_SIG and dwell_start:
                    dwell = time.time() - dwell_start
                    if dwell >= MIN_DWELL_SECONDS:
                        write_event(conn, cur, os_user, hostname, current_sig)
                        log(f"[IDLE] Exited idle; recorded {int(dwell)}s idle dwell.")
                    else:
                        log(f"[IDLE] Exited idle; too short ({int(dwell)}s) → not recorded.")
                    # Clear and let normal tracking pick up the real frontmost app.
                    current_sig = None
                    dwell_start = None
            # --- end idle-as-dwell logic ---
            # --- end new pause logic ---

            # (your existing logic continues below unchanged)
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
                        write_event(conn, cur, os_user, hostname, current_sig)
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
                        write_event(conn, cur, os_user, hostname, current_sig)
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
                write_event(conn, cur, os_user, hostname, current_sig)
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
            return run_agent()
        if sub in ("start-bg", "daemon"):
            if read_pid():
                print("Already running. Use `main.py status`.")
                return
            pid = os.fork()
            if pid > 0:
                print("Started agent in background.")
                return
            os.setsid()
            run_agent()
            return
        print("Usage: main.py [start|start-bg|stop|status]")
        return
    run_agent()

if __name__ == "__main__":
    main()