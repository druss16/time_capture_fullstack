#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows Activity Agent - Ported from Mac Agent

Features:
- Window tracking via win32gui
- Mouse idle detection via GetLastInputInfo
- Browser URL extraction (title parsing + optional Chrome DevTools)
- Office file paths via COM automation
- Device pairing with backend
- AI client suggestions
- Context bus server
- System tray GUI integration
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
import ctypes
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, List
from urllib.parse import urlparse

# Windows-specific imports
try:
    import win32gui
    import win32process
    import win32api
    import win32con
    import psutil
    WIN_API_AVAILABLE = True
except ImportError:
    WIN_API_AVAILABLE = False
    print("Warning: pywin32 not available. Install with: pip install pywin32")

# GUI imports (optional)
try:
    from timetracker_gui import run_gui_app, GUI_AVAILABLE
except ImportError:
    GUI_AVAILABLE = False


# ---------------- Client Sync ----------------
def get_current_client_from_backend(api_base, api_key):
    """Fetch current client from Django API via HTTP"""
    import urllib.request
    import urllib.error
    try:
        url = f"{api_base.rstrip('/')}/devices/current-client/"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[CLIENT] Failed to get current client: {e}")
        return None

# ---------------- Config ----------------
CONFIG_FILE = os.path.expanduser("~/.timetracker/config.json")
APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
PID_FILE = os.path.join(APPDATA, "TimeTracker", "agent.pid")
DB_PATH_DEFAULT = os.path.join(APPDATA, "TimeTracker", "agent.sqlite3")

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
print(f"[DEBUG] Config loaded: {config}")
print(f"[DEBUG] server_device_id = {config.get('server_device_id')}")

# Tunables
def _get(name, default=None, env=None):
    if name in config: return config[name]
    if env and os.getenv(env) is not None: return os.getenv(env)
    return default

API_BASE = (_get("api_base", os.getenv("AGENT_API_BASE")) or "https://timetracker-api-k375.onrender.com/api").rstrip("/")
POST_URL = _get("post_url", None) or f"{API_BASE}/raw-events/"
HELLO_URL = _get("hello_url", None) or f"{API_BASE}/agents/hello2/"
CONTROL_URL = _get("control_url", None) or f"{API_BASE}/agent/control/"
PAIR_CLAIM = _get("pair_claim_url", None) or f"{API_BASE}/agents/pair/claim/"

API_KEY = _get("api_key", os.getenv("AGENT_API_KEY"))
APP_VERSION = _get("app_version", os.getenv("AGENT_APP_VERSION")) or "1.0.0"
DEVICE_ID_FILE = _get("device_id_file", os.path.join(APPDATA, "TimeTracker", ".device_id"))

POLL_SECONDS = int(_get("poll_seconds", 5))
MIN_DWELL_SECONDS = int(_get("min_dwell_seconds", 15))
MOUSE_IDLE_PAUSE_S = int(_get("mouse_idle_pause_seconds", 90))
VERBOSE = bool(_get("verbose", os.getenv("AGENT_VERBOSE") == "1"))
DB_PATH = _get("db_path", os.getenv("WIN_AGENT_DB")) or DB_PATH_DEFAULT
CONTEXT_PORT = int(_get("context_port", 7321))
CONTROL_POLL_S = int(_get("agent_control_poll_seconds", 10))

IDLE_SIG = ("Idle", "__idle__", "Idle/Uncategorized", None, None)

# Nudge/Guess settings
NUDGE_ENABLED = bool(_get("nudge_enabled", True))
GUESS_POLL_SECONDS = int(_get("guess_poll_seconds", 10))
GUESS_MIN_CONF = float(_get("guess_min_conf", 0.45))
GUESS_MAX_CONF = float(_get("guess_max_conf", 0.80))
NUDGE_SNOOZE_MIN = int(_get("nudge_snooze_min", 20))
NUDGE_TIMEOUT_SEC = int(_get("nudge_timeout_sec", 15))

