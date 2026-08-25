"""
Regression tests for the MavOps "View as" privilege gate.

View-as swaps request.user during authentication, so every view in the app
trusts whatever tracker.impersonation.resolve_view_as_user returns. That makes
this one function the entire security boundary of the feature — these cases
pin its rules down.

Invariants:
  * Only staff/superuser can view as anyone at all.
  * No lateral escalation: plain staff cannot step into a superuser.
  * The MavOps console, auth and support paths NEVER swap — localStorage is
    shared across browser tabs, so without that exemption an admin who starts a
    view-as in one tab would lock themselves out of the console in the other.
  * Absent a header the function is a pure pass-through, so normal sessions are
    byte-for-byte unaffected.

Runs with ZERO database queries: _lookup is stubbed with an in-memory
directory, so this is safe to run against a container wired to production.

Run inside the app container:
    python manage.py shell -c "import tracker.view_as_test"
or standalone where Django is configured:
    python tracker/view_as_test.py

Exits non-zero if any assertion fails.
"""
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timeserver.settings")
try:
    django.setup()
except Exception as exc:  # pragma: no cover - bare python, nothing to test
    print(f"SKIP: Django not configured ({exc})")
    sys.exit(0)

from rest_framework.exceptions import AuthenticationFailed

from tracker import impersonation as imp
class U:
    def __init__(self, pk, username, staff=False, superuser=False, active=True):
        self.pk = pk; self.id = pk; self.username = username
        self.is_staff = staff; self.is_superuser = superuser
        self.is_active = active; self.is_authenticated = True
        self.first_name = ""; self.last_name = ""


class Req:
    def __init__(self, header=None, path="/api/blocks-today/", method="GET", get=None):
        self.META = {"HTTP_X_VIEW_AS_USER": header} if header else {}
        self.path = path; self.method = method
        self.GET = get or {}


DIRECTORY = {}
imp._lookup = lambda raw: DIRECTORY.get(raw)

admin = U(1, "dan", staff=True, superuser=True)
staff = U(2, "support", staff=True)
member = U(3, "emily")
owner = U(4, "tlwall_owner")
root = U(5, "root", staff=True, superuser=True)
dead = U(6, "gone", active=False)
for u in (admin, member, owner, root, dead, staff):
    DIRECTORY[str(u.pk)] = u
    DIRECTORY[u.username] = u

fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

def denies(req, real):
    try:
        imp.resolve_view_as_user(req, real); return None
    except AuthenticationFailed as e:
        return str(e.detail)

# ── happy path ────────────────────────────────────────────────────────────
r = Req("3")
check("admin -> member swaps identity", imp.resolve_view_as_user(r, admin) is member)
check("request is marked is_view_as", getattr(r, "is_view_as", False) is True)
check("impersonator recorded", getattr(r, "impersonator", None) is admin)
check("whoami context names the real admin",
      imp.view_as_context(r).get("real_username") == "dan")

check("username also resolves", imp.resolve_view_as_user(Req("emily"), admin) is member)

# ── no header = untouched ─────────────────────────────────────────────────
r2 = Req()
check("no header -> real user", imp.resolve_view_as_user(r2, admin) is admin)
check("no header -> not marked", getattr(r2, "is_view_as", False) is False)
check("no view_as context when off", imp.view_as_context(r2) == {})

# ── privilege gates ───────────────────────────────────────────────────────
check("non-staff CANNOT view as anyone",
      "staff access required" in (denies(Req("3"), member) or ""))
check("staff cannot view as a superuser",
      "cannot view as a superuser" in (denies(Req("5"), staff) or ""))
check("superuser CAN view as a superuser",
      imp.resolve_view_as_user(Req("5"), admin) is root)
check("deactivated target refused",
      "deactivated" in (denies(Req("6"), admin) or ""))
check("unknown target refused",
      "no such user" in (denies(Req("9999"), admin) or ""))
check("self is a no-op", imp.resolve_view_as_user(Req("1"), admin) is admin)

# ── the lockout guard ─────────────────────────────────────────────────────
for p in ("/api/mavops/orgs/", "/api/mavops/view-as/", "/api/auth/logout/", "/api/support/ask/"):
    check(f"exempt: {p}", imp.resolve_view_as_user(Req("3", path=p), admin) is admin)
check("non-exempt path still swaps",
      imp.resolve_view_as_user(Req("3", path="/api/reports/summary/"), admin) is member)

# ── query-param fallback (SSE) ────────────────────────────────────────────
check("?view_as= works for header-less transports",
      imp.resolve_view_as_user(Req(get={"view_as": "3"}), admin) is member)
check("?view_as= obeys the same staff gate",
      "staff access required" in (denies(Req(get={"view_as": "4"}), member) or ""))

# ── writes are permitted and audited ──────────────────────────────────────
w = Req("3", path="/api/blocks/1/confirm/", method="POST")
check("writes go through as the target", imp.resolve_view_as_user(w, admin) is member)

print()
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("ALL PASS")
