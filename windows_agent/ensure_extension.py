"""Silently force-install the "TimeTracker URL Reporter" browser extension for
the current user (Microsoft Edge), by writing a PER-USER
ExtensionInstallForcelist policy under HKCU.

Why HKCU (per-user) and not HKLM (per-machine): the agent runs as a limited,
non-admin user, so it cannot write HKLM — but it CAN write HKCU, which Edge
honors for the current user. This lets the extension reach machines that were
installed manually (no MDM / no GPO) through the agent's normal auto-update:
the updated agent runs this on startup and Edge force-installs the extension.

Idempotent and fail-open: it never raises and never blocks the agent. Edge-only
(the extension is published to the Edge Add-ons store, not the Chrome Web Store).
"""

import sys

# Published Edge Add-ons extension id (32-char CRX id) + the Edge store update URL.
_EXT_ID = "bnnifiompbeebhapoojlonamdghmlifh"
_EDGE_UPDATE_URL = "https://edge.microsoft.com/extensionwebstorebase/v1/crx"
_VALUE = f"{_EXT_ID};{_EDGE_UPDATE_URL}"
_EDGE_FORCELIST_KEY = r"Software\Policies\Microsoft\Edge\ExtensionInstallForcelist"


def ensure_edge_extension_forceinstall(log=None):
    """Ensure the extension is force-listed for the current user's Edge.

    Returns True if the policy is present (already or newly written), else False.
    Safe to call on every startup and on non-Windows (no-op).
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    if not sys.platform.startswith("win"):
        return False

    try:
        import winreg
    except Exception:
        return False

    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _EDGE_FORCELIST_KEY, 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
    except Exception as e:
        _log(f"[EXT] could not open/create Edge forcelist key: {e}")
        return False

    try:
        # Scan existing values: detect if already present, and find a free slot
        # so we never clobber another IT-managed force-installed extension.
        already = False
        used = set()
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            if isinstance(val, str) and val.lower().startswith(_EXT_ID + ";"):
                already = True
            if isinstance(name, str) and name.isdigit():
                used.add(int(name))

        if already:
            _log("[EXT] extension already force-listed for Edge (current user)")
            return True

        slot = 1
        while slot in used:
            slot += 1
        winreg.SetValueEx(key, str(slot), 0, winreg.REG_SZ, _VALUE)
        _log(f"[EXT] force-installed extension for Edge (current user) [slot {slot}]")
        return True
    except Exception as e:
        _log(f"[EXT] could not write Edge force-install policy: {e}")
        return False
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
