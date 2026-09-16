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

check("Re-link sets a marker the next start can see",
      'cfg["relink_requested"] = True' in _gui)
check("...and main.py consumes it with pop(), so it fires once",
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

print(f"\n  {_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
