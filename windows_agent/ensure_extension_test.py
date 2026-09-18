"""
Tests for the force-install / external-extension fallback.

WHY THESE EXIST
---------------
The force-install path could not work on a non-admin machine and nobody knew
for six months, because the failure printed to a stdout that did not exist.
When it finally spoke it said:

    [EXT] Chrome: could not open/create forcelist key: [WinError 5] Access is denied

HKCU\\Software\\Policies is ACL'd to Administrators and SYSTEM, so the premise
this file was built on — "a limited user can write HKCU" — was false for the one
subtree that mattered.

These cases pin the behaviour that replaced it: try force-install, fall back to
an external-extension registration that a standard user CAN write, and never
report success when neither worked. winreg is stubbed, so they run anywhere.

    python3 windows_agent/ensure_extension_test.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


class FakeKey:
    def __init__(self, store, path):
        self.store, self.path = store, path


HIVE = {0: "HKCU", 1: "HKLM"}


def make_winreg(deny_paths=(), fail_all=False, deny_hives=()):
    """
    A winreg stub.

    `deny_paths`: substrings whose CreateKeyEx raises WinError 5 (the Policies
    ACL in the field). `deny_hives`: whole hives that refuse writes, which is
    what an unprivileged process sees for HKLM.
    """
    m = types.ModuleType("winreg")
    m.HKEY_CURRENT_USER = 0
    m.HKEY_LOCAL_MACHINE = 1
    m.KEY_READ = m.KEY_WRITE = m.REG_SZ = 1
    m.store = {}

    def CreateKeyEx(root, path, reserved=0, access=0):
        key = f"{HIVE.get(root, root)}\\{path}"
        if (fail_all or HIVE.get(root) in deny_hives
                or any(d.lower() in path.lower() for d in deny_paths)):
            raise PermissionError(5, "Access is denied")
        m.store.setdefault(key, {})
        return FakeKey(m.store, key)

    def SetValueEx(key, name, reserved, typ, value):
        key.store[key.path][name] = value

    def QueryValueEx(key, name):
        if name not in key.store[key.path]:
            raise OSError("not found")
        return key.store[key.path][name], 1

    def EnumValue(key, i):
        items = list(key.store[key.path].items())
        if i >= len(items):
            raise OSError("no more")
        return items[i][0], items[i][1], 1

    m.CreateKeyEx, m.SetValueEx = CreateKeyEx, SetValueEx
    m.QueryValueEx, m.EnumValue = QueryValueEx, EnumValue
    m.CloseKey = lambda k: None
    return m


def run(deny_paths=(), fail_all=False, elevated=False, deny_hives=()):
    """Run the real entrypoint against a stubbed winreg + Windows platform."""
    import ensure_extension
    fake = make_winreg(deny_paths, fail_all, deny_hives)
    sys.modules["winreg"] = fake
    real_platform, real_elev = sys.platform, ensure_extension._is_elevated
    sys.platform = "win32"
    ensure_extension._is_elevated = lambda: elevated
    logs = []
    try:
        ok = ensure_extension.ensure_extensions_forceinstall(log=logs.append)
    finally:
        sys.platform = real_platform
        ensure_extension._is_elevated = real_elev
        sys.modules.pop("winreg", None)
    return ok, logs, fake.store


print("Windows extension install:")

# ── The happy path: admin machine, policy write succeeds ──────────────────
ok, logs, store = run()
check("admin machine -> reports success", ok is True)
check("admin machine -> writes BOTH forcelist keys",
      sum(1 for k in store if "ExtensionInstallForcelist" in k) == 2)
check("admin machine -> does NOT touch the weaker fallback key",
      not any(k.endswith("Extensions\\ophdgbaogdhfdhmfnnjniegccekmgfok")
              or k.endswith("Extensions\\bnnifiompbeebhapoojlonamdghmlifh")
              for k in store))

# ── The bug in the field: WinError 5 on the Policies subtree ──────────────
ok, logs, store = run(deny_paths=("Policies",))
joined = "\n".join(logs)
check("non-admin machine -> still reports success via the fallback", ok is True)
check("non-admin machine -> writes NO forcelist key",
      not any("ExtensionInstallForcelist" in k for k in store))
check("non-admin machine -> registers Chrome as an external extension",
      store.get("HKCU\\Software\\Google\\Chrome\\Extensions\\ophdgbaogdhfdhmfnnjniegccekmgfok", {})
           .get("update_url") == "https://clients2.google.com/service/update2/crx")
check("non-admin machine -> registers Edge as an external extension",
      store.get("HKCU\\Software\\Microsoft\\Edge\\Extensions\\bnnifiompbeebhapoojlonamdghmlifh", {})
           .get("update_url") == "https://edge.microsoft.com/extensionwebstorebase/v1/crx")
check("non-admin machine -> the log SAYS the install is the weaker kind",
      "DISABLED" in joined and "EXTERNAL" in joined)
check("non-admin machine -> the log names the silent alternative",
      "GPO" in joined or "ADMX" in joined)

# ── Neither path available: must not claim success ────────────────────────
ok, logs, store = run(fail_all=True)
check("nothing writable -> reports FAILURE rather than a false success",
      ok is False)
check("nothing writable -> wrote nothing at all", store == {})
check("nothing writable -> explains both failures",
      "forcelist key" in "\n".join(logs) and "fallback" in "\n".join(logs))

# ── Idempotence: this runs on EVERY agent startup ─────────────────────────
import ensure_extension
fake = make_winreg(deny_paths=("Policies",))
sys.modules["winreg"] = fake
_p = sys.platform
sys.platform = "win32"
try:
    ensure_extension.ensure_extensions_forceinstall(log=lambda m: None)
    second = []
    ensure_extension.ensure_extensions_forceinstall(log=second.append)
finally:
    sys.platform = _p
    sys.modules.pop("winreg", None)
check("second run recognises its own work instead of rewriting it",
      any("already registered" in m for m in second))

# ── Elevated: the silent path, which is the whole point of doing this ────
ok, logs, store = run(elevated=True)
joined = "\n".join(logs)
check("elevated -> writes the MACHINE-WIDE policy",
      sum(1 for k in store if k.startswith("HKLM") and "ExtensionInstallForcelist" in k) == 2)
check("elevated -> does not also write HKCU (HKLM already covers everyone)",
      not any(k.startswith("HKCU") for k in store))
check("elevated -> never touches the prompt-triggering fallback",
      not any("Extensions\\" in k for k in store))
check("elevated -> log states the install is silent and unremovable",
      "silent, enabled, user cannot remove" in joined)

# ── Elevated but HKLM refused: must not give up, must not lie ────────────
ok, logs, store = run(elevated=True, deny_hives=("HKLM",))
check("HKLM refused -> falls through to HKCU rather than failing",
      ok is True)
check("HKLM refused -> HKCU forcelist written",
      sum(1 for k in store if k.startswith("HKCU") and "ExtensionInstallForcelist" in k) == 2)

# ── Unelevated: don't log a denial for a write we know cannot land ───────
ok, logs, store = run(elevated=False)
check("unelevated -> HKLM is never attempted (no per-startup noise)",
      "HKLM" not in "\n".join(logs))

# ── The real field machine: unelevated AND Policies denied ───────────────
ok, logs, store = run(elevated=False, deny_paths=("Policies",))
check("field case -> still lands via the external fallback",
      ok is True and any(k.startswith("HKCU") and "Extensions\\" in k for k in store))

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
