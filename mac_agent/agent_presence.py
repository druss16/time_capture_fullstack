"""
agent_presence.py — MEASUREMENT ONLY: how much AI-agent activity is there on
this machine, and how much of it is the tracker currently mistaking for a
person?

Nothing here changes time attribution. It counts, and once an hour it posts the
counts to /api/agent-presence/. Shared verbatim by windows_agent/ and
mac_agent/ — keep the two copies identical.

WHY
---
The tracker measures a person by the foreground window plus "seconds since
last input". Both OS calls it uses for the second part (GetLastInputInfo on
Windows, the combined session state on macOS) count SYNTHETIC input too. So:

  * an agent that drives the screen (computer use, Power Automate Desktop,
    UiPath, AutoHotkey) looks exactly like the person working — its time is
    being booked as human time today;
  * an agent that acts inside a browser page (Claude in Chrome, ChatGPT agent)
    produces no OS input at all, so it shows up as foreground windows changing
    while the person is "idle";
  * a background agent (Claude Code, Codex) has neither and is invisible.

Four signals, one per blind spot, none of which can prompt the user for a new
permission:

  1. clicks       real vs synthetic mouse clicks. Windows: raw input, where
                  SendInput-injected events arrive with hDevice == NULL.
                  macOS: a listen-only event tap reading the sender's PID —
                  only if Input Monitoring was ALREADY granted (preflight,
                  never request). On macOS the raw sender names are recorded
                  rather than judged, because what hardware events report as
                  their sender is not yet verified on real machines.
  2. idle_changes foreground app/title changing while input has been idle
                  >= IDLE_ACTIVITY_S — the in-browser agent's footprint (and
                  also slideshows, auto-refreshing pages: hence per-app).
  3. processes    known agent programs running, and how much CPU they burned.
  4. local logs   how many Claude Code / Codex sessions wrote to their local
                  logs (file mtimes only; contents are never opened).
  5. unattended   macOS only, and needs NO permission: seconds the tracker's
     active      idle clock (combined session state, which counts posted
                  events) says "active" while the hardware-only HID clock says
                  nobody has touched anything for IDLE_ACTIVITY_S. That is the
                  mis-booked time itself, measured directly — and it works on
                  the Macs where signal 1 cannot (no Input Monitoring).
                  Unverified until fleet data: an automation tool that posts
                  with a HID-state event source may move the HID clock too.

Privacy: app/process NAMES and counts only. No window titles, no keystrokes,
no click positions, no log contents ever leave the machine.
"""
from __future__ import annotations

import glob
import os
import sys
import threading
import time
from datetime import datetime, timezone

BUCKET_S = 3600
FOREGROUND_POLL_S = 5 if sys.platform == "win32" else 10
PROCESS_POLL_S = 60
LOG_POLL_S = 300
SEND_POLL_S = 300
IDLE_ACTIVITY_S = 60
BUSY_CPU_S = 1.0          # CPU seconds in one process sample = "busy minute"
MAX_PENDING_BUCKETS = 72  # three days offline, then the oldest are dropped
MAX_NAMES = 25            # per-bucket cap on any name->count map

# Lowercased process name (".exe" stripped) -> label. Deliberately short and
# certain; extend as the data shows what customers actually run.
KNOWN_AGENT_PROCESSES = {
    "claude": "claude",               # desktop app or Claude Code; split below
    "codex": "codex",
    "chatgpt": "chatgpt_desktop",
    "chatgpt atlas": "chatgpt_atlas",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "copilot": "microsoft_copilot",
    "m365copilot": "microsoft_copilot",
    "pad.robot": "power_automate",
    "pad.console.host": "power_automate",
    "uirobot": "uipath",
    "uipath.executor": "uipath",
    "autohotkey": "autohotkey",
    "autohotkey64": "autohotkey",
    "autohotkeyu64": "autohotkey",
}
# Agents shipped as node scripts: the process is "node", the cmdline says who.
NODE_AGENT_MARKERS = {
    "claude-code": "claude_code",
    "@openai/codex": "codex",
}


def _proc_name(name: str) -> str:
    name = (name or "").strip().lower()
    return name[:-4] if name.endswith(".exe") else name


