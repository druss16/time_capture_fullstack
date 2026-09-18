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

macOS: the `...DeviceIsRunningSomewhere` property, which is the OS's own
answer to "is any process using this device" — CoreMediaIO for cameras,
CoreAudio for microphones. Measured on 15.1 against a live camera: the
in-use device reported 1 and the other three reported 0.

Two things this had to get past, both verified rather than assumed:

  · AVCaptureDevice.isInUseByAnotherApplication() looks like the obvious API
    and does not work. With Photo Booth holding the camera it returned False
    for every device, including the one in use.
  · The camera daemons the old meeting probe looked for (VDCAssistant,
    AppleCameraAssistant) do not run at all on macOS 13+. The ones that do
    (appleh13camerad, avconferenced, cameracaptured) run constantly, so
    their presence says nothing either way.

The two frameworks are reached differently because only one route works for
each: CoreMediaIO through pyobjc (raw ctypes calls into it segfault), and
CoreAudio through ctypes (its pyobjc binding rejects every buffer type).

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


def _mac_camera_in_use() -> list:
    """Cameras running in any process, via CoreMediaIO."""
    import struct
    import CoreMediaIO as CM

    element = getattr(CM, 'kCMIOObjectPropertyElementMain', None)
    if element is None:
        element = getattr(CM, 'kCMIOObjectPropertyElementMaster', 0)

    def address(selector):
        return CM.CMIOObjectPropertyAddress(
            selector, CM.kCMIOObjectPropertyScopeGlobal, element,
        )

    _, size = CM.CMIOObjectGetPropertyDataSize(
        CM.kCMIOObjectSystemObject, address(CM.kCMIOHardwarePropertyDevices),
        0, None, None,
    )
    if not size:
        return []

    result = CM.CMIOObjectGetPropertyData(
        CM.kCMIOObjectSystemObject, address(CM.kCMIOHardwarePropertyDevices),
        0, None, size, None, None,
    )
    device_ids = struct.unpack(f'<{size // 4}I', bytes(result[-1])[:size])

    running = []
    for device_id in device_ids:
        answer = CM.CMIOObjectGetPropertyData(
            device_id,
            address(CM.kCMIODevicePropertyDeviceIsRunningSomewhere),
            0, None, 4, None, None,
        )
        if struct.unpack('<I', bytes(answer[-1])[:4])[0]:
            running.append(f'camera:{device_id}')
    return running


def _mac_mic_in_use() -> list:
    """Microphones running in any process, via CoreAudio."""
    import ctypes
    import ctypes.util
    import struct

    class _Address(ctypes.Structure):
        _fields_ = [
            ('mSelector', ctypes.c_uint32),
            ('mScope', ctypes.c_uint32),
            ('mElement', ctypes.c_uint32),
        ]

    def fourcc(code):
        return int.from_bytes(code.encode(), 'big')

    SYSTEM_OBJECT = 1
    DEVICES, GLOBAL_SCOPE = fourcc('dev#'), fourcc('glob')
    RUNNING_SOMEWHERE, STREAMS, INPUT_SCOPE = fourcc('gone'), fourcc('stm#'), fourcc('inpt')

    lib = ctypes.CDLL(ctypes.util.find_library('CoreAudio'))
    get_size, get_data = lib.AudioObjectGetPropertyDataSize, lib.AudioObjectGetPropertyData
    # Without explicit prototypes ctypes truncates the pointers and the
    # process dies on the first call.
    get_size.restype = get_data.restype = ctypes.c_int32
    get_size.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(_Address), ctypes.c_uint32,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
    ]
    get_data.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(_Address), ctypes.c_uint32,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
    ]

    def size_of(obj, selector, scope=GLOBAL_SCOPE):
        addr, out = _Address(selector, scope, 0), ctypes.c_uint32(0)
        if get_size(obj, ctypes.byref(addr), 0, None, ctypes.byref(out)) != 0:
            return 0
        return out.value

    def read(obj, selector, size, scope=GLOBAL_SCOPE):
        if not size:
            return None
        addr = _Address(selector, scope, 0)
        io_size, buf = ctypes.c_uint32(size), ctypes.create_string_buffer(size)
        if get_data(obj, ctypes.byref(addr), 0, None, ctypes.byref(io_size), buf) != 0:
            return None
        return buf.raw[:io_size.value]

    raw = read(SYSTEM_OBJECT, DEVICES, size_of(SYSTEM_OBJECT, DEVICES)) or b''
    running = []
    for device_id in struct.unpack(f'<{len(raw) // 4}I', raw):
        # No input streams means it is a speaker, and can never be a mic.
        if not size_of(device_id, STREAMS, INPUT_SCOPE):
            continue
        answer = read(device_id, RUNNING_SOMEWHERE, 4)
        if answer and struct.unpack('<I', answer)[0]:
            running.append(f'mic:{device_id}')
    return running


