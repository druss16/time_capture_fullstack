#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mac Activity Agent with device pairing:

- One-time "pair" to exchange a short code for a persistent device api_key
- Authorization: DeviceKey <api_key> on every POST/GET
- /api/agents/hello2/ heartbeat auto-provisions user/device
- PID file + context bus + admin kill-switch
- GUI-based pairing when available
"""

import multiprocessing
import sys

# CRITICAL: Must be first for PyInstaller frozen apps
if __name__ == '__main__':
    multiprocessing.freeze_support()

# Check if this is a multiprocessing child - if so, let it run without CLI parsing
# NEW (works with all start methods)
_is_multiprocessing_child = multiprocessing.parent_process() is not None

import os
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

# CRITICAL: Set activation policy BEFORE any GUI imports


from urllib.parse import urlparse
from timetracker_gui import run_gui_app, show_pairing_window, GUI_AVAILABLE
import urllib.request
import urllib.error

from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListOptionOnScreenAboveWindow,
    kCGNullWindowID,
    CGEventSourceSecondsSinceLastEventType,
    kCGEventSourceStateCombinedSessionState,
    kCGEventMouseMoved,
    kCGEventKeyDown,
    kCGEventScrollWheel,
)

from quick_switcher import QuickSwitcher, start_hotkey_listener, stop_hotkey_listener

# Progress-based heartbeat + idle classification, shared with windows_agent.
# The watchdog's own heartbeat says the thread is alive; progress_tick() says
# it is actually getting somewhere. classify_idle() then separates a user who
# deliberately stopped from a loop that froze or a machine that slept — the
# second kind is not a real absence and should not be billed as one.
try:
    from tracking_health import (
        progress_tick,
        record_window_change,
        record_idle_enter,
        record_idle_exit,
        record_wake_event,
        classify_idle,
        IdleKind,
    )
    _TRACKING_HEALTH = True
except Exception as _th_err:  # pragma: no cover - import guard
    _TRACKING_HEALTH = False
    progress_tick = lambda: 0
    record_window_change = record_idle_enter = record_idle_exit = \
        record_wake_event = lambda: None
    classify_idle = None
    IdleKind = None
    print(f"[HEALTH] tracking_health unavailable: {_th_err}", flush=True)

import certifi
import ssl

os.environ['SSL_CERT_FILE'] = certifi.where()

import logging
from logging.handlers import RotatingFileHandler

# Notifications (PyObjC)
try:
    import objc
    from Foundation import NSObject, NSLog
    from UserNotifications import (
        UNUserNotificationCenter, UNMutableNotificationContent, UNNotificationRequest,
        UNNotificationAction, UNNotificationCategory, UNNotificationActionOptionForeground, UNNotificationSound
    )
    NOTIF_AVAILABLE = True
except Exception:
    NOTIF_AVAILABLE = False


# CORRECT - use print() at module level, or just delete it entirely
try:
    from ai_client_switcher import AIClientSwitcher
except ImportError:
    AIClientSwitcher = None
    print("[WARN] ai_client_switcher not found — disabled")

try:
    from mac_watchdog import heartbeat_touch, start_watchdog
    MAC_WATCHDOG_AVAILABLE = True
except ImportError:
    MAC_WATCHDOG_AVAILABLE = False
    print("[WARN] mac_watchdog not found — watchdog disabled")
    def heartbeat_touch():
        return time.time()

sync = None  # Global sync manager, initialized in run_agent()
notif_manager = None  # Global notification manager, initialized in run_agent()
ai_switcher = None          # ← ADD THIS

# ── v1.4.0 inference engine ──────────────────────────────────────────────
# Confidence-graded client inference. The structured result rides along on
# every outgoing RawEvent payload; the server-side classifier reads it via
# RawEvent.inference. Shared verbatim with windows_agent — the evidence
# collectors are pure Python and must reach the same verdict on both
# platforms, or the same firm gets different answers depending on whose
# desk the work happened at.
try:
    from inference import (
        WindowContext as _InferenceWindowContext,
        infer_client as _infer_client,
    )
    _INFERENCE_AVAILABLE = True
except Exception as _inference_import_err:  # pragma: no cover - import guard
    _INFERENCE_AVAILABLE = False
    _InferenceWindowContext = None
    _infer_client = None
    print(f"[INFERENCE] Module not available: {_inference_import_err}", flush=True)

try:
    from content_identity import content_identity as _content_identity
except Exception as _ci_import_err:  # pragma: no cover - import guard
    _content_identity = None
    print(f"[CONTENT-ID] Module not available: {_ci_import_err}", flush=True)

# Last computed inference result. The menu bar reads this (with decay
# applied) to show the live client + confidence.
_last_inference_lock = threading.Lock()
_last_inference: Optional[dict] = None  # InferenceResult.to_dict() shape


def _content_identity_safe(title: str, url: str, file_path: str) -> str:
    """content_identity() that can never take the event handler down with it.

    Returns the stable per-activity identity string ("file=varacchi 2024 1040",
    "qbo:customer=...") or "" when nothing is confident — the same contract as
    tracker/utils/content_identity.py on the server, which this mirrors.

    The server currently recomputes this in compaction and ignores what we
    send; it rides along for parity with windows_agent, so that the day the
    server starts trusting the agent's value, both agents already supply it.
    """
    if _content_identity is None:
        return ""
    try:
        return _content_identity(title, url, file_path) or ""
    except Exception as e:
        log(f"[CONTENT-ID] extraction failed: {e}", "warning")
        return ""


def _inference_clients():
    """The client list the engine reasons over, plus the Internal-Tax id."""
    clients = list(sync.clients) if sync and getattr(sync, "clients", None) else []
    internal_cid = None
    for c in clients:
        if (c.get("name") or "").strip().lower() == "internal - tax":
            internal_cid = c.get("id")
            break
    return clients, internal_cid


def _run_inference(app_name, bundle_id, title, url, fpath, when=None):
    """Run the engine for one window and publish the result to the cache.

    Returns the result dict (the payload's `inference` field). Returns {}
    when the engine is unavailable or blew up — inference is additive, and
    an event without it is still a usable event.

    MAC: the Windows agent passes app_name as exe_name, because on Windows
    app_name already IS the executable name. Here the bundle identifier is
    the stable handle, so that is what goes into exe_name — which is what
    the collectors' exe_family rules and the switcher both expect.
    """
    if not _INFERENCE_AVAILABLE:
        return {}

    from inference_cache import (
        get_manual_override as _get_override,
        update_inference_cache as _update_cache,
    )

    clients, internal_cid = _inference_clients()

    ctx = _InferenceWindowContext(
        title=title or "",
        app_name=app_name or "",
        exe_name=bundle_id or "",   # MAC: see docstring
        bundle_id=bundle_id,
        file_path=fpath,
        url=url,
        timestamp=when or datetime.now(timezone.utc),
        manual_override=_get_override(),
    )

    learned = None
    try:
        if ai_switcher is not None:
            learned = getattr(ai_switcher, "learned_rules", None)
    except Exception:
        learned = None

    result = _infer_client(
        ctx=ctx,
        clients=clients,
        learned_rules=learned,
        is_idle=False,
        firm_name_patterns=None,
        internal_client_id=internal_cid,
    )

    result_dict = result.to_dict()
    client_name = None
    if result.client_id is not None:
        client_name = next(
            (c.get("name") for c in clients if c.get("id") == result.client_id),
            None,
        )

    _update_cache(result_dict, client_name)

    global _last_inference
    with _last_inference_lock:
        _last_inference = {**result_dict, "client_name": client_name}

    return result_dict


def _compute_inference_for_event(app_name, bundle_id, title, url, fpath, when=None):
    """Inference on the event-emit path. Never raises."""
    try:
        return _run_inference(app_name, bundle_id, title, url, fpath, when)
    except Exception as e:
        log(f"[INFERENCE] compute failed: {e}", "warning")
        return {}


def _sync_ticker_to_inference():
    """Push the inference engine's verdict to the menu bar and local cache.

    The v1.4.0 architecture gutted AIClientSwitcher: on_window_change is a
    documented NO-OP and the inference engine decides everything per event.
    Windows kept its tray in step by reading the inference cache through
    widget_state_tracker. The Mac menu bar had no equivalent — it only ever
    updated from _apply_client_switch, which the switcher no longer calls —
    so the ticker read "None" forever while the EVENTS were being attributed
    correctly. The data was right and only the display was dead, which is the
    worst way to be wrong: it silently tells the user nothing is being
    tracked.

    Display only. No backend write: the event payload already carries the
    client, and posting on every window change would be a request per focus
    change for something the server already knows.
    """
    if not _INFERENCE_AVAILABLE:
        return
    try:
        from inference_cache import get_current_inference
        inf = get_current_inference()
    except Exception as e:
        log(f"[TICKER] inference read failed: {e}", "warning")
        return

    cid = (inf or {}).get("client_id")
    cname = (inf or {}).get("client_name")

    prev_id, _ = _get_cached_client()
    if cid == prev_id:
        return

    _set_cached_client(cid, cname)
    if notif_manager:
        try:
            notif_manager.set_current_client(cid, cname)
        except Exception:
            pass
    if gui_menu_bar and hasattr(gui_menu_bar, "state"):
        try:
            gui_menu_bar.state.set_client(cid, cname)
            app = getattr(gui_menu_bar, "app", None)
            if app is not None:
                app.title = f"⏱ {cname}" if cname else "⏱ None"
        except Exception as e:
            log(f"[TICKER] menu bar update failed: {e}", "warning")
    log(f"[TICKER] → {cname or 'None'} (client_id={cid})")


def _compute_window_inference_snapshot(app_name, bundle_id, title, url, fpath):
    """Inference at window-change time, so the menu bar reflects the new
    window within a poll instead of waiting for the next heartbeat (~60s).

    Deliberately duplicates the compute in the emit path: inference is cheap
    (~10ms) and both write the same cache, last write wins. The manual
    override survives because it is read back into the context each time.
    """
    try:
        _run_inference(app_name, bundle_id, title, url, fpath)
    except Exception as e:
        log(f"[INFERENCE] snapshot compute failed: {e}", "warning")

# ── Local client cache ────────────────────────────────────────────────────────
# Eliminates the HTTP round-trip in write_event() every 5 seconds.
# Updated by _apply_client_switch(). Safety-net backend refresh every 60s.
_cached_client_id: Optional[int] = None
_cached_client_name: Optional[str] = None
_cached_client_updated: float = 0.0
_CLIENT_CACHE_TTL = 60.0
_client_cache_lock = threading.Lock()


def _set_cached_client(client_id, client_name):
    global _cached_client_id, _cached_client_name, _cached_client_updated
    with _client_cache_lock:
        _cached_client_id = client_id
        _cached_client_name = client_name
        _cached_client_updated = time.time()


def _get_cached_client():
    global _cached_client_id, _cached_client_name, _cached_client_updated
    now = time.time()
    with _client_cache_lock:
        if (now - _cached_client_updated) < _CLIENT_CACHE_TTL:
            return _cached_client_id, _cached_client_name
    # Stale — refresh from backend
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
    with _client_cache_lock:
        return _cached_client_id, _cached_client_name



# Push notifications for client reminders
try:
    from notifications import (
        ClientNotificationManager,
        NotificationConfig,
        NotificationWorker,
        create_notification_system,
        NotificationType,

    )
    PUSH_NOTIF_AVAILABLE = True
except ImportError:
    PUSH_NOTIF_AVAILABLE = False
    print("[WARN] notifications.py not found - push notifications disabled")


# ---------------- Check Active Subscriptions ----------------
# Near top with other globals
_subscription_active = True
_subscription_check_interval = 1800  # Re-check every 30 min
_last_subscription_check = 0.0

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
    """Show macOS notification about inactive subscription.

    Silenced with the rest of them. This is the one worth naming: if the org's
    subscription lapses, tracking pauses and the only remaining signal is the
    "[SUB] Subscription inactive — agent paused" line in the log. Re-enable
    notifications (see notifications.py) to get the banner back.
    """
    # NOTIF_ENABLED is defined further down the module; this only runs at
    # call time, long after import.
    if NOTIF_AVAILABLE and NOTIF_ENABLED:
        try:
            content = UNMutableNotificationContent.alloc().init()
            content.setTitle_("TimeTracker - Subscription Inactive")
            content.setBody_(
                "Your organization's subscription is inactive. "
                "Time tracking has been paused. Contact your administrator to reactivate."
            )
            content.setSound_(UNNotificationSound.defaultSound())
            
            req_id = f"subscription-inactive-{int(time.time())}"
            request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                req_id, content, None
            )
            UNUserNotificationCenter.currentNotificationCenter().addNotificationRequest_withCompletionHandler_(
                request, None
            )
        except Exception as e:
            log(f"[SUB] Notification failed: {e}")
    # Fallback to AppleScript
    else:
        osa(f'display dialog "Your organization\'s TimeTracker subscription is inactive.\\n\\nContact your administrator to reactivate." with title "TimeTracker" buttons {{"OK"}} default button "OK"')

# ---------------- MDM Config ----------------
MDM_CONFIG_PATH_MAC = "/Library/Application Support/TimeTracker/config.plist"
MDM_CONFIG_PATH_WIN = r"C:\ProgramData\TimeTracker\config.json"

def get_mdm_config() -> Optional[dict]:
    """Load config from MDM-deployed file."""
    if sys.platform == 'darwin':
        config_path = MDM_CONFIG_PATH_MAC
        if os.path.exists(config_path):
            try:
                import plistlib
                with open(config_path, 'rb') as f:
                    mdm = plistlib.load(f)
                    log(f"[MDM] Loaded config from {config_path}")
                    return mdm
            except Exception as e:
                log(f"[MDM] Failed to load plist: {e}")
    elif sys.platform == 'win32':
        config_path = MDM_CONFIG_PATH_WIN
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    mdm = json.load(f)
                    log(f"[MDM] Loaded config from {config_path}")
                    return mdm
            except Exception as e:
                log(f"[MDM] Failed to load json: {e}")
    return None


# register_with_org_token() lived here. It posted to /agent/register/, which
# find-or-creates a user from the OS short name and mints an email like
# dan@yourfirm.local — a different identity namespace from the one the
# Windows agent pairs into, so one person on two machines became two users.
#
# It could not work in any case. The view raises TypeError on
# `user.groups.add(org)` (Organization is not a Group), and the key it
# returns lives in AgentRegistration, which AgentKeyAuthentication never
# consults — so even past the crash the key authenticates nothing.
#
# Replaced by mdm_deploy.do_org_token_claim, which walks the same
# auto-pair -> claim -> confirm-user endpoints the Windows agent uses.
# See mac_agent/PROVISIONING.md.

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

def _get(name, default=None, env=None):
    if name in config: return config[name]
    if env and os.getenv(env) is not None: return os.getenv(env)
    return default

API_BASE = (_get("api_base", os.getenv("AGENT_API_BASE")) or "http://localhost:7123/api").rstrip("/")
POST_URL    = _get("post_url", None) or f"{API_BASE}/raw-events/"
HELLO_URL   = _get("hello_url", None) or f"{API_BASE}/agents/hello2/"
CONTROL_URL = _get("control_url", None) or f"{API_BASE}/agent/control/"
PAIR_CLAIM  = _get("pair_claim_url", None) or f"{API_BASE}/agents/pair/claim/"

API_KEY           = _get("api_key", os.getenv("AGENT_API_KEY"))
try:
    from version import APP_VERSION as _BUILT_VERSION
    APP_VERSION = _BUILT_VERSION
except ImportError:
    APP_VERSION = _get("app_version", os.getenv("AGENT_APP_VERSION")) or "1.0.0"
DEVICE_ID_FILE    = _get("device_id_file", os.path.expanduser("~/.mavops_device_id"))

POLL_SECONDS      = int(_get("poll_seconds", _get("AGENT_POLL_SECONDS", 5, "AGENT_POLL_SECONDS")) or 5)
MIN_DWELL_SECONDS = int(_get("min_dwell_seconds", _get("AGENT_MIN_DWELL_SECONDS", 5, "AGENT_MIN_DWELL_SECONDS")) or 5)

# ── Heartbeat emission (parity with windows_agent, v1.3.38) ──────────────
# The agent used to emit ONE event when a dwell ended, stamped with a single
# ts_utc, and the server guessed the duration. It no longer guesses: every
# event carries the interval it actually covers, so a long dwell is emitted
# as a series of heartbeats rather than withheld until the user looks away.
#
# The server has required both stamps since v1.3.38 and returns 400 for an
# event carrying only ts_utc — there is no compatibility path.
HEARTBEAT_INTERVAL_S = int(_get("heartbeat_interval_seconds", 60))

# Meeting detection. The detector was written cross-platform in
# windows_agent and carries its own MacMeetingProbe (camera via lsof on
# VDCAssistant, audio via coreaudiod, both cross-referenced against the
# process table). The Mac agent had only is_in_meeting() — a title and URL
# test that answers "does this window look like a meeting", never "a meeting
# just started" — so meetings produced no blocks of their own.
try:
    from meeting_detector import MeetingDetector, MeetingState
    MEETING_DETECTOR_AVAILABLE = True
except Exception as _md_err:  # pragma: no cover - import guard
    MEETING_DETECTOR_AVAILABLE = False
    MeetingDetector = None
    MeetingState = None
    print(f"[MEETING] Module not available: {_md_err}", flush=True)


def _meeting_sig(meeting_app: str, title: str = None):
    """Build a window signature for a Meeting event.

    Matches the (app_name, bundle_id, window_title, url, file_path) tuple
    write_event expects. bundle_id uses the 'meeting:' prefix so the backend
    compactor recognises it as a meeting block.
    """
    return (
        "Meeting",
        f"meeting:{meeting_app}",
        title or f"{meeting_app.title()} meeting",
        None,
        None,
    )


# Hard ceiling on a single emitted event's duration. If the tracking loop
# stalls (sleep, network hang, a hung osascript) and recovers, we still want
# to emit sane intervals rather than one four-hour event. Anything longer is
# split into max_event_duration chunks.
MAX_EVENT_DURATION_S = int(_get("max_event_duration_seconds", 300))  # 5 min
VERBOSE           = bool(_get("verbose", os.getenv("AGENT_VERBOSE") == "1"))
PRINT_EVERY_POLL  = bool(_get("print_every", os.getenv("AGENT_PRINT_EVERY") == "1"))
DISABLE_AX        = bool(_get("disable_ax", os.getenv("AGENT_DISABLE_AX") == "1"))
# Filter blanks. "".split(",") is [""], so an unset AGENT_EXCLUDE_BUNDLES put
# the EMPTY STRING in this set — and the tracking loop excludes a window when
# `bundle_id in EXCLUDE_BUNDLES`. The SystemEvents detection path returns an
# empty bundle_id, so those windows were treated as excluded: the loop emitted
# the open dwell, CLEARED it, and skipped. Every second from there until the
# next app switch was silently dropped. Measured on a real machine: 5.4
# minutes captured out of 9.5 minutes of work, 43% gone before anything
# reached the server.
EXCLUDE_BUNDLES   = {
    b.strip() for b in (_get("exclude_bundles", os.getenv("AGENT_EXCLUDE_BUNDLES", "").split(",")) or [])
    if b and b.strip()
}
DB_PATH           = _get("db_path", os.getenv("MAC_AGENT_DB")) or DB_PATH_DEFAULT
CONTEXT_PORT      = int(_get("context_port", os.getenv("AGENT_CONTEXT_PORT")) or 7321)
CONTROL_POLL_S    = int(_get("agent_control_poll_seconds", 10))

EXCLUDE_BUNDLES.add("org.python.python")
EXCLUDE_BUNDLES.add("com.apple.python3")

_LAST_CLIENT_SUGGESTION = {}  # {client_id: timestamp} - prevent spam

# Add this global near the top of your file (after imports)
_DETECTION_STATS = {"system_events": 0, "nsworkspace": 0, "quartz": 0, "failed": 0}


PAIR_CODE = _get("pair_code", os.getenv("AGENT_PAIR_CODE"))

MOUSE_IDLE_PAUSE_S = int(_get("mouse_idle_pause_seconds", os.getenv("AGENT_MOUSE_IDLE_PAUSE_SECONDS") or 600))


# ── Camera/mic holds idle open ───────────────────────────────────────────────
# Talking is not input. A video consult with no typing looks exactly like an
# empty desk to the OS idle timer — which is how a 60-minute telehealth call
# became a 14-minute block. If a camera or microphone is open, the person is
# working, whatever the mouse says.
#
# This is separate from meeting detection on purpose. That asks "which meeting
# app, for which client" and is conservative — browser media without a known
# meeting title is dropped as playback, which is right for Spotify and wrong
# for a call on a site nobody whitelisted. Here a false negative silently
# destroys billable time, while a false positive inflates a block a human sees.
#
# Capped, because a device that is never released (a stuck tab, a dictation
# tool) would otherwise bill straight through the night.
CAPTURE_IDLE_SUPPRESS_MAX_S = int(_get("capture_idle_suppress_max_seconds", 7200))

_capture_suppress_since = 0.0
_capture_capped_logged = 0.0


def _capture_holds_idle_open(idle_s: float) -> bool:
    """True while a camera or mic is open and the suppression cap has room.

    Called every iteration, not only once the idle threshold is crossed: any
    input clears the cap timer, and a two-hour call with occasional typing
    must not arrive at its quiet stretches with the cap already spent. The
    device probe still only runs when idle, so an active user costs nothing.
    """
    global _capture_suppress_since, _capture_capped_logged

    if not MEDIA_CAPTURE_AVAILABLE:
        return False

    if idle_s < MOUSE_IDLE_PAUSE_S:
        _capture_suppress_since = 0.0
        return False

    state = capture_in_use()
    now = time.time()

    if not state.active:
        _capture_suppress_since = 0.0
        return False

    if not _capture_suppress_since:
        _capture_suppress_since = now
        log(f"[CAPTURE] {', '.join(state.devices) or 'device'} in use — "
            f"holding idle off (input quiet {int(idle_s)}s)")

    held = now - _capture_suppress_since
    if held > CAPTURE_IDLE_SUPPRESS_MAX_S:
        if now - _capture_capped_logged > 300:
            _capture_capped_logged = now
            log(f"[CAPTURE] Device held {int(held // 60)}m with no input — cap "
                f"reached, allowing idle ({', '.join(state.devices)})", "warning")
        return False

    return True
IDLE_SIG = ("Idle", "__idle__", "Idle/Uncategorized", None, None)
_wake_event = threading.Event()
_wake_idle_bypass_until = 0.0


NUDGE_ENABLED        = bool(_get("nudge_enabled", os.getenv("AGENT_NUDGE_ENABLED") == "1") or True)
GUESS_POLL_SECONDS   = int(_get("guess_poll_seconds", os.getenv("AGENT_GUESS_POLL_SECONDS") or 10))
GUESS_MIN_CONF       = float(_get("guess_min_conf", os.getenv("AGENT_GUESS_MIN_CONF") or 0.45))
GUESS_MAX_CONF       = float(_get("guess_max_conf", os.getenv("AGENT_GUESS_MAX_CONF") or 0.80))
NUDGE_SNOOZE_MIN     = int(_get("nudge_snooze_min", os.getenv("AGENT_NUDGE_SNOOZE_MIN") or 20))
NUDGE_TIMEOUT_SEC    = int(_get("nudge_timeout_sec", os.getenv("AGENT_NUDGE_TIMEOUT_SEC") or 15))
CONTEXT_GUESS_URL    = _get("context_guess_url", None) or f"{API_BASE}/context/guess"
CONTEXT_CONFIRM_URL  = _get("context_confirm_url", None) or f"{API_BASE}/context/confirm"
CONTEXT_REJECT_URL   = _get("context_reject_url", None) or f"{API_BASE}/context/reject"

# --- Tools vs Clients ---
TOOL_BUNDLES = set(
    [b.strip() for b in (_get("tool_bundles", os.getenv("AGENT_TOOL_BUNDLES")) or "").split(",") if b.strip()]
) or {
    "com.microsoft.VSCode", "com.microsoft.VSCodeInsiders",
    "com.jetbrains.pycharm", "com.jetbrains.intellij", "com.jetbrains.datagrip",
    "com.apple.dt.Xcode", "org.sublimetext.4",
    "com.googlecode.iterm2", "dev.warp.Warp-Stable", "net.kovidgoyal.kitty",
    "com.github.wez.wezterm", "org.alacritty", "com.apple.Terminal",
    "com.google.Chrome", "com.google.Chrome.canary", "com.google.Chrome.beta",
    "com.apple.Safari", "com.apple.SafariTechnologyPreview",
    "com.brave.Browser", "org.mozilla.firefox", "com.microsoft.edgemac",
    "com.apple.mail", "com.microsoft.Outlook",
    "com.tinyspeck.slackmacgap", "com.microsoft.teams2", "us.zoom.xos", "notion.id",
}

TOOL_HOSTS = set(
    [h.strip().lower() for h in (_get("tool_hosts", os.getenv("AGENT_TOOL_HOSTS")) or "").split(",") if h.strip()]
) or {
    "chatgpt.com", "openai.com", "localhost", "127.0.0.1",
    "github.com", "gitlab.com", "bitbucket.org",
    "stackoverflow.com", "vercel.app", "render.com"
}

# --- Meeting Apps ---
MEETING_BUNDLES = set(
    [b.strip() for b in (_get("meeting_bundles", os.getenv("AGENT_MEETING_BUNDLES")) or "").split(",") if b.strip()]
) or {
    "us.zoom.xos", "com.microsoft.teams", "com.microsoft.teams2",
    "com.google.Chrome", "com.apple.Safari", "com.brave.Browser", "org.mozilla.firefox",
    "com.cisco.webexmeetings", "com.ringcentral.rcapp", "com.skype.skype",
    "com.gotomeeting", "com.bluejeans.app",
}

MEETING_DOMAINS = {
    "zoom.us", "meet.google.com", "teams.microsoft.com", "teams.live.com",
    "webex.com", "gotomeeting.com", "bluejeans.com", "whereby.com", "around.co",
}

MEETING_KEYWORDS = {"zoom meeting", "teams meeting", "google meet", "webex meeting"}

# --- CPA-Specific Tools & Categories (COMPREHENSIVE VERSION) ---
CPA_TOOL_DETECTION = {
    "tax_prep_desktop": {
        "category": "Tax Preparation",
        "confidence": 0.95,
        "keywords": [
            "ultratax", "drake tax", "lacerte", "proseries", "atx",
            "taxact", "taxwise", "turbotax", "intuit tax", "proconnect",
            "cch axcess tax", "thomson reuters ultratax", "corptax",
            "onesource", "taxslayer pro", "crosslink", "gosystem tax",
            "safesend returns", "vertafore", "taxcaddy",
        ],
        "domains": [
            "ultratax.com", "drakesoftware.com", "intuit.com/lacerte",
            "intuit.com/proseries", "cchaxcess.com", "taxact.com",
            "taxwise.com", "proconnect.intuit.com"
        ],
        "urls": []
    },
    "tax_forms": {
        "category": "Tax Preparation",
        "confidence": 0.97,
        "keywords": [
            "form 1040", "form 1120", "form 1065", "form 1120s",
            "schedule c", "schedule e", "schedule k-1", "form 990",
            "form 1099", "form w-2", "form 8879", "form 8453",
            "form 706", "form 709", "form 5471", "form 8938",
            "form 3520", "form 1116", "form 2555", "schedule d",
            "schedule b", "form 4562", "form 8829", "form 6251"
        ],
        "domains": ["irs.gov", "taxformfinder.com"],
        "urls": ["1040", "1120", "1065", "990", "1099", "w-2", "k-1", "schedule", "tax return", "tax form", "extension"]
    },
    "accounting_cloud": {
        "category": "Accounting/Bookkeeping",
        "confidence": 0.94,
        "keywords": [
            "quickbooks online", "qbo", "xero", "freshbooks", "wave accounting",
            "zoho books", "sage intacct", "netsuite", "financialforce"
        ],
        "domains": [
            "quickbooks.intuit.com", "qbo.intuit.com", "app.xero.com",
            "freshbooks.com", "waveapps.com", "zoho.com/books",
            "sageintacct.com", "netsuite.com"
        ],
        "urls": ["dashboard", "reports", "banking", "invoices", "expenses"]
    },
    "accounting_desktop": {
        "category": "Accounting/Bookkeeping",
        "confidence": 0.93,
        "keywords": [
            "quickbooks desktop", "sage 50", "sage 100", "sage 300",
            "mas 90", "mas 200", "peachtree", "myob"
        ],
        "domains": [],
        "urls": []
    },
    "bookkeeping_tasks": {
        "category": "Accounting/Bookkeeping",
        "confidence": 0.92,
        "keywords": [],
        "domains": [],
        "urls": [
            "chart of accounts", "general ledger", "reconciliation",
            "bank rec", "journal entry", "adjusting entry",
            "trial balance", "financial statements", "balance sheet",
            "income statement", "cash flow statement", "p&l", "profit and loss"
        ]
    },
    "audit_software": {
        "category": "Audit/Assurance",
        "confidence": 0.96,
        "keywords": [
            "caseware", "caseview", "idea data analysis", "acl analytics",
            "teammate audit", "workiva", "auditboard", "aicpa audit",
            "cch engagement", "pfx engagement", "audit analytics",
            "confirmation.com", "auditfile"
        ],
        "domains": [
            "caseware.com", "caseware.cloud", "auditanalytics.com",
            "auditboard.com", "workiva.com", "confirmation.com",
            "teammate.wolterskluwer.com", "cchaxcess.com/engagement"
        ],
        "urls": [
            "audit program", "working papers", "workpaper", "lead schedule",
            "audit procedures", "testing", "substantive test",
            "controls testing", "walkthrough", "test of details"
        ]
    },
    "audit_procedures": {
        "category": "Audit/Assurance",
        "confidence": 0.93,
        "keywords": [],
        "domains": [],
        "urls": [
            "pcaob", "gaas", "ssars", "ssae", "audit report",
            "review report", "compilation", "agreed upon procedures",
            "audit opinion", "management letter", "internal controls",
            "sarbanes oxley", "sox", "icfr"
        ]
    },
    "research_platforms": {
        "category": "Tax Research",
        "confidence": 0.94,
        "keywords": [
            "checkpoint", "intelliconnect", "bloomberg tax", "ria",
            "tax notes", "bna", "lexis tax", "westlaw tax",
            "cch answerconnect", "thomson reuters checkpoint"
        ],
        "domains": [
            "checkpoint.riag.com", "intelliconnect.cch.com",
            "pro.bloombergtax.com", "news.bloombergtax.com",
            "taxnotes.com", "irs.gov", "taxfoundation.org",
            "lexisnexis.com", "westlaw.com"
        ],
        "urls": [
            "irc section", "treasury regulation", "treas reg",
            "revenue ruling", "rev rul", "revenue procedure", "rev proc",
            "private letter ruling", "plr", "technical advice memorandum",
            "tam", "notice", "publication", "internal revenue code"
        ]
    },
    "tax_authority_sites": {
        "category": "Tax Research",
        "confidence": 0.96,
        "keywords": [],
        "domains": ["irs.gov", "treasury.gov", "congress.gov", "tax.ny.gov", "ftb.ca.gov", "revenue.state.*.us"],
        "urls": ["guidance", "regulations", "statute", "code section"]
    },
    "payroll_platforms": {
        "category": "Payroll Services",
        "confidence": 0.95,
        "keywords": [
            "adp workforce now", "adp run", "paychex flex", "gusto",
            "quickbooks payroll", "patriot payroll", "onpay",
            "surepayroll", "paycor", "namely", "rippling", "zenefits"
        ],
        "domains": [
            "adp.com", "workforcenow.adp.com", "paychex.com",
            "gusto.com", "payroll.intuit.com", "onpay.com",
            "surepayroll.com", "paycor.com", "rippling.com"
        ],
        "urls": [
            "payroll", "pay stub", "paystub", "direct deposit",
            "form 941", "form 940", "unemployment", "workers comp",
            "wage report", "payroll tax", "fica", "withholding"
        ]
    },
    "financial_planning": {
        "category": "Advisory/Financial Planning",
        "confidence": 0.91,
        "keywords": [
            "moneyguidepro", "emoney", "rightcapital", "naviplan",
            "wealthbox", "redtail", "morningstar office"
        ],
        "domains": [
            "moneyguidepro.com", "emoney.com", "rightcapital.com",
            "naviplan.com", "wealthbox.com", "redtailtechnology.com"
        ],
        "urls": [
            "retirement planning", "investment analysis", "financial plan",
            "estate planning", "wealth management", "401k", "ira",
            "roth conversion", "financial projection"
        ]
    },
    "business_valuation": {
        "category": "Valuation/Advisory",
        "confidence": 0.92,
        "keywords": ["bizcomps", "pratt stats", "ibis world", "bvresources"],
        "domains": ["bizcomps.com", "bvresources.com", "ibisworld.com"],
        "urls": [
            "business valuation", "valuation report", "dcf model",
            "market approach", "income approach", "asset approach",
            "fair market value", "enterprise value"
        ]
    },
    "forensic_fraud": {
        "category": "Forensic/Fraud Investigation",
        "confidence": 0.93,
        "keywords": ["forensic accounting", "fraud investigation", "benford", "data analytics", "fraud detection"],
        "domains": [],
        "urls": [
            "fraud examination", "forensic analysis", "investigation",
            "litigation support", "expert witness", "damages calculation"
        ]
    },
    "sec_edgar": {
        "category": "SEC/Regulatory Compliance",
        "confidence": 0.97,
        "keywords": [
            "edgar", "sec filing", "form 10-k", "form 10-q",
            "form 8-k", "form s-1", "proxy statement", "def 14a"
        ],
        "domains": ["sec.gov", "edgar.sec.gov", "edgarfilings.com"],
        "urls": ["form 10-k", "form 10-q", "form 8-k", "form s-1", "prospectus", "registration statement", "proxy"]
    },
    "erisa_employee_benefits": {
        "category": "Employee Benefits/ERISA",
        "confidence": 0.92,
        "keywords": ["form 5500", "erisa", "employee benefit plan", "pension plan", "401k audit"],
        "domains": ["dol.gov", "efast.dol.gov"],
        "urls": ["5500", "erisa", "pension", "401k plan", "benefit plan audit"]
    },
    "practice_management": {
        "category": "Administration",
        "confidence": 0.89,
        "keywords": [
            "cch axcess practice", "thomson reuters cs", "xcm solutions",
            "karbon", "practice ignition", "canopy", "financial cents",
            "jetpack workflow", "taxdome", "liscio"
        ],
        "domains": [
            "cchaxcess.com", "cs.thomsonreuters.com", "karbonhq.com",
            "practiceignition.com", "getcanopy.com", "taxdome.com", "liscio.me"
        ],
        "urls": [
            "client portal", "workflow", "engagement", "billing",
            "engagement letter", "client management", "project management"
        ]
    },
    "time_billing": {
        "category": "Administration",
        "confidence": 0.90,
        "keywords": ["quickbooks time", "bill4time", "timeslips", "billing matters"],
        "domains": ["quickbooks.com/time", "bill4time.com", "timeslips.com"],
        "urls": ["timesheet", "time entry", "billing", "invoice", "wip", "work in progress", "realization"]
    },
    "document_management": {
        "category": "Document Management",
        "confidence": 0.91,
        "keywords": [
            "sharefile", "smartvault", "safesend", "docusign",
            "adobe sign", "rightfax", "dropbox business", "box"
        ],
        "domains": [
            "sharefile.com", "smartvault.com", "safesendreturns.com",
            "docusign.com", "adobesign.com", "dropbox.com", "box.com"
        ],
        "urls": ["signature", "e-signature", "esign", "secure file", "client upload", "file sharing", "document portal"]
    },
    "real_estate": {
        "category": "Real Estate/Property",
        "confidence": 0.90,
        "keywords": [],
        "domains": [],
        "urls": [
            "rental property", "real estate", "depreciation schedule",
            "section 1031", "like kind exchange", "cost segregation", "rental income", "schedule e"
        ]
    },
    "nonprofit": {
        "category": "Nonprofit/Form 990",
        "confidence": 0.94,
        "keywords": [],
        "domains": ["guidestar.org", "nonprofitexpert.com"],
        "urls": ["form 990", "990-n", "990-ez", "990-pf", "nonprofit", "tax exempt", "501c3", "charitable", "exempt organization"]
    },
    "healthcare": {
        "category": "Healthcare/Medical Practice",
        "confidence": 0.91,
        "keywords": [],
        "domains": [],
        "urls": ["medical practice", "healthcare", "physician", "dental practice", "practice acquisition", "medical billing", "rcm"]
    },
    "construction": {
        "category": "Construction/Contractors",
        "confidence": 0.90,
        "keywords": ["viewpoint", "spectrum", "foundation", "cmicrays", "jonas construction", "procore"],
        "domains": ["viewpoint.com", "procore.com", "cmic.com"],
        "urls": [
            "construction", "contractor", "job costing", "wip schedule",
            "percentage of completion", "completed contract", "prevailing wage", "certified payroll"
        ]
    },
}

# Notification settings
# Defaults to OFF, and delegates to notifications.notifications_enabled() so
# there is one answer to "should this agent raise banners" rather than one per
# call site. The previous expression also had a dead branch: `_get`'s default
# argument is only used when the key is ABSENT from config, but the outer
# conditional already returned True in that case — so AGENT_NOTIF_ENABLED was
# never read by anything.
try:
    from notifications import notifications_enabled as _notifications_enabled
except Exception:
    def _notifications_enabled() -> bool:
        return False
NOTIF_ENABLED = _notifications_enabled()
NOTIF_DURATION_MINUTES = int(_get("notif_duration_minutes", os.getenv("AGENT_NOTIF_DURATION_MINUTES")) or 60)
NOTIF_IDLE_THRESHOLD = int(_get("notif_idle_threshold", os.getenv("AGENT_NOTIF_IDLE_THRESHOLD")) or 300)
NOTIF_NO_CLIENT_MINUTES = int(_get("notif_no_client_minutes", os.getenv("AGENT_NOTIF_NO_CLIENT_MINUTES")) or 15)


# Vendor gate (from org_settings sync). Default False = hands-off: the desktop
# ticker stays hidden and MANUAL client switches are ignored. Auto-switching
# (ai_switcher / meeting detection) and attribution still run — hiding the
# ticker does not cost accuracy. MavOps flips this on per-org for demos.
_show_client_widget = False


def _set_show_client_widget(val):
    """Set the module-level hands-off gate, so callers need no `global`."""
    global _show_client_widget
    _show_client_widget = bool(val)


def _apply_client_switch(client_id, client_name, source="unknown"):
    # Hands-off gate: ignore MANUAL switches (menu bar / picker / hotkey /
    # notification) when the ticker is disabled for this org. Automatic
    # sources still flow through, so attribution is unaffected.
    if source in ("gui_prompt", "notification") and not _show_client_widget:
        log(f"[CLIENT-SWITCH] ignored manual switch → {client_name} (hands-off mode)")
        return

    log(f"[CLIENT-SWITCH] → {client_name} (id={client_id}) via {source}")
    
    api_key_val = config.get("api_key") or API_KEY
    if api_key_val and API_BASE:
        set_current_client_backend(API_BASE, api_key_val, client_id)
        _set_cached_client(client_id, client_name)

    
    if gui_menu_bar and hasattr(gui_menu_bar, 'state'):
        gui_menu_bar.state.set_client(client_id, client_name)
        if hasattr(gui_menu_bar, 'app') and gui_menu_bar.app:
            gui_menu_bar.app.title = f"⏱ {client_name}" if client_name else "⏱ None"
        # Rebuild submenu so checkmark moves to the new client
        if hasattr(gui_menu_bar, 'refresh_client_menu') and sync and sync.clients:
            gui_menu_bar.refresh_client_menu(sync.clients)
    
    if notif_manager:
        notif_manager.set_current_client(client_id, client_name)
    
    if ai_switcher and source != "ai_switcher":
        ai_switcher.on_manual_switch(client_id, client_name)
    elif ai_switcher:
        ai_switcher.set_current_client(client_id, client_name)

# ---------------- Logging Setup ----------------
LOG_DIR = os.path.expanduser("~/Library/Logs/TimeTracker")
LOG_FILE = os.path.join(LOG_DIR, "agent.log")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "agent_errors.log")

def setup_logging():
    """Setup file-based logging with rotation."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        
        # Main log - rotates at 5MB, keeps 3 backups
        main_handler = RotatingFileHandler(
            LOG_FILE, 
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        main_handler.setLevel(logging.INFO)
        main_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        
        # Error log - separate file for crashes only
        error_handler = RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=2*1024*1024,  # 2MB
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s\n%(exc_info)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        
        # Configure root logger
        logger = logging.getLogger('timetracker')
        logger.setLevel(logging.DEBUG)
        logger.addHandler(main_handler)
        logger.addHandler(error_handler)
        
        return logger
    except Exception as e:
        print(f"[WARN] Failed to setup logging: {e}")
        return None

_logger = setup_logging()

def detect_client_in_window(title: str, file_path: str = None) -> Optional[dict]:
    """
    Check if any known client name appears in window title or file path.
    Returns client dict if found, None otherwise.
    """
    global sync
    
    if not sync or not sync.clients:
        return None
    
    search_text = f"{title or ''} {file_path or ''}".lower()
    
    for client in sync.clients:
        client_name = client.get("name", "")
        if not client_name:
            continue
        
        # Check if client name appears in window/file
        if client_name.lower() in search_text:
            return client
        
        # Also check aliases if available
        aliases = client.get("aliases", []) or []
        for alias in aliases:
            if alias.lower() in search_text:
                return client
    
    return None


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
    
    Args:
        error_type: Category like 'tracking_loop', 'notification', 'sync'
        error_msg: The error message
        traceback_str: Full traceback string
        context: Additional context (current_sig, idle state, etc.)
    """
    api_key = config.get("api_key") or API_KEY
    if not api_key or not API_BASE:
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
        "error_message": error_msg[:1000],  # Limit size
        "traceback": (traceback_str or "")[:5000],  # Limit size
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
            # 404 = endpoint doesn't exist yet, that's ok
            if e.code != 404:
                log(f"[ERROR-REPORT] HTTP {e.code} sending error report")
        except Exception as e:
            log(f"[ERROR-REPORT] Failed to send: {e}")
        return False
    
    # Send async to not block
    threading.Thread(target=_send, daemon=True).start()
    return True

_last_log_ship: float = 0.0

def ship_logs_to_backend(tail_lines: int = 500, trigger: str = "scheduled"):
    """
    Ship the last N lines of agent.log to the backend for remote debugging.
    Called by the watchdog before exit, and every 30 min by background thread.
    """
    api_key = config.get("api_key") or API_KEY
    if not api_key or not API_BASE:
        return False

    log_lines = []
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                log_lines = f.readlines()[-tail_lines:]
    except Exception as e:
        log(f"[LOG-SHIP] Failed to read log: {e}")
        return False

    if not log_lines:
        return False

    url = f"{API_BASE}/agent/logs/"
    payload = {
        "device_id": get_device_id(),
        "hostname": platform.node(),
        "os_username": get_os_username(),
        "app_version": APP_VERSION,
        "platform": "macos",
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
                method="POST",
            )
            req.add_header("Authorization", f"DeviceKey {api_key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=15) as resp:
                log(f"[LOG-SHIP] ✅ Shipped {len(log_lines)} lines ({trigger})")
        except Exception as e:
            log(f"[LOG-SHIP] Failed: {e}")

    threading.Thread(target=_send, daemon=True).start()
    return True


def start_log_shipping(interval_minutes: int = 30):
    """Start background thread that ships logs every N minutes."""
    def _loop():
        time.sleep(120)  # Wait a bit after startup before first ship
        while True:
            try:
                ship_logs_to_backend(tail_lines=500, trigger="scheduled")
            except Exception as e:
                log(f"[LOG-SHIP] Scheduled ship error: {e}")
            time.sleep(interval_minutes * 60)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    log(f"[LOG-SHIP] Started — shipping every {interval_minutes} min")

def maybe_suggest_client(detected_client: dict, current_client_id: int):
    """
    Show notification if detected client differs from current.
    """
    global _LAST_CLIENT_SUGGESTION, notif_manager
    
    if not detected_client:
        return
    
    client_id = detected_client.get("id")
    client_name = detected_client.get("name")
    
    # Already working on this client
    if client_id == current_client_id:
        return
    
    # Rate limit - don't spam same suggestion within 10 minutes
    now = time.time()
    last_suggested = _LAST_CLIENT_SUGGESTION.get(client_id, 0)
    if now - last_suggested < 600:  # 10 minutes
        return
    
    _LAST_CLIENT_SUGGESTION[client_id] = now
    
    log(f"[CLIENT-DETECT] Found '{client_name}' in window title")
    
    # === ADD DEBUG HERE ===
    log(f"[CLIENT-DETECT] notif_manager={notif_manager}, ready={getattr(notif_manager, 'ready', False)}")
    log(f"[CLIENT-DETECT] has notify_client_suggestion={hasattr(notif_manager, 'notify_client_suggestion')}")
    
    # Use the new notification system if available
    if notif_manager and notif_manager.ready:
        notif_manager.notify_client_suggestion(
            client_id=client_id,
            client_name=client_name,
            confidence=0.85,
            reason="Detected in window title"
        )
    else:
        # Fallback to AppleScript
        msg = f"Are you working on {client_name}?"
        ans = prompt_yes_no("Time Tracker", msg, timeout_s=15)
        if ans is True:
            api_key = config.get("api_key") or API_KEY
            if api_key and API_BASE:
                set_current_client_on_backend(API_BASE, api_key, client_id=client_id)
                log(f"[CLIENT-DETECT] Set current client to {client_name}")


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
from AppKit import NSWorkspace, NSRunningApplication

# Camera/mic capture probe — keeps a silent video call out of idle
try:
    from media_capture import capture_in_use
    MEDIA_CAPTURE_AVAILABLE = True
except ImportError:
    MEDIA_CAPTURE_AVAILABLE = False
    capture_in_use = None
    print("[WARN] media_capture.py not found - camera/mic idle suppression disabled")

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
        out = subprocess.check_output(
            ["osascript", "-e", script], 
            text=True, 
            stderr=subprocess.DEVNULL,
            timeout=5
        ).strip()
        return out
    except subprocess.TimeoutExpired:
        log("[DETECT] ⚠️ osascript timed out (System Events hung after sleep)", "warning")
        return ""
    except Exception:
        return ""

def osa_retry(script: str, tries: int = 2, delay: float = 0.15) -> str:
    for _ in range(tries):
        out = osa(script)
        if out:
            return out
        time.sleep(delay)
    return ""


# ==============================================================================
# BACKEND CLIENT SYNC HELPERS
# ==============================================================================

def get_current_client_from_backend(api_base: str, api_key: str) -> dict:
    """Fetch current client from backend on startup."""
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


def set_current_client_on_backend(api_base: str, api_key: str, 
                                   client_id: int = None, client_name: str = None) -> bool:
    """Tell backend about client switch."""
    if not api_base or not api_key:
        return False
    
    url = f"{api_base}/client/set-current/"
    payload = {}
    if client_id:
        payload["client_id"] = client_id
    if client_name:
        payload["client_name"] = client_name
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"DeviceKey {api_key}") 
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
            log(f"[CLIENT] Backend updated: {data.get('message', 'ok')}")
            retro = data.get('retroactive_blocks', 0)
            if retro > 0:
                log(f"[CLIENT] Retroactively assigned {retro} recent blocks")
            return True
    except urllib.error.HTTPError as e:
        log(f"[CLIENT] HTTP error updating backend: {e.code}")
        return False
    except Exception as e:
        log(f"[CLIENT] Failed to update backend: {e}")
        return False


def fetch_clients_from_backend(api_base: str, api_key: str) -> list:
    """Use sync cache if available, otherwise fetch directly."""
    global sync
    if sync and sync.clients:
        return sync.clients  # ✅ Use cached data
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
    except urllib.error.HTTPError as e:
        log(f"[CLIENT] HTTP error fetching clients: {e.code}")
        return []
    except Exception as e:
        log(f"[CLIENT] Failed to fetch clients: {e}")
        return []


def set_current_client_backend(api_base: str, api_key: str, client_id: int) -> bool:
    """Set the current client on the backend."""
    if not api_base or not api_key:
        return False
    
    url = f"{api_base}/client/set-current/"
    data = {"client_id": client_id}
    
    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, data=json.dumps(data).encode('utf-8'), timeout=6) as resp:
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


def get_current_client_backend(api_base: str, api_key: str) -> dict:
    """Get the current client from the backend."""
    if not api_base or not api_key:
        return {}
    
    url = f"{api_base}/client/current/"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
            if data.get("client"):
                log(f"[CLIENT] Current client: {data['client'].get('name')}")
                return data["client"]
            else:
                log("[CLIENT] No current client set on backend")
                return {}
    except Exception as e:
        log(f"[CLIENT] Error getting current client: {e}")
        return {}

# ---------------- Native notifications ----------------
_NOTIFICATION_CATEGORY_ID = "MAVOPS_TIME_NUDGE"
_ACTION_YES = "ACTION_YES"
_ACTION_NO  = "ACTION_NO"
_PENDING_PROMPTS = {}

def _post_nudge_decision_async(is_yes: bool, data: dict):
    """Call /context/confirm or /context/reject asynchronously."""
    def _run():
        try:
            headers = api_headers(data["os_user"], data["hostname"])
            payload = {
                "client_id": data["client_id"],
                "confidence": data["confidence"],
                "hostname": data["hostname"],
                "device_id": get_device_id(),
                "os_username": data["os_user"],
                "prompt_id": data["prompt_id"],
                "channel": "agent",
            }
            url = CONTEXT_CONFIRM_URL if is_yes else CONTEXT_REJECT_URL
            http_post_json(url, payload, headers, timeout=6)
            log(f"[NUDGE] {'Confirmed' if is_yes else 'Rejected'} via notification: {data['client_name']} ({data['client_id']})")
        except Exception as e:
            log(f"[NUDGE] post decision error: {e}")
    threading.Thread(target=_run, daemon=True).start()


# ------------- Mouse Idle --------------
def mouse_idle_seconds() -> float:
    """Returns seconds since last user input (mouse, keyboard, OR scroll)."""
    try:
        mouse_idle = CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateCombinedSessionState,
            kCGEventMouseMoved
        )
        keyboard_idle = CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateCombinedSessionState,
            kCGEventKeyDown
        )
        scroll_idle = CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateCombinedSessionState,
            kCGEventScrollWheel
        )
        # User is only idle if ALL inputs are idle
        return min(float(mouse_idle), float(keyboard_idle), float(scroll_idle))
    except Exception:
        return 0.0

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

"""
FRONTMOST DETECTION FIX for TimeTracker Mac Agent

Problem: Quartz fallback was returning background windows instead of true frontmost.
Solution: 
  1. Reorder fallbacks (NSWorkspace before Quartz)
  2. Add logging to track which detection method is used
  3. Add validation to catch suspicious results

Replace the relevant functions in main.py with these:
"""

# Add this global near the top of your file (after imports)
_DETECTION_STATS = {"system_events": 0, "nsworkspace": 0, "quartz": 0, "failed": 0}


def get_frontmost_via_system_events() -> Optional[Tuple[str, int]]:
    """Most reliable method - uses System Events AppleScript."""
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
            log(f"[DETECT] System Events returned invalid PID: {out}", "warning")
            return None
    if out:
        log(f"[DETECT] System Events returned unexpected format: {out}", "warning")
    return None


def get_frontmost_via_nsworkspace() -> Optional[Tuple[str, int]]:
    """Second most reliable - uses NSWorkspace."""
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not app:
            return None
        return (str(app.localizedName() or ""), int(app.processIdentifier()))
    except Exception as e:
        log(f"[DETECT] NSWorkspace error: {e}", "warning")
        return None


def get_frontmost_via_quartz() -> Optional[Tuple[str, int, Optional[str]]]:
    """
    UNRELIABLE for frontmost detection!
    Only use as last resort. Returns topmost visible window, which may be background.
    """
    try:
        opts = kCGWindowListOptionOnScreenOnly | kCGWindowListOptionOnScreenAboveWindow
        info = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) or []
        if not info:
            return None
        
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
        
        # Fallback to first window if no good match
        top = info[0]
        return (
            str(top.get("kCGWindowOwnerName") or ""),
            int(top.get("kCGWindowOwnerPID") or 0),
            top.get("kCGWindowName") or None
        )
    except Exception as e:
        log(f"[DETECT] Quartz error: {e}", "warning")
        return None


def get_frontmost_app() -> Optional[Tuple[str, str, int, Optional[str]]]:
    """
    Get frontmost application with method logging.
    Returns: (app_name, bundle_id, pid, window_title) or None
    
    Fallback order (most to least reliable):
      1. System Events AppleScript
      2. NSWorkspace
      3. Quartz (UNRELIABLE - may return background windows!)
    """
    global _DETECTION_STATS
    
    # Method 1: System Events (most reliable)
    se = get_frontmost_via_system_events()
    if se:
        name, pid = se
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        _DETECTION_STATS["system_events"] += 1
        if VERBOSE:
            log(f"[DETECT] SystemEvents → {name} (pid={pid})")
        return (name, bid, pid, None)

    # Method 2: NSWorkspace (second most reliable)
    ws = get_frontmost_via_nsworkspace()
    if ws:
        name, pid = ws
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        _DETECTION_STATS["nsworkspace"] += 1
        log(f"[DETECT] ⚠️ NSWorkspace fallback → {name} (pid={pid})")
        return (name, bid, pid, None)

    # Method 3: Quartz (LAST RESORT - unreliable!)
    q = get_frontmost_via_quartz()
    if q:
        name, pid, qtitle = q
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        _DETECTION_STATS["quartz"] += 1
        log(f"[DETECT] ⚠️⚠️ QUARTZ fallback → {name} (pid={pid}, title={qtitle[:50] if qtitle else 'None'})")
        log(f"[DETECT] WARNING: Quartz detection may have returned a BACKGROUND window!")
        return (name, bid, pid, qtitle)

    _DETECTION_STATS["failed"] += 1
    log("[DETECT] ❌ All detection methods failed!")
    return None


# Optional: Add this function to periodically log detection stats
def log_detection_stats():
    """Call this periodically (e.g., every 5 minutes) to see detection method usage."""
    total = sum(_DETECTION_STATS.values())
    if total == 0:
        return
    
    se_pct = (_DETECTION_STATS["system_events"] / total) * 100
    ns_pct = (_DETECTION_STATS["nsworkspace"] / total) * 100
    q_pct = (_DETECTION_STATS["quartz"] / total) * 100
    fail_pct = (_DETECTION_STATS["failed"] / total) * 100
    
    log(f"[DETECT-STATS] Total={total} | SystemEvents={se_pct:.1f}% | NSWorkspace={ns_pct:.1f}% | Quartz={q_pct:.1f}% | Failed={fail_pct:.1f}%")
    
    # Alert if Quartz is being used too much (indicates System Events problems)
    if q_pct > 5:
        log(f"[DETECT-STATS] ⚠️ Quartz usage is high ({q_pct:.1f}%) - check System Events accessibility permissions!")


# ============================================================================
# ADDITIONAL FIX: Validate frontmost against NSWorkspace
# ============================================================================

def get_frontmost_app_validated() -> Optional[Tuple[str, str, int, Optional[str]]]:
    """
    Enhanced version that cross-validates detection methods.
    Use this instead of get_frontmost_app() for extra safety.
    """
    global _DETECTION_STATS
    
    # Get result from primary method (System Events)
    se = get_frontmost_via_system_events()
    
    # Always get NSWorkspace result for validation
    ws = get_frontmost_via_nsworkspace()
    
    if se and ws:
        se_name, se_pid = se
        ws_name, ws_pid = ws
        
        # If they agree, we're good
        if se_pid == ws_pid:
            ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(se_pid)
            bid = str(ra.bundleIdentifier() or "") if ra else ""
            _DETECTION_STATS["system_events"] += 1
            return (se_name, bid, se_pid, None)
        
        # They disagree! Log this and trust NSWorkspace (it's more direct)
        log(f"[DETECT] ⚠️ MISMATCH: SystemEvents says {se_name}(pid={se_pid}) but NSWorkspace says {ws_name}(pid={ws_pid})")
        log(f"[DETECT] Trusting NSWorkspace result")
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(ws_pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        _DETECTION_STATS["nsworkspace"] += 1
        return (ws_name, bid, ws_pid, None)
    
    # If System Events succeeded alone
    if se:
        name, pid = se
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        _DETECTION_STATS["system_events"] += 1
        return (name, bid, pid, None)
    
    # If NSWorkspace succeeded alone  
    if ws:
        name, pid = ws
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        _DETECTION_STATS["nsworkspace"] += 1
        log(f"[DETECT] ⚠️ NSWorkspace only → {name}")
        return (name, bid, pid, None)
    
    # Last resort: Quartz (but warn heavily)
    q = get_frontmost_via_quartz()
    if q:
        name, pid, qtitle = q
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = str(ra.bundleIdentifier() or "") if ra else ""
        _DETECTION_STATS["quartz"] += 1
        log(f"[DETECT] ⚠️⚠️ QUARTZ FALLBACK (unreliable!) → {name}")
        return (name, bid, pid, qtitle)
    
    _DETECTION_STATS["failed"] += 1
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

# Chromium browsers all answer the same AppleScript, differing only in the
# application name. Edge and Arc were missing entirely, so a client's portal
# opened in Edge contributed no URL at all.
_CHROMIUM_APPS = {
    "com.google.Chrome":         "Google Chrome",
    "com.google.Chrome.canary":  "Google Chrome Canary",
    "com.google.Chrome.beta":    "Google Chrome Beta",
    "com.brave.Browser":         "Brave Browser",
    "com.microsoft.edgemac":     "Microsoft Edge",
    "com.microsoft.edgemac.Beta": "Microsoft Edge Beta",
    "com.vivaldi.Vivaldi":       "Vivaldi",
    "company.thebrowser.Browser": "Arc",
}

# Office and iWork apps that can name the document they have open. The
# AppleScript differs per app, so each carries its own snippet.
_DOC_PATH_SCRIPTS = {
    # The `path` check is the important part. An unsaved scratch workbook
    # has full name "Book1" and no path, and POSIX path turns that into the
    # absolute-looking "/Book1" — a path to nothing, which the inference
    # engine would then read for a client name. Only a workbook that lives
    # somewhere on disk has a path to report.
    "com.microsoft.Excel": (
        'tell application "Microsoft Excel" to try\n'
        'if not (exists active workbook) then return ""\n'
        'if (path of active workbook) is "" then return ""\n'
        'set p to (full name of active workbook)\n'
        'return POSIX path of p\non error\nreturn ""\nend try'
    ),
    "com.microsoft.Word": (
        'tell application "Microsoft Word" to try\n'
        'if not (exists active document) then return ""\n'
        'if (path of active document) is "" then return ""\n'
        'set p to (full name of active document)\n'
        'return POSIX path of p\non error\nreturn ""\nend try'
    ),
    "com.microsoft.Powerpoint": (
        'tell application "Microsoft PowerPoint" to try\n'
        'if not (exists active presentation) then return ""\n'
        'if (path of active presentation) is "" then return ""\n'
        'set p to (full name of active presentation)\n'
        'return POSIX path of p\non error\nreturn ""\nend try'
    ),
    "com.apple.Preview": (
        'tell application "Preview" to try\n'
        'set theDoc to document 1\nset p to path of theDoc\n'
        'POSIX path of p\non error\nreturn ""\nend try'
    ),
    "com.apple.iWork.Numbers": (
        # `file of document 1` is an HFS specifier ("Macintosh HD:Users:...").
        # POSIX path cannot take it directly; coercing to alias first is what
        # works. Verified against Numbers on macOS 15.
        'tell application "Numbers" to try\n'
        'if (count of documents) is 0 then return ""\n'
        'return POSIX path of ((file of document 1) as alias)\n'
        'on error\nreturn ""\nend try'
    ),
    "com.apple.iWork.Pages": (
        # `file of document 1` is an HFS specifier ("Macintosh HD:Users:...").
        # POSIX path cannot take it directly; coercing to alias first is what
        # works. Verified against Pages on macOS 15.
        'tell application "Pages" to try\n'
        'if (count of documents) is 0 then return ""\n'
        'return POSIX path of ((file of document 1) as alias)\n'
        'on error\nreturn ""\nend try'
    ),
    "com.apple.iWork.Keynote": (
        # `file of document 1` is an HFS specifier ("Macintosh HD:Users:...").
        # POSIX path cannot take it directly; coercing to alias first is what
        # works. Verified against Keynote on macOS 15.
        'tell application "Keynote" to try\n'
        'if (count of documents) is 0 then return ""\n'
        'return POSIX path of ((file of document 1) as alias)\n'
        'on error\nreturn ""\nend try'
    ),
    # Finder's front window as a path. finder_watcher feeds the same path to
    # the AI switcher, but that is a different channel: the switcher decides
    # the CURRENT CLIENT, while the event payload is what the inference
    # engine reasons over on the server. Without this, a Finder event reached
    # the backend carrying no path at all, and the folder the user was
    # actually looking at was invisible to attribution.
    #
    # The Windows agent gets this for free because Explorer puts the folder
    # in its window title. Finder's title is the leaf name only, and is empty
    # altogether unless the app holds Accessibility permission.
    "com.apple.finder": (
        'tell application "Finder" to try\n'
        'if (count of Finder windows) is 0 then return ""\n'
        'return POSIX path of ((target of front Finder window) as alias)\n'
        'on error\nreturn ""\nend try'
    ),
    "com.apple.TextEdit": (
        # TextEdit's `path` is ALREADY a POSIX string, unlike every other
        # app here. Wrapping it in `POSIX path of` raises. Verified on
        # macOS 15: "Can't make POSIX path of path of document 1 into type
        # reference."
        'tell application "TextEdit" to try\n'
        'if (count of documents) is 0 then return ""\n'
        'return (path of document 1) as text\n'
        'on error\nreturn ""\nend try'
    ),
    "com.sublimetext.4": (
        'tell application "Sublime Text" to try\n'
        'if not (exists window 1) then return ""\n'
        'set theDoc to document of window 1\n'
        'if theDoc is missing value then return ""\n'
        'set p to (path of theDoc)\nreturn POSIX path of p\n'
        'on error\nreturn ""\nend try'
    ),
}
_DOC_PATH_SCRIPTS["com.sublimetext.3"] = _DOC_PATH_SCRIPTS["com.sublimetext.4"]


def try_get_url_or_path(bundle_id: str) -> Dict[str, Optional[str]]:
    """The URL or document path behind the frontmost window.

    This is the Mac's equivalent of the Windows agent reading Explorer's
    address bar and the browser address bar over UI Automation. Every app
    missing from these tables contributes a window title and nothing else,
    which for a document app means the client's own file is invisible.
    """
    if bundle_id == "com.apple.Safari":
        url = osa_retry(
            'tell application "Safari" to try\n'
            'set u to URL of current tab of front window\n'
            'return u\non error\nreturn ""\nend try'
        )
        return {"url": url or None, "file_path": None}

    app = _CHROMIUM_APPS.get(bundle_id)
    if app:
        script = f'''tell application "{app}"
            try
                if (count of windows) > 0 then
                    return URL of active tab of window 1
                end if
                return ""
            on error
                return ""
            end try
        end tell'''
        url = osa_retry(script, tries=3, delay=0.1)
        return {"url": url or None, "file_path": None}

    if bundle_id == "org.mozilla.firefox":
        # Firefox exposes no scripting dictionary for the address bar. Its
        # window title carries the page title, which the matcher already
        # reads; there is nothing further to extract.
        return {"url": None, "file_path": None}

    script = _DOC_PATH_SCRIPTS.get(bundle_id)
    if script:
        path = osa_retry(script)
        if path:
            # Finder hands back a directory with a trailing slash. Left on,
            # the basename is the empty string, so content_identity yields
            # nothing for the very folder the user is looking at. finder_watcher
            # strips it too — the two channels must agree on the same path.
            path = path.rstrip("/") or "/"
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
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    for k,v in headers.items(): req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def http_get_json(url: str, headers: dict, timeout=6) -> dict:
    req = urllib.request.Request(url, method="GET")
    for k,v in headers.items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", errors="ignore")
        except: pass
        log(f"[CTRL] HTTP {e.code} from control: {body[:200]}")
        return {}
    except Exception as e:
        if not hasattr(http_get_json, '_last_error_log'):
            http_get_json._last_error_log = 0
        now = time.time()
        if now - http_get_json._last_error_log > 60:
            log(f"[CTRL] get error: {e}")
            http_get_json._last_error_log = now
        return {}

_last_control_check = 0.0

def should_stop(control_url: str, user: str, host: str) -> bool:
    global _last_control_check
    now = time.time()
    if now - _last_control_check < CONTROL_POLL_S:
        return False
    _last_control_check = now
    
    qs = f"?host={host}"
    headers = api_headers(user, host)
    
    for attempt in range(2):
        data = http_get_json(control_url + qs, headers, timeout=3)
        if data:
            break
        if attempt == 0:
            time.sleep(0.5)
    
    stop = bool(data.get("stop"))
    if stop:
        log(f"[CTRL] Stop received from server: reason={data.get('reason','')}")
    return stop

def looks_toolish(bundle_id: Optional[str], url: Optional[str]) -> tuple[bool, str, str]:
    """Return (toolish, reason, host)."""
    b = (bundle_id or "").strip()
    host = ""
    if url:
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
    if b in TOOL_BUNDLES:
        return True, "bundle", host
    if host and (host in TOOL_HOSTS or host.startswith("localhost") or host.startswith("127.")):
        return True, "host", host
    return False, "", host


def is_in_meeting(bundle_id: Optional[str], url: Optional[str], 
                  app_name: Optional[str], title: Optional[str]) -> bool:
    """Detect if user is in a virtual meeting.
    
    FIX: Added title-based fallback for browser-hosted meetings (Teams in Chrome, etc.)
    so that failed URL capture doesn't cause meetings to be treated as idle.
    """
    if bundle_id and bundle_id in MEETING_BUNDLES:
        if bundle_id in {"com.google.Chrome", "com.apple.Safari", "com.brave.Browser", "org.mozilla.firefox"}:
            # Check URL first (most reliable)
            if url:
                try:
                    host = (urlparse(url).hostname or "").lower()
                    if any(domain in host for domain in MEETING_DOMAINS):
                        return True
                except:
                    pass
            
            # FIX 2: Title-based fallback when URL capture fails
            # This is critical for Chrome-hosted Teams, Meet, etc.
            title_lower = (title or "").lower()
            
            # Strong meeting indicators in window title
            meeting_title_patterns = [
                # Microsoft Teams
                "microsoft teams", "teams.microsoft.com", "teams.live.com",
                "| microsoft teams", "meeting | microsoft teams",
                # Google Meet  
                "google meet", "meet.google.com", "meet -",
                # Zoom
                "zoom meeting", "zoom.us",
                # WebEx
                "webex", "webex meeting",
                # Generic
                "- call", "video call", "screen sharing",
            ]
            
            if any(pattern in title_lower for pattern in meeting_title_patterns):
                log(f"[MEETING] Detected via window title: '{title[:80]}'")
                return True
            
            return False
        # Non-browser meeting apps (Zoom native, Teams native, etc.) - always meetings
        return True
    
    # Check URL even if bundle isn't in MEETING_BUNDLES
    if url:
        try:
            host = (urlparse(url).hostname or "").lower()
            if any(domain in host for domain in MEETING_DOMAINS):
                return True
        except:
            pass
    
    # Keyword check in app name + title
    check_str = f"{app_name or ''} {title or ''}".lower()
    if any(keyword in check_str for keyword in MEETING_KEYWORDS):
        return True
    
    return False

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

def clear_client_caches():
    """Clear cached client data when re-pairing or on fresh install."""
    cache_locations = [
        os.path.expanduser("~/.timetracker/clients.json"),
        os.path.expanduser("~/.timetracker/sync_cache.json"),
        os.path.expanduser("~/.timetracker/client_usage.json"),
        os.path.expanduser("~/.timetracker/gui_state.json"),
    ]
    
    for path in cache_locations:
        if os.path.exists(path):
            try:
                os.remove(path)
                log(f"[CACHE] Cleared: {path}")
            except Exception as e:
                log(f"[CACHE] Failed to clear {path}: {e}")
    for path in cache_locations:
        if os.path.exists(path):
            try:
                os.remove(path)
                log(f"[CACHE] Cleared: {path}")
            except Exception as e:
                log(f"[CACHE] Failed to clear {path}: {e}")

def _claim_pair(code: str, hostname: str) -> dict:
    """
    Claim a pairing code and return result dict.
    Returns {"api_key": str, "username": str, "org_name": str} on success
    or {"error": str} on failure.
    """
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
            clear_client_caches()
            config["api_key"] = key
            config["api_base"] = config.get("api_base") or "https://timetracker-api-k375.onrender.com/api"  # ADD
            config["verbose"] = config.get("verbose", True)  # ADD
            if "pair_code" in config: 
                del config["pair_code"]
            save_config(config)
            print("✅ Device paired; key saved.")
            return {
                "api_key": key,
                "username": data.get("username", ""),
                "org_name": data.get("org_name", ""),
            }
        else:
            error_msg = data.get("error", "Invalid pairing code")
            print(f"❌ Pair claim response: {error_msg}")
            return {"error": error_msg}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
            data = json.loads(body)
            error_msg = data.get("error", f"HTTP {e.code}")
        except:
            error_msg = f"HTTP {e.code}"
        print(f"❌ Pair claim failed: {error_msg}")
        return {"error": error_msg}
    except Exception as e:
        print(f"❌ Pair claim failed: {e}")
        return {"error": str(e)}


def _gui_pair_callback(code: str) -> dict:
    """Callback for GUI pairing window"""
    hostname = platform.node()
    return _claim_pair(code, hostname)


def ensure_api_key_interactive(hostname: str):
    """Ensure we have an API key; use GUI or terminal prompt if needed."""
    global API_KEY
    key = config.get("api_key") or API_KEY
    if key:
        return key
    
    # Headless pre-provided code
    if PAIR_CODE:
        with _pair_lock:
            result = _claim_pair(PAIR_CODE, hostname)
            if result.get("api_key"):
                API_KEY = result["api_key"]
                return API_KEY
            return None

    # Try GUI pairing first if available
    if GUI_AVAILABLE:
        print("\n🔗 Opening pairing window...")
        key = show_pairing_window(_gui_pair_callback)
        if key:
            import time
            import gc
            gc.collect()
            time.sleep(0.5)
            API_KEY = key
            return key
        # User cancelled - fall through to terminal if available

    # Interactive terminal prompt (only if a real TTY)
    if sys.stdin.isatty():
        print("\n🧩 Enter pairing code from the web app to link this device:")
        code = input("> ").strip()
        if code:
            with _pair_lock:
                result = _claim_pair(code, hostname)
                if result.get("api_key"):
                    API_KEY = result["api_key"]
                    return API_KEY
    
    print("⚠️ No api_key configured; set AGENT_API_KEY, or add 'pair_code' to config.json, or run interactively.")
    return None

def drop_api_key():
    """Remove bad key so we can re-pair on next cycle."""
    if "api_key" in config:
        del config["api_key"]
        save_config(config)
    global API_KEY
    API_KEY = None


# ---------------- Handshake & control ----------------
SERVER_USER_ID = None

def hello(server_url: str, user: str, host: str, device_id: str):
    """Hello using DeviceKey."""
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


# -------------- Guess/Nudge worker --------------
_nudge_lock = threading.Lock()
_last_nudge: Dict[str, float] = {}

def _snoozed(user: str, client_id: int) -> bool:
    key = f"{user}:{client_id}"
    until = _last_nudge.get(key, 0)
    return time.time() < until

def _snooze(user: str, client_id: int, minutes: int):
    key = f"{user}:{client_id}"
    _last_nudge[key] = time.time() + minutes * 60


class _NotificationDelegate(NSObject):
    """Handles action responses from Notification Center."""
    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(self, center, response, completion):
        try:
            req = response.notification().request()
            req_id = str(req.identifier())
            action_id = str(response.actionIdentifier())

            NSLog(f"[NOTIF] delegate fired: req_id={req_id} action_id={action_id}")

            data = _PENDING_PROMPTS.pop(req_id, None)
            if not data:
                # Handle timesheet review notifications by prefix
                if req_id.startswith("timesheet-review-"):
                    import webbrowser
                    webbrowser.open("https://timetracker.mavops.ai/daily")
                    NSLog(f"[NOTIF] Opened timesheet review in browser")
                else:
                    NSLog(f"[NOTIF] no pending meta for {req_id} (ignored)")
            else:
                # Handle timesheet review type
                if data.get("type") == "timesheet_review":
                    import webbrowser
                    webbrowser.open(data.get("url", "https://timetracker.mavops.ai/daily"))
                    NSLog(f"[NOTIF] Opened timesheet review in browser")
                    if completion:
                        completion()
                    return
                DEFAULT = "com.apple.UNNotificationDefaultActionIdentifier"
                DISMISS = "com.apple.UNNotificationDismissActionIdentifier"

                if action_id == _ACTION_YES or action_id == DEFAULT:
                    _post_nudge_decision_async(True, data)
                    NSLog(f"[NUDGE] Confirmed via notification: {data['client_name']} ({data['client_id']})")
                elif action_id == _ACTION_NO:
                    _post_nudge_decision_async(False, data)
                    NSLog(f"[NUDGE] Rejected via notification: {data['client_name']} ({data['client_id']})")
                elif action_id == DISMISS:
                    NSLog(f"[NUDGE] Dismissed notification: {data['client_name']} ({data['client_id']})")
                else:
                    NSLog(f"[NOTIF] Unhandled action_id={action_id}")

                evt = data.get("_evt")
                if evt:
                    try: evt.set()
                    except Exception: pass

        except Exception as e:
            NSLog(f"[NOTIF] error in delegate: {e}")

        if completion:
            completion()


class NotificationManager:
    def __init__(self):
        self.center = None
        self.delegate = None
        self.ready = False

    def setup(self):
        if not NOTIF_AVAILABLE:
            log("[NOTIF] UserNotifications not available; will fallback to AppleScript.")
            return False
        try:
            self.center = UNUserNotificationCenter.currentNotificationCenter()

            if not self.delegate:
                self.delegate = _NotificationDelegate.alloc().init()
                self.center.setDelegate_(self.delegate)

            yes_action = UNNotificationAction.actionWithIdentifier_title_options_(
                _ACTION_YES, "Yes", UNNotificationActionOptionForeground
            )
            no_action = UNNotificationAction.actionWithIdentifier_title_options_(
                _ACTION_NO, "No", 0
            )
            category = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                _NOTIFICATION_CATEGORY_ID, [yes_action, no_action], [], 0
            )
            self.center.setNotificationCategories_({category})

            evt = threading.Event()
            def _auth(granted, err):
                log(f"[NOTIF] authorization granted={bool(granted)}")
                self.ready = bool(granted)
                evt.set()

            self.center.requestAuthorizationWithOptions_completionHandler_(1 << 0 | 1 << 2, _auth)
            evt.wait(timeout=5)
            return self.ready
        except Exception as e:
            log(f"[NOTIF] setup error: {e}")
            self.ready = False
            return False

    def notify_nudge(self, *, prompt_id: str, client_id: int, client_name: str,
                     confidence: float, hostname: str, os_user: str) -> bool:
        if not (self.ready and NOTIF_AVAILABLE) or not NOTIF_ENABLED:
            return False
        try:
            req_id = f"mavops-{prompt_id}"

            _PENDING_PROMPTS[req_id] = {
                "prompt_id": prompt_id,
                "client_id": int(client_id),
                "client_name": client_name,
                "confidence": float(confidence),
                "hostname": hostname,
                "os_user": os_user,
            }

            content = UNMutableNotificationContent.alloc().init()
            content.setTitle_("Time Tracker")
            content.setSubtitle_(f"Are you working on \"{client_name}\"?")
            content.setBody_(f"Confidence {int(confidence*100)}% • Tap Yes or No")
            content.setCategoryIdentifier_(_NOTIFICATION_CATEGORY_ID)

            request = UNNotificationRequest.requestWithIdentifier_content_trigger_(req_id, content, None)
            self.center.addNotificationRequest_withCompletionHandler_(request, None)
            log(f"[NOTIF] scheduled id={req_id}")
            return True
        except Exception as e:
            log(f"[NOTIF] schedule error: {e}")
            return False


NOTIFIER = NotificationManager()


def prompt_yes_no(title: str, message: str, timeout_s: int = 15) -> Optional[bool]:
    """Native Yes/No prompt (AppleScript) with timeout."""
    try:
        script = f'''
        display dialog {json.dumps(message)} with title {json.dumps(title)}
            buttons {{"No","Yes"}} default button "Yes" giving up after {int(timeout_s)}
        '''
        out = osa(script)
        out_l = out.lower()
        if "gave up:true" in out_l:
            return None
        if "button returned:yes" in out_l:
            return True
        if "button returned:no" in out_l:
            return False
        if "yes" in out_l:
            return True
        if "no" in out_l:
            return False
        return None
    except Exception:
        return None


def guess_worker(hostname: str, os_user: str, stop_event: threading.Event, gui_menu_bar=None, notif_manager=None):
    """Polls /context/guess for client suggestions."""
    if not NUDGE_ENABLED:
        log("[NUDGE] Disabled.")
        return

    log(f"[NUDGE] Guess worker started (every {GUESS_POLL_SECONDS}s, conf {GUESS_MIN_CONF}..{GUESS_MAX_CONF}, snooze {NUDGE_SNOOZE_MIN}m)")
    headers = api_headers(os_user, hostname)

    def _fetch():
        params = f"?host={hostname}&device_id={get_device_id()}"
        return http_get_json(CONTEXT_GUESS_URL + params, headers=headers)

    try:
        data = _fetch()
    except Exception as e:
        log(f"[NUDGE] eager fetch error: {e}")
        data = None

    while not stop_event.is_set():
        try:
            if data is None:
                data = _fetch()

            if not data:
                data = None
                time.sleep(GUESS_POLL_SECONDS)
                continue

            client_id = data.get("client_id")
            client_name = data.get("client_name") or ""
            conf = float(data.get("confidence") or 0.0)
            data = None

            if not client_id or conf <= 0:
                time.sleep(GUESS_POLL_SECONDS)
                continue

            if conf >= GUESS_MAX_CONF:
                log(f"[NUDGE] High confidence {conf:.2f} for {client_name} (id={client_id}) → no prompt.")
                time.sleep(GUESS_POLL_SECONDS)
                continue

            if conf < GUESS_MIN_CONF:
                time.sleep(GUESS_POLL_SECONDS)
                continue

            if _snoozed(os_user, int(client_id)):
                time.sleep(GUESS_POLL_SECONDS)
                continue

            with _nudge_lock:
                if _snoozed(os_user, int(client_id)):
                    time.sleep(GUESS_POLL_SECONDS)
                    continue

                # === ADD THIS BLOCK HERE (before gui_menu_bar check) ===
                if notif_manager and notif_manager.ready:
                    notif_manager.notify_client_suggestion(
                        client_id=int(client_id),
                        client_name=client_name,
                        confidence=float(conf),
                        reason=None  # Could add context like "Opened QuickBooks"
                    )
                    _snooze(os_user, int(client_id), NUDGE_SNOOZE_MIN)
                    time.sleep(GUESS_POLL_SECONDS)
                    continue

                if gui_menu_bar:
                    prompt_id = f"{int(time.time())}-{client_id}"
                    prompt_data = {
                        "prompt_id": prompt_id,
                        "client_id": int(client_id),
                        "client_name": client_name,
                        "confidence": float(conf),
                        "hostname": hostname,
                        "os_user": os_user,
                    }
                    gui_menu_bar.show_client_prompt(
                        int(client_id), client_name, float(conf), prompt_data
                    )
                    log(f"[NUDGE] GUI prompt shown for {client_name} ({conf:.2f})")
                    _snooze(os_user, int(client_id), NUDGE_SNOOZE_MIN)
                    continue

                if NOTIFIER and getattr(NOTIFIER, "ready", False):
                    prompt_id = f"{int(time.time())}-{client_id}"
                    did_schedule = NOTIFIER.notify_nudge(
                        prompt_id=prompt_id,
                        client_id=int(client_id),
                        client_name=client_name,
                        confidence=float(conf),
                        hostname=hostname,
                        os_user=os_user,
                    )
                    if did_schedule:
                        log(f"[NUDGE] Notification scheduled for {client_name} ({conf:.2f}).")
                        _snooze(os_user, int(client_id), NUDGE_SNOOZE_MIN)
                        continue
                    else:
                        log("[NUDGE] Notification schedule failed; falling back to AppleScript.")

                msg = f"Are you working on {client_name} right now?\n(confidence {int(conf*100)}%)"
                ans = prompt_yes_no("Time Tracker", msg, timeout_s=NUDGE_TIMEOUT_SEC)

                if ans is True:
                    try:
                        payload = {
                            "client_id": client_id,
                            "confidence": conf,
                            "hostname": hostname,
                            "device_id": get_device_id(),
                            "os_username": os_user,
                        }
                        http_post_json(CONTEXT_CONFIRM_URL, payload, headers=headers, timeout=6)
                        log(f"[NUDGE] Confirmed {client_name} (id={client_id})")
                    except Exception as e:
                        log(f"[NUDGE] confirm error: {e}")
                    finally:
                        _snooze(os_user, int(client_id), NUDGE_SNOOZE_MIN)

                elif ans is False:
                    try:
                        payload = {
                            "client_id": client_id,
                            "confidence": conf,
                            "hostname": hostname,
                            "device_id": get_device_id(),
                            "os_username": os_user,
                        }
                        http_post_json(CONTEXT_REJECT_URL, payload, headers=headers, timeout=6)
                        log(f"[NUDGE] Rejected {client_name} (id={client_id})")
                    except Exception as e:
                        log(f"[NUDGE] reject error: {e}")
                    finally:
                        _snooze(os_user, int(client_id), NUDGE_SNOOZE_MIN)

                else:
                    _snooze(os_user, int(client_id), max(5, min(NUDGE_SNOOZE_MIN, 10)))
                    log(f"[NUDGE] Dismissed/timeout for {client_name} (id={client_id})")

            time.sleep(GUESS_POLL_SECONDS)

        except Exception as e:
            log(f"[NUDGE] worker error: {e}")
            time.sleep(max(5, GUESS_POLL_SECONDS))


# ---------------- Posting ----------------
def post_event_async(event: dict, user: str, host: str):
    if not POST_URL:
        return
    def _run():
        headers = api_headers(user, host)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(POST_URL, data=json.dumps(event).encode("utf-8"), method="POST")
                for k, v in headers.items(): req.add_header(k, v)
                with urllib.request.urlopen(req, timeout=6) as resp:
                    _ = resp.read()
                log(f"[POSTED] {POST_URL}")
                return  # Success
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="ignore")
                except:
                    pass
                log(f"[POST ERROR] HTTP {e.code}: {body[:200]}")
                if e.code == 403 and "subscription_inactive" in body:
                    check_subscription_response_from_body(body)
                    return
            except urllib.error.URLError as e:
                # Network not ready (common after wake from sleep)
                if attempt < max_retries - 1:
                    wait = 5 * (attempt + 1)  # 5s, 10s
                    log(f"[POST RETRY] Network error (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {wait}s: {e}")
                    time.sleep(wait)
                else:
                    log(f"[POST ERROR] All retries failed: {e}")
            except Exception as e:
                log(f"[POST ERROR] {e}")
                return  # Don't retry unknown errors
    threading.Thread(target=_run, daemon=True).start()


def write_event(
    conn,
    cur,
    user: str,
    hostname: str,
    sig,
    start_ts: float,
    end_ts: float,
    client_override=None,
):
    """
    Persist + transmit a single activity interval.

    PARAMETERS
    ==========
      sig:           (app_name, bundle_id, window_title, url, file_path) tuple
      start_ts:      epoch seconds — when this interval began
      end_ts:        epoch seconds — when this interval ended (now, or sleep_ts)
      client_override:  client_id captured at dwell_start. When provided, it
                        overrides the cached client so an AI-switcher flip
                        mid-dwell does not retroactively reattribute earlier
                        heartbeats.

    GUARANTEES
    ==========
      - end_ts > start_ts (caller must ensure)
      - end_ts - start_ts <= MAX_EVENT_DURATION_S (caller chunks if longer)
      - Local SQLite write always succeeds (even offline)
      - Backend POST is fire-and-forget; failure does not block tracking
    """
    app_name, bundle_id, title, url, fpath = sig

    if end_ts <= start_ts:
        log(f"[EVENT] ⚠️ Skipping invalid interval: start={start_ts} end={end_ts}")
        return

    duration = end_ts - start_ts
    if duration > MAX_EVENT_DURATION_S + 1:  # +1s tolerance for clock jitter
        log(f"[EVENT] ⚠️ Interval {duration:.0f}s exceeds max {MAX_EVENT_DURATION_S}s — "
            f"caller should have chunked. Recording as-is.")

    start_iso = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
    end_iso = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()

    # ── Local SQLite write FIRST — always succeeds offline ──
    # The local schema still keys on ts_utc; start_ts goes there.
    cur.execute(
        "INSERT INTO raw_events (ts_utc, app_name, bundle_id, window_title, url, file_path, user, hostname) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (start_iso, app_name, bundle_id, title or "", url, fpath, user, hostname),
    )
    conn.commit()

    # ── Client resolution: override wins, else the inference cache, else the
    # legacy state-machine cache. The inference cache is the source of truth
    # once the engine is available; _get_cached_client() remains the fallback
    # so an agent built without the inference package still attributes.
    current_client_id = None
    current_client_name = None
    if client_override is not None:
        current_client_id = client_override
        if sync and getattr(sync, "clients", None):
            obj = next((c for c in sync.clients if c.get("id") == client_override), None)
            current_client_name = obj.get("name") if obj else None
    else:
        _inf = None
        if _INFERENCE_AVAILABLE:
            try:
                from inference_cache import get_current_inference as _gci_inline
                _inf = _gci_inline()
            except Exception as e:
                log(f"[INFERENCE] cache read failed: {e}", "warning")
        if _inf:
            current_client_id = _inf.get("client_id")
            current_client_name = _inf.get("client_name")
        else:
            current_client_id, current_client_name = _get_cached_client()

    # Update notification state with current client
    if notif_manager:
        notif_manager.set_current_client(current_client_id, current_client_name)

    # ── v1.4.0: confidence-graded inference ──
    # Result goes in payload['inference']; the server-side classifier reads it
    # via RawEvent.inference. current_client_id stays populated for backwards
    # compatibility with older server code paths.
    inference_dict = {}
    if _INFERENCE_AVAILABLE:
        try:
            inference_dict = _compute_inference_for_event(
                app_name, bundle_id, title or "", url, fpath
            )
        except Exception as e:
            log(f"[INFERENCE] compute failed: {e}", "warning")
            inference_dict = {}

    payload = {
        "start_ts": start_iso,
        "end_ts": end_iso,
        "app_name": app_name,
        "bundle_id": bundle_id,
        "window_title": title or "",
        "url": url,
        "file_path": fpath,
        "content_identity": _content_identity_safe(title or "", url or "", fpath or ""),
        "hostname": hostname,
        "server_user_id": SERVER_USER_ID,
        "device_id": get_device_id(),
        "ctx": snapshot_ctx(),
        "current_client_id": current_client_id,
        "current_client_name": current_client_name,
        "agent_version": APP_VERSION,
        "inference": inference_dict,
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
        f"[EVENT] {int(duration)}s • {app_name} • {title or '(no title)'} "
        f"• url={url or '-'} • path={fpath or '-'}"
        + (f" • toolish({tool_reason})" if toolish else "")
        + client_msg
    )



def handle_client_confirmed(client_id, client_name, prompt_data):
    """Called when user confirms a client via GUI."""
    try:
        payload = {
            "client_id": client_id,
            "confidence": prompt_data.get("confidence", 0),
            "hostname": platform.node(),
            "device_id": get_device_id(),
            "os_username": get_os_username(),
        }
        http_post_json(CONTEXT_CONFIRM_URL, payload, 
                      api_headers(get_os_username(), platform.node()), timeout=6)
        
        api_key = config.get("api_key") or API_KEY
        if api_key and API_BASE:
            set_current_client_on_backend(API_BASE, api_key, client_id=client_id)
        
        log(f"[GUI] Client confirmed and set: {client_name}")
    except Exception as e:
        log(f"[GUI] confirm error: {e}")

    # Update notification state
    if notif_manager:
        notif_manager.set_current_client(client_id, client_name)

    # ADD: Inform AI switcher
    if ai_switcher:
        ai_switcher.on_manual_switch(client_id, client_name)


def handle_client_rejected(prompt_data):
    """Called when user rejects a client via GUI"""
    try:
        payload = {
            "client_id": prompt_data.get("client_id"),
            "confidence": prompt_data.get("confidence", 0),
            "hostname": platform.node(),
            "device_id": get_device_id(),
            "os_username": get_os_username(),
        }
        http_post_json(CONTEXT_REJECT_URL, payload,
                      api_headers(get_os_username(), platform.node()), timeout=6)
        log(f"[GUI] Client rejected")
    except Exception as e:
        log(f"[GUI] reject error: {e}")

def fetch_today_time():
    """Fetch today's time for GUI display"""
    api_key = config.get("api_key") or API_KEY
    if not api_key or not API_BASE:
        print("[GUI] No API key or API_BASE configured")
        return []
    
    url = f"{API_BASE}/today-time/"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
            print(f"[GUI] Today's time data: {len(data.get('clients', []))} clients, {data.get('global_hours', 0)} hrs")
            
            # API returns {"clients": [...], "global_hours": ..., ...}
            if isinstance(data, dict):
                return data  # Return the whole dict
            if isinstance(data, list):
                return data  # Legacy format
            return []
    except urllib.error.HTTPError as e:
        print(f"[GUI] HTTP {e.code} fetching today's time")
        return []
    except Exception as e:
        print(f"[GUI] Failed to fetch today's time: {e}")
        return []

def on_client_switch_from_menu(client_id: int, client_name: str):
    """Called when user manually switches client from menu bar."""
    if hasattr(gui_menu_bar, "state"):
        gui_menu_bar.state.set_client(client_id, client_name)
    
    api_key = config.get("api_key") or API_KEY
    if api_key and API_BASE:
        success = set_current_client_on_backend(
            API_BASE, api_key, 
            client_id=client_id,
            client_name=client_name
        )
        if success:
            print(f"[CLIENT] Switched to: {client_name}")
        else:
            print(f"[CLIENT] Failed to sync switch to backend")
    
    if hasattr(gui_menu_bar, "updateMenu_"):
        gui_menu_bar.updateMenu_(None)

    if notif_manager:
        notif_manager.set_current_client(client_id, client_name)

    # === ADD THIS: Tell AI switcher about manual choice ===
    if ai_switcher:
        ai_switcher.on_manual_switch(client_id, client_name)

# ---------------- Main loop ----------------
def run_agent():
    """Main agent function with GUI integration."""
    global API_KEY
    global sync
    global notif_manager
    global ai_switcher
    global gui_menu_bar

        # === Set macOS activation policy (MUST be in run_agent, never at module level) ===
    if sys.platform == 'darwin':
        try:
            from AppKit import NSApplication, NSApp, NSBundle
            NSApplication.sharedApplication()
            NSApp.setActivationPolicy_(1)  # Accessory - menu bar only
            info = NSBundle.mainBundle().infoDictionary()
            info["LSUIElement"] = "1"
            print("[INIT] Set macOS activation policy to Accessory")
        except Exception as e:
            print(f"[INIT] Could not set activation policy: {e}")

    # === FORCED UPDATE CHECK ===
    from update_checker import check_for_update_blocking, start_background_checker
    check_for_update_blocking(API_BASE, APP_VERSION)

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    start_context_bus(CONTEXT_PORT)

    # Setup sleep/wake handler to prevent morning stalls
    try:
        from AppKit import (
            NSWorkspace,
            NSWorkspaceDidWakeNotification,
            NSWorkspaceWillSleepNotification,
        )

        _last_sleep_time = [time.time()]  # list so inner functions can mutate

        def on_sleep(notification):
            _last_sleep_time[0] = time.time()
            log("[SLEEP] System going to sleep")

        def on_wake(notification):
            global _wake_idle_bypass_until
            sleep_duration = time.time() - _last_sleep_time[0]

            # Brief wake (Power Nap, display sleep, short lid close) — don't restart.
            # The freeze bug this exit fix was built for only occurs after real sleep.
            if sleep_duration < 60:
                log(f"[WAKE] Brief wake ({int(sleep_duration)}s) — skipping restart")
                _wake_idle_bypass_until = time.time() + 10
                try:
                    from update_checker import notify_wake as _notify_wake
                    _notify_wake()
                except Exception:
                    pass
                return

            log(f"[WAKE] System woke after {int(sleep_duration)}s — exiting for LaunchAgent restart")
            _wake_idle_bypass_until = time.time() + 30

            try:
                from update_checker import notify_wake as _notify_wake
                _notify_wake()
            except Exception:
                pass

            try:
                ship_logs_to_backend(tail_lines=100, trigger="pre_wake_exit")
            except Exception:
                pass

            def _restart():
                time.sleep(3)
                log("[WAKE] Forcing exit — LaunchAgent will restart cleanly")
                os._exit(1)  # Non-zero exit → LaunchAgent KeepAlive restarts us

            threading.Thread(target=_restart, daemon=True).start()

        nc = NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidWakeNotification,
            None,
            None,
            on_wake
        )
        nc.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceWillSleepNotification,
            None,
            None,
            on_sleep
        )
        print("[SLEEP] Sleep/wake handler registered")
    except Exception as e:
        print(f"[SLEEP] Could not register wake handler: {e}")

    # === CHECK FOR VERSION UPGRADE ===
    cached_version = config.get("last_app_version")
    if cached_version and cached_version != APP_VERSION:
        log(f"[UPGRADE] Version changed {cached_version} → {APP_VERSION}")
        sync_cache = os.path.expanduser("~/.timetracker/sync_cache.json")
        if os.path.exists(sync_cache):
            try:
                os.remove(sync_cache)
                log("[UPGRADE] Cleared sync cache - will fetch fresh data")
            except Exception as e:
                log(f"[UPGRADE] Failed to clear sync cache: {e}")
    
    # Save current version
    config["last_app_version"] = APP_VERSION
    save_config(config)

    print("=== Mac Activity Agent starting… (Ctrl+C to stop) ===", flush=True)
    if os.path.exists(CONFIG_FILE): 
        log(f"CONFIG={CONFIG_FILE} (loaded)")
    else: 
        log(f"CONFIG={CONFIG_FILE} (not found, using ENV)")

    log(f"DB_PATH={DB_PATH}")
    log(f"API_BASE={API_BASE}")
    log(f"POST_URL={POST_URL}")
    log(f"HELLO_URL={HELLO_URL}")
    log(f"CONTROL_URL={CONTROL_URL} (poll {CONTROL_POLL_S}s)")
    log(f"AX_AVAILABLE={AX_AVAILABLE}")
    log(f"POLL_SECONDS={POLL_SECONDS}, MIN_DWELL_SECONDS={MIN_DWELL_SECONDS}")
    if EXCLUDE_BUNDLES: 
        log(f"EXCLUDE_BUNDLES={sorted([b for b in EXCLUDE_BUNDLES if b])}")
    try:
        log(f"[NUDGE] enabled={NUDGE_ENABLED} poll={GUESS_POLL_SECONDS}s conf=[{GUESS_MIN_CONF:.2f}..{GUESS_MAX_CONF:.2f}] snooze={NUDGE_SNOOZE_MIN}m timeout={NUDGE_TIMEOUT_SEC}s")
    except Exception:
        pass

    os_user = get_os_username()
    hostname = platform.node()
    device_id = get_device_id()

    # PID file
    write_pid()

    # Ensure we have a device key (MDM → GUI → pair code → interactive terminal)
    key = config.get("api_key") or API_KEY
    
    if not key:
        # Try the org token IT deployed, before asking a human anything.
        #
        # This used to call register_with_org_token(), which posts to
        # /agent/register/ — an endpoint that find-or-creates a user from the
        # OS short name and invents an email like dan@yourfirm.local. That put
        # Mac users in a different identity namespace from the one Windows
        # pairs into, and it could not work regardless: the view raises
        # TypeError on user.groups.add(org), and the key it returns lives in
        # AgentRegistration, which AgentKeyAuthentication never reads.
        #
        # mdm_deploy walks the same three endpoints the Windows agent does, so
        # a Mac now pairs to whoever the DeviceProvisioningMap says owns it.
        # See mac_agent/PROVISIONING.md.
        # A deliberate Re-link must ASK, never silently re-pair. The org token
        # lives in the MDM plist under /Library, which the user cannot clear,
        # so without this the claim below would run on the next start and put
        # the device straight back on whoever DeviceProvisioningMap names —
        # making Re-link Device useless on exactly the managed fleets it
        # matters most for. Consumed once, so the NEXT start (or a fresh
        # deploy) auto-pairs normally.
        relink = bool(config.pop("relink_requested", False))
        if relink:
            save_config(config)
            log("[MDM] Re-link was requested — skipping the org-token claim "
                "so you can choose an account")

        mdm_config = None if relink else get_mdm_config()
        if mdm_config:
            log("[MDM] Found a deployed configuration — claiming with the org token")
            org_token = (mdm_config.get('OrgToken')
                         or mdm_config.get('org_token') or '').strip()
            api_endpoint = (mdm_config.get('ApiEndpoint')
                            or mdm_config.get('api_endpoint') or API_BASE)
            if org_token:
                # The claim writes api_key back into `config`, so hand it the
                # real one and let it persist through save_config.
                config['org_token'] = org_token
                config['api_base'] = api_endpoint
                config['os_username'] = os_user
                try:
                    from mdm_deploy import do_org_token_claim
                    key = do_org_token_claim(config, save_config, api_endpoint,
                                             APP_VERSION, get_device_id(), log=log)
                except Exception as e:
                    log(f"[MDM] Claim raised {type(e).__name__}: {e}")
                    key = None
                if key:
                    API_KEY = key
                else:
                    log("[MDM] Org token claim did not pair this Mac — "
                        "falling back to manual pairing")
            else:
                log("[MDM] Deployed config carries no OrgToken")
        
        # Fallback to interactive pairing (GUI or terminal)
        if not key:
            key = ensure_api_key_interactive(hostname)
        
        if not key:
            print("Exiting: no device key configured.")
            print("Options:")
            print("  1. Deploy MDM config to /Library/Application Support/TimeTracker/config.plist")
            print("  2. Run the app to show the pairing window")
            print("  3. Set AGENT_PAIR_CODE environment variable")
            remove_pid()
            return

    # Hello (with key)
    # Hello (with key)
    if not hello(HELLO_URL, os_user, hostname, device_id):
        log("[HELLO] First hello failed - retrying with backoff...")
        hello_success = False
        for attempt in range(4):
            wait = 5 * (attempt + 1)
            log(f"[HELLO] Retry {attempt + 1}/4 in {wait}s...")
            time.sleep(wait)
            if hello(HELLO_URL, os_user, hostname, device_id):
                hello_success = True
                log("[HELLO] ✅ Connected on retry")
                break
        
        if not hello_success:
            log("[HELLO] All retries failed — running in offline mode (key preserved)")
            # DON'T drop key. Server may be temporarily down.


    # === SYNC INITIALIZATION ===
    # === SYNC INITIALIZATION ===
    sync = None
    api_key = config.get("api_key") or API_KEY
    if api_key:
        from agent_sync_integration import AgentSync
        
        sync = AgentSync(
            api_base=API_BASE,
            device_token=api_key  # Use the paired device key
        )
        
        def on_sync_update():
            log(f"[SYNC] Data updated: {len(sync.clients)} clients")

            if sync.gui_menu_bar and hasattr(sync.gui_menu_bar, 'refresh_client_menu'):
                sync.gui_menu_bar.refresh_client_menu(sync.clients)
                log("[SYNC] GUI menu refreshed")
            else:
                log("[SYNC] GUI not ready yet")

            # Apply org settings delivered in /sync/full/ payload
            if hasattr(sync, 'org_settings') and sync.org_settings:
                new_idle_s = sync.org_settings.get("mouse_idle_pause_seconds")
                if new_idle_s is not None:
                    global MOUSE_IDLE_PAUSE_S
                    new_idle_s = int(new_idle_s)
                    if new_idle_s != MOUSE_IDLE_PAUSE_S:
                        log(f"[SYNC] Idle timeout updated: {MOUSE_IDLE_PAUSE_S}s → {new_idle_s}s")
                        MOUSE_IDLE_PAUSE_S = new_idle_s

        sync.on_update = on_sync_update
        sync.start()  # Start background polling
        log(f"[SYNC] Started - polling every {sync.poll_interval}s")

