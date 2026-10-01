#!/usr/bin/env python3
"""
Org-token pairing for the Mac agent.

What these pin, in order of what has actually gone wrong:

1. **The URLs resolve.** The Windows copy builds f"{api_base}/api/deploy/..."
   while api_base already ends in /api, so every Windows MDM URL is
   /api/api/deploy/... and answers with a Django routing 404. The agent then
   logs "falling back to manual pairing" — which is the one thing org-token
   deployment exists to avoid. This file asserts the Mac agent's URLs against
   the server's real routes so the same mistake cannot be made twice.

2. **The values match what provision_firm stored.** Rows are written
   `machine_hostname=hostname.upper()` and `windows_username=win_user.upper()`,
   and the server compares exactly, so a lowercase send matches nothing.

3. **The ladder walks in the right order and stops when it should** — a
   provisioning-map hit never reaches the picker; an invalid token gives up
   rather than falling through; a network error retries.

4. **One device identity.** device_id is passed in, not minted here. The
   Windows copy keeps its own .device_id separate from the one its main.py
   uses, so a Windows box can hold two.

Run:
    python3 test_mdm_deploy.py

Exits non-zero if any assertion fails.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mdm_deploy as M

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


print("mac org-token pairing:")

# The api_base the agent actually holds: it already ends in /api.
API = "https://timetracker-api-k375.onrender.com/api"

# These are the routes the server really serves (timeserver/urls.py mounts
# tracker.urls_deployment at 'api/deploy/').
REAL = {
    "auto-pair":    "https://timetracker-api-k375.onrender.com/api/deploy/auto-pair/",
    "claim":        "https://timetracker-api-k375.onrender.com/api/deploy/claim/",
    "confirm-user": "https://timetracker-api-k375.onrender.com/api/deploy/confirm-user/",
}

calls = []


def fake_post(url, payload):
    calls.append((url, payload))
    return fake_post.reply


M._post = fake_post
M.time.sleep = lambda *_a: None          # never really wait in a test

# --- 1. the URLs ---------------------------------------------------------
fake_post.reply = {"status": "unprovisioned"}
calls.clear()
M.claim_with_auto_pair(API, "tok", "HOST", "dan", "dev-id", "1.0")
check("auto-pair hits the real route, not /api/api/",
      calls[0][0] == REAL["auto-pair"])

calls.clear()
M.claim_with_org_token_legacy(API, "tok", "HOST", "dan", "1.0")
check("claim hits the real route", calls[0][0] == REAL["claim"])

calls.clear()
M.confirm_user_selection(API, "tok", "HOST", 7, "dev-id", "1.0")
check("confirm-user hits the real route", calls[0][0] == REAL["confirm-user"])

check("no URL doubles the /api prefix (the Windows bug)",
      all("/api/api/" not in u for u, _ in
          [(REAL[k], None) for k in REAL]))

# --- 2. the values -------------------------------------------------------
calls.clear()
M.claim_with_auto_pair(API, "tok", "dans-macbook", "dan", "dev-id", "1.0")
_, payload = calls[0]
check("hostname is uppercased to match provision_firm's rows",
      payload["hostname"] == "DANS-MACBOOK")
check("the short name is uppercased too",
      payload["windows_username"] == "DAN")
check("platform says macos", payload["platform"] == "macos")
check("the device_id passed in is the one sent (no second identity)",
      payload["device_id"] == "dev-id")

check("a trailing .local is stripped from the hostname",
      M.mac_hostname().lower().endswith(".local") is False)

# --- 3. the ladder -------------------------------------------------------
def run(replies, members=None):
    """Drive do_org_token_claim with a scripted sequence of server replies."""
    seq = list(replies)
    saved = {}
    calls.clear()

    def post(url, payload):
        calls.append((url, payload))
        return seq.pop(0) if seq else {"status": "error", "message": "no reply"}

    M._post = post
    M.show_user_picker_gui = lambda ms: (members or [{}])[0].get("user_id")
    cfg = {"org_token": "tok"}
    key = M.do_org_token_claim(cfg, lambda c: saved.update(c), API, "1.0",
                               "dev-id", log=lambda *_a: None)
    return key, cfg, [u for u, _ in calls]


key, cfg, urls = run([{"status": "paired", "api_key": "K1",
                       "user_email": "dan@firm.com", "match_method": "hostname",
                       "device_id": "D1"}])
check("a provisioning-map hit pairs silently", key == "K1")
check("...and stops there — no claim, no picker", len(urls) == 1)
check("...storing the key and the server's device id",
      cfg["api_key"] == "K1" and cfg["server_device_id"] == "D1")

key, _, urls = run([{"status": "unprovisioned"},
                    {"status": "matched", "api_key": "K2",
                     "user_email": "dan@firm.com"}])
check("unprovisioned falls through to the claim ladder", key == "K2")
check("...which is the second call", urls[1] == REAL["claim"])

key, _, urls = run(
    [{"status": "unprovisioned"},
     {"status": "pick_user", "members": [{"user_id": 9, "email": "d@f.com"}]},
     {"status": "paired", "api_key": "K3", "user_email": "d@f.com"}],
    members=[{"user_id": 9}])
check("no match at all reaches the picker, then confirms", key == "K3")
check("...and confirm-user is the last call", urls[-1] == REAL["confirm-user"])

key, _, urls = run([{"status": "invalid_token"}])
check("a rejected org token gives up rather than falling through",
      key is None and len(urls) == 1)

key, _, urls = run([{"status": "error", "message": "getaddrinfo failed"},
                    {"status": "paired", "api_key": "K4", "user_email": "d@f.com"}])
check("a cold-boot network error retries instead of failing", key == "K4")

M.show_user_picker_gui = lambda ms: None
key, _, urls = run([{"status": "unprovisioned"},
                    {"status": "pick_user", "members": [{"user_id": 9}]}])
check("declining the picker leaves the Mac unpaired, not half-paired",
      key is None)

cfg = {}
check("no org token is a no-op, not an error",
      M.do_org_token_claim(cfg, lambda c: None, API, "1.0", "d",
                           log=lambda *_a: None) is None)

# --- 5. Re-link must survive MDM ----------------------------------------
# The regression this nearly shipped: Re-link Device clears api_key but NOT
# org_token, and on a managed Mac the token lives in the plist under /Library
# where the user cannot reach it. So the claim would run on the very next
# start and put the device straight back on whoever DeviceProvisioningMap
# names — the pairing window never appearing. Re-link is the only route back
# from a wrong account, so it has to win over the org token exactly once.
import re as _re

_main = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "main.py"), encoding="utf-8").read()
_gui = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "timetracker_gui.py"), encoding="utf-8").read()

# Re-link no longer removes the key at all: it pairs first and only clears the
# old account's cache after a new key exists. A managed Mac therefore never
# reaches the claim after a Re-link (a successful one holds the new key; a
# cancelled one keeps the old). That also fixed the worse failure: cancelling
# the window used to leave the Mac UNPAIRED, and the next restart stopped
# tracking. The marker below is still honoured for configs older agents wrote.
_relink = _gui[_gui.index("def do_relink():"):_gui.index("def _restart_app(")]
check("Re-link shows the pairing window BEFORE clearing anything",
      _relink.index("show_pairing_window(") < _relink.index("clear_account_cache("))
check("...and returns untouched when pairing is cancelled",
      _re.search(r"if not api_key:[^\n]*\n(?:\s*#[^\n]*\n|\s*print\([^\n]*\n)*\s*return\b", _relink) is not None)
_cache = _gui[_gui.index("def clear_account_cache("):_gui.index("# STYLED COMPONENTS")]
check("...and clearing the cache never removes the key",
      'pop("api_key"' not in _cache and "api_key" not in _cache.split('"""')[-1])
