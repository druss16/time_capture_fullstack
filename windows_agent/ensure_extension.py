"""Silently force-install the "TimeTracker URL Reporter" browser extension for
the current user, by writing a PER-USER ExtensionInstallForcelist policy under
HKCU — for both Microsoft Edge and Google Chrome.

Why HKCU (per-user) and not HKLM (per-machine): the agent runs as a limited,
non-admin user, so it cannot write HKLM — but it CAN write HKCU, which Edge and
Chrome both honor for the current user. This lets the extension reach machines
that were installed manually (no MDM / no GPO) through the agent's normal
auto-update: the updated agent runs this on startup and the browser
force-installs the extension.

Idempotent and fail-open: it never raises and never blocks the agent. Each store
assigns its own extension id (the CRX id differs between the Edge and Chrome
stores). A browser whose extension is not yet published/approved simply won't
find it until it is — setting the policy early is harmless.
"""

import sys

# Per-store: the published extension id (32-char CRX id), that store's update
# URL, and the browser's per-user force-install policy key.
_BROWSERS = [
    {
        "name": "Edge",
        "ext_id": "bnnifiompbeebhapoojlonamdghmlifh",
        "update_url": "https://edge.microsoft.com/extensionwebstorebase/v1/crx",
        "key": r"Software\Policies\Microsoft\Edge\ExtensionInstallForcelist",
    },
    {
        "name": "Chrome",
        "ext_id": "ophdgbaogdhfdhmfnnjniegccekmgfok",
        "update_url": "https://clients2.google.com/service/update2/crx",
        "key": r"Software\Policies\Google\Chrome\ExtensionInstallForcelist",
    },
]


def _forceinstall_one(browser, log):
    """Force-list one browser's extension for the current user. Returns bool."""
    import winreg

    ext_id = browser["ext_id"]
    value = f'{ext_id};{browser["update_url"]}'
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, browser["key"], 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
    except Exception as e:
        log(f"[EXT] {browser['name']}: could not open/create forcelist key: {e}")
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
            if isinstance(val, str) and val.lower().startswith(ext_id + ";"):
                already = True
            if isinstance(name, str) and name.isdigit():
                used.add(int(name))

        if already:
            log(f"[EXT] {browser['name']}: extension already force-listed (current user)")
            return True

        slot = 1
        while slot in used:
            slot += 1
        winreg.SetValueEx(key, str(slot), 0, winreg.REG_SZ, value)
        log(f"[EXT] {browser['name']}: force-installed extension (current user) [slot {slot}]")
        return True
    except Exception as e:
        log(f"[EXT] {browser['name']}: could not write force-install policy: {e}")
        return False
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass


def ensure_extensions_forceinstall(log=None):
    """Force-install the extension for Edge and Chrome (current user, HKCU).

    Returns True if at least one browser's policy is in place. Safe to call on
    every startup and on non-Windows (no-op). Never raises.
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
        import winreg  # noqa: F401  — probe availability before looping
    except Exception:
        return False

    ok = False
    for browser in _BROWSERS:
        try:
            if _forceinstall_one(browser, _log):
                ok = True
        except Exception as e:
            _log(f"[EXT] {browser.get('name', '?')}: unexpected error: {e}")
    return ok


# Backward-compatible alias — older callers referenced the Edge-only name.
def ensure_edge_extension_forceinstall(log=None):
    return ensure_extensions_forceinstall(log=log)
