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


def make_winreg(deny_paths=(), fail_all=False):
    """A winreg stub. `deny_paths`: substrings whose CreateKeyEx raises WinError 5."""
    m = types.ModuleType("winreg")
    m.HKEY_CURRENT_USER = 0
    m.KEY_READ = m.KEY_WRITE = m.REG_SZ = 1
    m.store = {}

    def CreateKeyEx(root, path, reserved=0, access=0):
        if fail_all or any(d.lower() in path.lower() for d in deny_paths):
            raise PermissionError(5, "Access is denied")
        m.store.setdefault(path, {})
        return FakeKey(m.store, path)

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


def run(deny_paths=(), fail_all=False):
    """Run the real entrypoint against a stubbed winreg + Windows platform."""
    import ensure_extension
    fake = make_winreg(deny_paths, fail_all)
    sys.modules["winreg"] = fake
    real_platform = sys.platform
    sys.platform = "win32"
    logs = []
    try:
        ok = ensure_extension.ensure_extensions_forceinstall(log=logs.append)
    finally:
        sys.platform = real_platform
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
      store.get("Software\\Google\\Chrome\\Extensions\\ophdgbaogdhfdhmfnnjniegccekmgfok", {})
           .get("update_url") == "https://clients2.google.com/service/update2/crx")
check("non-admin machine -> registers Edge as an external extension",
      store.get("Software\\Microsoft\\Edge\\Extensions\\bnnifiompbeebhapoojlonamdghmlifh", {})
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

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
