"""macOS privacy permissions: what TimeTracker holds, and getting the rest.

Apple will not let an app grant itself Accessibility or Automation. What we
can do is make sure nobody is left silently degraded:

* Managed Macs get everything from the MDM PPPC profile (see PROVISIONING.md)
  and never see any of this.
* Unmanaged Macs get a TimeTracker-owned setup checklist (setup_checklist.py)
  that shows a live check/cross per permission with a Fix button, a warning
  on the menu-bar icon while anything required is missing, and the same
  status reported to the server so the firm's admin can see which Mac needs
  attention.

macOS's own prompts are one-shot. A dismissed Automation prompt is never shown
again, and the Accessibility prompt is easy to click past. So the checklist,
not the system prompt, is what keeps asking.

Accessibility is an ENHANCEMENT, not a gate. Without it the agent still gets
browser titles from the extension or AppleScript and document names from
AppleScript (title_fallback.py). What it adds is window titles for apps with
no scripting at all — Slack desktop, Figma, Canva.

This module is the state machine plus thin probes. The probes touch macOS;
everything else is plain Python driven by an injected probe object, so the
logic is tested without a Mac (test_permissions.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

# The shipped bundle id (CFBundleIdentifier), which is also the TCC client id.
APP_BUNDLE_ID = "TimeTracker"

AX_PANE_URL = ("x-apple.systempreferences:com.apple.preference.security"
               "?Privacy_Accessibility")
AUTOMATION_PANE_URL = ("x-apple.systempreferences:com.apple.preference.security"
                       "?Privacy_Automation")

# How often to re-check while something is missing. AXIsProcessTrusted() is a
# cheap local call, so 12s costs nothing and makes a grant show up promptly.
RECHECK_MISSING_S = 12
# And while everything is granted: only to notice a revocation.
RECHECK_OK_S = 120
# "Remind me later" puts the checklist away for this long.
REMIND_LATER_S = 4 * 3600
# The browser extension posts to the local context bus about every 30s while
# its browser is open AND IN FRONT — it stays silent while the person works in
# another app, so a quiet extension says nothing about whether it is on. A
# post within this long counts as "on".
EXTENSION_FRESH_S = 5 * 60
# "Off" needs a browser in front this long with no post: the extension posts
# within a second of the browser gaining focus, then every 30s. Two minutes
# also covers a stretch on a new-tab or chrome:// page, which it skips.
EXTENSION_FRONT_GRACE_S = 2 * 60


@dataclass(frozen=True)
class AutomationTarget:
    bundle_id: str
    label: str
    required: bool
    why: str  # what the agent asks this app, for the checklist row


# ---------------------------------------------------------------------------
# THE classification. Edit here to change what the checklist shows and what
# nags.
#
# required=True  -> counts toward "Finish setup (N missing)", the menu-bar
#                   warning, and the checklist re-appearing at launch.
# required=False -> shown with its status, never nags.
#
# Only targets INSTALLED on this Mac are shown. Keep in step with the
# AppleEvents receivers in mavops-pppc-timetracker.mobileconfig.
# ---------------------------------------------------------------------------
AX_REQUIRED = False
AX_BENEFIT = "Also capture window titles in apps like Slack desktop, Figma and Canva"
EXTENSION_REQUIRED = True

AUTOMATION_TARGETS: tuple = (
    # Browsers: the address (and, without Accessibility, the title) of the
    # front tab. Without it a client's portal is just "Google Chrome".
    AutomationTarget("com.google.Chrome", "Google Chrome", True, "the page you are on"),
    AutomationTarget("com.microsoft.edgemac", "Microsoft Edge", True, "the page you are on"),
    AutomationTarget("com.apple.Safari", "Safari", True, "the page you are on"),
    AutomationTarget("com.brave.Browser", "Brave", True, "the page you are on"),
    AutomationTarget("company.thebrowser.Browser", "Arc", True, "the page you are on"),
    # Adobe: which document is in front, and the client folder above it.
    AutomationTarget("com.adobe.Photoshop", "Adobe Photoshop", True, "which file is open"),
    AutomationTarget("com.adobe.illustrator", "Adobe Illustrator", True, "which file is open"),
    AutomationTarget("com.adobe.InDesign", "Adobe InDesign", True, "which file is open"),
    AutomationTarget("com.adobe.Acrobat.Pro", "Adobe Acrobat", True, "which PDF is open"),
    # Optional: useful, never nags.
    AutomationTarget("com.microsoft.Excel", "Microsoft Excel", False, "which workbook is open"),
    AutomationTarget("com.microsoft.Word", "Microsoft Word", False, "which document is open"),
    AutomationTarget("com.microsoft.Powerpoint", "Microsoft PowerPoint", False, "which presentation is open"),
    AutomationTarget("com.apple.finder", "Finder", False, "which folder is open"),
    AutomationTarget("com.apple.systemevents", "System Events", False, "which app is in front"),
)

# Browsers the extension can be installed in.
EXTENSION_BROWSERS = ("com.google.Chrome", "com.microsoft.edgemac",
                      "com.brave.Browser", "company.thebrowser.Browser")

# Automation status values.
GRANTED = "granted"
DENIED = "denied"
NOT_ASKED = "not_asked"          # app running, never asked: we can ask now
NOT_RUNNING = "not_running"      # macOS can only answer while the app runs
UNKNOWN = "unknown"

# AEDeterminePermissionToAutomateTarget results.
_AE_NOERR = 0
_AE_DENIED = -1743               # errAEEventNotPermitted
_AE_WOULD_ASK = -1744            # errAEEventWouldRequireUserConsent
_AE_PROC_NOT_FOUND = -600        # procNotFound: target not running


def ae_code_to_status(code: int) -> str:
    if code == _AE_NOERR:
        return GRANTED
    if code == _AE_DENIED:
        return DENIED
    if code == _AE_WOULD_ASK:
        return NOT_ASKED
    if code == _AE_PROC_NOT_FOUND:
        return NOT_RUNNING
    return UNKNOWN


def osascript_denied(returncode: int, stderr: str) -> bool:
    """True if an osascript run failed because Automation is not allowed.

    osascript reports it as error -1743 ("Not authorized to send Apple events
    to <app>."). A script that catches every error itself never gets here,
    which is why the browser scripts in main.py re-raise -1743.
    """
    if returncode == 0:
        return False
    s = (stderr or "").lower()
    return ("-1743" in s or "not authorized to send apple events" in s
            or "not allowed to send apple events" in s)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def disabled_report(now: float) -> dict:
    """The hello2 permission report when `disable_ax` is set in the config.

    No monitor runs then (that is the point of the switch: the macOS 26
    AEDetermine hang), so nothing is probed. Saying so beats saying nothing:
    a silent Mac looked fully healthy on the Devices page while every window
    title was empty, and switching Accessibility on in System Settings does
    nothing until the config switch is removed.
    """
    return {"accessibility": "disabled", "capture_mode": "ax_disabled",
            "checked_at": _iso(now)}


# ---------------------------------------------------------------------------
# macOS probes. Everything that touches the OS lives here; tests swap in a
# fake with the same methods.
# ---------------------------------------------------------------------------
class MacProbes:
    def ax_trusted(self) -> bool:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())

    def ax_prompt(self) -> bool:
        """macOS's own Accessibility prompt (it also adds TimeTracker to the list)."""
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))

    def installed(self, bundle_id: str) -> bool:
        try:
            from AppKit import NSWorkspace
            return NSWorkspace.sharedWorkspace() \
                .URLForApplicationWithBundleIdentifier_(bundle_id) is not None
        except Exception:
            return False

    def running_path(self, bundle_id: str) -> Optional[str]:
        """Bundle path of a running copy, or None. Photoshop 2024-2026 share
        one id; addressing the RUNNING copy by path keeps a prompt from
        launching a different version."""
        try:
            from AppKit import NSRunningApplication
            apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
            for a in apps or []:
                url = a.bundleURL()
                if url is not None:
                    return str(url.path())
        except Exception:
            pass
        return None

    def frontmost_bundle(self) -> Optional[str]:
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return str(app.bundleIdentifier() or "") if app is not None else None
        except Exception:
            return None

    def ae_status(self, bundle_id: str) -> str:
        """Ask macOS, WITHOUT prompting, whether we may script `bundle_id`.

        AEDeterminePermissionToAutomateTarget can block FOREVER. On macOS 26
        (2026-10-07, a More Than Cars M3) it never returned for an app that was
        installed but not running: the very first check at startup hung, so
        the agent paired, then froze before its first hello on every launch —
        no tracking, no menu bar, and clicking the app said "TimeTracker is no
        longer open". So: never ask about an app that is not running (macOS
        would only say procNotFound anyway), and bound every call that is made.
        """
        if self.running_path(bundle_id) is None:
            return NOT_RUNNING
        return _ae_status_bounded(bundle_id)

    def ae_prompt(self, bundle_id: str, app_path: Optional[str]) -> str:
        """Make macOS show "TimeTracker wants to control <app>" now.

        Sent through osascript, as the agent's real scripts are: osascript
        holds Apple's prompting entitlement and macOS attributes the request
        to TimeTracker (its responsible process), so the answer is recorded
        against TimeTracker. Blocks until the person answers (or 120s). The
        event only counts windows; it changes nothing.
        """
        target = (f'application "{app_path}"' if app_path
                  else f'application id "{bundle_id}"')
        try:
            r = subprocess.run(["osascript", "-e", f"tell {target} to count windows"],
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return NOT_ASKED
        except Exception:
            return UNKNOWN
        if r.returncode == 0:
            return GRANTED
        if osascript_denied(r.returncode, r.stderr):
            return DENIED
        return self.ae_status(bundle_id)

    def open_url(self, url: str, bundle_id: Optional[str] = None) -> None:
        """Open a System Settings pane, or (bundle_id) bring an app forward."""
        cmd = ["open", "-b", bundle_id] if bundle_id else ["open", url]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def tcc_reset_accessibility(self) -> bool:
        """Remove TimeTracker's Accessibility row so the next prompt adds a
        fresh one. Runs as the logged-in user — no admin, no SIP change:
        `tccutil reset <service> <bundle id>` only REVOKES, which macOS lets
        a user do. Verified on macOS 15 (system tccd replied 0 to
        TCCAccessResetInternal from uid 501)."""
        try:
            r = subprocess.run(["/usr/bin/tccutil", "reset", "Accessibility",
                                APP_BUNDLE_ID], capture_output=True, text=True,
                               timeout=15)
            return r.returncode == 0
        except Exception:
            return False


_AE = None

# The longest one non-prompting Automation check may hold up its caller. A
# real answer comes back in milliseconds.
AE_STATUS_TIMEOUT_S = 3.0
# Bundle ids whose check is still stuck in macOS. A hung call cannot be
# cancelled, so its thread is left behind; while it is, that app reads UNKNOWN
# rather than starting another thread that would hang the same way.
_ae_pending: set = set()
_ae_pending_lock = threading.Lock()


def _ae_status_bounded(bundle_id: str, determine=None,
                       timeout: float = AE_STATUS_TIMEOUT_S) -> str:
    """ae_code_to_status(_ae_determine(bundle_id, ask=False)), or UNKNOWN if
    macOS has not answered within `timeout`. Never blocks longer than that."""
    determine = determine or _ae_determine
    with _ae_pending_lock:
        if bundle_id in _ae_pending:
            return UNKNOWN
        _ae_pending.add(bundle_id)
    box: dict = {}

    def _run():
        try:
            box["status"] = ae_code_to_status(determine(bundle_id, False))
        except Exception:
            box["status"] = UNKNOWN
        finally:
            with _ae_pending_lock:
                _ae_pending.discard(bundle_id)

    t = threading.Thread(target=_run, daemon=True, name=f"AECheck-{bundle_id}")
    t.start()
    t.join(timeout)
    return box.get("status", UNKNOWN)


def _ae_determine(bundle_id: str, ask: bool) -> int:
    """AEDeterminePermissionToAutomateTarget via ctypes (PyObjC has no binding)."""
    import ctypes
    import struct
    global _AE
    if _AE is None:
        cs = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")

        class AEDesc(ctypes.Structure):
            _fields_ = [("descriptorType", ctypes.c_uint32),
                        ("dataHandle", ctypes.c_void_p)]

        cs.AECreateDesc.argtypes = [ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_long, ctypes.POINTER(AEDesc)]
        cs.AECreateDesc.restype = ctypes.c_int16
        cs.AEDeterminePermissionToAutomateTarget.argtypes = [
            ctypes.POINTER(AEDesc), ctypes.c_uint32, ctypes.c_uint32, ctypes.c_ubyte]
        cs.AEDeterminePermissionToAutomateTarget.restype = ctypes.c_int32
        cs.AEDisposeDesc.argtypes = [ctypes.POINTER(AEDesc)]
        _AE = (cs, AEDesc)
    cs, AEDesc = _AE

    def fcc(s: str) -> int:
        return struct.unpack(">I", s.encode("ascii"))[0]

    desc = AEDesc()
    data = bundle_id.encode("utf-8")
    err = cs.AECreateDesc(fcc("bund"), data, len(data), ctypes.byref(desc))
    if err != 0:
        return int(err)
    try:
        return int(cs.AEDeterminePermissionToAutomateTarget(
            ctypes.byref(desc), fcc("****"), fcc("****"), 1 if ask else 0))
    finally:
        cs.AEDisposeDesc(ctypes.byref(desc))


# ---------------------------------------------------------------------------
# Orphaned executable — the root cause of the grant "dropped" by v1.9.17
# ---------------------------------------------------------------------------
def executable_orphaned(pid: Optional[int] = None) -> bool:
    """True if this process's executable no longer exists on disk.

    The self-update swaps TimeTracker.app/Contents with two renames and then
    deletes the old Contents. launchd's KeepAlive respawned the agent ~50ms
    after the old one exited — BEFORE the swap — so the new process was
    exec'd from the OLD binary, which the helper then deleted. PyInstaller's
    bootloader loaded the NEW Python code from the same path, so the process
    ran, reported v1.9.17 and looked healthy. But tccd identifies a process by
    its executable path (proc_pidpath), which now failed with ENOENT, so it
    could not attribute the process to TimeTracker and denied EVERY TCC
    request: Accessibility (empty titles) AND Automation (empty Chrome URLs),
    while System Settings still showed the switch on. tccd logged
    "proc_pidpath_audittoken() failed from PID[78168]: (#2) No such file or
    directory" (2026-09-30 22:15:32). A restart from the real binary fixes it.
    """
    if sys.platform != "darwin":
        return False
    import ctypes
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        buf = ctypes.create_string_buffer(4096)
        n = lib.proc_pidpath(pid or os.getpid(), buf, 4096)
        if n > 0:
            return False
        return ctypes.get_errno() == 2  # ENOENT; anything else: don't guess
    except Exception:
        return False


def orphan_restart_allowed(state_path: str, now: Optional[float] = None,
                           max_restarts: int = 3, window_s: int = 600) -> bool:
    """Loop guard for the orphan self-restart: at most `max_restarts` in
    `window_s`. Records this attempt when it allows it."""
    now = time.time() if now is None else now
    try:
        with open(state_path) as f:
            stamps = [float(x) for x in json.load(f) if now - float(x) < window_s]
    except Exception:
        stamps = []
    if len(stamps) >= max_restarts:
        return False
    stamps.append(now)
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(stamps, f)
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------
class PermissionMonitor:
    """Live permission state + the rules for when to ask and when to nag.

    tick()/refresh() run on a background thread; the checklist window reads
    rows() on the main thread. Attributes are replaced wholesale, never
    mutated in place, so a reader always sees one consistent value.
    """

    def __init__(self, probes, state_path: str, *,
                 clock: Callable[[], float] = time.time,
                 log: Callable[[str], None] = print,
                 targets: tuple = AUTOMATION_TARGETS,
                 extension_last_seen: Optional[Callable[[], Optional[float]]] = None,
                 version: str = ""):
        self.p = probes
        self.state_path = state_path
        self.clock = clock
        self.log = log
        self.targets = targets
        self.extension_last_seen = extension_last_seen or (lambda: None)
        self.version = version

        self.ax_granted: Optional[bool] = None
        self.automation: Dict[str, str] = {}      # bundle_id -> status
        self.installed: tuple = ()                # AutomationTargets on this Mac
        self.extension: Optional[str] = None      # seen | not_seen | not_running | None
        self._browser_front_since: Optional[float] = None
        self.checked_at: Optional[float] = None
        self.stale_entry_reset = False
        self.ax_prompted_this_launch = False
        self.asking: Optional[str] = None         # label of an in-flight prompt
        self._last_check = 0.0
        self._state = self._load()
        # refresh() runs on the ticker thread AND (checklist open) the main
        # thread; one at a time.
        self._lock = threading.RLock()

    # -- persisted state -----------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.state_path) as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._state, f)
            os.replace(tmp, self.state_path)
        except Exception as e:
            self.log(f"[PERMS] could not save state: {e}")

    # -- probing -------------------------------------------------------------
    def _safe(self, fn, *a, default=None):
        try:
            return fn(*a)
        except Exception:
            return default

    def refresh(self) -> bool:
        with self._lock:
            return self._refresh()

    def _refresh(self) -> bool:
        """Re-read everything. Returns True if anything reportable changed."""
        before = self.report(include_time=False)
        ax = bool(self._safe(self.p.ax_trusted, default=False))
        was = self.ax_granted
        self.ax_granted = ax
        if was is True and not ax:
            self.log("[AX] ⚠️ Accessibility was revoked while running — "
                     "titles now come from the extension/AppleScript only")
        elif was is False and ax:
            self.log("[AX] ✅ Accessibility granted — full window titles resume now (no restart)")

        installed = tuple(t for t in self.targets
                          if self._safe(self.p.installed, t.bundle_id, default=False))
        known = dict(self._state.get("ae_known") or {})
        automation = {}
        for t in installed:
            st = self._safe(self.p.ae_status, t.bundle_id, default=UNKNOWN)
            if st in (GRANTED, DENIED):
                known[t.bundle_id] = st          # remember the last definite answer
            elif st == NOT_ASKED:
                known.pop(t.bundle_id, None)     # open again (e.g. after a reset)
            elif t.bundle_id in known:
                st = known[t.bundle_id]          # macOS can't say now; we can
            automation[t.bundle_id] = st
        self.installed = installed
        self.automation = automation
        if known != (self._state.get("ae_known") or {}):
            self._state["ae_known"] = known
            self._save()

        browsers = [t.bundle_id for t in installed if t.bundle_id in EXTENSION_BROWSERS]
        if browsers:
            now = self.clock()
            seen = self._safe(self.extension_last_seen)
            if self._safe(self.p.frontmost_bundle) in browsers:
                if self._browser_front_since is None:
                    self._browser_front_since = now
            else:
                self._browser_front_since = None
            front = self._browser_front_since
            if seen and now - seen < EXTENSION_FRESH_S:
                self.extension = "seen"
            elif front is not None and now - max(front, seen or 0) >= EXTENSION_FRONT_GRACE_S:
                # The browser has been in front for minutes and the extension
                # has said nothing: it is off or not installed. Only judged
                # while a browser is in front — in the background the
                # extension is silent on purpose.
                self.extension = "not_seen"
            elif seen and any(self._safe(self.p.running_path, b) for b in browsers):
                self.extension = "seen"           # it spoke the last time it could
            else:
                self.extension = NOT_RUNNING      # can't tell until a browser is used
        else:
            self.extension = None
            self._browser_front_since = None

        self.checked_at = self.clock()
        self._last_check = self.checked_at
        return self.report(include_time=False) != before

    def record_observed(self, bundle_id: str, status: str) -> bool:
        with self._lock:
            return self._record_observed(bundle_id, status)

    def _record_observed(self, bundle_id: str, status: str) -> bool:
        """What a REAL capture script just learned (main.py's osascript calls).

        A -1743 from the agent's own capture is the surest denial signal, and
        it puts the row back on the checklist even if the app was not
        running when the checklist last looked. Returns True if the reported
        state changed.
        """
        if status not in (GRANTED, DENIED):
            return False
        if bundle_id not in {t.bundle_id for t in self.targets}:
            return False
        if self.automation.get(bundle_id) == status:
            return False
        self.automation = {**self.automation, bundle_id: status}
        known = dict(self._state.get("ae_known") or {})
        known[bundle_id] = status
        self._state["ae_known"] = known
        self._save()
        if status == DENIED:
            self.log(f"[PERMS] Automation of {bundle_id} is not allowed (-1743) "
                     "— back on the setup checklist")
            self.clear_snooze()
        return True

    # -- startup / periodic --------------------------------------------------
    def startup(self, version_changed: bool) -> None:
        """First check of a launch.

        Accessibility missing right AFTER AN UPGRADE most likely means the
        row in System Settings is stale: switched on but tied to a code
        identity macOS no longer accepts. Toggling does nothing; it must be
        removed and re-added. `tccutil reset` does the removal (no admin), so
        the prompt that follows adds a fresh row. Once per version, never
        otherwise. (The orphaned-executable case is handled BEFORE this, by
        a restart — main.py — so a perfectly good grant is not reset.)
        """
        self.refresh()
        if self.ax_granted is False and version_changed:
            done = list(self._state.get("stale_reset_versions") or [])
            if self.version not in done:
                ok = bool(self._safe(self.p.tcc_reset_accessibility, default=False))
                self.stale_entry_reset = ok
                self._state["stale_reset_versions"] = (done + [self.version])[-10:]
                self._save()
                self.log("[AX] Not trusted right after an upgrade — cleared the stale "
                         f"Accessibility entry (tccutil ok={ok}) so it can be re-added")
        if self.ax_granted is False:
            self.prompt_accessibility(user_clicked=False)

    def prompt_accessibility(self, user_clicked: bool) -> bool:
        """macOS's own prompt: once per launch on its own, plus every time
        the person clicks Fix."""
        if not user_clicked and self.ax_prompted_this_launch:
            return False
        self.ax_prompted_this_launch = True
        try:
            self.p.ax_prompt()
            return True
        except Exception as e:
            self.log(f"[AX] prompt failed: {e}")
            return False

    def due(self) -> bool:
        missing = self.ax_granted is not True or bool(self.missing_required())
        interval = RECHECK_MISSING_S if missing else RECHECK_OK_S
        return self.clock() - self._last_check >= interval

    def tick(self) -> bool:
        """Call every few seconds; does work only when due. Returns True if
        the reported state changed."""
        if not self.due():
            return False
        changed = self.refresh()
        if self.ax_granted is False:
            # Revoked mid-run, or never granted: still only once per launch.
            self.prompt_accessibility(user_clicked=False)
        return changed

    # -- what's missing ------------------------------------------------------
    def missing_required(self) -> List[str]:
        """Labels of REQUIRED permissions that are not granted. An app that
        isn't running is "will ask when you open it", not missing — unless
        macOS already said no."""
        out = []
        if AX_REQUIRED and self.ax_granted is False:
            out.append("Accessibility")
        for t in self.installed:
            if t.required and self.automation.get(t.bundle_id) in (DENIED, NOT_ASKED):
                out.append(t.label)
        if EXTENSION_REQUIRED and self.extension == "not_seen":
            out.append("Browser extension")
        return out

    def recommended_missing(self) -> List[str]:
        return ["Accessibility"] if (not AX_REQUIRED and self.ax_granted is False) else []

    def capture_mode(self) -> Optional[str]:
        """'full' with Accessibility; 'no_accessibility' without (titles come
        from the extension and AppleScript only)."""
        if self.ax_granted is None:
            return None
        return "full" if self.ax_granted else "no_accessibility"

    def needs_attention(self) -> bool:
        return bool(self.missing_required())

    def should_show_checklist(self) -> bool:
        """At launch / when a snooze runs out, while anything required is missing."""
        if not self.needs_attention():
            return False
        return self.clock() >= float(self._state.get("remind_after") or 0)

    def remind_later(self, seconds: int = REMIND_LATER_S) -> None:
        self._state["remind_after"] = self.clock() + seconds
        self._save()

    def clear_snooze(self) -> None:
        if self._state.pop("remind_after", None) is not None:
            self._save()

    def menu_label(self) -> Optional[str]:
        n = len(self.missing_required())
        if not n:
            return None
        return f"⚠️ Finish setup ({n} permission{'s' if n != 1 else ''} missing)"

    # -- actions -------------------------------------------------------------
    def fix(self, key: str) -> None:
        """The Fix / Ask button of one row. May block (an Automation prompt
        waits for the person) — call off the main thread."""
        if key == "accessibility":
            self.prompt_accessibility(user_clicked=True)
            self.p.open_url(AX_PANE_URL)
            return
        if key == "extension":
            # Bring the browser forward; the row says which menu to open.
            for t in self.installed:
                if t.bundle_id in EXTENSION_BROWSERS and self.p.running_path(t.bundle_id):
                    self.p.open_url("", bundle_id=t.bundle_id)
                    return
            return
        if self.automation.get(key) == NOT_ASKED and self.p.running_path(key):
            self.ask_automation(key)
            return
        self.p.open_url(AUTOMATION_PANE_URL)

    def ask_automation(self, bundle_id: str) -> str:
        """Trigger macOS's Automation prompt for one RUNNING app."""
        t = next((t for t in self.targets if t.bundle_id == bundle_id), None)
        path = self.p.running_path(bundle_id)
        if t is None or not path:
            return NOT_RUNNING
        self.asking = t.label
        try:
            st = self.p.ae_prompt(bundle_id, path)
        finally:
            self.asking = None
        if st in (GRANTED, DENIED):
            self.record_observed(bundle_id, st)
        else:
            self.automation = {**self.automation, bundle_id: st}
        return st

    def ask_all_pending(self) -> List[str]:
        """Inside the setup flow — never mid-work: ask every running,
        never-asked app, one at a time (each waits for its answer).
        Returns the labels asked."""
        asked = []
        for t in self.installed:
            if self.automation.get(t.bundle_id) == NOT_ASKED and self.p.running_path(t.bundle_id):
                asked.append(t.label)
                self.ask_automation(t.bundle_id)
        return asked

    # -- views ---------------------------------------------------------------
    def rows(self) -> List[dict]:
        """One dict per checklist row: required first, then the rest.

        ok: True (granted), False (needs fixing), None (can't tell yet)."""
        ax_ok = bool(self.ax_granted)
        if ax_ok:
            ax_detail = AX_BENEFIT + "."
        elif self.stale_entry_reset:
            ax_detail = (AX_BENEFIT + ". Click Fix. If TimeTracker is already on, remove "
                         "it with “−” and add it back with “+”.")
        else:
            ax_detail = AX_BENEFIT + ". Click Fix, then turn on TimeTracker in the list."
        rows = [{
            "key": "accessibility",
            "label": "Accessibility" + ("" if AX_REQUIRED else " (recommended)"),
            "required": AX_REQUIRED, "ok": ax_ok,
            "status": GRANTED if ax_ok else "missing",
            "detail": ax_detail, "fix": None if ax_ok else "Fix",
        }]
        for t in sorted(self.installed, key=lambda t: t.label):
            st = self.automation.get(t.bundle_id, UNKNOWN)
            ok: Optional[bool] = st == GRANTED
            fix = None
            if st == GRANTED:
                detail = f"Reads {t.why}."
            elif st == DENIED:
                detail = (f"Click Fix, then under TimeTracker turn on “{t.label}”.")
                fix = "Fix"
            elif st == NOT_ASKED:
                detail = (f"Click Ask, then OK on the popup, so TimeTracker can read {t.why}.")
                fix = "Ask"
            elif st == NOT_RUNNING:
                detail, ok = f"Will ask the first time you open {t.label}.", None
            else:
                detail, ok = "Can't tell yet.", None
            rows.append({"key": t.bundle_id, "label": f"Automation: {t.label}",
                         "required": t.required, "ok": ok, "status": st,
                         "detail": detail, "fix": fix})
        if self.extension is not None:
            st = self.extension
            rows.append({
                "key": "extension", "label": "TimeTracker browser extension",
                "required": EXTENSION_REQUIRED,
                "ok": True if st == "seen" else (None if st == NOT_RUNNING else False),
                "status": st,
                "detail": ("Sending the page you are on." if st == "seen" else
                           "Will check the next time you use your browser." if st == NOT_RUNNING
                           else "Not heard from in 5 minutes. Click Fix, then in your browser "
                                "open Extensions and turn on “TimeTracker”."),
                "fix": "Fix" if st == "not_seen" else None})
        rows.sort(key=lambda r: not r["required"])
        return rows

    def report(self, include_time: bool = True) -> dict:
        """What goes to the server in the device check-in (hello2)."""
        auto = {bid: (st if st in (GRANTED, DENIED) else UNKNOWN)
                for bid, st in sorted(self.automation.items())}
        out = {
            "accessibility": None if self.ax_granted is None else
            (GRANTED if self.ax_granted else "missing"),
            "automation": auto,
            "capture_mode": self.capture_mode(),
            "required_missing": self.missing_required(),
        }
        if self.extension is not None:
            out["extension"] = self.extension
        if self.stale_entry_reset:
            out["stale_entry_reset"] = True
        if include_time and self.checked_at:
            out["checked_at"] = _iso(self.checked_at)
        return out