def classify_process(name: str, exe: str = "", cmdline=None) -> str | None:
    """The agent label for a process, or None if it is not a known agent."""
    n = _proc_name(name)
    if n == "node":
        joined = " ".join(cmdline or []).lower()
        for marker, label in NODE_AGENT_MARKERS.items():
            if marker in joined:
                return label
        return None
    exe_l = (exe or "").lower()
    if n == "chrome-native-host":
        # The bridge Claude in Chrome talks through; generic name, so only
        # when it ships inside Claude.
        return "claude_in_chrome" if "claude" in exe_l else None
    label = KNOWN_AGENT_PROCESSES.get(n)
    if label == "claude":
        # The desktop app and Claude Code share a name — and the desktop app
        # runs its own Claude Code from .../Claude/claude-code/<ver>/claude.app.
        if "claude-code" in exe_l:
            return "claude_code"
        return "claude_desktop" if (".app/" in exe_l or "anthropicclaude" in exe_l) else "claude_code"
    return label


def _bump(d: dict, key: str, by=1):
    key = (key or "unknown")[:64]
    if key in d or len(d) < MAX_NAMES:
        d[key] = d.get(key, 0) + by
    else:
        d["_other"] = d.get("_other", 0) + by


def _bucket_start(ts: float) -> int:
    return int(ts // BUCKET_S * BUCKET_S)


def _new_bucket(start: int) -> dict:
    return {
        "bucket_start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
        "seconds_observed": 0,
        "idle_seconds": 0,
        "remote_session": False,
        "input_monitor": "off",
        "clicks_real": 0,
        "clicks_synthetic": 0,
        "synthetic_by": {},      # Windows: foreground app at the click; macOS: sender
        "idle_changes": 0,
        "idle_changes_by_app": {},
        "unattended_active_seconds": 0,
        "unattended_active_by_app": {},
        "processes": {},         # label -> {seen_min, busy_min, cpu_s}
        "local_sessions": {},    # tool -> distinct session logs written
    }


class Collector:
    """Thread-safe hourly buckets. Every public method is safe to call from
    any thread and never raises."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[int, dict] = {}
        self._session_files: dict[int, dict[str, set]] = {}
        self.input_monitor = "off"
        self.remote_session = False
        self._last_fg = None
        self._last_cpu: dict[int, float] = {}

    def _bucket(self, now: float) -> dict:
        start = _bucket_start(now)
        b = self._buckets.get(start)
        if b is None:
            b = self._buckets[start] = _new_bucket(start)
        return b

    # ── signal 1: clicks ──
    def note_click(self, synthetic: bool, source: str = "", now: float | None = None):
        with self._lock:
            b = self._bucket(now or time.time())
            if synthetic:
                b["clicks_synthetic"] += 1
                _bump(b["synthetic_by"], source)
            else:
                b["clicks_real"] += 1

    # ── signal 2: foreground changes while idle ──
    def note_foreground(self, app: str, title: str, idle_s: float, interval_s: float,
                        now: float | None = None, hid_idle_s: float | None = None):
        fg = (app or "", title or "")
        with self._lock:
            b = self._bucket(now or time.time())
            b["seconds_observed"] += int(interval_s)
            # The tracker would book this interval (recent input on its clock)
            # but no physical input has happened in a while: software input.
            if hid_idle_s is not None and idle_s < interval_s + 2 \
                    and hid_idle_s >= IDLE_ACTIVITY_S:
                b["unattended_active_seconds"] += int(interval_s)
                _bump(b["unattended_active_by_app"], _proc_name(app), int(interval_s))
            if idle_s >= IDLE_ACTIVITY_S:
                b["idle_seconds"] += int(interval_s)
                if self._last_fg is not None and fg != self._last_fg:
                    b["idle_changes"] += 1
                    _bump(b["idle_changes_by_app"], _proc_name(app))
            self._last_fg = fg

    # ── signal 3: agent processes ──
    def note_processes(self, samples, interval_s: float, now: float | None = None):
        """samples: iterable of (pid, label, cpu_seconds_total)."""
        with self._lock:
            b = self._bucket(now or time.time())
            seen_cpu = {}
            per_label: dict[str, float] = {}
            for pid, label, cpu_total in samples:
                prev = self._last_cpu.get(pid)
                delta = max(cpu_total - prev, 0.0) if prev is not None else 0.0
                seen_cpu[pid] = cpu_total
                per_label[label] = per_label.get(label, 0.0) + delta
            self._last_cpu = seen_cpu
            minutes = max(int(round(interval_s / 60)), 1)
            for label, cpu in per_label.items():
                p = b["processes"].setdefault(label, {"seen_min": 0, "busy_min": 0, "cpu_s": 0.0})
                p["seen_min"] += minutes
                if cpu >= BUSY_CPU_S:
                    p["busy_min"] += minutes
                p["cpu_s"] = round(p["cpu_s"] + cpu, 1)

    # ── signal 4: local agent logs ──
    def note_session_files(self, tool: str, paths_with_mtime, now: float | None = None):
        """Count each log written since the last scan in the CURRENT hour.

        Never the hour of its mtime: that hour may already have been sent,
        and re-creating it would post a near-empty bucket over the real one.
        """
        now = now or time.time()
        start = _bucket_start(now)
        with self._lock:
            files = self._session_files.setdefault(start, {}).setdefault(tool, set())
            files.update(os.path.basename(p) for p, _ in paths_with_mtime)
            self._bucket(now)["local_sessions"][tool] = len(files)

    def take_closed(self, now: float | None = None) -> list[dict]:
        """Buckets whose hour has ended. They stay pending until mark_sent."""
        cur = _bucket_start(now or time.time())
        with self._lock:
            out = []
            for start in sorted(self._buckets):
                if start < cur:
                    b = self._buckets[start]
                    b["input_monitor"] = self.input_monitor
                    b["remote_session"] = b["remote_session"] or self.remote_session
                    out.append(dict(b))
            return out

    def mark_sent(self, buckets: list[dict]):
        sent = {b["bucket_start"] for b in buckets}
        with self._lock:
            for start in list(self._buckets):
                if self._buckets[start]["bucket_start"] in sent:
                    del self._buckets[start]
                    self._session_files.pop(start, None)
            # Offline for days: drop the oldest rather than grow forever.
            while len(self._buckets) > MAX_PENDING_BUCKETS:
                oldest = min(self._buckets)
                del self._buckets[oldest]
                self._session_files.pop(oldest, None)


# ──────────────────────────────────────────────
# Platform input monitors
# ──────────────────────────────────────────────

def _start_windows_input_monitor(collector: Collector, get_foreground, log):
    """Raw input, mouse only, button-downs only.

    Raw input rather than a low-level hook on purpose: WM_INPUT is delivered
    asynchronously, so a busy agent can never add latency to the user's mouse
    (a WH_MOUSE_LL callback stuck behind the GIL can), and it is not the
    keyboard-hook pattern endpoint security products flag as a keylogger.
    SendInput-injected events arrive with RAWINPUTHEADER.hDevice == NULL.
    Unverified on real fleets: whether RDP/Citrix input or touch-promoted
    clicks also arrive with a NULL device. remote_session and synthetic_by
    are recorded so the data can show it before anything relies on this.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    collector.remote_session = bool(user32.GetSystemMetrics(0x1000))  # SM_REMOTESESSION

    WM_INPUT = 0x00FF
    RID_INPUT = 0x10000003
    RIM_TYPEMOUSE = 0
    RIDEV_INPUTSINK = 0x00000100
    BUTTON_DOWNS = 0x0001 | 0x0004 | 0x0010  # left, right, middle
    HWND_MESSAGE = wintypes.HWND(-3)

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                    ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]

    class _BTN(ctypes.Structure):
        _fields_ = [("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT)]

    class _BTNU(ctypes.Union):
        _fields_ = [("ulButtons", wintypes.ULONG), ("b", _BTN)]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [("usFlags", wintypes.USHORT), ("u", _BTNU),
                    ("ulRawButtons", wintypes.ULONG), ("lLastX", wintypes.LONG),
                    ("lLastY", wintypes.LONG), ("ulExtraInformation", wintypes.ULONG)]

    class RAWINPUT(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                    ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                       ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    user32.CreateWindowExW.restype = wintypes.HWND

    buf = RAWINPUT()
    hdr_size = ctypes.sizeof(RAWINPUTHEADER)

    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            try:
                size = wintypes.UINT(ctypes.sizeof(buf))
                if user32.GetRawInputData(lparam, RID_INPUT, ctypes.byref(buf),
                                          ctypes.byref(size), hdr_size) > 0 \
                        and buf.header.dwType == RIM_TYPEMOUSE \
                        and buf.mouse.u.b.usButtonFlags & BUTTON_DOWNS:
                    synthetic = not buf.header.hDevice
                    source = ""
                    if synthetic:
                        fg = get_foreground()
                        source = _proc_name(fg[0]) if fg else ""
                    collector.note_click(synthetic, source)
            except Exception:
                pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run():
        try:
            proc = WNDPROC(wndproc)
            run.proc = proc  # keep the callback alive
            wc = WNDCLASSW()
            wc.lpfnWndProc = proc
            wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            wc.lpszClassName = "TimeTrackerAgentPresence"
            user32.RegisterClassW(ctypes.byref(wc))
            hwnd = user32.CreateWindowExW(0, wc.lpszClassName, None, 0, 0, 0, 0, 0,
                                          HWND_MESSAGE, None, wc.hInstance, None)
            dev = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)
            if not hwnd or not user32.RegisterRawInputDevices(ctypes.byref(dev), 1,
                                                              ctypes.sizeof(dev)):
                collector.input_monitor = "error"
                log("[PRESENCE] raw input registration failed")
                return
            collector.input_monitor = "ok"
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            collector.input_monitor = "error"
            log(f"[PRESENCE] input monitor stopped: {e}")

    threading.Thread(target=run, name="agent-presence-input", daemon=True).start()


def _start_mac_input_monitor(collector: Collector, log):
    """Listen-only tap on mouse-downs, reading the sender's PID.

    Only runs if Input Monitoring is ALREADY granted: CGPreflightListenEventAccess
    never prompts, and a measurement must not pop a permission dialog on a
    customer's machine. Hardware events are expected to carry sender PID 0;
    that is unverified, so the sender NAME is recorded for every click and the
    data decides.
    """
    import Quartz as Q
    try:
        import psutil
    except ImportError:
        psutil = None

    if not Q.CGPreflightListenEventAccess():
        collector.input_monitor = "no_permission"
        return

    own_pid = os.getpid()
    names: dict[int, str] = {}

    def name_of(pid: int) -> str:
        if pid not in names:
            try:
                names[pid] = psutil.Process(pid).name() if psutil else f"pid{pid}"
            except Exception:
                names[pid] = "exited"
        return names[pid]

    state = {}

    def callback(proxy, etype, event, refcon):
        try:
            if etype in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
                Q.CGEventTapEnable(state["tap"], True)
                return event
            pid = Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUnixProcessID)
            if pid == own_pid:
                return event
            if pid == 0:
                collector.note_click(False)
            else:
                collector.note_click(True, name_of(pid))
        except Exception:
            pass
        return event

    def run():
        try:
            mask = (Q.CGEventMaskBit(Q.kCGEventLeftMouseDown)
                    | Q.CGEventMaskBit(Q.kCGEventRightMouseDown)
                    | Q.CGEventMaskBit(Q.kCGEventOtherMouseDown))
            tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap,
                                     Q.kCGEventTapOptionListenOnly, mask, callback, None)
            if tap is None:
                collector.input_monitor = "error"
                return
            state["tap"] = tap
            src = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
            Q.CFRunLoopAddSource(Q.CFRunLoopGetCurrent(), src, Q.kCFRunLoopCommonModes)
            Q.CGEventTapEnable(tap, True)
            collector.input_monitor = "ok"
            Q.CFRunLoopRun()
        except Exception as e:
            collector.input_monitor = "error"
            log(f"[PRESENCE] input monitor stopped: {e}")

    threading.Thread(target=run, name="agent-presence-input", daemon=True).start()


