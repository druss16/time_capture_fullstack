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
- Error logging and remote error reporting
- Watchdog thread for crash recovery
- Sleep/wake recovery with automatic reconnection
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
import traceback
import logging
import socket
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, List
from urllib.parse import urlparse

from widget_state_tracker import get_widget_state_tracker

from tracking_health import (
    progress_tick,
    record_window_change,
    record_idle_enter,
    record_idle_exit,
    record_wake_event,
    classify_idle,
    watchdog_check,
    get_loop_stats,
    IdleKind,
)

# Windows-specific imports
try:
    import win32gui
    import win32process
    import win32api
    import win32con
    WIN_API_AVAILABLE = True
except ImportError:
    WIN_API_AVAILABLE = False
    print("Warning: pywin32 not available. Install with: pip install pywin32")

try:
    import psutil
except ImportError:
    psutil = None
    print("Warning: psutil not available. Install with: pip install psutil")

# GUI imports (optional)
try:
    from timetracker_gui import run_gui_app, GUI_AVAILABLE
except ImportError:
    GUI_AVAILABLE = False
    show_client_picker = None

# Push notifications for client reminders
try:
    from notifications import (
        ClientNotificationManager,
        NotificationConfig,
        NotificationWorker,
        create_notification_system,
        NOTIF_AVAILABLE,
    )
    PUSH_NOTIF_AVAILABLE = NOTIF_AVAILABLE
except ImportError:
    PUSH_NOTIF_AVAILABLE = False
    print("[WARN] notifications.py not found - push notifications disabled")

# Meeting detection (Zoom, Teams, Meet, etc.)
try:
    from meeting_detector import MeetingDetector, MeetingState
    MEETING_DETECTOR_AVAILABLE = True
except ImportError:
    MEETING_DETECTOR_AVAILABLE = False
    MeetingDetector = None
    MeetingState = None
    print("[WARN] meeting_detector.py not found - meeting capture disabled")

# Fix Windows console encoding for Unicode characters
import io
if sys.platform == 'win32':
    try:
        if sys.stdout:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if sys.stderr:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

register_hotkey = None
ai_switcher = None  # Will be initialized after GUI setup
widget_tracker = get_widget_state_tracker()  # Drives the floating widget's color/state
# Single instance lock — named mutex held for entire process lifetime
_lock_mutex = None

# ---------------- Check Active Subscriptions ----------------
# Near top with other globals
_subscription_active = True
_subscription_check_interval = 1800  # Re-check every 30 min
_last_subscription_check = 0.0
_idle_reading_unchanged_since: float = 0.0


def check_subscription_response(http_error):
    """Check if a 403 is subscription_inactive. Returns True if subscription is dead."""
    global _subscription_active
    if http_error.code != 403:
        return False
    try:
        body = http_error.read().decode("utf-8", errors="ignore")
        if "subscription_inactive" in body:
            _subscription_active = False
            log("[SUB] ⚠️ Subscription inactive — agent paused")
            show_subscription_inactive_notification()
            return True
    except:
        pass
    return False

def show_subscription_inactive_notification():
    """Show Windows toast notification about inactive subscription."""
    try:
        from tkinter import Tk, messagebox
        root = Tk()
        root.withdraw()
        messagebox.showwarning(
            "TimeTracker - Subscription Inactive",
            "Your organization's TimeTracker subscription is inactive.\n\n"
            "Time tracking has been paused.\n\n"
            "Please contact your administrator to reactivate at:\n"
            "https://timetracker.mavops.ai/account/billing"
        )
        root.destroy()
    except Exception as e:
        log(f"[SUB] Could not show dialog: {e}")


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

def merge_deploy_config(cfg: dict) -> dict:
    """Read deploy.json from ProgramData (dropped by IT via GPO) and merge into config."""
    deploy_path = os.path.join(
        os.environ.get('PROGRAMDATA', 'C:\\ProgramData'),
        'TimeTracker',
        'deploy.json'
    )
    if os.path.exists(deploy_path):
        try:
            with open(deploy_path, 'r') as f:
                deploy = json.load(f)
            if deploy.get('org_token') and not cfg.get('api_key'):
                cfg['org_token'] = deploy['org_token']
                print(f"[DEPLOY] Found org token from {deploy_path}")
            if deploy.get('server_url') and not cfg.get('api_base'):
                cfg['api_base'] = deploy['server_url']
                print(f"[DEPLOY] Found server URL from {deploy_path}")
            save_config(cfg)
        except Exception as e:
            print(f"[DEPLOY] Failed to read {deploy_path}: {e}")
    return cfg

def save_config(cfg: dict):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save {CONFIG_FILE}: {e}")

config = load_config()
config = merge_deploy_config(config)  # ← Add this line

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
try:
    from version import APP_VERSION as _FILE_VERSION
except ImportError:
    _FILE_VERSION = "dev"
APP_VERSION = _get("app_version", os.getenv("AGENT_APP_VERSION")) or _FILE_VERSION
DEVICE_ID_FILE = _get("device_id_file", os.path.join(APPDATA, "TimeTracker", ".device_id"))

POLL_SECONDS = int(_get("poll_seconds", 5))
MIN_DWELL_SECONDS = int(_get("min_dwell_seconds", 15))
MOUSE_IDLE_PAUSE_S = int(_get("mouse_idle_pause_seconds", 600))  # mutable — updated by sync
_IDLE_WATCHDOG_MAX_MINUTES = 30    # Force-reset idle if stuck longer than this
_IDLE_HARD_CAP_HOURS = 2           # Absolute max idle duration regardless of input
_idle_entered_at: float = 0.0      # Wall time when we entered idle
VERBOSE = bool(_get("verbose", os.getenv("AGENT_VERBOSE") == "1"))
DB_PATH = _get("db_path", os.getenv("WIN_AGENT_DB")) or DB_PATH_DEFAULT
CONTEXT_PORT = int(_get("context_port", 7321))
CONTROL_POLL_S = int(_get("agent_control_poll_seconds", 10))

IDLE_SIG = ("Idle", "__idle__", "Idle/Uncategorized", None, None)

# Synthetic signature for Meeting events — forms its own block in compactor
def _meeting_sig(meeting_app: str, title: str = None):
    """Build a window signature for a Meeting event.

    Format matches the (app_name, bundle_id, window_title, url, file_path) tuple
    that write_event expects. bundle_id uses 'meeting:' prefix so the backend
    compactor recognizes it as a meeting block.
    """
    return (
        "Meeting",
        f"meeting:{meeting_app}",
        title or f"{meeting_app.title()} meeting",
        None,
        None,
    )

# Idle safety limits
MAX_IDLE_SECONDS = 3600          # 1 hour max idle before force-reset
IDLE_STUCK_CHECK_SECONDS = 300   # 5 min — re-evaluate if stuck in idle

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

# Notification settings
NOTIF_ENABLED = bool(_get("notifications_enabled", os.getenv("AGENT_NOTIF_ENABLED") != "0") if _get("notifications_enabled") is not None else True)
NOTIF_DURATION_MINUTES = int(_get("notif_duration_minutes", os.getenv("AGENT_NOTIF_DURATION_MINUTES")) or 60)
NOTIF_IDLE_THRESHOLD = int(_get("notif_idle_threshold", os.getenv("AGENT_NOTIF_IDLE_THRESHOLD")) or 300)
NOTIF_NO_CLIENT_MINUTES = int(_get("notif_no_client_minutes", os.getenv("AGENT_NOTIF_NO_CLIENT_MINUTES")) or 15)

# At top of file with other globals
sync = None
notif_manager = None
notif_worker = None
gui_menu_bar = None  # Global reference

# Network health state — used to skip blocking network calls when offline
_network_ok = True
_network_ok_lock = threading.Lock()
_last_successful_post = 0.0
_wake_timestamp = 0.0  # When we last woke from sleep
_wake_event = threading.Event()   # Signal tracking loop to reset after sleep/wake
_wake_handled = False     
_health_monitor_running = False
NETWORK_GRACE_PERIOD = 30  # Seconds after wake to skip network calls

# ---------------- Local Client Cache ----------------
# Eliminates the HTTP round-trip in write_event() every 5 seconds.
# Updated by _apply_client_switch(). Safety-net refresh every 60s.

_cached_client_id: Optional[int] = None
_cached_client_name: Optional[str] = None
_cached_client_updated: float = 0.0
_CLIENT_CACHE_TTL = 60.0
_client_cache_lock = threading.Lock()


def _set_cached_client(client_id, client_name):
    """Update the local client cache."""
    global _cached_client_id, _cached_client_name, _cached_client_updated
    with _client_cache_lock:
        _cached_client_id = client_id
        _cached_client_name = client_name
        _cached_client_updated = time.time()
        log(f"[CLIENT-CACHE] Set: {client_name} (id={client_id})")


def _get_cached_client():
    """
    Get current client from cache. If stale, refresh from backend.
    Returns (client_id, client_name).
    """
    global _cached_client_id, _cached_client_name, _cached_client_updated

    now = time.time()
    with _client_cache_lock:
        if (now - _cached_client_updated) < _CLIENT_CACHE_TTL:
            return _cached_client_id, _cached_client_name

    # Stale — refresh from backend (only if network is up)
    if not is_network_ok():
        with _client_cache_lock:
            return _cached_client_id, _cached_client_name

    api_key = config.get("api_key") or API_KEY
    if api_key and API_BASE:
        try:
            current = get_current_client_from_backend(API_BASE, api_key)
            if current:
                cid = current.get("client_id")
                cname = current.get("client_name")
                _set_cached_client(cid, cname)
                return cid, cname
        except Exception as e:
            log(f"[CLIENT-CACHE] Backend refresh failed: {e}")

    # Return stale cache rather than nothing
    with _client_cache_lock:
        return _cached_client_id, _cached_client_name


def _apply_client_switch(client_id: int, client_name: str, source: str = "unknown"):
    """
    Single source of truth for all client switches.

    Every code path that changes the current client MUST call this:
      - System tray menu switch
      - Notification confirm (toast)
      - Client picker confirm
      - AI switcher auto-switch
      - Nudge/guess confirm
    """
    log(f"[CLIENT-SWITCH] → {client_name} (id={client_id}) via {source}")

    # 1. Backend
    api_key = config.get("api_key") or API_KEY
    if api_key and API_BASE and is_network_ok():
        success = set_current_client_backend(API_BASE, api_key, client_id)
        if not success:
            log("[CLIENT-SWITCH] ⚠️ Backend update failed")

    # 2. Local cache (so write_event picks it up immediately)
    _set_cached_client(client_id, client_name)

    # 3. GUI update (tray tooltip, floating widget, state, menu checkmarks)
    if gui_menu_bar:
        # Update state directly — do NOT call _switch_client (creates callback loop)
        if hasattr(gui_menu_bar, 'state'):
            gui_menu_bar.state.set_client(client_id, client_name)
        # Update widget state tracker — user explicitly picked, start in confirmed
        if widget_tracker:
            widget_tracker.on_user_set_client(client_name=client_name)
            if hasattr(gui_menu_bar, 'state'):
                gui_menu_bar.state.current_widget_state = widget_tracker.state
        # Update floating widget. State is 'committed' (green) since user
        # explicitly chose — the timer will demote it later if title stops matching.
        if hasattr(gui_menu_bar, 'floating_widget') and gui_menu_bar.floating_widget:
            gui_menu_bar.floating_widget.update_client(
                client_id, client_name,
                state=widget_tracker.state if widget_tracker else "committed"
            )
        # Update tray tooltip
        if hasattr(gui_menu_bar, 'icon') and gui_menu_bar.icon:
            tooltip = f"TimeTracker - {client_name}"
            if hasattr(gui_menu_bar, 'user_name') and gui_menu_bar.user_name:
                tooltip = f"TimeTracker ({gui_menu_bar.user_name}) - {client_name}"
            gui_menu_bar.icon.title = tooltip
            try:
                gui_menu_bar.icon.update_menu()
            except Exception:
                pass

    # 4. Notification manager
    if notif_manager:
        notif_manager.set_current_client(client_id, client_name)

    # 5. AI switcher
    # 5. AI switcher — only snooze on MANUAL switches, not AI auto-switches
    if ai_switcher and source != "ai_switcher":
        ai_switcher.on_manual_switch(client_id, client_name)
    elif ai_switcher:
        ai_switcher.set_current_client(client_id, client_name)


