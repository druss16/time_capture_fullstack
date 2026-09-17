"""Is a camera or microphone being recorded from right now?

One question, for one purpose: whether to keep counting time once the keyboard
and mouse have gone quiet. A 60-minute telehealth consult in Chrome produced a
14-minute block because talking is not input, and nothing else said the user
was still working.

This is deliberately NOT the meeting detector. That one answers "which meeting
app, for which client, so the block can be attributed" and is conservative by
design — browser audio without a known meeting title is treated as media
playback and dropped, which is right for Spotify and wrong for a video call on
a site nobody whitelisted. This module answers the narrower question where a
false negative costs real billable time and a false positive only inflates a
block that a human will see in review.

macOS: AVCaptureDevice.isInUseByAnotherApplication() — the OS's own answer,
across every video and audio device (built-in, Continuity Camera, virtual
cameras). The camera daemons the old probe looked for (VDCAssistant,
AppleCameraAssistant) do not run at all on macOS 13+, so that probe reported
False on every modern Mac.

Windows: the CapabilityAccessManager consent store, where LastUsedTimeStop == 0
means the device is open right now. Unlike the meeting detector's use of the
same hive, this does not filter to known meeting apps — any process holding the
camera or mic counts.
"""
import logging
import sys
import time
from dataclasses import dataclass, field

logger = logging.getLogger('timetracker.media_capture')

IS_MAC = sys.platform == 'darwin'
IS_WINDOWS = sys.platform.startswith('win')

# The probes cost a few milliseconds; the caller polls every loop iteration.
CACHE_TTL_S = 5.0


@dataclass
class CaptureState:
    active: bool = False
    devices: tuple = field(default_factory=tuple)   # human-readable, for logs
    checked_at: float = 0.0
    error: str = ''


_cache = CaptureState()


def _probe_mac() -> CaptureState:
    import AVFoundation as AV
    from AVFoundation import AVCaptureDevice

    in_use = []
    for media_type in (AV.AVMediaTypeVideo, AV.AVMediaTypeAudio):
        kind = 'camera' if media_type == AV.AVMediaTypeVideo else 'mic'
        for device in (AVCaptureDevice.devicesWithMediaType_(media_type) or []):
            try:
                if device.isInUseByAnotherApplication():
                    in_use.append(f"{kind}:{device.localizedName()}")
            except Exception:
                continue
    return CaptureState(active=bool(in_use), devices=tuple(in_use))


def _probe_windows() -> CaptureState:
    import winreg

    in_use = []
    for device_type in ('webcam', 'microphone'):
        kind = 'camera' if device_type == 'webcam' else 'mic'
        base = (
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\CapabilityAccessManager\ConsentStore"
            f"\\{device_type}"
        )
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as consent:
                hives = []
                i = 0
                while True:
                    try:
                        hives.append(winreg.EnumKey(consent, i))
                        i += 1
                    except OSError:
                        break
        except FileNotFoundError:
            continue

        for hive in hives:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{base}\\{hive}") as hive_key:
                    j = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(hive_key, j)
                            j += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(hive_key, sub) as entry:
                                last_stop, _ = winreg.QueryValueEx(entry, 'LastUsedTimeStop')
                        except (FileNotFoundError, OSError):
                            continue
                        # 0 means the app still holds the device.
                        if last_stop == 0:
                            who = sub.replace('#', '\\') if hive.lower() == 'nonpackaged' else hive
                            in_use.append(f"{kind}:{who.rsplit(chr(92), 1)[-1]}")
            except OSError:
                continue

    return CaptureState(active=bool(in_use), devices=tuple(in_use))


def capture_in_use(force: bool = False) -> CaptureState:
    """Cached answer. Never raises — a probe that fails reports 'not in use',
    because an error must not be able to hold someone out of idle forever."""
    global _cache

    now = time.time()
    if not force and (now - _cache.checked_at) < CACHE_TTL_S:
        return _cache

    try:
        if IS_MAC:
            state = _probe_mac()
        elif IS_WINDOWS:
            state = _probe_windows()
        else:
            state = CaptureState()
    except Exception as e:
        logger.debug(f"[CAPTURE] Probe failed: {e}")
        state = CaptureState(error=str(e)[:200])

    state.checked_at = now
    _cache = state
    return state