def _probe_mac() -> CaptureState:
    in_use, broken = [], []
    for name, probe in (('camera', _mac_camera_in_use), ('mic', _mac_mic_in_use)):
        try:
            in_use.extend(probe())
        except Exception as e:
            # One framework failing must not blind the other — but it must not
            # pass for "no device in use" either. A probe that cannot run and a
            # camera that is off are the same silence, and only one of them is
            # good news.
            broken.append(f"{name}: {e}")
            logger.debug(f"[CAPTURE] mac {name} probe failed: {e}")
    return CaptureState(
        active=bool(in_use),
        devices=tuple(in_use),
        error='; '.join(broken),
    )


FIELDS = ('webcam', 'microphone')


def _windows_in_use_at(winreg, path):
    """True when the key at `path` records a device still held."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            last_stop, _ = winreg.QueryValueEx(key, 'LastUsedTimeStop')
    except (FileNotFoundError, OSError):
        return False
    return last_stop == 0          # 0 = the app has not let go


def _probe_windows() -> CaptureState:
    r"""Read the CapabilityAccessManager consent store.

    The store nests two different ways, and reading only one of them is how
    this probe reported "nothing" on a machine with its camera plainly on:

        ConsentStore\webcam\Microsoft.WindowsCamera_8wekyb3d8bbwe
            LastUsedTimeStop = 0                    <- on the package key
        ConsentStore\webcam\NonPackaged\C:#...#chrome.exe
            LastUsedTimeStop = 0                    <- one level down

    Packaged apps — Windows Camera, new Teams, anything from the Store —
    record usage on the package family key itself. Desktop executables record
    it under NonPackaged, keyed by encoded path. Both levels are checked.
    """
    import winreg

    in_use = []
    missing_stores = 0

    for device_type in FIELDS:
        kind = 'camera' if device_type == 'webcam' else 'mic'
        base = (
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\CapabilityAccessManager\ConsentStore"
            f"\\{device_type}"
        )

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as consent:
                hives, i = [], 0
                while True:
                    try:
                        hives.append(winreg.EnumKey(consent, i))
                        i += 1
                    except OSError:
                        break
        except FileNotFoundError:
            missing_stores += 1
            continue

        for hive in hives:
            hive_path = f"{base}\\{hive}"

            # Packaged app: the value lives on the package family key.
            if _windows_in_use_at(winreg, hive_path):
                in_use.append(f"{kind}:{hive}")

            # Desktop app: one level down, keyed by encoded exe path.
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hive_path) as hive_key:
                    j = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(hive_key, j)
                            j += 1
                        except OSError:
                            break
                        if not _windows_in_use_at(winreg, f"{hive_path}\\{sub}"):
                            continue
                        who = sub.replace('#', chr(92)) if hive.lower() == 'nonpackaged' else hive
                        in_use.append(f"{kind}:{who.rsplit(chr(92), 1)[-1]}")
            except OSError:
                continue

    if missing_stores == len(FIELDS):
        # No consent store at all: this machine cannot report device use, which
        # is not the same as no device being in use.
        return CaptureState(
            error='no CapabilityAccessManager consent store for webcam or microphone',
        )

    return CaptureState(active=bool(in_use), devices=tuple(dict.fromkeys(in_use)))


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
