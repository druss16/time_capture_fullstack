r"""Silently force-install the "TimeTracker URL Reporter" browser extension for
the current user, by writing a PER-USER ExtensionInstallForcelist policy under
HKCU — for both Microsoft Edge and Google Chrome.

TWO MECHANISMS, DELIBERATELY
---------------------------
1. FORCE-INSTALL via ExtensionInstallForcelist. The extension arrives enabled
   and the user cannot remove it. This is what we want.

2. EXTERNAL EXTENSION via Software\<vendor>\<browser>\Extensions\<id>. The
   browser installs it but leaves it DISABLED behind "Another program on your
   computer added an extension...", and the user can remove it.

(1) is tried first and (2) is the fallback, because (1) frequently cannot work.

WHY (1) OFTEN FAILS — THE BUG THIS FILE USED TO HAVE
----------------------------------------------------
This file used to claim: "the agent runs as a limited, non-admin user, so it
cannot write HKLM — but it CAN write HKCU". That is true of HKCU generally and
FALSE of HKCU\Software\Policies, which is ACL'd to Administrators and SYSTEM
so that a standard user cannot grant themselves policies. Group Policy writes
there as SYSTEM.

So on any non-admin machine the force-install write failed with

    [EXT] Chrome: could not open/create forcelist key: [WinError 5] Access is denied

and the agent installed nothing. Observed in the field on v1.9.3. The premise
the whole design rested on was wrong.

The external-extension key is NOT under Policies and is genuinely user-writable,
which is why it can be the fallback. It is the same mechanism, and the same
trade, as the drop files the Mac package writes.

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
        # Not under Policies, so writable without admin. Fallback only.
        "ext_key": r"Software\Microsoft\Edge\Extensions",
    },
    {
        "name": "Chrome",
        "ext_id": "ophdgbaogdhfdhmfnnjniegccekmgfok",
        "update_url": "https://clients2.google.com/service/update2/crx",
        "key": r"Software\Policies\Google\Chrome\ExtensionInstallForcelist",
        "ext_key": r"Software\Google\Chrome\Extensions",
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


def _external_install_one(browser, log):
    r"""
    Register the extension as an EXTERNAL extension for the current user.

    HKCU\Software\<vendor>\<browser>\Extensions\<id> with an `update_url`
    value. Unlike the Policies subtree this is ordinarily user-writable, so it
    works on the non-admin machines where force-install cannot.

    Weaker on purpose, and the caller says so: the browser installs the
    extension DISABLED behind "Another program on your computer added an
    extension...", the approval is per browser profile, and the user can remove
    it afterwards. Force-install has none of those. This is the floor, not the
    goal.
    """
    import winreg

    ext_key = browser.get("ext_key")
    if not ext_key:
        return False

    path = ext_key + "\\" + browser["ext_id"]
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE,
        )
    except Exception as e:
        log(f"[EXT] {browser['name']}: fallback key unavailable too: {e}")
        return False

    try:
        try:
            existing, _ = winreg.QueryValueEx(key, "update_url")
        except OSError:
            existing = None
        if existing == browser["update_url"]:
            log(f"[EXT] {browser['name']}: already registered as an external "
                f"extension (needs the user to enable it once per profile)")
            return True

        winreg.SetValueEx(key, "update_url", 0, winreg.REG_SZ, browser["update_url"])
        log(f"[EXT] {browser['name']}: registered as an EXTERNAL extension "
            f"(fallback). It installs DISABLED — the user must approve it once "
            f"per browser profile. Deploy the ADMX/GPO policy for a silent install.")
        return True
    except Exception as e:
        log(f"[EXT] {browser['name']}: could not write external-extension key: {e}")
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
                continue
        except Exception as e:
            _log(f"[EXT] {browser.get('name', '?')}: unexpected error: {e}")

        # Force-install did not take — almost always WinError 5 on the Policies
        # subtree. Fall back so the extension still arrives, and say plainly
        # that it arrives weaker, because "installed" and "installed, enabled
        # and locked" are different promises to a firm.
        try:
            if _external_install_one(browser, _log):
                ok = True
        except Exception as e:
            _log(f"[EXT] {browser.get('name', '?')}: fallback error: {e}")
    return ok


# Backward-compatible alias — older callers referenced the Edge-only name.
def ensure_edge_extension_forceinstall(log=None):
    return ensure_extensions_forceinstall(log=log)