# ---------------- Logging Setup ----------------
LOG_DIR = os.path.join(APPDATA, "TimeTracker", "Logs")
LOG_FILE = os.path.join(LOG_DIR, "agent.log")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "agent_errors.log")

def setup_logging():
    """Setup file-based logging with rotation."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        
        logger = logging.getLogger('timetracker')
        
        # Prevent duplicate handlers on reload/restart
        if logger.handlers:
            return logger
        
        # Main log - rotates at 5MB, keeps 3 backups
        main_handler = RotatingFileHandler(
            LOG_FILE, 
            maxBytes=5*1024*1024,
            backupCount=3,
            encoding='utf-8'
        )
        main_handler.setLevel(logging.INFO)
        main_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        
        # Error log - separate file for crashes only
        error_handler = RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=2*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        
        # ── removed second getLogger call here ──
        logger.setLevel(logging.DEBUG)
        logger.addHandler(main_handler)
        logger.addHandler(error_handler)
        
        return logger
    except Exception as e:
        print(f"[WARN] Failed to setup logging: {e}")
        return None

_logger = setup_logging()

# Make stdout/stderr survive parent-process detach (pythonw.exe, console close, etc).
# Without this, any stray print() from a third-party lib will throw ValueError
# and poison the Tkinter event loop — clicks, drags, polls all silently fail.
class _LogStream:
    """File-like object that forwards writes to the rotating log + swallows errors."""
    def __init__(self, level="info"):
        self._level = level
        self._buf = ""

    def write(self, msg):
        try:
            if not msg:
                return
            self._buf += msg
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip() and _logger:
                    if self._level == "error":
                        _logger.error(line.rstrip())
                    else:
                        _logger.info(line.rstrip())
        except Exception:
            pass

    def flush(self):
        try:
            if self._buf.strip() and _logger:
                _logger.info(self._buf.rstrip())
            self._buf = ""
        except Exception:
            pass

    def isatty(self):
        return False

# Probe stdout/stderr; if either is broken or gets closed later, redirect to log
try:
    sys.stdout.write("")
except (ValueError, OSError, AttributeError):
    sys.stdout = _LogStream("info")

try:
    sys.stderr.write("")
except (ValueError, OSError, AttributeError):
    sys.stderr = _LogStream("error")
# Browser app name suffixes that leak into window titles via win32 fallback
_BROWSER_TITLE_SUFFIXES = [
    " \u2013 Microsoft Edge",   # em dash (most common)
    " - Microsoft Edge",
    " \u2013 Google Chrome",
    " - Google Chrome",
    " \u2013 Brave Browser",
    " - Brave Browser",
    " \u2013 Mozilla Firefox",
    " - Mozilla Firefox",
]

def normalize_window_title(title: str) -> str:
    """Strip browser app name suffixes that leak in via win32 GetWindowText."""
    if not title:
        return title
    for suffix in _BROWSER_TITLE_SUFFIXES:
        if title.endswith(suffix):
            return title[:-len(suffix)].strip()
    return title

# ---------------- Logging ----------------
def log(msg: str, level: str = "info"):
    """Log to console (if verbose) and to file."""
    if VERBOSE:
        print(msg, flush=True)
    
    if _logger:
        if level == "error":
            _logger.error(msg)
        elif level == "warning":
            _logger.warning(msg)
        elif level == "debug":
            _logger.debug(msg)
        else:
            _logger.info(msg)


def log_error(msg: str, exc_info=True):
    """Log an error with optional traceback."""
    if VERBOSE:
        print(f"[ERROR] {msg}", flush=True)
    if _logger:
        _logger.error(msg, exc_info=exc_info)


# ---------------- Network Health Helpers ----------------
def is_network_ok() -> bool:
    """Thread-safe check if network is healthy."""
    with _network_ok_lock:
        return _network_ok

def set_network_ok(ok: bool):
    """Thread-safe set network health."""
    global _network_ok
    with _network_ok_lock:
        _network_ok = ok

def check_dns() -> bool:
    """Quick DNS check against our API host."""
    try:
        host = urlparse(API_BASE).hostname
        socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        return True
    except Exception:
        return False

def _start_health_monitor():
    """Background thread that checks connectivity every 30s until restored."""
    global _health_monitor_running

    if _health_monitor_running:
        return
    _health_monitor_running = True

    def _monitor():
        global _health_monitor_running
        log("[HEALTH] Starting network health monitor (checking every 30s)")
        while True:
            time.sleep(30)
            if is_network_ok():
                log("[HEALTH] Network already restored — monitor exiting")
                _health_monitor_running = False
                return

            try:
                if not check_dns():
                    log("[HEALTH] Still offline (DNS failed)")
                    continue

                # DNS works — try actual hello
                api_key_val = config.get("api_key") or API_KEY
                if api_key_val:
                    os_user = get_os_username()
                    hostname = platform.node()
                    device_id = get_device_id()
                    headers = api_headers(os_user, hostname)
                    payload = {
                        "hostname": hostname,
                        "app_version": APP_VERSION,
                        "device_id": device_id,
                        "os_username": os_user,
                    }
                    http_post_json(HELLO_URL, payload, headers, timeout=5)
                    set_network_ok(True)
                    log("[HEALTH] ✅ Network restored — resuming normal operation")
                    _health_monitor_running = False
                    return
            except Exception as e:
                log(f"[HEALTH] Still offline: {e}")

    threading.Thread(target=_monitor, daemon=True).start()


# ---------------- Error Reporting ----------------
_error_report_cache = {}  # Prevent spamming same error
ERROR_REPORT_COOLDOWN = 300  # 5 minutes between same errors

def report_error_to_backend(
    error_type: str, 
    error_msg: str, 
    traceback_str: str = None,
    context: dict = None
):
    """
    Send error report to backend for remote debugging.
    """
    api_key = config.get("api_key") or API_KEY
    if not api_key or not API_BASE:
        return False
    
    # Don't try to report errors when network is down
    if not is_network_ok():
        return False
    
    # Rate limit - don't spam same error
    error_key = f"{error_type}:{error_msg[:100]}"
    now = time.time()
    last_sent = _error_report_cache.get(error_key, 0)
    if now - last_sent < ERROR_REPORT_COOLDOWN:
        return False
    _error_report_cache[error_key] = now
    
    url = f"{API_BASE}/agent/errors/"
    
    payload = {
        "error_type": error_type,
        "error_message": error_msg[:1000],
        "traceback": (traceback_str or "")[:5000],
        "device_id": get_device_id(),
        "hostname": platform.node(),
        "os_username": get_os_username(),
        "app_version": APP_VERSION,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context or {},
    }
    
    def _send():
        try:
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode("utf-8"), 
                method="POST"
            )
            req.add_header("Authorization", f"DeviceKey {api_key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                log(f"[ERROR-REPORT] Sent to backend: {error_type}")
                return True
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log(f"[ERROR-REPORT] HTTP {e.code} sending error report")
        except Exception as e:
            log(f"[ERROR-REPORT] Failed to send: {e}")
        return False
    
    # Send async to not block
    threading.Thread(target=_send, daemon=True).start()
    
    return True

def ship_logs_to_backend(tail_lines: int = 500, trigger: str = "scheduled"):
    """
    Ship the last N lines of the agent log to the backend.
    Called automatically every 30 min and on-demand via control endpoint.
    """
    api_key = config.get("api_key") or API_KEY
    if not api_key or not API_BASE or not is_network_ok():
        return False

    # Read last N lines from agent log
    log_lines = []
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                log_lines = f.readlines()[-tail_lines:]
    except Exception as e:
        log(f"[LOG-SHIP] Failed to read log: {e}")
        return False

    if not log_lines:
        return False

    # Also append last 50 lines of watchdog log if it exists
    watchdog_log = os.path.join(LOG_DIR, "watchdog.log")
    try:
        if os.path.exists(watchdog_log):
            with open(watchdog_log, 'r', encoding='utf-8', errors='replace') as f:
                watchdog_lines = f.readlines()[-50:]
            if watchdog_lines:
                log_lines += ["\n--- WATCHDOG LOG ---\n"] + watchdog_lines
    except Exception:
        pass  # non-fatal — don't block main log ship

    url = f"{API_BASE}/agent/logs/"
    payload = {
        "device_id": get_device_id(),
        "hostname": platform.node(),
        "os_username": get_os_username(),
        "app_version": APP_VERSION,
        "platform": "windows",
        "trigger": trigger,
        "log_lines": log_lines,
        "log_line_count": len(log_lines),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    def _send():
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                method="POST"
            )
            req.add_header("Authorization", f"DeviceKey {api_key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=15) as resp:
                log(f"[LOG-SHIP] ✅ Shipped {len(log_lines)} lines ({trigger})")
                return True
        except Exception as e:
            log(f"[LOG-SHIP] Failed: {e}")
            return False

    threading.Thread(target=_send, daemon=True).start()
    return True

def start_log_shipping(interval_minutes: int = 30):
    """Start background thread that ships logs every N minutes."""
    def _loop():
        # Wait a bit after startup before first ship
        time.sleep(120)
        while True:
            try:
                ship_logs_to_backend(tail_lines=500, trigger="scheduled")
            except Exception as e:
                log(f"[LOG-SHIP] Scheduled ship error: {e}")
            time.sleep(interval_minutes * 60)
 
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    log(f"[LOG-SHIP] Started — shipping every {interval_minutes} min")


# ---------------- Context Bus ----------------
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request
import urllib.error

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
    """Get seconds since last mouse/keyboard input using GetLastInputInfo.
    
    Clamps to _IDLE_HARD_CAP_HOURS to prevent stale dwTime values (seen after
    screen lock / sleep on some Windows configs) from locking the idle state
    permanently.
    """
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
        raw = millis / 1000.0
        
        # Clamp: if GetLastInputInfo returns a stale/corrupted value after
        # sleep or screen lock, the delta can be days. Cap it so the idle
        # watchdog can still force-exit below.
        return min(raw, _IDLE_HARD_CAP_HOURS * 3600)
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
            if psutil:
                process = psutil.Process(pid)
                exe_name = process.name()
                app_name = exe_name.replace(".exe", "").title()
            else:
                exe_name = "Unknown"
                app_name = "Unknown"
        except (psutil.NoSuchProcess, psutil.AccessDenied) if psutil else Exception:
            exe_name = "Unknown"
            app_name = "Unknown"
        
        return (app_name, exe_name, pid, title)
    
    except Exception as e:
        if VERBOSE:
            log(f"[WARN] get_foreground_window_info error: {e}")
        return None

# UIA cache — keyed by HWND, expires after a few seconds
_uia_cache = {}
_UIA_CACHE_TTL = 3.0  # seconds

def _get_explorer_folder_path() -> Optional[str]:
    """Get current folder path of the active Explorer window via Shell COM."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        hwnd = win32gui.GetForegroundWindow()
        for window in shell.Windows():
            try:
                if window.HWND == hwnd:
                    folder = window.Document.Folder
                    if folder:
                        return folder.Self.Path
            except Exception:
                continue
    except Exception:
        return None
    return None