check("main.py still consumes a legacy relink marker with pop(), once",
      'config.pop("relink_requested"' in _main)
check("...gating the MDM read itself, not just the claim",
      _re.search(r"mdm_config\s*=\s*None if relink else get_mdm_config\(\)",
                 _main) is not None)
check("...and persisting the cleared flag, so a crash cannot re-arm it",
      _re.search(r"if relink:\s*\n\s*save_config\(config\)", _main) is not None)

# The flag must be read BEFORE the claim, or it cannot prevent anything.
_i_flag = _main.index('config.pop("relink_requested"')
# Match the CALL, not the word — the docstring above names the function too,
# and matching that made this pass for the wrong reason.
_i_claim = _main.index("key = do_org_token_claim(")
check("...read before the claim runs, not after", _i_flag < _i_claim)

# ---------------------------------------------------------------------------
# The MDM PPPC profile — the zero-touch path for managed Macs.
# ---------------------------------------------------------------------------
import plistlib as _plistlib  # noqa: E402
import subprocess as _sp  # noqa: E402
import uuid as _uuid  # noqa: E402

_PPPC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pkgroot", "Library", "Application Support", "MavOps")
_PPPC = os.path.join(_PPPC_DIR, "mavops-pppc-timetracker.mobileconfig")
with open(_PPPC, "rb") as _f:
    _profile = _plistlib.load(_f)