# ──────────────────────────────────────────────
# Pollers
# ──────────────────────────────────────────────

def mac_hid_idle_seconds() -> float:
    """Seconds since the last PHYSICAL keyboard/mouse/scroll event, on the same
    event types the Mac tracker's mouse_idle_seconds() reads — but from the
    HID system state, which posted (synthetic) events are not expected to
    update. Needs no permission."""
    import Quartz as Q
    st = Q.kCGEventSourceStateHIDSystemState
    return float(min(Q.CGEventSourceSecondsSinceLastEventType(st, t)
                     for t in (Q.kCGEventMouseMoved, Q.kCGEventKeyDown, Q.kCGEventScrollWheel)))


def sample_agent_processes():
    """[(pid, label, cpu_seconds_total)] for running known agents."""
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = p.info.get("name") or ""
            n = _proc_name(name)
            if n not in ("node", "chrome-native-host") and n not in KNOWN_AGENT_PROCESSES:
                continue
            exe = cmd = None
            if n in ("claude", "chrome-native-host"):
                exe = p.exe()
            if n == "node":
                cmd = p.cmdline()
            label = classify_process(name, exe or "", cmd)
            if label:
                t = p.cpu_times()
                out.append((p.pid, label, t.user + t.system))
        except Exception:
            continue
    return out