# === PUSH NOTIFICATION SYSTEM ===
    global notif_manager
    notif_worker = None
    gui_menu_bar = None

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
            def _do():
                log(f"[NOTIF] User confirmed: {client_name} (ID: {client_id})")
                api_key = config.get("api_key") or API_KEY
                if api_key and API_BASE:
                    set_current_client_on_backend(API_BASE, api_key, client_id=client_id)
                if gui_menu_bar:
                    if hasattr(gui_menu_bar, 'state'):
                        gui_menu_bar.state.set_client(client_id, client_name)
                    if hasattr(gui_menu_bar, 'app') and gui_menu_bar.app:
                        gui_menu_bar.app.title = f"⏱ {client_name}" if client_name else "⏱ None"
                    # === FIX: Refresh the Switch Client submenu checkmarks ===
                    if hasattr(gui_menu_bar, 'updateMenu_'):
                        gui_menu_bar.updateMenu_(None)
                    elif hasattr(gui_menu_bar, 'refresh_client_menu') and sync and sync.clients:
                        gui_menu_bar.refresh_client_menu(sync.clients)
                if notif_manager:
                    notif_manager.set_current_client(client_id, client_name)
                # === FIX: Tell AI switcher ===
                if ai_switcher:
                    ai_switcher.on_manual_switch(client_id, client_name)
            threading.Thread(target=_do, daemon=True).start()
                
        def on_notif_switch():
            """Handle user requesting client switch from notification"""
            def _do():
                log("[NOTIF] User requested client switch - opening picker")
                if gui_menu_bar and hasattr(gui_menu_bar, 'app'):
                    try:
                        gui_menu_bar.app._on_search(None)
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
        
        if notif_manager.ready:
            log("[NOTIF] ✅ Push notification system ready")
            
            # Start the notification worker thread
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
                poll_interval=30,
            )
            notif_worker.start()
            log("[NOTIF] Notification worker started")
            
            # Check for timesheet review on startup
            def check_startup_timesheet():
                try:
                    time.sleep(3)  # Wait for app to fully initialize
                    
                    api_key = config.get("api_key") or API_KEY
                    if not api_key or not API_BASE:
                        log("[NOTIF] Startup review: no API key")
                        return
                    
                    url = f"{API_BASE}/agent/startup-notification/"
                    req = urllib.request.Request(url, method="GET")
                    req.add_header("Authorization", f"DeviceKey {api_key}")
                    req.add_header("Content-Type", "application/json")
                    
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read())
                    
                    if not data.get("show_notification"):
                        log("[NOTIF] Startup timesheet review: nothing to review")
                        return
                    
                    title = data.get("title", "⏰ Review Your Timesheet")
                    message = data.get("message", "You have hours from yesterday to review.")
                    subtitle = data.get("subtitle")
                    
                    log(f"[NOTIF] Startup review: {data.get('hours', 0)}h, {data.get('unassigned', 0)} unassigned")
                    
                    if NOTIF_AVAILABLE and NOTIF_ENABLED:
                        from UserNotifications import UNNotificationSound, UNTimeIntervalNotificationTrigger
                        content = UNMutableNotificationContent.alloc().init()
                        content.setTitle_(title)
                        content.setBody_(message)
                        if subtitle:
                            content.setSubtitle_(subtitle)
                        content.setSound_(UNNotificationSound.defaultSound())
                        content.setCategoryIdentifier_("TIMETRACKER_TIMESHEET_REVIEW")
                        
                        trigger = UNTimeIntervalNotificationTrigger.triggerWithTimeInterval_repeats_(3, False)
                        req_id = f"timesheet-review-{int(time.time())}"
                        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                            req_id, content, trigger
                        )
                        UNUserNotificationCenter.currentNotificationCenter().addNotificationRequest_withCompletionHandler_(
                            request, None
                        )
                        log("[NOTIF] ✅ Startup timesheet review notification sent")
                    elif not NOTIF_ENABLED:
                        log("[NOTIF] Startup timesheet review suppressed "
                            "(notifications disabled)")
                    else:
                        log("[NOTIF] No notification framework available")

                    # from datetime import date, timedelta
                    # yesterday = (date.today() - timedelta(days=1)).isoformat()
                    # review_url = data.get("url", f"https://timetracker.mavops.ai/daily?date={yesterday}")
                    
                    # notif_manager._send_notification(
                    #     notif_type=NotificationType.PERIODIC_CHECKIN,
                    #     title=title,
                    #     body=message,
                    #     subtitle=subtitle,
                    #     category_id="TIMETRACKER_TIMESHEET_REVIEW",
                    #     data={"url": review_url},
                    #     delay_seconds=3,
                    # )
                    # log("[NOTIF] ✅ Startup timesheet review notification sent via manager")
                    
                except urllib.error.HTTPError as e:
                    body = ""
                    try: body = e.read().decode()[:200]
                    except: pass
                    log(f"[NOTIF] Startup review HTTP {e.code}: {body}")
                except Exception as e:
                    log(f"[NOTIF] Startup review failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            threading.Thread(target=check_startup_timesheet, daemon=True).start()

        else:
            log("[NOTIF] ⚠️ Push notifications not authorized")
            notif_manager = None
    else:
        if not PUSH_NOTIF_AVAILABLE:
            log("[NOTIF] Push notifications not available (module not found)")
        elif not NOTIF_ENABLED:
            log("[NOTIF] Push notifications disabled by config")

    def _on_gui_client_switch(client_id):
        """Called when user picks a client from the GUI menu."""
        set_current_client_backend(API_BASE, api_key, client_id)
        if ai_switcher:
            cname = None
            if sync and sync.clients:
                for c in sync.clients:
                    if c.get("id") == client_id:
                        cname = c.get("name")
                        break
            ai_switcher.on_manual_switch(client_id, cname or "Unknown")
        if notif_manager:
            cname_for_notif = None
            if sync and sync.clients:
                for c in sync.clients:
                    if c.get("id") == client_id:
                        cname_for_notif = c.get("name")
                        break
            notif_manager.set_current_client(client_id, cname_for_notif)

    # === GUI INITIALIZATION (after pairing succeeds) ===
    # === GUI INITIALIZATION (after pairing succeeds) ===
    # === GUI INITIALIZATION (after pairing succeeds) ===
    gui_menu_bar = None
    quick_switcher = None
    # _hotkey_global_monitor = None   # ADD
    # _hotkey_local_monitor = None    # ADD
    if GUI_AVAILABLE:
        try:
            gui_menu_bar = run_gui_app(
                on_client_confirmed=handle_client_confirmed,
                on_client_rejected=handle_client_rejected,
                get_today_time=fetch_today_time,
                fetch_clients=lambda: fetch_clients_from_backend(API_BASE, API_KEY),
                set_current_client=lambda client_id: _on_gui_client_switch(client_id),
                get_current_client=lambda: get_current_client_backend(API_BASE, API_KEY),
                repair_callback=_gui_pair_callback,
                sync=sync,
            )
            log("[GUI] Menu bar initialized")
            
            # Register GUI with sync
            if sync and gui_menu_bar:
                sync.gui_menu_bar = gui_menu_bar
                if sync.clients and hasattr(gui_menu_bar, 'refresh_client_menu'):
                    gui_menu_bar.refresh_client_menu(sync.clients)
                    log(f"[GUI] Refreshed menu with {len(sync.clients)} clients from sync")
            
            # === QUICK SWITCHER (Option+Shift+T) ===
            # === QUICK SWITCHER (Ctrl+Option+T) ===
            # === QUICK SWITCHER (Ctrl+Option+T) ===
            try:
                from pynput import keyboard
                
                # Track pressed modifier keys
                _pressed_keys = set()
                _hotkey_listener = None
                
                def on_key_press(key):
                    """Track key presses for hotkey detection"""
                    try:
                        # Track modifiers
                        if key == keyboard.Key.ctrl or key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                            _pressed_keys.add('ctrl')
                        elif key == keyboard.Key.alt or key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
                            _pressed_keys.add('alt')
                        elif hasattr(key, 'char') and key.char and key.char.lower() == 't':
                            # Check if Ctrl+Alt+T is pressed
                            if 'ctrl' in _pressed_keys and 'alt' in _pressed_keys:
                                log("[QUICK] Ctrl+Option+T pressed!")
                                if gui_menu_bar and gui_menu_bar.app:
                                    def show_picker():
                                        try:
                                            gui_menu_bar.app._on_search(None)
                                        except Exception as e:
                                            log(f"[QUICK] Error showing picker: {e}")
                                    threading.Thread(target=show_picker, daemon=True).start()
                    except Exception as e:
                        # Silently ignore errors to prevent crashes
                        pass
                
                def on_key_release(key):
                    """Track key releases"""
                    try:
                        if key == keyboard.Key.ctrl or key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                            _pressed_keys.discard('ctrl')
                        elif key == keyboard.Key.alt or key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
                            _pressed_keys.discard('alt')
                    except Exception:
                        pass
                
                # Use Listener instead of GlobalHotKeys (more reliable on macOS)
                _hotkey_listener = keyboard.Listener(
                    on_press=on_key_press,
                    on_release=on_key_release,
                    suppress=False  # Don't block other apps from seeing keys
                )
                _hotkey_listener.start()
                log("[QUICK] ✅ Ready - Ctrl+Option+T (⌃⌥T)")
                
            except ImportError:
                log("[QUICK] pynput not installed - hotkey disabled (pip install pynput)")
            except Exception as e:
                log(f"[QUICK] Failed to setup hotkey: {e}")
                import traceback
                traceback.print_exc()
                    
        except Exception as e:
            log(f"[GUI] Failed to initialize: {e}")

    log("=== DEBUG: GUI init complete, continuing... ===")  # ADD THIS LINE
    
    # Restore client state from backend

    # Restore client state from backend
    api_key = config.get("api_key") or API_KEY
    if api_key and API_BASE and gui_menu_bar:
        try:
            log("[CLIENT] Fetching current client from backend...")
            current = get_current_client_from_backend(API_BASE, api_key)
            
            if current and current.get("client_id"):
                if hasattr(gui_menu_bar, "state"):
                    gui_menu_bar.state.set_client(
                        current["client_id"], 
                        current["client_name"]
                    )
                    log(f"[CLIENT] Restored from backend: {current['client_name']}")
            else:
                log("[CLIENT] No current client set on backend")
            
            if hasattr(gui_menu_bar, '_sync_from_backend'):
                gui_menu_bar._sync_from_backend()
            
        except Exception as e:
            log(f"[CLIENT] Failed to restore client state: {e}")

    # === STARTUP: Prompt for client if none selected ===
    # === STARTUP: Prompt for client if none selected ===
    _startup_prompt_done = False  # Flag to run only once

    def prompt_client_on_startup():
        """Show client picker on startup if no client is selected"""
        nonlocal _startup_prompt_done
        if _startup_prompt_done:
            return
        _startup_prompt_done = True
        
        import time
        time.sleep(2)  # Wait for GUI to fully initialize
        
        # Check LOCAL state first (faster, already loaded)
        if gui_menu_bar and hasattr(gui_menu_bar, 'state'):
            if gui_menu_bar.state.current_client_id:
                log(f"[STARTUP] Client already set locally: {gui_menu_bar.state.current_client_name}")
                return
        
        # Fallback: check backend
        api_key = config.get("api_key") or API_KEY
        if not api_key or not API_BASE:
            return
        
        try:
            current = get_current_client_from_backend(API_BASE, api_key)
            
            if not current or not current.get("client_id"):
                log("[STARTUP] No client selected - showing client picker")
                
                if gui_menu_bar and hasattr(gui_menu_bar, 'app') and gui_menu_bar.app:
                    def show_picker():
                        time.sleep(0.5)
                        try:
                            gui_menu_bar.app._on_search(None)
                        except Exception as e:
                            log(f"[STARTUP] Failed to show picker: {e}")
                    
                    threading.Thread(target=show_picker, daemon=True).start()
            else:
                log(f"[STARTUP] Client already set: {current.get('client_name')}")
                
        except Exception as e:
            log(f"[STARTUP] Error checking client: {e}")

    # Start the startup prompt in background
    if gui_menu_bar:
        threading.Thread(target=prompt_client_on_startup, daemon=True).start()

    # Notifications setup
    # Notifications setup (OLD system - skip if new system is active)
    if not notif_manager:
        try:
            if NOTIFIER.setup():
                log("[NOTIF] Ready (UNUserNotificationCenter).")
            else:
                log("[NOTIF] Not ready; will fallback to AppleScript prompt.")
        except Exception as e:
            log(f"[NOTIF] setup exception: {e}")
    else:
        log("[NOTIF] Skipping old notification system (new system active)")

    # Guess/Nudge worker
    stop_flag = threading.Event()
    t_guess = None
    try:
        if NUDGE_ENABLED:
            t_guess = threading.Thread(
                target=guess_worker,
                args=(hostname, os_user, stop_flag, gui_menu_bar, notif_manager),  # ← add notif_manager
                daemon=True
            )
            t_guess.start()
    except Exception as e:
        log(f"[NUDGE] failed to start worker: {e}")

    # ... GUI INITIALIZATION section (already exists) ...
    # ... Restore client state from backend (already exists) ...
    # ... Startup prompt (already exists) ...

    # === AI CLIENT SWITCHER (must be after GUI + notif_manager are ready) ===
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

        # Sync ai_switcher's state with current client
        if gui_menu_bar and hasattr(gui_menu_bar, "state"):
            cid = gui_menu_bar.state.current_client_id
            cname = gui_menu_bar.state.current_client_name
            if cid:
                ai_switcher.set_current_client(cid, cname)

        # Keep client list fresh when sync updates
        if sync:
            _original_on_sync = sync.on_update
            def _on_sync_with_switcher():
                if _original_on_sync:
                    _original_on_sync()
                ai_switcher.update_clients(sync.clients)
                # Push org client patterns (Tier-0 rules) to switcher
                if hasattr(sync, 'client_patterns') and sync.client_patterns:
                    ai_switcher.update_client_patterns(sync.client_patterns)
                # Tier -1 org routing rules — the highest-priority matcher.
                # These never reached the Mac agent before: the switcher had
                # no update_routing_rules() and sync never fetched them.
                if hasattr(sync, 'routing_rules'):
                    ai_switcher.update_routing_rules(sync.routing_rules or [])
                # Push org AI sensitivity setting to the switcher on every sync
                if hasattr(sync, 'org_settings') and sync.org_settings:
                    ai_sensitivity = sync.org_settings.get("ai_sensitivity", 50)
                    ai_switcher.update_sensitivity(ai_sensitivity)
                    # Vendor ticker gate → hands-off unless enabled for this org.
                    _sw = bool(sync.org_settings.get("show_client_widget", False))
                    _set_show_client_widget(_sw)
                    try:
                        if gui_menu_bar is not None and hasattr(
                            gui_menu_bar, "set_client_widget_enabled"
                        ):
                            gui_menu_bar.set_client_widget_enabled(_sw)
                    except Exception as _e:
                        log(f"[TICKER] set_client_widget_enabled failed: {_e}")
            sync.on_update = _on_sync_with_switcher
            # Push anything that arrived before the switcher existed
            if hasattr(sync, 'routing_rules') and sync.routing_rules:
                ai_switcher.update_routing_rules(sync.routing_rules)

        log(f"[AI-SWITCH] ✅ Initialized")
    except ImportError:
        log("[AI-SWITCH] ai_client_switcher.py not found — disabled")
    except Exception as e:
        log(f"[AI-SWITCH] Init failed: {e}")

    # === FINDER FOLDER WATCHER ===
    # A Finder window's title is only the folder's leaf name ("2024 1040"),
    # which names no client. Its path is "/Users/dan/Clients/Varacchi/2024
    # 1040", which names one. The tracking loop only ever saw the title, so
    # browsing a client's folder produced no signal. This feeds the path.
    finder_watcher = None
    try:
        from finder_watcher import FinderFolderWatcher

        if ai_switcher:
            finder_watcher = FinderFolderWatcher(
                ai_switcher=ai_switcher,
                log_fn=log,
                poll_seconds=2.0,
                enabled=True,
            )
            finder_watcher.start()
    except ImportError:
        log("[FINDER] finder_watcher.py not found — folder signal disabled")
    except Exception as e:
        log(f"[FINDER] Init failed: {e}")

    # === MEETING DETECTOR ===
    meeting_detector = None
    if MEETING_DETECTOR_AVAILABLE:
        try:
            def _get_fg_title():
                """Foreground window title, for browser-hosted meetings."""
                try:
                    front = get_frontmost_app()
                    if front:
                        _app, _bundle, pid, fallback_title = front
                        return get_window_title_via_ax(pid) or fallback_title
                except Exception:
                    pass
                return None

            def _on_meeting_start(state):
                log(f"[MEETING] Started: {state.app} — {state.title or '(no title)'}")

            def _on_meeting_end(state):
                dur = int(state.ended_at - state.started_at) if state.started_at else 0
                log(f"[MEETING] Ended: {state.app} ({dur}s)")

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
    else:
        log("[MEETING] Module not available — meeting capture disabled")

    _tracking_stop_event = threading.Event()

    # Heartbeat timestamp — updated at top of every loop iteration.
    # mac_watchdog fires os._exit(1) if this goes stale > 90s.
    _last_detect_heartbeat = heartbeat_touch()  # initializes to time.time()

    # Idle wall-clock timestamp — set when entering idle, cleared on exit.
    # Used by the idle safety cap to prevent multi-hour idle blocks.
    _idle_entered_at: float = 0.0
    _IDLE_WALL_CAP_SECONDS = 1800  # 30 minutes — matches Windows _IDLE_WATCHDOG_MAX_MINUTES


    # === TRACKING LOOP FUNCTION ===

    def tracking_loop():
        import traceback  # ensure available for format_exc() calls in except blocks
        global _last_subscription_check, _subscription_active
        nonlocal _last_detect_heartbeat, _idle_entered_at

        """Main tracking loop - monitors frontmost app and records dwell time"""
        print("[TRACKING] Initializing...")
        
        try:
            conn = ensure_db()
            cur = conn.cursor()
        except Exception as e:
            log_error(f"[TRACKING] ❌ Failed to init DB: {e}")
            report_error_to_backend("tracking_init", str(e), traceback.format_exc())
            return
        
        # ── Dwell state ──
        current_sig = None
        dwell_start = None          # epoch when this dwell began
        last_emit_ts = None         # epoch of the last event emitted for it
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10
        LOCK_SCREEN_BUNDLES = {"com.apple.loginwindow", "com.apple.ScreenSaver.Engine"}
        LOCK_SCREEN_APPS = {"loginwindow", "screensaverengine"}

        def _emit_current_dwell(end_ts: float):
            """Emit events covering [last_emit_ts → end_ts].

            Each event reads the live client at write time, so a mid-dwell
            AI-switcher flip applies to the next heartbeat rather than
            rewriting the ones already sent.

            An interval longer than MAX_EVENT_DURATION_S is split, so no
            single event claims more than ~5 minutes.
            """
            nonlocal last_emit_ts
            if current_sig is None or last_emit_ts is None:
                return
            if end_ts <= last_emit_ts:
                return
            if (end_ts - last_emit_ts) < 1.0:
                return

            cursor_ts = last_emit_ts
            while cursor_ts < end_ts:
                chunk_end = min(cursor_ts + MAX_EVENT_DURATION_S, end_ts)
                write_event(
                    conn, cur, os_user, hostname, current_sig,
                    start_ts=cursor_ts,
                    end_ts=chunk_end,
                )
                cursor_ts = chunk_end

            last_emit_ts = end_ts

        def _start_new_dwell(sig, start_ts: float):
            """Enter a new dwell."""
            nonlocal current_sig, dwell_start, last_emit_ts
            current_sig = sig
            dwell_start = start_ts
            last_emit_ts = start_ts
            cid, _ = _get_cached_client()
            log(f"[DWELL] Started {sig[0]} • {(sig[2] or '')[:40]} • client={cid}")

        def _clear_dwell():
            nonlocal current_sig, dwell_start, last_emit_ts
            current_sig = None
            dwell_start = None
            last_emit_ts = None

        try:
            while not _tracking_stop_event.is_set():
                try:
                    # ── Heartbeat: MUST be first ──────────────────────────────────
                    # If anything below blocks (osascript hang, Quartz freeze after
                    # wake), this timestamp goes stale and mac_watchdog fires
                    # os._exit(1) after WATCHDOG_FROZEN_THRESHOLD (90s).
                    _last_detect_heartbeat = heartbeat_touch()
                    progress_tick()

                    # ── Drain meeting detector events ──
                    # The detector runs on its own thread; sqlite belongs to
                    # this one, so it queues and we write. Start and end are
                    # 1-second marker events — the compactor turns the pair
                    # into the meeting block.
                    if meeting_detector:
                        for kind, state in meeting_detector.drain_events():
                            try:
                                if kind == "start":
                                    sig = _meeting_sig(state.app, state.title)
                                    write_event(
                                        conn, cur, os_user, hostname, sig,
                                        start_ts=state.started_at,
                                        end_ts=state.started_at + 1.0,
                                    )
                                    log(f"[MEETING] START event: {sig[0]} / {sig[2]}")
                                elif kind == "end":
                                    sig = ("Meeting-End", f"meeting:{state.app}",
                                           state.title or "", None, None)
                                    write_event(
                                        conn, cur, os_user, hostname, sig,
                                        start_ts=state.ended_at,
                                        end_ts=state.ended_at + 1.0,
                                    )
                                    log("[MEETING] END event written")
                            except Exception as e:
                                log(f"[MEETING] Failed to write {kind} event: {e}")

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
                    
                    # ── SUSPEND RECOVERY: Detect time gaps (sleep/Power Nap) ──
                    if not hasattr(tracking_loop, '_last_iter_time'):
                        tracking_loop._last_iter_time = time.time()
                    
                    now_t = time.time()
                    iter_gap = now_t - tracking_loop._last_iter_time
                    tracking_loop._last_iter_time = now_t
                    
                    _suspended = iter_gap > 60
                    
                    if _wake_event.is_set() or _suspended:
                        _wake_event.clear()
                        
                        record_wake_event()
                        if _suspended:
                            log(f"[TRACKING] ⏰ Thread was suspended for {int(iter_gap)}s (sleep or Power Nap)")
                        else:
                            log("[TRACKING] 🔄 Wake event detected — resetting tracking state")
                        
                        if current_sig and last_emit_ts and current_sig != IDLE_SIG:
                            # Close the dwell at the moment the machine went
                            # away, not at the moment it came back — otherwise
                            # the sleep itself is billed as work.
                            # _last_iter_time was already advanced to now_t
                            # above, so the last tick before the gap is
                            # now_t - iter_gap.
                            pre_suspend_ts = (now_t - iter_gap) if _suspended else now_t
                            try:
                                _emit_current_dwell(min(pre_suspend_ts, now_t))
                                log(f"[TRACKING] Flushed pre-suspend dwell")
                            except Exception as e:
                                log(f"[TRACKING] Failed to flush dwell: {e}")

                        _clear_dwell()
                        
                        time.sleep(10)
                        continue

                    if should_stop(CONTROL_URL, os_user, hostname):
                        log("[CTRL] Stopping agent per admin request.")
                        break

                    idle = mouse_idle_seconds()
                    
                    # ── FIX: Check for lock screen BEFORE idle timer ──
                    force_idle = False
                    front_peek = get_frontmost_app()
                    if front_peek:
                        peek_app, peek_bundle, peek_pid, peek_title = front_peek
                        if (peek_bundle and peek_bundle.lower() in LOCK_SCREEN_BUNDLES) or \
                           (peek_app and peek_app.lower() in LOCK_SCREEN_APPS) or \
                           (peek_title and "lock screen" in (peek_title or "").lower()):
                            force_idle = True
                            if current_sig != IDLE_SIG:
                                log(f"[IDLE] Lock screen detected ({peek_app}/{peek_bundle}) → entering idle immediately")

                    # Check if currently in a meeting (meetings skip idle)
                    in_meeting = False
                    if current_sig and current_sig != IDLE_SIG:
                        app_name, bundle_id, title, url, fpath = current_sig
                        in_meeting = is_in_meeting(bundle_id, url, app_name, title)

                    # A live camera or mic counts as working, even when the
                    # site is one nobody whitelisted — see
                    # _capture_holds_idle_open().
                    if _capture_holds_idle_open(idle):
                        in_meeting = True
                    
                    # ── IDLE ENTRY: lock screen, or mouse idle (unless in meeting) ──
                    _in_wake_bypass = time.time() < _wake_idle_bypass_until
                    if not _in_wake_bypass and (force_idle or (idle >= MOUSE_IDLE_PAUSE_S and not in_meeting)):
                        if current_sig != IDLE_SIG:
                            if notif_manager:
                                try:
                                    notif_manager.on_idle_start()
                                except Exception as e:
                                    log(f"[TRACKING] notif on_idle_start error: {e}", "warning")
                                    report_error_to_backend("notification", str(e), traceback.format_exc(), 
                                                          {"event": "on_idle_start"})
                            now = time.time()
                            # The user stopped working when the input stopped,
                            # not when the idle timer finally noticed. Close the
                            # work dwell there and open the idle dwell there.
                            if force_idle:
                                effective_end = now
                            else:
                                effective_end = now - max(0.0, idle - MOUSE_IDLE_PAUSE_S)
                            if current_sig and last_emit_ts:
                                _emit_current_dwell(max(effective_end, last_emit_ts))
                            idle_start = now if force_idle else (now - min(idle, MOUSE_IDLE_PAUSE_S))
                            _start_new_dwell(IDLE_SIG, idle_start)
                            _idle_entered_at = time.time()
                            record_idle_enter()

                            # Was this the user stepping away, or the loop
                            # freezing / the machine sleeping? The second kind
                            # is not a real absence, and recording it puts a
                            # multi-hour Idle block in someone's day that they
                            # then have to explain. Drop it.
                            if _TRACKING_HEALTH:
                                verdict = classify_idle(idle, MOUSE_IDLE_PAUSE_S)
                                if verdict.kind == IdleKind.UNINTENTIONAL:
                                    log(f"[IDLE] ⚠️ Unintentional ({verdict.reason}) — skipping")
                                    _clear_dwell()
                                    _idle_entered_at = 0.0
                                    record_idle_exit()
                                    # Sleep before re-checking. Without it the
                                    # `continue` below skips the poll sleep and,
                                    # because the dwell was just cleared, the
                                    # loop re-enters this branch every tick — a
                                    # busy-loop that spams the log and pins a
                                    # core through a long AFK. Same fix as
                                    # windows_agent 6061b952.
                                    time.sleep(POLL_SECONDS)
                                    _last_detect_heartbeat = heartbeat_touch()
                                    consecutive_errors = 0
                                    continue
                            if not force_idle:
                                log(f"[IDLE] Entered idle (mouse idle {int(idle)}s ≥ {MOUSE_IDLE_PAUSE_S}s)")
                        
                        # ── Idle wall-clock safety cap ─────────────────────────────
                        # Prevents multi-hour idle blocks caused by Power Nap or
                        # partial wake cycles where os._exit(1) didn't fire cleanly.
                        if _idle_entered_at > 0 and current_sig == IDLE_SIG:
                            wall_idle = time.time() - _idle_entered_at
                            if wall_idle > _IDLE_WALL_CAP_SECONDS:
                                log(
                                    f"[IDLE-CAP] ⚠️ Idle wall-clock cap hit "
                                    f"({int(wall_idle)}s > {_IDLE_WALL_CAP_SECONDS}s) — "
                                    f"force-flushing idle block"
                                )
                                report_error_to_backend(
                                    "idle_wall_cap",
                                    f"Idle cap hit: {int(wall_idle)}s",
                                    context={
                                        "wall_idle_seconds": wall_idle,
                                        "hostname": platform.node(),
                                    },
                                )
                                if last_emit_ts:
                                    _emit_current_dwell(time.time())
                                _clear_dwell()
                                _idle_entered_at = 0.0
                                continue

                        if force_idle:
                            time.sleep(POLL_SECONDS * 3)
                        else:
                            time.sleep(POLL_SECONDS)
                        _last_detect_heartbeat = heartbeat_touch()
                        consecutive_errors = 0
                        continue

                    # ── MEETING: idle mouse but in a meeting → flush periodically, don't go idle ──
                    elif in_meeting and idle >= MOUSE_IDLE_PAUSE_S:
                        now = time.time()
                        # A meeting is the one place the user legitimately sits
                        # still for an hour. The heartbeat carries it: no
                        # special flush interval, same cadence as everything
                        # else, so a meeting can never become one giant event.
                        if last_emit_ts and (now - last_emit_ts) >= HEARTBEAT_INTERVAL_S:
                            chunk_seconds = now - last_emit_ts
                            _emit_current_dwell(now)
                            log(f"[MEETING] Flushed {int(chunk_seconds)}s meeting chunk for {current_sig[0]} "
                                f"(total dwell {int(now - dwell_start)}s, mouse idle {int(idle)}s)")
                        
                        if PRINT_EVERY_POLL or (int(idle) % 60 < POLL_SECONDS):
                            log(f"[MEETING] In meeting ({current_sig[0]}), skipping idle check "
                                f"(mouse idle {int(idle)}s, dwell {int(now - dwell_start)}s)")
                        time.sleep(POLL_SECONDS)
                        _last_detect_heartbeat = heartbeat_touch()
                        consecutive_errors = 0
                        continue

                    # ── ACTIVE: user is back or was never idle ──
                    else:
                        # Exit idle if we were idle
                        if current_sig == IDLE_SIG and dwell_start:
                            if notif_manager:
                                try:
                                    notif_manager.on_idle_end()
                                except Exception as e:
                                    log(f"[TRACKING] notif on_idle_end error: {e}", "warning")
                                    report_error_to_backend("notification", str(e), traceback.format_exc(),
                                                          {"event": "on_idle_end"})
                            dwell = time.time() - dwell_start
                            record_idle_exit()
                            if last_emit_ts:
                                _emit_current_dwell(time.time())
                                log(f"[IDLE] Exited idle; recorded {int(dwell)}s idle dwell.")
                            _clear_dwell()
                            _idle_entered_at = 0.0  # clear on idle exit


                    # ── FIX: Reuse the peek we already did (no double call) ──
                    front = front_peek
                    if front:
                        _last_detect_heartbeat = heartbeat_touch()
                    if not front:
                        if PRINT_EVERY_POLL:
                            log("[POLL] No frontmost")
                        time.sleep(POLL_SECONDS)
                        consecutive_errors = 0
                        continue

                    app_name, bundle_id, pid, fallback_title = front

                    if bundle_id in EXCLUDE_BUNDLES:
                        if PRINT_EVERY_POLL:
                            log(f"[POLL] Excluded: {bundle_id}")
                        if current_sig and last_emit_ts:
                            _emit_current_dwell(time.time())
                        _clear_dwell()
                        time.sleep(POLL_SECONDS)
                        consecutive_errors = 0
                        continue

                    title_ax = get_window_title_via_ax(pid) or ""
                    title = title_ax or (fallback_title or "")

                    extras = try_get_url_or_path(bundle_id)
                    url, fpath = extras.get("url"), extras.get("file_path")
                    
                    # FIX 3: Retry URL capture for potential meeting apps
                    # Critical for Chrome-based Teams/Meet where URL fetch can fail
                    if bundle_id in MEETING_BUNDLES and not url:
                        title_lower = (title or "").lower()
                        # Only retry if title suggests a meeting
                        meeting_title_hints = [
                            "google meet", "meet -", "meeting", "zoom", 
                            "teams", "microsoft teams", "webex", "- call",
                            "teams.microsoft.com", "teams.live.com",
                            "meet.google.com",
                        ]
                        if any(hint in title_lower for hint in meeting_title_hints):
                            for retry in range(2):
                                time.sleep(0.2)
                                extras = try_get_url_or_path(bundle_id)
                                url = extras.get("url")
                                if url:
                                    log(f"[MEETING] URL captured on retry {retry+1}: {url[:80]}")
                                    fpath = extras.get("file_path")
                                    break
                            if not url:
                                log(f"[MEETING] URL retry failed for {bundle_id}, title='{title[:60]}' "
                                    f"- will rely on title-based detection")

                    sig = (app_name, bundle_id, title, url, fpath)

                    now_loop = time.time()

                    if sig != current_sig:
                        if current_sig and last_emit_ts:
                            _emit_current_dwell(now_loop)
                        _start_new_dwell(sig, now_loop)
                        record_window_change()

                        # Snapshot inference for the NEW window so the menu bar
                        # shows the right client within a poll, instead of
                        # waiting up to HEARTBEAT_INTERVAL_S for the next emit.
                        _compute_window_inference_snapshot(
                            app_name, bundle_id, title, url, fpath
                        )
                        # The snapshot just refreshed the cache; show it.
                        _sync_ticker_to_inference()

                                                # === AI CLIENT SWITCHER: Check new window ===
                        if ai_switcher:
                            _in_mtg = is_in_meeting(bundle_id, url, app_name, title)
                            ai_switcher.on_window_change(
                                app_name=app_name,
                                exe_name=bundle_id or "",  # Mac uses bundle_id instead of exe_name
                                title=title or "",
                                url=url,
                                file_path=fpath,
                                in_meeting=_in_mtg,
                            )
                        # === END AI SWITCHER ===                        
                        if is_in_meeting(bundle_id, url, app_name, title):
                            log(f"[FOCUS] {app_name} • {title or '(no title)'} • url={url or '-'} • path={fpath or '-'} • [MEETING]")
                        else:
                            log(f"[FOCUS] {app_name} • {title or '(no title)'} • url={url or '-'} • path={fpath or '-'}")

                        # === Local client detection ===
                        # === Local client detection (fallback for low-confidence) ===
                        if not ai_switcher:
                            # No AI switcher — use old notification system
                            try:
                                detected = detect_client_in_window(title, fpath)
                                current_id = None
                                if gui_menu_bar and hasattr(gui_menu_bar, 'state'):
                                    current_id = gui_menu_bar.state.current_client_id
                                maybe_suggest_client(detected, current_id)
                            except Exception as e:
                                log(f"[TRACKING] client detection error: {e}", "warning")
                    else:
                        # Same window as last poll. Emit a heartbeat once the
                        # interval is up, so long focused work reaches the
                        # server as it happens rather than being withheld
                        # until the user finally looks away.
                        if last_emit_ts and (now_loop - last_emit_ts) >= HEARTBEAT_INTERVAL_S:
                            _emit_current_dwell(now_loop)
                        if PRINT_EVERY_POLL:
                            log(f"[POLL] dwelling {int(now_loop - dwell_start)}s • {app_name}")

                    time.sleep(POLL_SECONDS)
                    consecutive_errors = 0

                    # === AI SWITCHER: Check if pending switch met dwell threshold ===
                    if ai_switcher:
                        ai_switcher.on_dwell_tick()

                except Exception as e:
                    consecutive_errors += 1
                    error_context = {
                        "current_sig": str(current_sig) if current_sig else None,
                        "dwell_start": dwell_start,
                        "consecutive_errors": consecutive_errors,
                    }
                    
                    log_error(f"[TRACKING] ⚠️ Error in loop iteration ({consecutive_errors}): {e}")
                    import traceback
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
            if current_sig and last_emit_ts:
                _emit_current_dwell(time.time())
        except Exception as e:
            log_error(f"[TRACKING] ❌ Fatal error: {e}")
            import traceback
            tb = traceback.format_exc()
            traceback.print_exc()
            report_error_to_backend("tracking_fatal", str(e), tb)
        finally:
            log("[TRACKING] Cleaning up...")
            try:
                conn.close()
                if stop_flag:
                    stop_flag.set()
                if t_guess is not None:
                    t_guess.join(timeout=2.0)
            except Exception:
                pass
            if notif_worker:
                notif_worker.stop()
            if finder_watcher:
                try:
                    finder_watcher.stop()
                except Exception:
                    pass
            if meeting_detector:
                try:
                    meeting_detector.stop()
                except Exception:
                    pass
            remove_pid()

    # === START TRACKING THREAD ===
    print("=== DEBUG: About to start tracking thread ===")  # ADD THIS LINE
    tracking_thread = threading.Thread(target=tracking_loop, daemon=False)
    tracking_thread.start()
    print("[TRACKING] Started tracking thread")

    # === RE-CHECK FOR UPDATES EVERY HOUR ===
    start_background_checker(API_BASE, APP_VERSION)

    # === LOG SHIPPING (every 30 min → backend visibility for remote debugging) ===
    start_log_shipping(interval_minutes=30)
    # === WATCHDOG: Detect dead OR frozen tracking thread ===
    # Uses mac_watchdog.py heartbeat system (ported from Windows watchdog.py).
    # Detects hard freezes (osascript/Quartz blocking) via heartbeat staleness.
    # On freeze/death: os._exit(1) → LaunchAgent KeepAlive restarts cleanly.
    if MAC_WATCHDOG_AVAILABLE:
        _thread_ref = [tracking_thread]
        start_watchdog(_thread_ref, tracking_loop, log, report_error_to_backend)
    else:
        log("[WATCHDOG] ⚠️ mac_watchdog not available — running without freeze detection")

    # === RUN GUI IN MAIN THREAD ===
    if gui_menu_bar and GUI_AVAILABLE:
        from AppKit import NSApp
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

    # === ADD CLEANUP HERE ===
    # Cleanup hotkey monitor
    if '_hotkey_listener' in dir() and _hotkey_listener:
        try:
            _hotkey_listener.stop()
            log("[QUICK] Hotkey listener stopped")
        except:
            pass
    
    if sync:
        sync.stop()
        log("[SYNC] Stopped")
    # === END CLEANUP ===

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
    # Skip CLI parsing for multiprocessing children
    if _is_multiprocessing_child:
        return
    
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