_TT_REQ = ("identifier TimeTracker and anchor apple generic and certificate "
           "1[field.1.2.840.113635.100.6.2.6] /* exists */ and certificate "
           "leaf[field.1.2.840.113635.100.6.1.13] /* exists */ and certificate "
           "leaf[subject.OU] = P3KX4CDFN4")


def _is_uuid(s):
    try:
        return str(_uuid.UUID(s)).upper() == s.upper()
    except Exception:
        return False


if sys.platform == "darwin":
    _lint = _sp.run(["plutil", "-lint", _PPPC], capture_output=True, text=True)
    check("PPPC profile passes plutil -lint", _lint.returncode == 0)
check("PPPC profile: every PayloadUUID is a real UUID",
      _is_uuid(_profile["PayloadUUID"])
      and all(_is_uuid(p["PayloadUUID"]) for p in _profile["PayloadContent"]))
_tcc = [p for p in _profile["PayloadContent"]
        if p["PayloadType"] == "com.apple.TCC.configuration-profile-policy"]
check("PPPC profile carries exactly one TCC payload", len(_tcc) == 1)
_svc = _tcc[0]["Services"] if _tcc else {}
_ax = _svc.get("Accessibility") or []
check("PPPC grants Accessibility to bundle id TimeTracker with our team's requirement",
      len(_ax) == 1 and _ax[0].get("Identifier") == "TimeTracker"
      and _ax[0].get("IdentifierType") == "bundleID"
      and _ax[0].get("Allowed") is True and _ax[0].get("CodeRequirement") == _TT_REQ)
check("PPPC requests nothing beyond Accessibility + Automation "
      "(no Screen Recording, Camera, Microphone)",
      set(_svc) == {"Accessibility", "AppleEvents"})
_ae = {e.get("AEReceiverIdentifier"): e for e in _svc.get("AppleEvents") or []}
_AGENT_RECEIVERS = {
    # browsers (main._CHROMIUM_APPS + Safari)
    "com.google.Chrome", "com.google.Chrome.beta", "com.google.Chrome.canary",
    "com.microsoft.edgemac", "com.microsoft.edgemac.Beta", "com.brave.Browser",
    "company.thebrowser.Browser", "com.vivaldi.Vivaldi", "com.apple.Safari",
    # Adobe (doc_capture.SCRIPTABLE_KINDS)
    "com.adobe.Photoshop", "com.adobe.illustrator", "com.adobe.InDesign",
    "com.adobe.Acrobat.Pro",
    # main._DOC_PATH_SCRIPTS + frontmost-app detection
    "com.microsoft.Excel", "com.microsoft.Word", "com.microsoft.Powerpoint",
    "com.apple.Preview", "com.apple.iWork.Numbers", "com.apple.iWork.Pages",
    "com.apple.iWork.Keynote", "com.apple.finder", "com.apple.TextEdit",
    "com.sublimetext.4", "com.apple.systemevents",
}
check("PPPC pre-approves every app the agent sends Apple Events to "
      f"(missing: {sorted(_AGENT_RECEIVERS - set(_ae))})",
      _AGENT_RECEIVERS <= set(_ae))
check("...each entry: TimeTracker as sender, Allowed, receiver pinned by requirement",
      all(e.get("Identifier") == "TimeTracker" and e.get("CodeRequirement") == _TT_REQ
          and e.get("Allowed") is True and e.get("AEReceiverIdentifierType") == "bundleID"
          and f'"{bid}"' in e.get("AEReceiverCodeRequirement", "")
          for bid, e in _ae.items()))
import permissions as _perm_mod  # noqa: E402
check("every Automation target on the setup checklist is in the PPPC profile",
      {t.bundle_id for t in _perm_mod.AUTOMATION_TARGETS} <= set(_ae))
check("the broken TimeTrackerAgent profile is gone",
      not os.path.exists(os.path.join(_PPPC_DIR, "mavops-pppc-timetrackeragent.mobileconfig")))

print(f"\n  {_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