CONTEXT_GUESS_URL = _get("context_guess_url", None) or f"{API_BASE}/context/guess"
CONTEXT_CONFIRM_URL = _get("context_confirm_url", None) or f"{API_BASE}/context/confirm"
CONTEXT_REJECT_URL = _get("context_reject_url", None) or f"{API_BASE}/context/reject"

# Tool detection
TOOL_EXES = set(_get("tool_exes", "").split(",")) or {
    "code.exe", "devenv.exe", "pycharm64.exe", "idea64.exe",
    "chrome.exe", "msedge.exe", "firefox.exe",
    "outlook.exe", "slack.exe", "teams.exe",
}

TOOL_HOSTS = set(_get("tool_hosts", "").split(",")) or {
    "chatgpt.com", "openai.com", "localhost", "127.0.0.1",
    "github.com", "gitlab.com", "stackoverflow.com",
}

# ---------------- Logging ----------------
def log(msg: str):
    if VERBOSE:
        print(msg, flush=True)

# ---------------- Context Bus ----------------
from http.server import BaseHTTPRequestHandler, HTTPServer

_CONTEXT: Dict[str, dict] = {}

class _CtxHandler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    
    def do_POST(self):
        if self.path != "/context":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw or b"{}")
            src = (data.get("source") or "unknown").lower()
            _CONTEXT[src] = data
            self.send_response(200)
            self.end_headers()
        except Exception:
            self.send_response(400)
            self.end_headers()

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

# ---------------- Database ----------------
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

# ---------------- Windows API Helpers ----------------

def mouse_idle_seconds() -> float:
    """Get seconds since last mouse/keyboard input using GetLastInputInfo"""
    if not WIN_API_AVAILABLE:
        return 0.0
    
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ('cbSize', ctypes.c_uint),
                ('dwTime', ctypes.c_uint),
            ]
        
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return millis / 1000.0
    except Exception:
        return 0.0

def get_foreground_window_info() -> Optional[Tuple[str, str, int, Optional[str]]]:
    """
    Get info about foreground window.
    Returns: (app_name, exe_name, pid, window_title) or None
    """
    if not WIN_API_AVAILABLE:
        return None
    
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        
        # Get window title
        title = win32gui.GetWindowText(hwnd)
        
        # Get process info
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        
        try:
            process = psutil.Process(pid)
            exe_name = process.name()
            app_name = exe_name.replace(".exe", "").title()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            exe_name = "Unknown"
            app_name = "Unknown"
        
        return (app_name, exe_name, pid, title)
    
    except Exception as e:
        if VERBOSE:
            log(f"[WARN] get_foreground_window_info error: {e}")
        return None

def try_get_url_or_path(exe_name: str, window_title: str) -> Dict[str, Optional[str]]:
    """
    Try to extract URL or file path from window context.
    
    For browsers: Parse from title (format: "Page Title - Browser Name")
    For Office: Try COM automation
    """
    exe_lower = exe_name.lower()
    
    # Browser URL extraction from title
    if exe_lower in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"):
        url = extract_url_from_browser_title(window_title, exe_lower)
        return {"url": url, "file_path": None}
    
    # Office files via COM
    if exe_lower in ("excel.exe", "winword.exe", "powerpnt.exe"):
        file_path = get_office_file_path(exe_lower)
        return {"url": None, "file_path": file_path}
    
    return {"url": None, "file_path": None}

