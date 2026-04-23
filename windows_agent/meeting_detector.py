#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meeting Detector — Cross-platform (Windows + Mac)

Detects active video/audio meetings (Zoom, Teams, Google Meet, Webex, FaceTime, etc.)
and emits start/end events independent of foreground focus.

Design:
- Runs on its own polling thread (10s interval)
- Publishes state to the context bus so every raw_event carries meeting context
- Emits synthetic "Meeting" events at start/end via a thread-safe event queue
  that main.py drains in the tracking loop
- Uses hysteresis to prevent flapping:
    * 2 consecutive positive polls → fire on_meeting_start (20s min)
    * 3 consecutive negative polls → fire on_meeting_end (30s grace)

Detection signals (priority order):
1. Audio session active on meeting app (pycaw on Windows, CoreAudio on Mac)
2. Camera/mic in use by meeting app (registry on Windows, lsof on Mac)
3. Known meeting subprocess running (CptHost.exe, ms-teams.exe, etc.)
4. Browser window title matches meeting pattern (Google Meet, Zoom web, Teams web)

Any two signals = high confidence. One signal = medium confidence, still fires
after hysteresis clears.
"""

import os
import sys
import time
import threading
import subprocess
import queue
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Dict, Set
from enum import Enum

# ---------------- Platform detection ----------------
IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

# ---------------- Optional dependencies ----------------
# Windows
_PYCAW_AVAILABLE = False
_PSUTIL_AVAILABLE = False
_WIN32_AVAILABLE = False

if IS_WINDOWS:
    try:
        from pycaw.pycaw import AudioUtilities
        _PYCAW_AVAILABLE = True
    except ImportError:
        pass
    try:
        import winreg
    except ImportError:
        pass
    try:
        import win32gui
        import win32process
        _WIN32_AVAILABLE = True
    except ImportError:
        pass

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    pass

# Mac
_COREAUDIO_AVAILABLE = False
if IS_MAC:
    try:
        import CoreAudio  # via pyobjc
        _COREAUDIO_AVAILABLE = True
    except ImportError:
        pass

logger = logging.getLogger('timetracker.meeting')


# ---------------- Meeting app registry ----------------
# Maps platform-specific process names / identifiers to canonical app keys

MEETING_APPS_WINDOWS = {
    # exe name (lowercase) → canonical key
    "cpthost.exe": "zoom",           # Zoom meeting subprocess (NOT Zoom.exe tray)
    "zoom.exe": "zoom",              # fallback — main Zoom process during active call
    "ms-teams.exe": "teams",         # new Teams
    "teams.exe": "teams",            # classic Teams
    "webexmta.exe": "webex",
    "webex.exe": "webex",
    "webexhost.exe": "webex",
    "slack.exe": "slack",            # Slack Huddles
    "discord.exe": "discord",
    "googlemeet.exe": "meet",        # rare — Meet PWA
}

MEETING_APPS_MAC = {
    # process name (lowercase) → canonical key
    "zoom.us": "zoom",
    "cpthelper": "zoom",             # Zoom's renderer helper
    "microsoft teams": "teams",
    "microsoft teams (work or school)": "teams",
    "teams": "teams",
    "ms teams": "teams",
    "webex": "webex",
    "cisco webex meetings": "webex",
    "facetime": "facetime",
    "slack": "slack",
    "discord": "discord",
    "google meet": "meet",
}

# Browser tab title patterns (case-insensitive substring match)
MEETING_TITLE_PATTERNS = {
    "zoom meeting": "zoom",
    " zoom ": "zoom",
    "meet.google.com": "meet",
    "google meet": "meet",
    "| microsoft teams": "teams",
    "- microsoft teams": "teams",
    "teams.microsoft.com": "teams",
    "webex": "webex",
    "whereby": "whereby",
    "around.co": "around",
    "gather.town": "gather",
}


# ---------------- State & events ----------------

class DetectionSource(Enum):
    AUDIO = "audio"
    CAMERA = "camera"
    PROCESS = "process"
    TITLE = "title"
    NONE = "none"


@dataclass
class MeetingState:
    active: bool = False
    app: Optional[str] = None                    # "zoom" | "teams" | "meet" | etc.
    sources: Set[str] = field(default_factory=set)  # which signals triggered
    started_at: float = 0.0
    ended_at: float = 0.0
    title: Optional[str] = None                  # extracted from window if available
    confidence: float = 0.0                      # 0.0-1.0 based on signal count

    def to_context_dict(self) -> dict:
        """Convert to dict for context bus publishing."""
        return {
            "source": "meeting_detector",
            "active": self.active,
            "app": self.app,
            "detection_sources": sorted(self.sources),
            "started_at": self.started_at,
            "title": self.title,
            "confidence": self.confidence,
            "ts": time.time(),
        }


@dataclass
class DetectionProbe:
    """Single poll result from a probe."""
    active: bool
    app: Optional[str] = None
    source: DetectionSource = DetectionSource.NONE
    title: Optional[str] = None


# ---------------- Platform probes ----------------

class _BaseProbe:
    """Base class — platform probes implement these methods."""

    def probe_audio(self) -> List[DetectionProbe]:
        """Check for active audio sessions from meeting apps."""
        return []

    def probe_camera(self) -> List[DetectionProbe]:
        """Check if camera/mic is actively in use by a meeting app."""
        return []

    def probe_process(self) -> List[DetectionProbe]:
        """Scan running processes for known meeting subprocesses."""
        return []

    def probe_browser_title(self, foreground_title: Optional[str] = None) -> List[DetectionProbe]:
        """Scan browser window titles for meeting patterns."""
        if not foreground_title:
            return []
        title_lower = foreground_title.lower()
        for pattern, app in MEETING_TITLE_PATTERNS.items():
            if pattern in title_lower:
                return [DetectionProbe(
                    active=True, app=app,
                    source=DetectionSource.TITLE,
                    title=foreground_title.strip()
                )]
        return []


class WindowsMeetingProbe(_BaseProbe):
    """Windows-specific detection via pycaw, registry, and psutil."""

    def __init__(self):
        self._last_audio_check = 0.0
        self._last_audio_result: List[DetectionProbe] = []

    def probe_audio(self) -> List[DetectionProbe]:
        """Check Windows audio sessions for active meeting app streams."""
        if not _PYCAW_AVAILABLE:
            return []

        # Cache audio sessions briefly — expensive call
        now = time.time()
        if now - self._last_audio_check < 5:
            return self._last_audio_result

        results = []
        try:
            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                if not session.Process:
                    continue
                try:
                    exe_name = session.Process.name().lower()
                except Exception:
                    continue

                app = MEETING_APPS_WINDOWS.get(exe_name)
                if not app:
                    continue

                # Check if session is actually producing/consuming audio
                # State 1 = Active, 2 = Inactive, 0 = Expired
                try:
                    volume = session.SimpleAudioVolume
                    peak = 0.0
                    if hasattr(session, '_ctl') and session._ctl:
                        try:
                            meter = session._ctl.QueryInterface(
                                __import__('pycaw.pycaw', fromlist=['IAudioMeterInformation']).IAudioMeterInformation
                            )
                            peak = meter.GetPeakValue()
                        except Exception:
                            pass

                    # Active state or non-trivial peak = real audio flowing
                    state_active = getattr(session, 'State', 0) == 1
                    if state_active or peak > 0.001:
                        results.append(DetectionProbe(
                            active=True, app=app,
                            source=DetectionSource.AUDIO
                        ))
                except Exception as e:
                    logger.debug(f"[MEETING] Audio session probe error: {e}")

        except Exception as e:
            logger.warning(f"[MEETING] pycaw enumeration failed: {e}")

        self._last_audio_check = now
        self._last_audio_result = results
        return results

    def probe_camera(self) -> List[DetectionProbe]:
        """Check registry for in-use camera/mic by meeting apps.

        Windows tracks device access at:
          HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\
          ConsentStore\\{webcam,microphone}\\NonPackaged\\*

        LastUsedTimeStop == 0 means "currently in use"
        """
        if not IS_WINDOWS:
            return []

        results = []
        for device_type in ("webcam", "microphone"):
            source = DetectionSource.CAMERA if device_type == "webcam" else DetectionSource.AUDIO
            try:
                base_path = (
                    r"Software\Microsoft\Windows\CurrentVersion"
                    r"\CapabilityAccessManager\ConsentStore"
                    f"\\{device_type}\\NonPackaged"
                )
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base_path) as base_key:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(base_key, i)
                            i += 1
                        except OSError:
                            break

                        try:
                            with winreg.OpenKey(base_key, subkey_name) as sub:
                                try:
                                    last_stop, _ = winreg.QueryValueEx(sub, "LastUsedTimeStop")
                                except FileNotFoundError:
                                    continue

                                # 0 = currently in use
                                if last_stop != 0:
                                    continue

                                # subkey_name is a registry-encoded exe path
                                # e.g. "C:#Program Files#Zoom#bin#Zoom.exe"
                                path_lower = subkey_name.lower().replace('#', '\\')
                                for exe, app in MEETING_APPS_WINDOWS.items():
                                    if exe in path_lower:
                                        results.append(DetectionProbe(
                                            active=True, app=app, source=source
                                        ))
                                        break
                        except OSError:
                            continue
            except FileNotFoundError:
                # Registry path doesn't exist — no apps have requested access
                continue
            except Exception as e:
                logger.debug(f"[MEETING] Registry probe error ({device_type}): {e}")

        return results

    def probe_process(self) -> List[DetectionProbe]:
        """Scan running processes for meeting subprocesses."""
        if not _PSUTIL_AVAILABLE:
            return []

        results = []
        seen_apps = set()
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    name = (proc.info['name'] or '').lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                app = MEETING_APPS_WINDOWS.get(name)
                if not app or app in seen_apps:
                    continue

                # Special case: Zoom.exe is always running when Zoom is installed
                # Only CptHost.exe indicates an active meeting
                # (We still include Zoom.exe but weight via audio/camera confirmation)
                seen_apps.add(app)
                results.append(DetectionProbe(
                    active=True, app=app, source=DetectionSource.PROCESS
                ))
        except Exception as e:
            logger.debug(f"[MEETING] Process scan error: {e}")

        return results


class MacMeetingProbe(_BaseProbe):
    """Mac-specific detection via lsof, system_profiler, and psutil."""

    def __init__(self):
        self._last_camera_check = 0.0
        self._last_camera_result: List[DetectionProbe] = []

    def probe_camera(self) -> List[DetectionProbe]:
        """Detect camera-in-use via lsof on VDCAssistant / AppleCameraAssistant.

        When any process opens the camera, macOS spawns VDCAssistant.
        lsof reveals which process owns the camera device.
        """
        now = time.time()
        if now - self._last_camera_check < 8:
            return self._last_camera_result

        results = []
        try:
            # VDCAssistant is the system camera broker
            out = subprocess.run(
                ["lsof", "-c", "VDCAssistant", "-c", "AppleCameraAssistant"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout:
                # If these processes are running, camera is in use by *someone*.
                # Cross-reference with running processes to find which app.
                if _PSUTIL_AVAILABLE:
                    for proc in psutil.process_iter(['name']):
                        try:
                            name = (proc.info['name'] or '').lower()
                        except Exception:
                            continue
                        for mac_name, app in MEETING_APPS_MAC.items():
                            if mac_name in name:
                                results.append(DetectionProbe(
                                    active=True, app=app,
                                    source=DetectionSource.CAMERA
                                ))
                                break
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"[MEETING] lsof probe error: {e}")

        # De-dupe
        seen = set()
        unique = []
        for r in results:
            if r.app not in seen:
                seen.add(r.app)
                unique.append(r)

        self._last_camera_check = now
        self._last_camera_result = unique
        return unique

    def probe_audio(self) -> List[DetectionProbe]:
        """Detect active audio input via system_profiler.

        This is less precise than Windows — we can see if audio input is
        active but not always which app owns it. Combined with process
        scan, good enough.
        """
        results = []
        try:
            # Check if coreaudiod is streaming — cheap heuristic
            out = subprocess.run(
                ["lsof", "-c", "coreaudiod"],
                capture_output=True, text=True, timeout=3,
            )
            # If any meeting app shows up in audio-connected processes, fire
            if out.returncode == 0 and _PSUTIL_AVAILABLE:
                # Look for meeting apps that have audio unit references
                for proc in psutil.process_iter(['name']):
                    try:
                        name = (proc.info['name'] or '').lower()
                    except Exception:
                        continue
                    for mac_name, app in MEETING_APPS_MAC.items():
                        if mac_name == name:  # exact match for audio confidence
                            # Only report audio if process is actively consuming CPU
                            try:
                                cpu = proc.cpu_percent(interval=None)
                                if cpu > 0.5:  # very low threshold — meetings use ~5-20%
                                    results.append(DetectionProbe(
                                        active=True, app=app,
                                        source=DetectionSource.AUDIO
                                    ))
                            except Exception:
                                pass
                            break
        except Exception as e:
            logger.debug(f"[MEETING] Mac audio probe error: {e}")

        # De-dupe
        seen = set()
        unique = []
        for r in results:
            if r.app not in seen:
                seen.add(r.app)
                unique.append(r)
        return unique

    def probe_process(self) -> List[DetectionProbe]:
        if not _PSUTIL_AVAILABLE:
            return []

        results = []
        seen_apps = set()
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    name = (proc.info['name'] or '').lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                for mac_name, app in MEETING_APPS_MAC.items():
                    if mac_name in name and app not in seen_apps:
                        seen_apps.add(app)
                        results.append(DetectionProbe(
                            active=True, app=app, source=DetectionSource.PROCESS
                        ))
                        break
        except Exception as e:
            logger.debug(f"[MEETING] Mac process scan error: {e}")

        return results


# ---------------- Main detector ----------------

class MeetingDetector:
    """
    Runs on background thread. Polls every 10s. Fires callbacks on meeting
    start/end. Publishes state to context bus so every raw_event carries it.

    Usage:
        detector = MeetingDetector(
            on_meeting_start=my_start_handler,
            on_meeting_end=my_end_handler,
            context_bus=_CONTEXT,  # main.py's shared dict
            get_foreground_title=lambda: current_window_title,
        )
        detector.start()
        # ... later ...
        detector.stop()
    """

    # Polling tunables
    POLL_INTERVAL_S = 10
    POSITIVE_HYSTERESIS = 2   # consecutive positives → start (20s)
    NEGATIVE_HYSTERESIS = 3   # consecutive negatives → end (30s)

    def __init__(
        self,
        on_meeting_start: Optional[Callable[[MeetingState], None]] = None,
        on_meeting_end: Optional[Callable[[MeetingState], None]] = None,
        context_bus: Optional[Dict[str, dict]] = None,
        get_foreground_title: Optional[Callable[[], Optional[str]]] = None,
        enabled: bool = True,
    ):
        self.on_meeting_start = on_meeting_start
        self.on_meeting_end = on_meeting_end
        self.context_bus = context_bus
        self.get_foreground_title = get_foreground_title
        self.enabled = enabled

        # Platform probe
        if IS_WINDOWS:
            self.probe = WindowsMeetingProbe()
        elif IS_MAC:
            self.probe = MacMeetingProbe()
        else:
            self.probe = _BaseProbe()
            logger.warning(f"[MEETING] Unsupported platform: {sys.platform}")
            self.enabled = False

        # State
        self.state = MeetingState()
        self._state_lock = threading.Lock()
        self._positive_streak = 0
        self._negative_streak = 0
        self._last_poll_app: Optional[str] = None

        # Thread control
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Event queue — main.py's tracking loop drains this to write events
        # with its local conn/cur (thread-safe sqlite access)
        self.event_queue: "queue.Queue[tuple]" = queue.Queue(maxsize=100)

    # ---------- Public API ----------

    def start(self):
        if not self.enabled:
            logger.info("[MEETING] Detector disabled (unsupported platform or no deps)")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="MeetingDetector"
        )
        self._thread.start()
        logger.info(
            f"[MEETING] Detector started (platform={sys.platform}, "
            f"interval={self.POLL_INTERVAL_S}s)"
        )

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def get_state(self) -> MeetingState:
        """Thread-safe snapshot of current state."""
        with self._state_lock:
            # Return a shallow copy
            s = MeetingState(
                active=self.state.active,
                app=self.state.app,
                sources=set(self.state.sources),
                started_at=self.state.started_at,
                ended_at=self.state.ended_at,
                title=self.state.title,
                confidence=self.state.confidence,
            )
            return s

    def is_active(self) -> bool:
        with self._state_lock:
            return self.state.active

    # ---------- Polling loop ----------

    def _poll_loop(self):
        logger.info("[MEETING] Poll loop started")
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as e:
                logger.warning(f"[MEETING] Poll error: {e}", exc_info=True)

            # Wait for next poll, but respond to stop event quickly
            self._stop_event.wait(self.POLL_INTERVAL_S)
        logger.info("[MEETING] Poll loop stopped")

    def _poll_once(self):
        """Run all probes, aggregate, update state with hysteresis."""
        probes: List[DetectionProbe] = []

        # Gather signals from all probes (failures in one don't kill others)
        for probe_name, probe_fn in [
            ("audio", self.probe.probe_audio),
            ("camera", self.probe.probe_camera),
            ("process", self.probe.probe_process),
        ]:
            try:
                probes.extend(probe_fn())
            except Exception as e:
                logger.debug(f"[MEETING] {probe_name} probe failed: {e}")

        # Browser title probe needs foreground title from caller
        if self.get_foreground_title:
            try:
                title = self.get_foreground_title()
                if title:
                    probes.extend(self.probe.probe_browser_title(title))
            except Exception as e:
                logger.debug(f"[MEETING] Title probe failed: {e}")

        # Aggregate: group by app, collect sources
        app_sources: Dict[str, Set[str]] = {}
        app_titles: Dict[str, str] = {}
        for p in probes:
            if not p.active or not p.app:
                continue
            app_sources.setdefault(p.app, set()).add(p.source.value)
            if p.title and p.app not in app_titles:
                app_titles[p.app] = p.title

        # Process alone is never enough. Meeting apps (Teams, Zoom, Slack,
        # Webex) run persistent background processes even when no call is
        # active. Browser window titles alone can also be misleading
        # (e.g., "Zoom Meeting" left in a browser tab).
        #
        # Require: at least one STRONG signal (audio or camera), OR
        #          at least 2 independent signals of any kind.
        filtered = {}
        for app, sources in app_sources.items():
            has_strong = bool(sources & {"audio", "camera"})
            has_multiple = len(sources) >= 2
            if not (has_strong or has_multiple):
                logger.debug(
                    f"[MEETING] Dropping {app}: weak signal "
                    f"(sources={sources}, need audio/camera or 2+ signals)"
                )
                continue
            filtered[app] = sources

        # Pick the app with the most signals (ties broken by arbitrary order)
        if filtered:
            best_app = max(filtered.keys(), key=lambda a: len(filtered[a]))
            best_sources = filtered[best_app]
            best_title = app_titles.get(best_app)
            is_meeting_active_now = True
        else:
            best_app = None
            best_sources = set()
            best_title = None
            is_meeting_active_now = False

        # Update hysteresis counters
        with self._state_lock:
            was_active = self.state.active

            if is_meeting_active_now:
                self._positive_streak += 1
                self._negative_streak = 0

                # If app changed mid-meeting (back-to-back meetings), reset counters
                if self.state.active and best_app != self.state.app:
                    logger.info(
                        f"[MEETING] App switch detected: "
                        f"{self.state.app} → {best_app} (ending old, starting new)"
                    )
                    self._fire_end_locked()
                    self._positive_streak = self.POSITIVE_HYSTERESIS  # fire immediately
            else:
                self._negative_streak += 1
                self._positive_streak = 0

            # State transitions
            if not was_active and self._positive_streak >= self.POSITIVE_HYSTERESIS:
                # Transition to active
                self.state.active = True
                self.state.app = best_app
                self.state.sources = best_sources
                self.state.started_at = time.time()
                self.state.ended_at = 0.0
                self.state.title = best_title
                self.state.confidence = min(1.0, len(best_sources) / 3.0)
                self._fire_start_locked()

            elif was_active and self._negative_streak >= self.NEGATIVE_HYSTERESIS:
                # Transition to inactive
                self._fire_end_locked()

            elif was_active:
                # Still in meeting — refresh title/sources if we got new info
                if best_title and not self.state.title:
                    self.state.title = best_title
                if best_sources:
                    # Accumulate all sources seen during meeting
                    self.state.sources |= best_sources
                    self.state.confidence = min(1.0, len(self.state.sources) / 3.0)

            # Always publish to context bus so every raw_event carries current state
            self._publish_context_locked()

        # Log poll result (debug level)
        if probes:
            logger.debug(
                f"[MEETING] poll: active_now={is_meeting_active_now} "
                f"best_app={best_app} sources={best_sources} "
                f"streaks(+{self._positive_streak}/-{self._negative_streak})"
            )

    # ---------- State transitions (must hold _state_lock) ----------

    def _fire_start_locked(self):
        logger.info(
            f"[MEETING] ▶ START: app={self.state.app} "
            f"sources={sorted(self.state.sources)} "
            f"confidence={self.state.confidence:.0%} "
            f"title={self.state.title!r}"
        )
        snapshot = MeetingState(
            active=True, app=self.state.app,
            sources=set(self.state.sources),
            started_at=self.state.started_at,
            title=self.state.title,
            confidence=self.state.confidence,
        )

        # Enqueue synthetic event for tracking loop to write
        try:
            self.event_queue.put_nowait(("start", snapshot))
        except queue.Full:
            logger.warning("[MEETING] Event queue full, dropping start event")

        # Fire callback (non-blocking — run in thread so slow handlers don't stall poll)
        if self.on_meeting_start:
            threading.Thread(
                target=self._safe_callback,
                args=(self.on_meeting_start, snapshot, "start"),
                daemon=True,
            ).start()

    def _fire_end_locked(self):
        self.state.active = False
        self.state.ended_at = time.time()
        duration = self.state.ended_at - self.state.started_at if self.state.started_at else 0
        logger.info(
            f"[MEETING] ■ END: app={self.state.app} "
            f"duration={int(duration)}s "
            f"title={self.state.title!r}"
        )
        snapshot = MeetingState(
            active=False, app=self.state.app,
            sources=set(self.state.sources),
            started_at=self.state.started_at,
            ended_at=self.state.ended_at,
            title=self.state.title,
            confidence=self.state.confidence,
        )

        try:
            self.event_queue.put_nowait(("end", snapshot))
        except queue.Full:
            logger.warning("[MEETING] Event queue full, dropping end event")

        if self.on_meeting_end:
            threading.Thread(
                target=self._safe_callback,
                args=(self.on_meeting_end, snapshot, "end"),
                daemon=True,
            ).start()

        # Reset for next meeting
        self.state.app = None
        self.state.sources = set()
        self.state.title = None
        self.state.confidence = 0.0

    def _safe_callback(self, fn, state, kind):
        try:
            fn(state)
        except Exception as e:
            logger.error(f"[MEETING] Callback {kind} failed: {e}", exc_info=True)

    def _publish_context_locked(self):
        if self.context_bus is None:
            return
        try:
            self.context_bus["meeting_detector"] = self.state.to_context_dict()
        except Exception as e:
            logger.debug(f"[MEETING] Context publish error: {e}")

    # ---------- Event queue drain (called by main.py tracking loop) ----------

    def drain_events(self) -> List[tuple]:
        """
        Return all queued (kind, state) tuples and clear the queue.
        main.py calls this each tick from its tracking loop so it can
        write the synthetic Meeting events using its own conn/cur.
        """
        events = []
        while True:
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events


# ---------------- Stand-alone test harness ----------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )

    print(f"Platform: {sys.platform}")
    print(f"pycaw: {_PYCAW_AVAILABLE}")
    print(f"psutil: {_PSUTIL_AVAILABLE}")
    print(f"win32: {_WIN32_AVAILABLE}")
    print()
    print("Starting detector — join a Zoom/Teams/Meet call to test...")
    print("Press Ctrl+C to stop.")
    print()

    bus = {}

    def on_start(s: MeetingState):
        print(f"\n🟢 MEETING START: {s.app} via {sorted(s.sources)} (conf={s.confidence:.0%})")
        if s.title:
            print(f"   Title: {s.title}")

    def on_end(s: MeetingState):
        dur = s.ended_at - s.started_at
        print(f"\n🔴 MEETING END: {s.app} (duration={int(dur)}s)\n")

    d = MeetingDetector(
        on_meeting_start=on_start,
        on_meeting_end=on_end,
        context_bus=bus,
    )
    d.start()

    try:
        while True:
            time.sleep(5)
            s = d.get_state()
            if s.active:
                dur = time.time() - s.started_at
                print(f"  ... in meeting: {s.app} ({int(dur)}s)", end='\r')
    except KeyboardInterrupt:
        print("\n\nStopping...")
        d.stop()