def recent_session_logs(home: str, since: float):
    """{tool: [(path, mtime)]} for agent session logs written since `since`.

    Only directory listings and mtimes — no file is opened.
    """
    found = {}
    patterns = {
        "claude_code": [os.path.join(home, ".claude", "projects", "*", "*.jsonl")],
        "codex": [os.path.join(home, ".codex", "sessions", time.strftime("%Y/%m/%d", time.localtime(t)), "*.jsonl")
                  for t in (since, time.time())],
    }
    for tool, pats in patterns.items():
        hits = {}
        for pat in pats:
            for path in glob.glob(pat):
                try:
                    m = os.path.getmtime(path)
                except OSError:
                    continue
                if m >= since:
                    hits[path] = m
        if hits:
            found[tool] = list(hits.items())
    return found


def start(get_foreground, get_idle, post, log, enabled=True, get_hid_idle=None):
    """Start measuring. Returns the Collector, or None if disabled.

    get_foreground() -> (app_or_exe, title) | None
    get_idle()       -> seconds since last input, as the tracker sees it
    post(payload)    -> raises on failure
    get_hid_idle()   -> seconds since last PHYSICAL input (macOS), optional
    """
    if not enabled:
        log("[PRESENCE] disabled by config")
        return None
    collector = Collector()

    try:
        if sys.platform == "win32":
            _start_windows_input_monitor(collector, get_foreground, log)
        elif sys.platform == "darwin":
            _start_mac_input_monitor(collector, log)
    except Exception as e:
        collector.input_monitor = "error"
        log(f"[PRESENCE] input monitor unavailable: {e}")

    home = os.path.expanduser("~")

    def loop():
        last = {"fg": 0.0, "proc": 0.0, "logs": time.time() - BUCKET_S, "send": time.time()}
        while True:
            now = time.time()
            try:
                if now - last["fg"] >= FOREGROUND_POLL_S:
                    fg = get_foreground()
                    if fg:
                        collector.note_foreground(
                            fg[0], fg[1], get_idle(), FOREGROUND_POLL_S, now,
                            hid_idle_s=get_hid_idle() if get_hid_idle else None)
                    last["fg"] = now
                if now - last["proc"] >= PROCESS_POLL_S:
                    collector.note_processes(sample_agent_processes(), PROCESS_POLL_S, now)
                    last["proc"] = now
                if now - last["logs"] >= LOG_POLL_S:
                    for tool, files in recent_session_logs(home, last["logs"] - 60).items():
                        collector.note_session_files(tool, files, now)
                    last["logs"] = now
                if now - last["send"] >= SEND_POLL_S:
                    last["send"] = now
                    closed = collector.take_closed(now)
                    if closed:
                        post({"buckets": closed})
                        collector.mark_sent(closed)
            except Exception as e:
                log(f"[PRESENCE] {type(e).__name__}: {e}")
            time.sleep(1)

    threading.Thread(target=loop, name="agent-presence", daemon=True).start()
    log("[PRESENCE] measuring agent activity (counts only)")
    return collector