def _get_browser_address_bar(exe_name: str) -> Optional[str]:
    """Get URL/path from browser address bar via UI Automation. Cached per HWND."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        now = _time.time()
        
        # Check cache
        cached = _uia_cache.get(hwnd)
        if cached and now - cached[0] < _UIA_CACHE_TTL:
            return cached[1]
        
        # Lazy import — uiautomation is slow to load
        try:
            import uiautomation as auto
        except ImportError:
            return None
        
        # Get the foreground window control
        control = auto.ControlFromHandle(hwnd)
        if not control:
            return None
        
        # Search for the address bar — Edge/Chrome use EditControl with role
        # like "Address and search bar"
        addr_bar = control.EditControl(searchDepth=12)
        url = None
        if addr_bar.Exists(maxSearchSeconds=0.3):
            url = addr_bar.GetValuePattern().Value
        
        _uia_cache[hwnd] = (now, url)
        return url
    except Exception:
        return None


def try_get_url_or_path(exe_name: str, window_title: str) -> Dict[str, Optional[str]]:
    exe_lower = exe_name.lower()
    
    if exe_lower in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"):
        # First try title-based (fast, works for normal pages with full URL in title)
        url = extract_url_from_browser_title(window_title, exe_lower)
        if not url:
            # Fall back to UI Automation address bar (slower but works for PDFs, file:// etc.)
            url = _get_browser_address_bar(exe_lower)
        return {"url": url, "file_path": None}
    
    if exe_lower in ("excel.exe", "winword.exe", "powerpnt.exe"):
        file_path = get_office_file_path(exe_lower, window_title)
        return {"url": None, "file_path": file_path}
    
    if exe_lower == "explorer.exe":
        path = _get_explorer_folder_path()
        return {"url": None, "file_path": path}
    
    return {"url": None, "file_path": None}
def extract_url_from_browser_title(title: str, exe: str) -> Optional[str]:
    """Parse URL from browser window title."""
    if not title:
        return None
    
    for suffix in [" - Google Chrome", " — Mozilla Firefox", " - Microsoft Edge", " - Brave"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
    
    if "://" in title or title.startswith("localhost") or "/" in title:
        parts = title.split()
        for part in parts:
            if "://" in part or part.startswith("localhost"):
                return part.strip()
    
    return None

def get_office_file_path(exe: str, window_title: str = None) -> Optional[str]:
    """Get active Office file path by matching window title against open files."""
    if not psutil:
        return None
    
    exe_lower = exe.lower()
    extensions = {
        "excel.exe": {".xlsx", ".xls", ".xlsm", ".xlsb", ".csv"},
        "winword.exe": {".docx", ".doc", ".docm"},
        "powerpnt.exe": {".pptx", ".ppt", ".pptm"},
    }
    
    target_exts = extensions.get(exe_lower, set())
    if not target_exts:
        return None

    try:
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"].lower() != exe_lower:
                    continue
                files = proc.open_files()
                
                # Filter to only Office files
                office_files = [
                    f.path for f in files
                    if any(f.path.lower().endswith(ext) for ext in target_exts)
                ]
                
                if not office_files:
                    return None
                
                # If only one file open — return it
                if len(office_files) == 1:
                    return office_files[0]
                
                # Multiple files open — match against window title
                if window_title:
                    title_lower = window_title.lower()
                    for path in office_files:
                        filename = os.path.basename(path).lower()
                        # Strip extension for matching
                        name_no_ext = os.path.splitext(filename)[0].lower()
                        if name_no_ext in title_lower or filename in title_lower:
                            return path
                
                # Fallback — return most recently modified file
                return max(office_files, key=lambda p: os.path.getmtime(p))
                
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        log(f"[FILE] Process file detection failed: {e}")
    
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
    if config.get("server_device_id"):
        return config["server_device_id"]
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
        server_device_id = data.get("device_id")
        if key:
            config["api_key"] = key
            if server_device_id:
                config["server_device_id"] = server_device_id
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
    
    pair_code = _get("pair_code", os.getenv("AGENT_PAIR_CODE"))
    if pair_code:
        with _pair_lock:
            key = _claim_pair(pair_code, hostname)
            API_KEY = key
            return key
    
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
    """Only used by repair_device(). NEVER call on transient network failures."""
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
SERVER_USER_NAME = None  # Store user's display name

def hello(server_url: str, user: str, host: str, device_id: str):
    global SERVER_USER_ID, SERVER_USER_NAME
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
        SERVER_USER_NAME = data.get("user_name") or data.get("username") or data.get("display_name")
        log(f"[HELLO] Registered with server: user_id={SERVER_USER_ID}, name={SERVER_USER_NAME}")
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

    # Skip network call when offline — don't block the tracking loop
    if not is_network_ok():
        return False

    qs = f"?host={host}"
    headers = api_headers(user, host)
    try:
        data = http_get_json(control_url + qs, headers, timeout=5)
        stop = bool(data.get("stop"))
        if stop:
            log(f"[CTRL] Stop received from server: reason={data.get('reason','')}")
        return stop
    except Exception as e:
        log(f"[CTRL] get error: {e}")
        return False  # network down = don't stop, keep tracking


def check_control_commands(control_url: str, user: str, host: str) -> bool:
    global _last_control_check
    now = time.time()
    if now - _last_control_check < CONTROL_POLL_S:
        return False
    _last_control_check = now

    if not is_network_ok():
        return False

    qs = f"?host={host}"
    headers = api_headers(user, host)
    try:
        data = http_get_json(control_url + qs, headers, timeout=5)

        if data.get("stop"):
            log(f"[CTRL] Stop received from server: reason={data.get('reason','')}")
            return True  # stop

        if data.get("ship_logs"):
            log(f"[CTRL] Log ship requested by admin")
            ship_logs_to_backend(tail_lines=500, trigger="on_demand")

        if data.get("ship_full_logs"):
            log(f"[CTRL] Full log ship requested by admin")
            ship_logs_to_backend(tail_lines=2000, trigger="on_demand_full")

        if data.get("restart"):
            log(f"[CTRL] Restart requested by admin — restarting in 3s")
            ship_logs_to_backend(tail_lines=500, trigger="pre_restart")
            def _do_restart():
                time.sleep(3)
                log(f"[CTRL] Restarting now...")
                os._exit(0)
            threading.Thread(target=_do_restart, daemon=True).start()

        return False

    except Exception as e:
        log(f"[CTRL] check error: {e}")
        return False

# ---------------- Sleep/Wake Recovery ----------------
def register_power_notifications(os_user: str, hostname: str, device_id: str):
    """
    Register for Windows power state changes (sleep/wake/resume).
    Creates a hidden window on a background thread to receive WM_POWERBROADCAST messages.
    On wake: marks network unhealthy, resets control timer, reconnects with backoff.
    """
    if not WIN_API_AVAILABLE:
        log("[POWER] pywin32 not available — sleep/wake detection disabled")
        return

    def _power_listener():
        import win32gui
        import win32con

        PBT_APMRESUMESUSPEND = 0x0007     # Resume from suspend
        PBT_APMRESUMEAUTOMATIC = 0x0012   # Automatic resume (e.g. wake timers)
        PBT_APMSUSPEND = 0x0004           # Going to sleep

        def _on_wake():
            global _last_control_check, _wake_timestamp, _wake_handled
            
            now = time.time()
            if _wake_handled and (now - _wake_timestamp) < 10:
                log("[WAKE] Duplicate wake event — skipping")
                return
            _wake_handled = True
            
            log("[WAKE] System resumed from sleep — resetting connections")
            record_wake_event()
            _last_control_check = 0.0
            _wake_timestamp = now
            set_network_ok(False)
            
            _wake_event.set()  # Signal tracking loop

            try:
                from update_checker import notify_wake
                notify_wake()
            except Exception:
                pass

            # Windows — signal tracking loop reset, don't exit
            # Mac — exit so LaunchAgent restarts cleanly
            if sys.platform == 'darwin':
                log("[WAKE] Forcing exit — LaunchAgent will restart cleanly")
                os._exit(1)

            def _reconnect():
                global _wake_handled
                for attempt in range(10):
                    wait = min(5 * (attempt + 1), 30)
                    time.sleep(wait)
                    try:
                        api_key_val = config.get("api_key") or API_KEY
                        if api_key_val and API_BASE:
                            headers = api_headers(os_user, hostname)
                            payload = {
                                "hostname": hostname,
                                "app_version": APP_VERSION,
                                "device_id": device_id,
                                "os_username": os_user,
                            }
                            http_post_json(HELLO_URL, payload, headers, timeout=5)
                            set_network_ok(True)
                            log(f"[WAKE] ✅ Reconnected (attempt {attempt + 1})")
                            
                            # Re-register hotkey — Windows may have
                            # killed the low-level hook during sleep
                            if register_hotkey:
                                try:
                                    register_hotkey()
                                    log("[WAKE] ✅ Hotkey re-registered")
                                except Exception as e:
                                    log(f"[WAKE] ⚠️ Hotkey re-register failed: {e}")
                            
                            _wake_handled = False  # Allow future wake events
                            return
                    except Exception as e:
                        log(f"[WAKE] Reconnect attempt {attempt + 1}/10 failed: {e}")

                log("[WAKE] ⚠️ All reconnect attempts failed — starting health monitor")
                _wake_handled = False
                _start_health_monitor()

            threading.Thread(target=_reconnect, daemon=True).start()

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == win32con.WM_POWERBROADCAST:
                if wparam == PBT_APMSUSPEND:
                    log("[POWER] System going to sleep...")
                elif wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                    _on_wake()
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        # Create hidden window to receive power messages
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = wndproc
        wc.lpszClassName = "TimeTrackerPowerWatcher"
        wc.hInstance = win32api.GetModuleHandle(None)

        try:
            class_atom = win32gui.RegisterClass(wc)
            hwnd = win32gui.CreateWindow(
                class_atom, "TimeTrackerPowerWatcher",
                0, 0, 0, 0, 0,
                0, 0, wc.hInstance, None
            )
            log("[POWER] ✅ Sleep/wake handler registered (hidden window)")

            # Message pump — must run forever on this thread
            while True:
                win32gui.PumpWaitingMessages()
                time.sleep(0.5)
        except Exception as e:
            log(f"[POWER] ❌ Failed to create power watcher: {e}")
            log_error(f"[POWER] {e}")

    t = threading.Thread(target=_power_listener, daemon=True)
    t.start()
    log("[POWER] Started power notification listener thread")


# ---------------- Startup Task Registration ----------------
from startup_task import register_startup_task


# ---------------- Event Posting ----------------
_consecutive_auth_failures = 0  # Track consecutive 401/403 errors

def post_event_async(event: dict, user: str, host: str):
    if not POST_URL:
        return
    
    def _run():
        global _consecutive_auth_failures
        headers = api_headers(user, host)
        try:
            req = urllib.request.Request(POST_URL, data=json.dumps(event).encode("utf-8"), method="POST")
            for k, v in headers.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=6) as resp:
                _ = resp.read()
            log(f"[POSTED] {POST_URL}")
            _consecutive_auth_failures = 0  # Reset on success
            # Successful post confirms network is up
            set_network_ok(True)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except:
                pass
            log(f"[POST ERROR] HTTP {e.code}: {body[:200]}")
            if e.code == 403 and "subscription_inactive" in body:
                global _subscription_active
                _subscription_active = False
                log("[SUB] ⚠️ Subscription inactive — agent paused")
                show_subscription_inactive_notification()
                return
            if e.code in (401, 403):
                _consecutive_auth_failures += 1
                log(f"[AUTH] Got {e.code} posting event (consecutive: {_consecutive_auth_failures}) — will retry next cycle")
            else:
                set_network_ok(True)
        except Exception as e:
            log(f"[POST ERROR] {e}")
            # Network-level error — mark as unhealthy if not already being monitored
            if is_network_ok():
                set_network_ok(False)
                _start_health_monitor()
    
    threading.Thread(target=_run, daemon=True).start()

def write_event(conn, cur, user: str, hostname: str, sig, ts_override: float = None):
    app_name, bundle_id, title, url, fpath = sig
    
    if ts_override is not None:
        ts_dt = datetime.fromtimestamp(ts_override, tz=timezone.utc)
    else:
        ts_dt = datetime.now(timezone.utc)
    ts_iso = ts_dt.isoformat()
    
    # ── Local DB write FIRST — always succeeds even if network is down ──
    cur.execute(
        "INSERT INTO raw_events (ts_utc, app_name, bundle_id, window_title, url, file_path, user, hostname) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts_iso, app_name, bundle_id, title or "", url, fpath, user, hostname),
    )
    conn.commit()
    
    # ── FIX: Use local cache instead of HTTP call every 5 seconds ──
    current_client_id, current_client_name = _get_cached_client()
    
    if notif_manager:
        notif_manager.set_current_client(current_client_id, current_client_name)
    
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
    
    # ── Post event (async, non-blocking) ──
    post_event_async(payload, user, hostname)
    
    network_status = "" if is_network_ok() else " [OFFLINE - saved locally]"
    client_msg = f" → {current_client_name}" if current_client_name else ""
    log(
        f"[EVENT] dwell-finalized • {app_name} • {title or '(no title)'} "
        f"• url={url or '-'} • path={fpath or '-'}"
        + (f" • toolish({tool_reason})" if toolish else "")
        + client_msg
        + f" at {ts_iso}"
        + network_status
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

# ---------------- Repair Device ----------------
def repair_device():
    """Reset device pairing - called from GUI"""
    global API_KEY, config
    
    print("[REPAIR] Starting device repair...")  # Always print, not just when verbose
    
    try:
        # Clear device ID file
        device_id_file = os.path.expanduser("~/.timetracker/.device_id")
        if os.path.exists(device_id_file):
            os.remove(device_id_file)
            print(f"[REPAIR] Removed device ID file: {device_id_file}")
        else:
            print(f"[REPAIR] No device ID file found at: {device_id_file}")
        
        # Also check Windows AppData location
        appdata_device_id = os.path.join(APPDATA, "TimeTracker", ".device_id")
        if os.path.exists(appdata_device_id):
            os.remove(appdata_device_id)
            print(f"[REPAIR] Removed AppData device ID: {appdata_device_id}")
        
        # Clear config
        if "api_key" in config:
            del config["api_key"]
            print("[REPAIR] Cleared api_key from config")
        if "server_device_id" in config:
            del config["server_device_id"]
            print("[REPAIR] Cleared server_device_id from config")
        
        save_config(config)
        API_KEY = None
        
        print("[REPAIR] Device reset complete!")
        
        # Find and launch pairing GUI
        # Try multiple locations
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "gui.py"),
            os.path.join(os.path.dirname(sys.executable), "gui.py"),
            os.path.join(os.getcwd(), "gui.py"),
        ]
        
        # If running as frozen exe, look for gui.exe too
        if getattr(sys, 'frozen', False):
            possible_paths.extend([
                os.path.join(os.path.dirname(sys.executable), "TimeTrackerGUI.exe"),
                os.path.join(os.path.dirname(sys.executable), "gui.exe"),
            ])
        
        gui_launched = False
        for gui_path in possible_paths:
            print(f"[REPAIR] Checking for GUI at: {gui_path}")
            if os.path.exists(gui_path):
                print(f"[REPAIR] Found GUI, launching: {gui_path}")
                if gui_path.endswith('.exe'):
                    subprocess.Popen([gui_path])
                else:
                    subprocess.Popen([sys.executable, gui_path])
                gui_launched = True
                print("[REPAIR] ✅ Pairing GUI launched!")
                break
        
        if not gui_launched:
            print("[REPAIR] ⚠️ Could not find GUI to launch")
            print("[REPAIR] Please restart the agent manually to re-pair")
        
        # Show success message using tkinter
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()  # Hide main window
            messagebox.showinfo(
                "Device Reset", 
                "Device has been reset successfully!\n\n"
                "Please enter a new pairing code in the GUI window."
            )
            root.destroy()
        except Exception as e:
            print(f"[REPAIR] Could not show dialog: {e}")
            
    except Exception as e:
        print(f"[REPAIR] ❌ Error during repair: {e}")
        import traceback
        traceback.print_exc()
        
        # Show error message
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Repair Failed", f"Error during device repair:\n\n{e}")
            root.destroy()
        except:
            pass


# ---------------- Main Agent ----------------
def run_agent():
    """Main agent function with GUI integration"""
    global API_KEY, notif_manager, notif_worker, sync, gui_menu_bar, SERVER_USER_NAME, ai_switcher

    # ── Global socket timeout — prevents any network call hanging indefinitely ──
    socket.setdefaulttimeout(8)

    from watchdog import heartbeat_touch, watchdog as _watchdog



    # === FORCED UPDATE CHECK ===
    from update_checker import check_for_update_blocking, start_background_checker
    log(f"[UPDATE] Starting update check (current={APP_VERSION})")
    check_for_update_blocking(API_BASE, APP_VERSION)
    
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    
    start_context_bus(CONTEXT_PORT)

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
                global MOUSE_IDLE_PAUSE_S
                print(f"[SYNC] Data updated: {len(sync.clients)} clients")
                if hasattr(sync, 'gui_menu_bar') and sync.gui_menu_bar and hasattr(sync.gui_menu_bar, 'refresh_client_menu'):
                    sync.gui_menu_bar.refresh_client_menu(sync.clients)
                    print("[SYNC] GUI menu refreshed")
                else:
                    print("[SYNC] GUI not ready yet")
                # Apply org settings from sync
                if hasattr(sync, 'org_settings') and sync.org_settings:
                    new_idle_s = sync.org_settings.get("mouse_idle_pause_seconds")
                    if new_idle_s is not None:
                        new_idle_s = int(new_idle_s)
                        if new_idle_s != MOUSE_IDLE_PAUSE_S:
                            log(f"[SYNC] Idle timeout updated: {MOUSE_IDLE_PAUSE_S}s → {new_idle_s}s")
                            MOUSE_IDLE_PAUSE_S = new_idle_s
            
            sync.on_update = on_sync_update
            sync.start()
            print(f"[SYNC] Started - polling every {sync.poll_interval}s")
        except ImportError:
            print("[SYNC] agent_sync_integration not available")

    # === PUSH NOTIFICATION SYSTEM ===
    notif_worker = None
    
    if PUSH_NOTIF_AVAILABLE and NOTIF_ENABLED:
        log("[NOTIF] Initializing push notification system...")
        
        notif_config = NotificationConfig(
            enabled=True,
            duration_reminder_enabled=True,
            duration_reminder_interval_minutes=NOTIF_DURATION_MINUTES,
            duration_reminder_first_minutes=30,
            idle_return_enabled=True,
            idle_threshold_seconds=NOTIF_IDLE_THRESHOLD,
            context_change_enabled=True,
            context_confidence_threshold=0.6,
            no_client_reminder_enabled=True,
            no_client_reminder_after_minutes=NOTIF_NO_CLIENT_MINUTES,
            min_seconds_between_notifications=60,
            respect_quiet_hours=False,
        )
        
        def on_notif_confirm(client_id, client_name):
            """Handle user confirming client from notification"""
            def _do():
                _apply_client_switch(client_id, client_name, source="notification")
            threading.Thread(target=_do, daemon=True).start()
        
        def on_notif_switch():
            """Handle user requesting client switch from notification"""
            def _do():
                log("[NOTIF] User requested client switch - opening picker")
                if gui_menu_bar and hasattr(gui_menu_bar, '_show_client_picker'):
                    try:
                        gui_menu_bar._show_client_picker()
                    except Exception as e:
                        log(f"[NOTIF] Failed to open picker: {e}")
            threading.Thread(target=_do, daemon=True).start()

        def on_notif_snooze(client_id, minutes):
            """Handle user snoozing a client suggestion"""
            def _do():
                log(f"[NOTIF] User snoozed client {client_id} for {minutes} minutes")
            threading.Thread(target=_do, daemon=True).start()
        
        # Create API client for timesheet review notifications
        class _NotifAPIClient:
            def __init__(self, base_url, api_key):
                self.base_url = base_url
                self.api_key = api_key
            def get(self, path):
                req = urllib.request.Request(
                    f"{self.base_url}{path}",
                    headers={"Authorization": f"DeviceKey {self.api_key}"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read())

        _notif_api = _NotifAPIClient(API_BASE, config.get("api_key") or API_KEY)

        def on_review(data):
            log(f"[NOTIF] User clicked Review Now: {data}")

        notif_manager = create_notification_system(
            on_confirm=on_notif_confirm,
            on_switch=on_notif_switch,
            on_snooze=on_notif_snooze,
            config=notif_config,
            api_client=_notif_api,
            agent_config={'base_url': 'https://timetracker.mavops.ai'},
            on_review=on_review,
        )
        
        if notif_manager and notif_manager.ready:
            log("[NOTIF] ✅ Push notification system ready")
            
            def get_current_client_for_notif():
                if gui_menu_bar and hasattr(gui_menu_bar, 'state'):
                    return {
                        "client_id": gui_menu_bar.state.current_client_id,
                        "client_name": gui_menu_bar.state.current_client_name
                    }
                return {"client_id": None, "client_name": None}
            
            notif_worker = NotificationWorker(
                notification_manager=notif_manager,
                get_current_client=get_current_client_for_notif,
                poll_interval=30
            )

            notif_worker.start()
            log("[NOTIF] Notification worker started")
            
            # Check for timesheet review on startup (delayed)
            def check_startup_timesheet():
                time.sleep(8)  # Wait for toaster to fully initialize
                try:
                    review_result = notif_manager.notify_timesheet_review(force=False)
                    log(f"[NOTIF] Startup timesheet review check: {review_result}")
                except Exception as e:
                    log(f"[NOTIF] Startup review check failed: {e}")
            
            threading.Thread(target=check_startup_timesheet, daemon=True).start()
        else:
            log("[NOTIF] ⚠️ Push notifications not authorized")
            notif_manager = None
    else:
        if not PUSH_NOTIF_AVAILABLE:
            log("[NOTIF] Push notifications not available (module not found)")
        elif not NOTIF_ENABLED:
            log("[NOTIF] Push notifications disabled by config")
    
    # === GUI INITIALIZATION ===
    if GUI_AVAILABLE:
        try:
            api_key = config.get("api_key") or API_KEY
            api_base = API_BASE
            
            gui_menu_bar = run_gui_app(
                on_client_confirmed=lambda cid, cname, data: (
                    _apply_client_switch(cid, cname, source="gui_prompt"),
                ),
                on_client_rejected=lambda data: log(f"[GUI] Client rejected"),
                get_today_time=fetch_today_time,
                fetch_clients=lambda: fetch_clients_from_backend(api_base, api_key),
                set_current_client=lambda cid: _apply_client_switch(
                    cid,
                    next((c.get("name") for c in (sync.clients or []) if c.get("id") == cid), "Unknown"),
                    source="tray_menu"
                ),
                get_current_client=lambda: get_current_client_from_backend(api_base, api_key),
                repair_callback=repair_device,
                sync=sync,
            )
            log("[GUI] System tray initialized")

            import atexit
            def _cleanup_tray():
                try:
                    if gui_menu_bar and gui_menu_bar.icon:
                        gui_menu_bar.icon.stop()
                except:
                    pass
            atexit.register(_cleanup_tray)
            
            if sync and gui_menu_bar:
                sync.gui_menu_bar = gui_menu_bar
                if sync.clients and hasattr(gui_menu_bar, 'refresh_client_menu'):
                    gui_menu_bar.refresh_client_menu(sync.clients)
                    log(f"[GUI] Refreshed menu with {len(sync.clients)} clients from sync")
            
            # === QUICK SWITCHER (Alt+Ctrl+T) - FIXED ===
            # === QUICK SWITCHER (Alt+Ctrl+T) ===
            # v1.2.96: Use native Windows RegisterHotKey to avoid system-wide
            # keyboard hook. The `keyboard` library with suppress=True installs
            # a WH_KEYBOARD_LL hook that can freeze keyboard input system-wide
            # when the agent is blocked on I/O (backend calls, sync polling).
            # Wayne@TL Wall reported exactly this symptom. Native RegisterHotKey
            # is the standard Windows approach — zero hook, zero risk.
            if gui_menu_bar:
                _hotkey_lock = threading.Lock()
                _hotkey_last = [0]
 
                def on_hotkey_pressed():
                    """Called when Alt+Ctrl+T fires. Debounced to 1.5s."""
                    with _hotkey_lock:
                        now = time.time() * 1000
                        if now - _hotkey_last[0] < 1500:
                            return
                        _hotkey_last[0] = now
 
                    log("[HOTKEY] Alt+Ctrl+T pressed!")
                    # Brief delay to let user release keys before picker grabs focus
                    time.sleep(0.02)
                    try:
                        gui_menu_bar._show_client_picker()
                    except Exception as e:
                        log(f"[HOTKEY] Picker launch failed: {e}")
 
                # ── Attempt 1: Native Windows RegisterHotKey ──────────────────
                # This uses the same Windows API that every other app uses
                # for system-wide shortcuts (e.g. Win+D, Alt+Tab). No hook
                # installed — Windows delivers a WM_HOTKEY message to our
                # message pump thread when the combo is pressed.
                _native_hotkey_registered = False
                try:
                    from ctypes import wintypes
 
                    MOD_ALT = 0x0001
                    MOD_CONTROL = 0x0002
                    MOD_NOREPEAT = 0x4000  # Don't fire on key-repeat
                    WM_HOTKEY = 0x0312
                    VK_T = 0x54
                    HOTKEY_ID = 1
 
                    _user32 = ctypes.windll.user32
 
                    # GetMessageW needs correct argtypes/restype or it silently
                    # truncates on 64-bit Python. Declare them explicitly.
                    _user32.GetMessageW.argtypes = [
                        ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                        wintypes.UINT, wintypes.UINT,
                    ]
                    _user32.GetMessageW.restype = wintypes.BOOL
                    _user32.RegisterHotKey.argtypes = [
                        wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT,
                    ]
                    _user32.RegisterHotKey.restype = wintypes.BOOL
                    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
                    _user32.UnregisterHotKey.restype = wintypes.BOOL
 
                    # Must register + pump on the SAME thread. Spawn dedicated thread.
                    _hotkey_ready = threading.Event()
                    _hotkey_success = [False]
 
                    def _native_hotkey_loop():
                        """Dedicated thread: registers hotkey + pumps WM_HOTKEY messages."""
                        # RegisterHotKey with hWnd=None means messages are posted
                        # to THIS thread's message queue (not any window).
                        ok = _user32.RegisterHotKey(
                            None, HOTKEY_ID,
                            MOD_ALT | MOD_CONTROL | MOD_NOREPEAT,
                            VK_T,
                        )
                        if not ok:
                            err = ctypes.windll.kernel32.GetLastError()
                            log(f"[HOTKEY] RegisterHotKey failed (err={err}) — will fall back to keyboard lib")
                            _hotkey_ready.set()
                            return
 
                        _hotkey_success[0] = True
                        _hotkey_ready.set()
                        log("[HOTKEY] ✅ Alt+Ctrl+T registered (native Windows API, no hook)")
 
                        try:
                            msg = wintypes.MSG()
                            while True:
                                # Block until WM_HOTKEY arrives (or thread exits)
                                result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                                if result == 0 or result == -1:
                                    break
                                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                                    # Dispatch on a worker thread so a slow picker
                                    # can't block future hotkey presses.
                                    threading.Thread(
                                        target=on_hotkey_pressed, daemon=True
                                    ).start()
                        except Exception as e:
                            log(f"[HOTKEY] Native pump error: {e}")
                        finally:
                            try:
                                _user32.UnregisterHotKey(None, HOTKEY_ID)
                            except Exception:
                                pass
 
                    _hotkey_thread = threading.Thread(
                        target=_native_hotkey_loop, daemon=True, name="NativeHotkey",
                    )
                    _hotkey_thread.start()
 
                    # Wait up to 3 seconds for registration to complete
                    _hotkey_ready.wait(timeout=3.0)
                    _native_hotkey_registered = _hotkey_success[0]
 
                except Exception as e:
                    log(f"[HOTKEY] Native RegisterHotKey setup error: {e}")
                    _native_hotkey_registered = False
 
                # ── Set up register_hotkey() for the wake-from-sleep handler ──
                # (main.py's power handler calls register_hotkey() on wake.
                # With native RegisterHotKey, Windows preserves the registration
                # across sleep, so this becomes a no-op.)
                global register_hotkey
                if _native_hotkey_registered:
                    def register_hotkey():
                        """No-op — native hotkey survives sleep/wake."""
                        pass
                else:
                    # ── Attempt 2: Fallback to keyboard library (NO SUPPRESS) ─
                    # Only runs if native API failed. suppress=False avoids
                    # installing the system-wide low-level hook that caused
                    # Wayne's keyboard lockup. Tradeoff: the Alt+Ctrl+T
                    # keystroke will pass through to the active app as well,
                    # but most apps don't bind that combo so it's harmless.
                    try:
                        import keyboard as _kb_lib
 
                        def register_hotkey():
                            """Register (or re-register) the fallback hotkey."""
                            try:
                                _kb_lib.unhook_all()
                            except Exception:
                                pass
                            _kb_lib.add_hotkey(
                                'alt+ctrl+t',
                                on_hotkey_pressed,
                                suppress=False,  # v1.2.96: NEVER suppress — causes system freezes
                            )
                            log("[HOTKEY] ⚠️ Fallback: keyboard lib registered (suppress=False)")
 
                        register_hotkey()
 
                    except ImportError:
                        log("[HOTKEY] ❌ Both native API failed AND keyboard lib not installed — no hotkey")
                        register_hotkey = None
                    except Exception as e:
                        log(f"[HOTKEY] ❌ Fallback also failed: {e}")
                        register_hotkey = None

        except Exception as e:
            log(f"[GUI] Failed to initialize: {e}")
            import traceback
            traceback.print_exc()

    # === AI CLIENT AUTO-SWITCHER ===
    ai_switcher = None
    try:
        from ai_client_switcher import AIClientSwitcher
        
        ai_switcher = AIClientSwitcher(
            config={
                "enabled": True,
                "dwell_seconds_before_switch": 0,
                "cooldown_seconds": 0,
                "manual_override_snooze_minutes": 0,
                "debug": VERBOSE,
            },
            api_base=API_BASE,
            api_key=config.get("api_key") or API_KEY,
            set_current_client_fn=lambda cid, cname=None, source="ai_switcher": _apply_client_switch(cid, cname or "Unknown", source=source),
            gui_menu_bar=gui_menu_bar,
            notif_manager=notif_manager,
            sync=sync,
        )
        # Sync current client state on startup
        api_key_val = config.get("api_key") or API_KEY
        if api_key_val and API_BASE:
            try:
                current = get_current_client_from_backend(API_BASE, api_key_val)
                if current and current.get("client_id"):
                    ai_switcher.set_current_client(current["client_id"], current.get("client_name"))
            except Exception:
                pass
        
        log("[AI-SWITCH] ✅ Initialized")


        # Keep client list + sensitivity fresh when sync updates
        # Keep client list + sensitivity fresh when sync updates
        # Keep client list + patterns + routing rules + sensitivity fresh when sync updates
        if sync:
            _original_on_sync = sync.on_update
            def _on_sync_with_switcher():
                if _original_on_sync:
                    _original_on_sync()
                ai_switcher.update_clients(sync.clients)
                if hasattr(sync, 'client_patterns') and sync.client_patterns:
                    ai_switcher.update_client_patterns(sync.client_patterns)
                # v1.2.95: Tier -1 org routing rules
                if hasattr(sync, 'routing_rules'):
                    ai_switcher.update_routing_rules(sync.routing_rules or [])
                if hasattr(sync, 'org_settings') and sync.org_settings:
                    ai_sensitivity = sync.org_settings.get("ai_sensitivity", 50)
                    ai_switcher.update_sensitivity(ai_sensitivity)
            sync.on_update = _on_sync_with_switcher
            # Push any rules that already arrived before switcher was created
            if hasattr(sync, 'routing_rules') and sync.routing_rules:
                ai_switcher.update_routing_rules(sync.routing_rules)

    except ImportError:
        log("[AI-SWITCH] ai_client_switcher.py not found — disabled")


    # === EXPLORER FOLDER WATCHER (Mac parity) ===
    # When user opens a folder in Explorer, feed the path into the AI switcher
    # so it can auto-switch the client — same behavior as Mac's NSWorkspace hook.
    explorer_watcher = None
    try:
        from explorer_watcher import ExplorerFolderWatcher
     
        if ai_switcher:
            explorer_watcher = ExplorerFolderWatcher(
                ai_switcher=ai_switcher,
                log_fn=log,
                poll_seconds=2.0,
                enabled=True,
            )
            explorer_watcher.start()
        else:
            log("[EXPLORER] AI switcher unavailable — folder watcher not started")
    except ImportError:
        log("[EXPLORER] explorer_watcher.py not found — folder watching disabled")
    except Exception as e:
        log(f"[EXPLORER] Failed to initialize: {e}")
        import traceback
        traceback.print_exc()


    # === MEETING DETECTOR ===
    meeting_detector = None
    if MEETING_DETECTOR_AVAILABLE:
        try:
            # Helper to get current foreground title — used for browser meeting detection
            def _get_fg_title():
                try:
                    info = get_foreground_window_info()
                    if info:
                        return info[3]  # window_title is index 3
                except Exception:
                    pass
                return None

            def _on_meeting_start(state):
                """Fired when a meeting is detected starting.

                - Attempts client classification via AI switcher on the meeting title
                - High confidence → auto-attribute (toast notification)
                - Medium confidence → nudge-style confirm prompt
                - Low/no match → meeting block gets no client, prompt at end
                """
                log(f"[MEETING] Started: {state.app} — {state.title or '(no title)'}")

                # Try AI classification if we have a title and switcher is available
                if state.title and ai_switcher and hasattr(ai_switcher, 'classify_text'):
                    try:
                        match = ai_switcher.classify_text(state.title)
                        if match:
                            cid, cname, conf = match.get("client_id"), match.get("client_name"), match.get("confidence", 0)
                            if conf >= 0.85 and cid:
                                log(f"[MEETING] High-conf match: {cname} ({conf:.0%}) — auto-attributing")
                                _apply_client_switch(cid, cname, source="meeting_detector")
                                # Passive toast
                                if notif_manager:
                                    try:
                                        notif_manager.notify_meeting_attributed(cname, state.title)
                                    except Exception:
                                        pass
                            elif conf >= 0.45 and cid:
                                log(f"[MEETING] Medium-conf match: {cname} ({conf:.0%}) — nudging")
                                if notif_manager:
                                    try:
                                        notif_manager.notify_meeting_confirm(cid, cname, state.title)
                                    except Exception:
                                        pass
                            else:
                                log(f"[MEETING] Low-conf match — leaving unattributed")
                    except Exception as e:
                        log(f"[MEETING] Classification error: {e}")

            def _on_meeting_end(state):
                """Fired when a meeting ends.

                If the meeting never got a client attribution, prompt the user now.
                """
                dur = int(state.ended_at - state.started_at) if state.started_at else 0
                log(f"[MEETING] Ended: {state.app} ({dur}s)")

                # If no client was attributed during the meeting, prompt now
                current_cid, _ = _get_cached_client()
                needs_attribution = not current_cid
                if needs_attribution and notif_manager:
                    try:
                        notif_manager.notify_meeting_needs_client(
                            meeting_title=state.title,
                            meeting_app=state.app,
                            duration_seconds=dur,
                        )
                    except Exception as e:
                        log(f"[MEETING] Needs-attribution prompt failed: {e}")

            meeting_detector = MeetingDetector(
                on_meeting_start=_on_meeting_start,
                on_meeting_end=_on_meeting_end,
                context_bus=_CONTEXT,
                get_foreground_title=_get_fg_title,
                enabled=True,
            )
            meeting_detector.start()
            log("[MEETING] ✅ Detector initialized")
        except Exception as e:
            log(f"[MEETING] Failed to initialize: {e}")
            import traceback
            traceback.print_exc()
    else:
        log("[MEETING] Module not available — meeting capture disabled")
                        

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
    
    key = config.get("api_key") or API_KEY
    # ── MDM/Intune org token claim ──
    if not key:
        org_token = config.get("org_token")
        if org_token:
            from mdm_deploy import do_org_token_claim
            key = do_org_token_claim(config, save_config, API_BASE, APP_VERSION)
            if key:
                API_KEY = key
                log("[MDM] ✅ Device claimed via org token")
            else:
                log("[MDM] ⚠️ Org token claim failed — falling back to manual pairing")
    if not key:
        gui_launched = False
        
        # If frozen exe, look for TimeTracker.exe (GUI) in same directory
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            gui_exe = os.path.join(exe_dir, "TimeTracker.exe")
            if os.path.exists(gui_exe):
                print(f"[AGENT] No API key - launching GUI: {gui_exe}")
                try:
                    subprocess.Popen([gui_exe])
                    gui_launched = True
                except Exception as e:
                    print(f"[AGENT] Failed to launch GUI exe: {e}")
        
        # Dev mode: look for gui.py
        if not gui_launched:
            gui_script = os.path.join(os.path.dirname(__file__), "gui.py")
            if os.path.exists(gui_script):
                print(f"[AGENT] No API key - launching GUI script: {gui_script}")
                try:
                    subprocess.Popen([sys.executable, gui_script])
                    gui_launched = True
                except Exception as e:
                    print(f"[AGENT] Failed to launch GUI script: {e}")
        
        if gui_launched:
            print("[AGENT] Please pair your device in the GUI window, then restart the agent.")
            remove_pid()
            return
        
        # Fallback to console pairing
        key = ensure_api_key_interactive(hostname)
        if not key:
            print("Exiting: no device key configured.")
            remove_pid()
            return
    
    if not hello(HELLO_URL, os_user, hostname, device_id):
        log("[HELLO] First hello failed - retrying with backoff...")
        hello_success = False
        for attempt in range(10):  # Up to ~5 minutes
            wait = min(10 * (attempt + 1), 60)  # 10s, 20s, 30s... max 60s
            log(f"[HELLO] Retry {attempt + 1}/10 in {wait}s...")
            time.sleep(wait)
            if hello(HELLO_URL, os_user, hostname, device_id):
                hello_success = True
                log("[HELLO] ✅ Connected on retry")
                break
        
        if not hello_success:
            log("[HELLO] ⚠️ Server unreachable - running offline, will retry on next event post")
            # DON'T drop the key. DON'T exit. Just keep running.
            # The key is valid - the server is just down.
    
    # Pass user name to GUI
    if gui_menu_bar and SERVER_USER_NAME:
        gui_menu_bar.user_name = SERVER_USER_NAME
        log(f"[GUI] Set user name: {SERVER_USER_NAME}")
    
    if gui_menu_bar:
    # Seed client cache from backend (so write_event has it from the first event)
        api_key = config.get("api_key") or API_KEY
        if api_key and API_BASE:
            try:
                current = get_current_client_from_backend(API_BASE, api_key)
                if current is not None:
                    _set_cached_client(current.get("client_id"), current.get("client_name"))
                    log(f"[CLIENT-CACHE] Seeded: {current.get('client_name')}")
            except Exception as e:
                log(f"[CLIENT-CACHE] Seed failed: {e}")

    # Prompt client selection shortly after startup if no client set
    def _prompt_client_after_startup():
        try:
            # ── Skip prompt on auto-update / restart ──
            # Only show the startup picker on FIRST EVER launch (no config yet).
            # On every subsequent start (including auto-update restarts), users
            # already know about the app and don't need an interruption — the
            # floating widget's red "no client" dot is enough of a passive hint.
            config_path = os.path.expanduser("~/.timetracker/config.json")
            widget_state_path = os.path.expanduser("~/.timetracker/widget_state.json")
            if os.path.exists(config_path) or os.path.exists(widget_state_path):
                log("[AGENT] Existing install detected - skipping startup picker prompt")
                return

            # First-ever launch: wait a moment for sync to finish, then prompt.
            time.sleep(15)

            api_key_val = config.get("api_key")
            if not api_key_val:
                log("[AGENT] No API key yet - skipping startup client prompt")
                return
            current = get_current_client_from_backend(API_BASE, api_key_val)
            if not current or not current.get("client_id"):
                log("[AGENT] No client selected after first launch - prompting picker")
                if gui_menu_bar:
                    gui_menu_bar._show_client_picker()
        except Exception as e:
            log(f"[AGENT] Startup client check failed: {e}")

    threading.Thread(target=_prompt_client_after_startup, daemon=True).start()

    
    # === SLEEP/WAKE RECOVERY ===
    register_power_notifications(os_user, hostname, device_id)

    # === AUTO-START ON LOGON ===
    register_startup_task()

    # === EXTERNAL WATCHDOG TASK ===
    try:
        from tt_watchdog import register_watchdog_task
        register_watchdog_task()
    except Exception as e:
        log(f"[WATCHDOG-TASK] Failed to register: {e}")

    # === DIRECT LAUNCH — no GPO/task registration needed ===
    def _start_external_watchdog():
        try:
            if not getattr(sys, 'frozen', False):
                return
            watchdog_exe = os.path.join(
                os.path.dirname(sys.executable),
                "tt_watchdog.exe"
            )
            if not os.path.exists(watchdog_exe):
                log(f"[WATCHDOG-EXT] ⚠️ Not found: {watchdog_exe}")
                return
            for proc in psutil.process_iter(["name"]):
                try:
                    if "tt_watchdog" in (proc.info["name"] or "").lower():
                        log("[WATCHDOG-EXT] ✅ Already running")
                        return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            subprocess.Popen(
                [watchdog_exe],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            log("[WATCHDOG-EXT] ✅ Launched tt_watchdog.exe")
        except Exception as e:
            log(f"[WATCHDOG-EXT] Failed: {e}")

    _start_external_watchdog()

    # === TRACKING LOOP WITH ERROR HANDLING ===
    def tracking_loop():
        global _last_subscription_check, _subscription_active, _idle_entered_at, _idle_reading_unchanged_since
        log("[TRACKING] Initializing...")
        _last_idle_reading = 0.0
        _last_idle_reading_time = 0.0

        # At the very top of tracking_loop(), before the while True:
        if not hasattr(tracking_loop, '_running'):
            tracking_loop._running = True
        else:
            log("[TRACKING] ⚠️ Duplicate tracking loop detected — aborting this instance")
            return
                
        try:
            conn = ensure_db()
            cur = conn.cursor()
        except Exception as e:
            log_error(f"[TRACKING] ❌ Failed to init DB: {e}")
            report_error_to_backend("tracking_init", str(e), traceback.format_exc())
            return
        
        current_sig = None
        dwell_start = None
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10

        # ── FIX 1: Lock screen process names that trigger instant idle ──
        LOCK_SCREEN_APPS = {"lockapp", "logonui"}
        
        try:
            while True:
                try:
                    heartbeat_touch()   # ← add this
                    progress_tick()

                    # ── Drain meeting detector events every tick ──
                    # Runs regardless of idle/meeting/focus state. Events carry
                    # their own timestamps (state.started_at / state.ended_at) so
                    # they're correct even if drained a few seconds after the
                    # actual start/end.
                    if meeting_detector:
                        for kind, state in meeting_detector.drain_events():
                            if kind == "start":
                                sig = _meeting_sig(state.app, state.title)
                                try:
                                    write_event(conn, cur, os_user, hostname, sig,
                                               ts_override=state.started_at)
                                    log(f"[MEETING] Wrote START event: {sig[0]} / {sig[2]}")
                                except Exception as e:
                                    log(f"[MEETING] Failed to write start event: {e}")
                            elif kind == "end":
                                sig = ("Meeting-End", f"meeting:{state.app}",
                                       state.title or "", None, None)
                                try:
                                    write_event(conn, cur, os_user, hostname, sig,
                                               ts_override=state.ended_at)
                                    log(f"[MEETING] Wrote END event")
                                except Exception as e:
                                    log(f"[MEETING] Failed to write end event: {e}")

                    # ── IDLE WATCHDOG: force-exit idle if stuck > 30 min ──────────
                    # GetLastInputInfo returns stale values on some machines after
                    # screen lock or sleep (Wendy/Terri pattern). If we've been in
                    # idle longer than _IDLE_WATCHDOG_MAX_MINUTES wall-clock minutes,
                    # assume the counter is corrupted and force-exit idle state.
                    if current_sig == IDLE_SIG and _idle_entered_at > 0:
                        wall_idle_minutes = (time.time() - _idle_entered_at) / 60.0

                        # ── Stale counter detection ──
                        # If mouse_idle_seconds() returns the same value for >60s,
                        # GetLastInputInfo is frozen — force-reset immediately
                        current_idle_reading = mouse_idle_seconds()
                        now_t = time.time()

                        if abs(current_idle_reading - _last_idle_reading) < 0.5:
                            # Reading hasn't changed
                            if _idle_reading_unchanged_since == 0.0:
                                _idle_reading_unchanged_since = now_t
                            elif (now_t - _idle_reading_unchanged_since) > 60:  # Frozen for 60s
                                log(f"[IDLE-WD] ⚠️ GetLastInputInfo frozen at {current_idle_reading:.0f}s "
                                    f"for {(now_t - _idle_reading_unchanged_since):.0f}s — force-resetting")
                                report_error_to_backend(
                                    "idle_stuck_frozen",
                                    f"GetLastInputInfo frozen at {current_idle_reading:.0f}s",
                                    context={"frozen_seconds": now_t - _idle_reading_unchanged_since,
                                             "hostname": hostname}
                                )
                                if dwell_start:
                                    dwell = now_t - dwell_start
                                    if dwell >= MIN_DWELL_SECONDS:
                                        write_event(conn, cur, os_user, hostname, IDLE_SIG,
                                                    ts_override=dwell_start)
                                current_sig = None
                                dwell_start = None
                                _idle_entered_at = 0.0
                                _idle_reading_unchanged_since = 0.0
                                record_idle_exit()
                                continue
                        else:
                            # Reading is changing — legitimate idle, reset staleness timer
                            _idle_reading_unchanged_since = 0.0

                        _last_idle_reading = current_idle_reading
                        _last_idle_reading_time = now_t

                        # ── Wall clock safety net (catches any other freeze scenario) ──
                        if wall_idle_minutes > _IDLE_WATCHDOG_MAX_MINUTES:
                            log(f"[IDLE-WD] ⚠️ Idle watchdog triggered — stuck {wall_idle_minutes:.1f} min")
                            report_error_to_backend(
                                "idle_stuck",
                                f"Idle stuck {wall_idle_minutes:.1f} min",
                                context={"wall_idle_minutes": wall_idle_minutes, "hostname": hostname}
                            )
                            if dwell_start:
                                dwell = now_t - dwell_start
                                if dwell >= MIN_DWELL_SECONDS:
                                    write_event(conn, cur, os_user, hostname, IDLE_SIG,
                                                ts_override=dwell_start)
                            current_sig = None
                            dwell_start = None
                            _idle_entered_at = 0.0
                            _idle_reading_unchanged_since = 0.0
                            record_idle_exit()
                            continue

                     # === SUBSCRIPTION CHECK ===
                    if not _subscription_active:
                        now = time.time()
                        if now - _last_subscription_check < _subscription_check_interval:
                            time.sleep(30)
                            continue
                        _last_subscription_check = now
                        try:
                            hello(HELLO_URL, os_user, hostname, device_id)
                            _subscription_active = True
                            log("[SUB] ✅ Subscription reactivated — resuming tracking")
                        except urllib.error.HTTPError as e:
                            if e.code == 403:
                                log("[SUB] Still inactive — checking again in 30 min")
                            time.sleep(30)
                            continue
                        except:
                            time.sleep(30)
                            continue
                    # ── WAKE RECOVERY: Reset tracking state after sleep/wake ──
                    # ── SUSPEND RECOVERY: Detect time gaps (Modern Standby + real sleep) ──
                    if not hasattr(tracking_loop, '_last_iter_time'):
                        tracking_loop._last_iter_time = time.time()
                    
                    now_t = time.time()
                    iter_gap = now_t - tracking_loop._last_iter_time
                    tracking_loop._last_iter_time = now_t
                    
                    # If >60s passed between iterations, thread was frozen
                    _suspended = iter_gap > 60
                    
                    if _wake_event.is_set() or _suspended:
                        _wake_event.clear()
                        
                        if _suspended:
                            log(f"[TRACKING] ⏰ Thread was suspended for {int(iter_gap)}s (Modern Standby or sleep)")
                        else:
                            log("[TRACKING] 🔄 Wake event detected — resetting tracking state")
                        
                        # Flush current dwell if any
                        if current_sig and dwell_start and current_sig != IDLE_SIG:
                            dwell = now_t - dwell_start
                            if dwell >= MIN_DWELL_SECONDS:
                                try:
                                    write_event(conn, cur, os_user, hostname, current_sig)
                                    log(f"[TRACKING] Flushed pre-suspend dwell ({int(dwell)}s)")
                                except Exception as e:
                                    log(f"[TRACKING] Failed to flush dwell: {e}")
                        
                        # Reset state completely
                        current_sig = None
                        dwell_start = None
                        
                        # Brief wait for network (don't block long)
                        for _i in range(6):  # Up to 15s
                            if is_network_ok():
                                break
                            time.sleep(2.5)
                        
                        if is_network_ok():
                            log("[TRACKING] ✅ Network OK — resuming capture")
                        else:
                            log("[TRACKING] ⚠️ Network still down — resuming in offline mode")
                            _start_health_monitor()
                        
                        continue
                        
                    if check_control_commands(CONTROL_URL, os_user, hostname):
                        log("[CTRL] Stopping agent per admin request.")
                        break
                    
                    idle = mouse_idle_seconds()

                    # ── FIX 2: Peek at foreground BEFORE idle check ──
                    # If the lock screen is active, force immediate idle
                    # regardless of mouse idle timer
                    force_idle = False
                    front_peek = get_foreground_window_info()
                    if front_peek:
                        peek_app, peek_exe, peek_pid, peek_title = front_peek
                        if (peek_app and peek_app.lower() in LOCK_SCREEN_APPS) or \
                           (peek_title and "lock screen" in peek_title.lower()):
                            force_idle = True
                            if current_sig != IDLE_SIG:
                                log(f"[IDLE] Lock screen detected ({peek_app}) → entering idle immediately")


                    # === MEETING IDLE SUPPRESSION ===
                    # If we're in a meeting, mouse idle is EXPECTED (people listen,
                    # don't move their mouse). Suppress the idle watchdog so the
                    # foreground dwell keeps accumulating and the parallel Meeting
                    # block forms independently.
                    in_meeting = False
                    if meeting_detector and meeting_detector.is_active():
                        in_meeting = True
                        if idle >= MOUSE_IDLE_PAUSE_S and current_sig != IDLE_SIG:
                            # Log once per minute to avoid spam
                            _now = time.time()
                            if not hasattr(tracking_loop, '_last_meeting_idle_log'):
                                tracking_loop._last_meeting_idle_log = 0.0
                            if _now - tracking_loop._last_meeting_idle_log > 60:
                                log(f"[MEETING] Suppressing idle (mouse idle {int(idle)}s, but in meeting)")
                                tracking_loop._last_meeting_idle_log = _now

                    if in_meeting:
                        # Continue normal foreground capture — meeting runs in parallel
                        # Fall through to the foreground-capture path below, skipping idle
                        front = front_peek
                        if front:
                            app_name, exe_name, pid, window_title = front
                            window_title = normalize_window_title(window_title or "")
                            extras = try_get_url_or_path(exe_name, window_title)
                            url, fpath = extras.get("url"), extras.get("file_path")
                            sig = (app_name, exe_name, window_title, url, fpath)

                            if sig != current_sig:
                                if current_sig and current_sig != IDLE_SIG and dwell_start:
                                    dwell = time.time() - dwell_start
                                    if dwell >= MIN_DWELL_SECONDS:
                                        write_event(conn, cur, os_user, hostname, current_sig)
                                current_sig = sig
                                dwell_start = time.time()
                                record_window_change()
                                if ai_switcher:
                                    ai_switcher.on_window_change(app_name, exe_name, window_title, url, fpath)
                                # Update widget state tracker with the same signal.
                                # State stored on gui_menu_bar.state.current_widget_state;
                                # the floating widget polls it every 2s.
                                if widget_tracker and gui_menu_bar and hasattr(gui_menu_bar, 'state'):
                                    cur_id, cur_name = _get_cached_client()
                                    # Get aliases for current client from AI switcher's loaded list
                                    cur_aliases = []
                                    if ai_switcher and cur_id and hasattr(ai_switcher, '_client_map'):
                                        client_data = ai_switcher._client_map.get(cur_id)
                                        if client_data:
                                            cur_aliases = client_data.get('aliases') or []
                                    new_state = widget_tracker.on_window_change(
                                        window_title, fpath, url, cur_name, cur_aliases
                                    )
                                    if new_state != getattr(gui_menu_bar.state, 'current_widget_state', None):
                                        log(f"[WIDGET-STATE] {new_state} client={cur_name}")
                                    gui_menu_bar.state.current_widget_state = new_state

                            if ai_switcher:
                                ai_switcher.on_dwell_tick()
                            # Periodic time-based demotion for the widget
                            if widget_tracker and gui_menu_bar and hasattr(gui_menu_bar, 'state'):
                                new_state = widget_tracker.tick()
                                if new_state != getattr(gui_menu_bar.state, 'current_widget_state', None):
                                    log(f"[WIDGET-STATE] {new_state} (timer demotion)")
                                gui_menu_bar.state.current_widget_state = new_state

                        time.sleep(POLL_SECONDS)
                        consecutive_errors = 0
                        continue

                    # === END MEETING IDLE SUPPRESSION ===

                    if force_idle or idle >= MOUSE_IDLE_PAUSE_S:
                        if current_sig != IDLE_SIG:
                            if notif_manager:
                                try:
                                    notif_manager.on_idle_start()
                                except Exception as e:
                                    log(f"[TRACKING] notif on_idle_start error: {e}", "warning")
                            
                            if current_sig and dwell_start:
                                now = time.time()
                                if force_idle:
                                    effective_end = now
                                else:
                                    effective_end = now - max(0.0, idle - MOUSE_IDLE_PAUSE_S)
                                dwell = effective_end - dwell_start
                                if dwell >= MIN_DWELL_SECONDS:
                                    write_event(conn, cur, os_user, hostname, current_sig)
                            current_sig = IDLE_SIG
                            _idle_entered_at = time.time()  # ← ADD THIS
                            record_idle_enter()
                            verdict = classify_idle(idle, MOUSE_IDLE_PAUSE_S)
                            if verdict.kind == IdleKind.UNINTENTIONAL:
                                log(f"[IDLE] ⚠️ Unintentional idle detected — {verdict.reason} "
                                    f"(confidence={verdict.confidence:.0%})")
                                # Don't record this idle block; just reset state and continue
                                current_sig = None
                                dwell_start = None
                                _idle_entered_at = 0.0
                                record_idle_exit()
                                continue
                            else:
                                log(f"[IDLE] Intentional idle — {verdict.reason}")
                                # Fall through to normal idle handling
                            if force_idle:
                                dwell_start = time.time()
                            else:
                                dwell_start = time.time() - min(idle, MOUSE_IDLE_PAUSE_S)
                            if not force_idle:
                                log(f"[IDLE] Entered idle (mouse idle {int(idle)}s ≥ {MOUSE_IDLE_PAUSE_S}s)")

                        # ── IDLE WATCHDOG: detect stuck idle ──
                        # If we've been in idle state longer than IDLE_STUCK_CHECK_SECONDS
                        # but GetLastInputInfo says user is active, force exit idle
                        if current_sig == IDLE_SIG and dwell_start:
                            idle_duration = time.time() - dwell_start

                            # Max idle cap — never idle longer than 2 hours
                            if idle_duration > MAX_IDLE_SECONDS:
                                log(f"[IDLE] ⚠️ Max idle cap reached ({int(idle_duration)}s) — force resetting")
                                write_event(conn, cur, os_user, hostname, current_sig, ts_override=dwell_start)
                                current_sig = None
                                dwell_start = None
                                _idle_entered_at = 0.0
                                record_idle_exit()
                                continue

                            # Stuck idle check — re-read idle timer fresh
                            if idle_duration > IDLE_STUCK_CHECK_SECONDS:
                                fresh_idle = mouse_idle_seconds()
                                if fresh_idle < MOUSE_IDLE_PAUSE_S:
                                    log(f"[IDLE] ⚠️ Stuck idle detected — fresh idle={int(fresh_idle)}s, forcing exit")
                                    dwell = time.time() - dwell_start
                                    if dwell >= MIN_DWELL_SECONDS:
                                        write_event(conn, cur, os_user, hostname, current_sig, ts_override=dwell_start)
                                    current_sig = None
                                    dwell_start = None
                                    _idle_entered_at = 0.0  # ← ADD THIS
                                    record_idle_exit()
                                    continue
                                else:
                                    _now = time.time()
                                    if not hasattr(tracking_loop, '_last_idle_log') or _now - tracking_loop._last_idle_log > 60:
                                        log(f"[IDLE] Still genuinely idle after {int(idle_duration)}s (fresh={int(fresh_idle)}s)")
                                        tracking_loop._last_idle_log = _now
                                    if idle_duration > (_IDLE_WATCHDOG_MAX_MINUTES * 60):
                                        log(f"[IDLE-WD] ⚠️ Wall clock cap hit — force-flushing idle dwell")
                                        write_event(conn, cur, os_user, hostname, IDLE_SIG, ts_override=dwell_start)
                                        current_sig = None
                                        dwell_start = None
                                        _idle_entered_at = 0.0
                                        _idle_reading_unchanged_since = 0.0
                                        record_idle_exit()
                                        continue

                        if force_idle:
                            time.sleep(POLL_SECONDS * 3)
                        else:
                            time.sleep(POLL_SECONDS)
                        consecutive_errors = 0
                        continue

                    else:
                        if current_sig == IDLE_SIG and dwell_start:
                            if notif_manager:
                                try:
                                    notif_manager.on_idle_end()
                                except Exception as e:
                                    log(f"[TRACKING] notif on_idle_end error: {e}", "warning")
                            
                            dwell = time.time() - dwell_start
                            if dwell >= MIN_DWELL_SECONDS:
                                write_event(conn, cur, os_user, hostname, current_sig, ts_override=dwell_start)
                                log(f"[IDLE] Exited idle; recorded {int(dwell)}s idle dwell.")
                            else:
                                log(f"[IDLE] Exited idle; too short ({int(dwell)}s) → not recorded.")
                            current_sig = None
                            dwell_start = None
                            _idle_entered_at = 0.0  # ← ADD THIS
                            record_idle_exit()


                            # ── FIX 4: After waking from idle, re-peek foreground ──
                            # Use the front_peek we already grabbed above
                            # instead of calling get_foreground_window_info() again


                        # Reuse the peek we already did (avoid double call)
                        front = front_peek
                        if not front:
                            # Log periodically so we can diagnose silent failures
                            _now = time.time()
                            if not hasattr(tracking_loop, '_last_no_front_log'):
                                tracking_loop._last_no_front_log = 0.0
                            if _now - tracking_loop._last_no_front_log > 60:
                                log("[TRACKING] ⚠️ No foreground window detected (win32 may need reset after sleep)")
                                tracking_loop._last_no_front_log = _now
                            time.sleep(POLL_SECONDS)
                            consecutive_errors = 0
                            continue
                        
                        app_name, exe_name, pid, window_title = front
                        window_title = normalize_window_title(window_title or "")

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
                            record_window_change()
                            
                            # >>> ADD THIS: Feed focus change to AI switcher
                            # >>> ADD THIS: Feed focus change to AI switcher
                            if ai_switcher:
                                ai_switcher.on_window_change(app_name, exe_name, window_title, url, fpath)
                            # Update widget state tracker with the same signal
                            if widget_tracker and gui_menu_bar and hasattr(gui_menu_bar, 'state'):
                                cur_id, cur_name = _get_cached_client()
                                new_state = widget_tracker.on_window_change(
                                    window_title, fpath, url, cur_name, []
                                )
                                if new_state != getattr(gui_menu_bar.state, 'current_widget_state', None):
                                    log(f"[WIDGET-STATE] {new_state} client={cur_name}")
                                gui_menu_bar.state.current_widget_state = new_state

                        # >>> ADD THIS: Check pending dwell switches every tick
                        if ai_switcher:
                            ai_switcher.on_dwell_tick()
                        # Periodic time-based demotion for the widget
                        if widget_tracker and gui_menu_bar and hasattr(gui_menu_bar, 'state'):
                            new_state = widget_tracker.tick()
                            if new_state != getattr(gui_menu_bar.state, 'current_widget_state', None):
                                log(f"[WIDGET-STATE] {new_state} (timer demotion)")
                            gui_menu_bar.state.current_widget_state = new_state

                        time.sleep(POLL_SECONDS)
                        consecutive_errors = 0

                except Exception as e:
                    consecutive_errors += 1
                    error_context = {
                        "current_sig": str(current_sig) if current_sig else None,
                        "dwell_start": dwell_start,
                        "consecutive_errors": consecutive_errors,
                    }
                    
                    log_error(f"[TRACKING] ⚠️ Error in loop iteration ({consecutive_errors}): {e}")
                    tb = traceback.format_exc()
                    traceback.print_exc()
                    
                    report_error_to_backend("tracking_loop", str(e), tb, error_context)
                    
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        log_error(f"[TRACKING] ❌ Too many consecutive errors ({consecutive_errors}), pausing 60s")
                        report_error_to_backend("tracking_loop_critical", 
                                               f"Too many errors: {consecutive_errors}", tb, error_context)
                        time.sleep(60)
                        consecutive_errors = 0
                    else:
                        time.sleep(POLL_SECONDS)
                    continue
        
        except KeyboardInterrupt:
            log("=== Stopping (Ctrl+C) ===")
            if current_sig and dwell_start:
                dwell = time.time() - dwell_start
                if dwell >= MIN_DWELL_SECONDS:
                    write_event(conn, cur, os_user, hostname, current_sig)
        except Exception as e:
            log_error(f"[TRACKING] ❌ Fatal error: {e}")
            tb = traceback.format_exc()
            traceback.print_exc()
            report_error_to_backend("tracking_fatal", str(e), tb)
        finally:
            log("[TRACKING] Cleaning up...")
            conn.close()
            remove_pid()
            if notif_worker:
                notif_worker.stop()

    # === START TRACKING THREAD ===
    tracking_thread = threading.Thread(target=tracking_loop, daemon=False)
    tracking_thread.start()
    log("[TRACKING] Started tracking thread")

    # === RE-CHECK FOR UPDATES EVERY HOUR ===
    start_background_checker(API_BASE, APP_VERSION)
    
    # === WATCHDOG: Restart process if tracking freezes OR dies ===
    _thread_ref = [tracking_thread]
    watchdog_thread = threading.Thread(
        target=_watchdog,
        args=(_thread_ref, tracking_loop, log, report_error_to_backend),
        daemon=True,
    )
    watchdog_thread.start()

    # === START LOG SHIPPING ===
    start_log_shipping(interval_minutes=30)
    
    # Run GUI if available
    if gui_menu_bar and GUI_AVAILABLE:
        log("[GUI] Starting GUI event loop...")
        try:
            gui_menu_bar.run()
        except KeyboardInterrupt:
            log("[GUI] Interrupted")
    else:
        log("[TRACKING] No GUI, waiting for tracking thread...")
        try:
            tracking_thread.join()
        except KeyboardInterrupt:
            log("[TRACKING] Interrupted")
    
    # === CLEANUP ON EXIT ===
    log("[AGENT] Shutting down...")
    
    # Stop sync thread
    if sync:
        try:
            sync.stop()
            log("[SYNC] Stopped")
        except Exception as e:
            log(f"[SYNC] Error stopping: {e}")

    # Stop meeting detector
    if meeting_detector:
        try:
            meeting_detector.stop()
            log("[MEETING] Stopped")
        except Exception as e:
            log(f"[MEETING] Error stopping: {e}")

    # Stop explorer watcher
    if explorer_watcher:
        try:
            explorer_watcher.stop()
            log("[EXPLORER] Stopped")
        except Exception as e:
            log(f"[EXPLORER] Error stopping: {e}")
    
    # Stop notification worker
    if notif_worker:
        try:
            notif_worker.stop()
            log("[NOTIF] Stopped")
        except Exception as e:
            log(f"[NOTIF] Error stopping: {e}")
    
    # Stop hotkey listener (only matters if keyboard lib fallback was used)
    try:
        import keyboard
        keyboard.unhook_all()
    except Exception:
        pass
    
    # Remove PID file
    remove_pid()
    
    log("[AGENT] Shutdown complete")
    
    # Force exit to kill any remaining threads
    os._exit(0)

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
    # ── Single instance lock — named mutex (Windows-standard) ──
    if sys.platform == 'win32':
        import ctypes
        global _lock_mutex

        # Try Global mutex first (works across all sessions on machine)
        _lock_mutex = ctypes.windll.kernel32.CreateMutexW(
            None, True, "Global\\TimeTrackerAgent_MavOps"
        )
        last_error = ctypes.windll.kernel32.GetLastError()

        # Fallback to session-local mutex if Global fails
        # (some domain machines restrict SeCreateGlobalPrivilege)
        if not _lock_mutex:
            _lock_mutex = ctypes.windll.kernel32.CreateMutexW(
                None, True, "TimeTrackerAgent_MavOps"
            )
            last_error = ctypes.windll.kernel32.GetLastError()

        if last_error == 183:  # ERROR_ALREADY_EXISTS
            print("[AGENT] Another instance is already running — exiting.")
            ctypes.windll.kernel32.CloseHandle(_lock_mutex)
            _lock_mutex = None
            sys.exit(0)

        if not _lock_mutex:
            print("[AGENT] ⚠️ Failed to create mutex — proceeding without lock")


    # Handle uninstaller flag FIRST before anything else
    if "--unregister-task" in sys.argv:
        from startup_task import unregister_startup_task
        from tt_watchdog import unregister_watchdog_task
        unregister_startup_task()
        unregister_watchdog_task()
        sys.exit(0)

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