def extract_url_from_browser_title(title: str, exe: str) -> Optional[str]:
    """
    Parse URL from browser window title.
    Common formats:
    - "Page Title - Google Chrome"
    - "Page Title — Mozilla Firefox"
    - "localhost:3000/dashboard - Chrome"
    """
    if not title:
        return None
    
    # Remove browser name suffixes
    for suffix in [" - Google Chrome", " — Mozilla Firefox", " - Microsoft Edge", " - Brave"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
    
    # Check if title contains URL-like patterns
    if "://" in title or title.startswith("localhost") or "/" in title:
        # Try to extract clean URL
        parts = title.split()
        for part in parts:
            if "://" in part or part.startswith("localhost"):
                return part.strip()
    
    return None

def get_office_file_path(exe: str) -> Optional[str]:
    """
    Get currently open file path from Office application via COM.
    Requires: pip install pywin32
    """
    try:
        import win32com.client
        
        if exe == "excel.exe":
            xl = win32com.client.Dispatch("Excel.Application")
            if xl.Workbooks.Count > 0:
                return xl.ActiveWorkbook.FullName
        
        elif exe == "winword.exe":
            word = win32com.client.Dispatch("Word.Application")
            if word.Documents.Count > 0:
                return word.ActiveDocument.FullName
        
        elif exe == "powerpnt.exe":
            ppt = win32com.client.Dispatch("PowerPoint.Application")
            if ppt.Presentations.Count > 0:
                return ppt.ActivePresentation.FullName
    
    except Exception:
        pass
    
    return None

def looks_toolish(exe_name: Optional[str], url: Optional[str]) -> Tuple[bool, str, str]:
    """Check if activity is a development tool."""
    exe = (exe_name or "").lower()
    host = ""
    
    if url:
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
    
    if exe in TOOL_EXES:
        return True, "exe", host
    
    if host and (host in TOOL_HOSTS or host.startswith("localhost") or host.startswith("127.")):
        return True, "host", host
    
    return False, "", host

# ---------------- Device Identity ----------------
def get_device_id():
    # Prefer server's integer device_id if we have it
    print(f"[DEBUG get_device_id] config.get('server_device_id') = {config.get('server_device_id')}")
    if config.get("server_device_id"):
        print(f"[DEBUG get_device_id] Returning server_device_id: {config['server_device_id']}")
        return config["server_device_id"]
    print("[DEBUG get_device_id] Falling back to UUID file")
    
    # Fall back to UUID for initial pairing
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
    return getpass.getuser() or os.environ.get("USERNAME", "unknown")

# ---------------- Pairing ----------------
import urllib.request
import urllib.error

_pair_lock = threading.Lock()

def _claim_pair(code: str, hostname: str) -> Optional[str]:
    payload = {
        "code": code.strip().upper(),
        "hostname": hostname,
        "platform": "Windows",
        "version": APP_VERSION,
        "device_id": get_device_id(),
    }
    try:
        raw = http_post_json(PAIR_CLAIM, payload, {"Content-Type": "application/json"})
        data = json.loads(raw or b"{}")
        key = data.get("api_key")
        server_device_id = data.get("device_id")  # Get server's integer device_id
        if key:
            config["api_key"] = key
            if server_device_id:
                config["server_device_id"] = server_device_id  # Save it!
            if "pair_code" in config:
                del config["pair_code"]
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
    global API_KEY
    key = config.get("api_key") or API_KEY
    if key:
        return key
    
    # Headless pre-provided code
    pair_code = _get("pair_code", os.getenv("AGENT_PAIR_CODE"))
    if pair_code:
        with _pair_lock:
            key = _claim_pair(pair_code, hostname)
            API_KEY = key
            return key
    
    # Interactive prompt
    if sys.stdin and sys.stdin.isatty():
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
    if "api_key" in config:
        del config["api_key"]
        save_config(config)
    global API_KEY
    API_KEY = None

# ---------------- Networking ----------------
def api_headers(user: str, host: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Agent-Host": host,
        "X-Agent-Platform": platform.platform(),
        "X-Agent-Version": APP_VERSION,
        "Authorization": f"DeviceKey {config.get('api_key') or API_KEY}"
    }

def http_post_json(url: str, payload: dict, headers: dict, timeout=6):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def http_get_json(url: str, headers: dict, timeout=6) -> dict:
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except:
            pass
        log(f"[CTRL] HTTP {e.code} from control: {body[:200]}")
        return {}
    except Exception as e:
        log(f"[CTRL] get error: {e}")
        return {}

# ---------------- Handshake & Control ----------------
SERVER_USER_ID = None

def hello(server_url: str, user: str, host: str, device_id: str):
    global SERVER_USER_ID
    headers = api_headers(user, host)
    payload = {
        "hostname": host,
        "app_version": APP_VERSION,
        "device_id": device_id,
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
    qs = f"?host={host}"
    headers = api_headers(user, host)
    data = http_get_json(control_url + qs, headers)
    stop = bool(data.get("stop"))
    if stop:
        log(f"[CTRL] Stop received from server: reason={data.get('reason','')}")
    return stop

# ---------------- Event Posting ----------------
def post_event_async(event: dict, user: str, host: str):
    if not POST_URL:
        return
    
    def _run():
        headers = api_headers(user, host)
        try:
            req = urllib.request.Request(POST_URL, data=json.dumps(event).encode("utf-8"), method="POST")
            for k, v in headers.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=6) as resp:
                _ = resp.read()
            log(f"[POSTED] {POST_URL}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except:
                pass
            log(f"[POST ERROR] HTTP {e.code}: {body[:200]}")
            if e.code in (401, 403):
                log("[AUTH] Device key rejected — will re-pair.")
                drop_api_key()
        except Exception as e:
            log(f"[POST ERROR] {e}")
    
    threading.Thread(target=_run, daemon=True).start()

def write_event(conn, cur, user: str, hostname: str, sig, ts_override: float = None):
    app_name, bundle_id, title, url, fpath = sig
    
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
    
    # Get current client from backend
    # Replaced with local function
    api_key = config.get("api_key") or API_KEY
    current_client_id = None
    current_client_name = None
    
    if api_key and API_BASE:
        try:
            current = get_current_client_from_backend(API_BASE, api_key)
            if current and current.get("client_id"):
                current_client_id = current["client_id"]
                current_client_name = current.get("client_name")
        except Exception as e:
            log(f"[CLIENT] Failed to get current client: {e}")
    
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
        "current_client_id": current_client_id,
        "current_client_name": current_client_name,
    }
    
    toolish, tool_reason, tool_host = looks_toolish(bundle_id, url)
    payload["toolish"] = bool(toolish)
    if toolish:
        payload["tool_reason"] = tool_reason
        if tool_host:
            payload["tool_host"] = tool_host
    
    post_event_async(payload, user, hostname)
    
    client_msg = f" → {current_client_name}" if current_client_name else ""
    log(
        f"[EVENT] dwell-finalized • {app_name} • {title or '(no title)'} "
        f"• url={url or '-'} • path={fpath or '-'}"
        + (f" • toolish({tool_reason})" if toolish else "")
        + client_msg
        + f" at {ts_iso}"
    )

# ---------------- Client Sync Helpers ----------------
def get_current_client_from_backend(api_base: str, api_key: str) -> dict:
    if not api_base or not api_key:
        return {"client_id": None, "client_name": None}
    
    url = f"{api_base}/client/current/"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
            return data
    except urllib.error.HTTPError as e:
        log(f"[CLIENT] HTTP error fetching current client: {e.code}")
        return {"client_id": None, "client_name": None}
    except Exception as e:
        log(f"[CLIENT] Failed to fetch current client: {e}")
        return {"client_id": None, "client_name": None}

def set_current_client_backend(api_base: str, api_key: str, client_id: int) -> bool:
    if not api_base or not api_key:
        return False
    
    url = f"{api_base}/client/set-current/"
    data = {"client_id": client_id}
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        method="POST"
    )
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log(f"[CLIENT] Set current client to ID {client_id}")
                return True
            else:
                log(f"[CLIENT] Failed to set client: {result.get('error', 'unknown')}")
                return False
    except Exception as e:
        log(f"[CLIENT] Error setting current client: {e}")
        return False

