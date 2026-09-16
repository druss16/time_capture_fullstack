#!/usr/bin/env python3
"""
The three MDM URLs, pinned against the server's real routes.

Why this file exists. For a long time every URL in mdm_deploy.py appended
/api/deploy/... to an api_base that already ends in /api, so all three
resolved to /api/api/deploy/... — a Django routing 404, not the view:

    POST /api/deploy/auto-pair/       {"error": "Invalid org token"}   the view
    POST /api/api/deploy/auto-pair/   <!doctype html> ... Not Found    routing

do_org_token_claim then logged "Org token claim failed — falling back to
manual pairing" on every IT-deployed machine, which is precisely the outcome
org-token deployment exists to prevent. It failed silently and looked like a
provisioning-data problem rather than a typo.

Nothing about that is visible from inside the file: both spellings are valid
strings and both "work" until something actually posts them. So these
assertions compare against the routes the server really serves
(timeserver/urls.py mounts tracker.urls_deployment at 'api/deploy/'), and
against how main.py builds every OTHER agent URL from the same API_BASE.

Also pinned: a repair must not be silently undone by the very claim this fix
re-enables.

Run:
    python3 test_mdm_urls.py

Exits non-zero if any assertion fails.
"""
import os
import re
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


print("windows MDM urls:")

# The api_base main.py actually passes: it already ends in /api.
API = "https://timetracker-api-k375.onrender.com/api"

REAL = {
    "auto-pair":    "https://timetracker-api-k375.onrender.com/api/deploy/auto-pair/",
    "claim":        "https://timetracker-api-k375.onrender.com/api/deploy/claim/",
    "confirm-user": "https://timetracker-api-k375.onrender.com/api/deploy/confirm-user/",
}

seen = []
M._post_captured = seen


def fake_urlopen(req, timeout=None):
    seen.append(req.full_url)
    raise RuntimeError("stop here — the URL is all this test wants")


M.urllib.request.urlopen = fake_urlopen


def url_of(fn, *args):
    seen.clear()
    try:
        fn(*args)
    except Exception:
        pass
    return seen[0] if seen else ""


u = url_of(M.claim_with_auto_pair, API, "tok", "HOST", "USER", "1.0")
check("auto-pair posts to the route the server serves", u == REAL["auto-pair"])

u = url_of(M.claim_with_org_token_legacy, API, "tok", "HOST", "USER", "1.0")
check("claim posts to the route the server serves", u == REAL["claim"])

u = url_of(M.confirm_user_selection, API, "tok", "HOST", 7, "1.0")
check("confirm-user posts to the route the server serves",
      u == REAL["confirm-user"])

# --- the shape of the bug, stated directly -------------------------------
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mdm_deploy.py"), encoding="utf-8").read()
check("no URL in the file re-adds the /api prefix",
      "/api/deploy/" not in src.replace('"/api/deploy/', "@@")
      or not re.search(r'f"\{api_base\.rstrip\(.\/.\)\}/api/deploy/', src))

# --- consistency with the rest of the agent ------------------------------
main_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "main.py"), encoding="utf-8").read()
others = re.findall(r'f"\{API_BASE\}(/[a-z0-9/\-]+)', main_src)
check("every other agent URL appends straight onto API_BASE, "
      f"same as these now do ({len(others)} of them)",
      bool(others) and not any(o.startswith("/api/") for o in others))

# --- a repair must survive the claim -------------------------------------
check("repair_device marks the next start to ask, not re-claim",
      'config["relink_requested"] = True' in main_src)
check("...and run_agent pops it", 'config.pop("relink_requested"' in main_src)
def _before(a, b, text):
    """True only if both are present and a precedes b.

    .index() would raise when the marker is absent, which turns a plain
    failure into a traceback and hides the checks after it.
    """
    i, j = text.find(a), text.find(b)
    return i != -1 and j != -1 and i < j


check("...before deciding whether to use the org token",
      _before('config.pop("relink_requested"',
              "from mdm_deploy import do_org_token_claim", main_src))
check("...saving immediately, so a crash cannot leave it armed",
      re.search(r'config\.pop\("relink_requested", False\):\s*\n\s*save_config\(config\)',
                main_src) is not None)

print(f"\n  {_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