def fetch_clients_from_backend(api_base: str, api_key: str) -> list:
    if not api_base or not api_key:
        return []
    
    url = f"{api_base}/clients/list/"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
            if isinstance(data, list):
                log(f"[CLIENT] Loaded {len(data)} clients from backend")
                return data
            return []
    except Exception as e:
        log(f"[CLIENT] Failed to fetch clients: {e}")
        return []

def fetch_today_time():
    """Fetch today's time for GUI display"""
    api_key = config.get("api_key") or API_KEY
    if not api_key or not API_BASE:
        return []
    
    url = f"{API_BASE}/today-time/"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
            if isinstance(data, list):
                return data
            return []
    except Exception as e:
        print(f"[GUI] Failed to fetch today's time: {e}")
        return []

# ---------------- PID Management ----------------
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
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None

# ---------------- Main Tracking Loop ----------------
def run_agent():
    """Main agent function with GUI integration"""
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    
    start_context_bus(CONTEXT_PORT)

    # After the hello() call, add sync initialization:

    # === SYNC INITIALIZATION ===
    sync = None
    api_key = config.get("api_key") or API_KEY
    if api_key:
        try:
            from agent_sync_integration import AgentSync
            
            sync = AgentSync(
                api_base=API_BASE,
                device_token=api_key
            )
            
            def on_sync_update():
                print(f"[SYNC] Data updated: {len(sync.clients)} clients")
                if sync.gui_menu_bar and hasattr(sync.gui_menu_bar, 'refresh_client_menu'):
                    sync.gui_menu_bar.refresh_client_menu(sync.clients)
                    print("[SYNC] GUI menu refreshed")
                else:
                    print("[SYNC] GUI not ready yet")
            
            sync.on_update = on_sync_update
            sync.start()
            print(f"[SYNC] Started - polling every {sync.poll_interval}s")
        except ImportError:
            print("[SYNC] agent_sync_integration not available")
    
    # GUI initialization
    gui_menu_bar = None
    if GUI_AVAILABLE:
        try:
            api_key = config.get("api_key") or API_KEY
            api_base = API_BASE
            
            gui_menu_bar = run_gui_app(
                on_client_confirmed=lambda cid, cname, data: log(f"[GUI] Client confirmed: {cname}"),
                on_client_rejected=lambda data: log(f"[GUI] Client rejected"),
                get_today_time=fetch_today_time,
                fetch_clients=lambda: fetch_clients_from_backend(api_base, api_key),
                set_current_client=lambda cid: set_current_client_backend(api_base, api_key, cid),
                get_current_client=lambda: get_current_client_from_backend(api_base, api_key),
                sync=sync,
            )
            log("[GUI] System tray initialized")
        except Exception as e:
            log(f"[GUI] Failed to initialize: {e}")
            import traceback
            traceback.print_exc()
    
    log("=== Windows Activity Agent starting… (Ctrl+C to stop) ===")
    log(f"CONFIG={CONFIG_FILE}")
    log(f"DB_PATH={DB_PATH}")
    log(f"API_BASE={API_BASE}")
    log(f"POLL_SECONDS={POLL_SECONDS}, MIN_DWELL_SECONDS={MIN_DWELL_SECONDS}")
    log(f"MOUSE_IDLE_PAUSE_S={MOUSE_IDLE_PAUSE_S}")
    
    os_user = get_os_username()
    hostname = platform.node()
    device_id = get_device_id()
    
    write_pid()
    
    # Ensure API key
    key = config.get("api_key") or API_KEY
    if not key:
        key = ensure_api_key_interactive(hostname)
        if not key:
            print("Exiting: no device key configured.")
            remove_pid()
            return
    
    # Hello
    if not hello(HELLO_URL, os_user, hostname, device_id):
        log("[HELLO] Attempting re-pair after hello failure.")
        drop_api_key()
        key = ensure_api_key_interactive(hostname)
        if not key or not hello(HELLO_URL, os_user, hostname, device_id):
            print("Exiting: hello failed.")
            remove_pid()
            return
    
    # Restore client state from backend
    if gui_menu_bar:
        api_key = config.get("api_key") or API_KEY
        if api_key and API_BASE:
            try:
                current = get_current_client_from_backend(API_BASE, api_key)
                if current and current.get("client_id"):
                    log(f"[CLIENT] Restored from backend: {current['client_name']}")
            except Exception as e:
                log(f"[CLIENT] Failed to restore client state: {e}")
    
    # Tracking loop
    def tracking_loop():
        conn = ensure_db()
        cur = conn.cursor()
        current_sig = None
        dwell_start = None
        
        try:
            while True:
                if should_stop(CONTROL_URL, os_user, hostname):
                    log("[CTRL] Stopping agent per admin request.")
                    break
                
                idle = mouse_idle_seconds()
                if idle >= MOUSE_IDLE_PAUSE_S:
                    if current_sig != IDLE_SIG:
                        if current_sig and dwell_start:
                            now = time.time()
                            effective_end = now - max(0.0, idle - MOUSE_IDLE_PAUSE_S)
                            dwell = effective_end - dwell_start
                            if dwell >= MIN_DWELL_SECONDS:
                                write_event(conn, cur, os_user, hostname, current_sig)
                        current_sig = IDLE_SIG
                        dwell_start = time.time() - min(idle, MOUSE_IDLE_PAUSE_S)
                        log(f"[IDLE] Entered idle (mouse idle {int(idle)}s ≥ {MOUSE_IDLE_PAUSE_S}s)")
                    time.sleep(POLL_SECONDS)
                else:
                    if current_sig == IDLE_SIG and dwell_start:
                        dwell = time.time() - dwell_start
                        if dwell >= MIN_DWELL_SECONDS:
                            write_event(conn, cur, os_user, hostname, current_sig)
                        current_sig = None
                        dwell_start = None
                    
                    front = get_foreground_window_info()
                    if not front:
                        time.sleep(POLL_SECONDS)
                        continue
                    
                    app_name, exe_name, pid, window_title = front
                    
                    extras = try_get_url_or_path(exe_name, window_title)
                    url, fpath = extras.get("url"), extras.get("file_path")
                    
                    sig = (app_name, exe_name, window_title, url, fpath)
                    
                    if sig != current_sig:
                        if current_sig and dwell_start:
                            dwell = time.time() - dwell_start
                            if dwell >= MIN_DWELL_SECONDS:
                                write_event(conn, cur, os_user, hostname, current_sig)
                        current_sig = sig
                        dwell_start = time.time()
                        log(f"[FOCUS] {app_name} • {window_title or '(no title)'}")
                    
                    time.sleep(POLL_SECONDS)
        
        except KeyboardInterrupt:
            log("=== Stopping (Ctrl+C) ===")
            if current_sig and dwell_start:
                dwell = time.time() - dwell_start
                if dwell >= MIN_DWELL_SECONDS:
                    write_event(conn, cur, os_user, hostname, current_sig)
        finally:
            conn.close()
            remove_pid()
    
    # Run tracking in thread
    tracking_thread = threading.Thread(target=tracking_loop, daemon=False)
    tracking_thread.start()
    log("[TRACKING] Started tracking thread")
    
    # Run GUI if available
    if gui_menu_bar and GUI_AVAILABLE:
        log("[GUI] Starting GUI event loop...")
        try:
            gui_menu_bar.run()  # Blocks here
        except KeyboardInterrupt:
            log("[GUI] Interrupted")
    else:
        log("[TRACKING] No GUI, waiting for tracking thread...")
        try:
            tracking_thread.join()
        except KeyboardInterrupt:
            log("[TRACKING] Interrupted")
    
    log("[AGENT] Shutdown complete")

# ---------------- CLI ----------------
def cmd_status():
    pid = read_pid()
    if not pid:
        print("Agent status: not running")
        return
    try:
        os.kill(pid, 0)
        print(f"Agent status: running (PID {pid})")
    except (ProcessLookupError, OSError):
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
    except (ProcessLookupError, OSError):
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
        print("Usage: main.py [start|stop|status]")
        return
    run_agent()

if __name__ == "__main__":
    main()
