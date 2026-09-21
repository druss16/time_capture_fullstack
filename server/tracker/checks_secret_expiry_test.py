"""
Regression tests for graph_client_secrets_are_current (tracker.checks).

This check runs before EVERY management command, so its failure modes are
unusually expensive:

  * It must never raise. A crash here takes down migrate, and the most likely
    bad input is a human-typed date in an env var.
  * It must stay silent for registrations that are not configured. An install
    with no mail, or no calendar, is not missing anything, and a warning that
    fires for everyone gets filtered out mentally — including on the day it
    finally matters.
  * It must never print the secret. The whole point is to be loud in deploy
    logs, which is the last place a credential should surface.

Run inside the app container:
    python manage.py shell -c "import tracker.checks_secret_expiry_test"

Exits non-zero if any assertion fails.
"""
import os
import sys
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


try:
    from tracker import checks as chk
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("graph secret expiry:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


def run(**kw):
    """Run the check against a stubbed settings object."""
    base = dict(
        MS_GRAPH_CLIENT_ID='', MS_GRAPH_CLIENT_SECRET='',
        MS_GRAPH_CLIENT_SECRET_EXPIRES='',
        MS_GRAPH_MAIL_CLIENT_ID='', MS_GRAPH_MAIL_CLIENT_SECRET='',
        MS_GRAPH_MAIL_CLIENT_SECRET_EXPIRES='',
    )
    base.update(kw)
    real = chk.settings
    chk.settings = SimpleNamespace(**base)
    try:
        return chk.graph_client_secrets_are_current(None)
    finally:
        chk.settings = real


def ids(results):
    return sorted(w.id for w in results)


if _ok:
    print("graph secret expiry:")

    today = date.today()
    far = (today + timedelta(days=400)).isoformat()
    soon = (today + timedelta(days=30)).isoformat()
    gone = (today - timedelta(days=5)).isoformat()
    CAL = dict(MS_GRAPH_CLIENT_ID='x', MS_GRAPH_CLIENT_SECRET='y')

    # --- silence where silence is right --------------------------------------
    check("nothing configured -> silent",
          ids(run()) == [])
    check("expiry comfortably far off -> silent",
          ids(run(**CAL, MS_GRAPH_CLIENT_SECRET_EXPIRES=far)) == [])
    check("client id without a secret is not 'in use' -> silent",
          ids(run(MS_GRAPH_CLIENT_ID='x')) == [])

    # --- the nudge ------------------------------------------------------------
    check("configured but no expiry recorded -> W002",
          ids(run(**CAL)) == ['tracker.W002'])
    check("a date nobody can parse -> W002, and NO exception",
          ids(run(**CAL, MS_GRAPH_CLIENT_SECRET_EXPIRES='next tuesday'))
          == ['tracker.W002'])

    # --- the alarm ------------------------------------------------------------
    check("inside the warning window -> W003",
          ids(run(**CAL, MS_GRAPH_CLIENT_SECRET_EXPIRES=soon)) == ['tracker.W003'])
    check("already expired -> W003",
          ids(run(**CAL, MS_GRAPH_CLIENT_SECRET_EXPIRES=gone)) == ['tracker.W003'])

    # --- the two registrations are independent --------------------------------
    check("both expiring -> one warning each",
          ids(run(**CAL, MS_GRAPH_CLIENT_SECRET_EXPIRES=soon,
                  MS_GRAPH_MAIL_CLIENT_ID='a', MS_GRAPH_MAIL_CLIENT_SECRET='b',
                  MS_GRAPH_MAIL_CLIENT_SECRET_EXPIRES=soon))
          == ['tracker.W003', 'tracker.W003'])
    check("mail configured, calendar not -> only mail speaks",
          ids(run(MS_GRAPH_MAIL_CLIENT_ID='a', MS_GRAPH_MAIL_CLIENT_SECRET='b'))
          == ['tracker.W002'])
    check("the warning names which registration it means",
          'mail' in run(MS_GRAPH_MAIL_CLIENT_ID='a', MS_GRAPH_MAIL_CLIENT_SECRET='b',
                        MS_GRAPH_MAIL_CLIENT_SECRET_EXPIRES=soon)[0].msg)

    # --- never leak the credential -------------------------------------------
    leaked = any(
        'SUPERSECRET' in (w.msg + (w.hint or ''))
        for w in run(MS_GRAPH_CLIENT_ID='client-abc',
                     MS_GRAPH_CLIENT_SECRET='SUPERSECRET',
                     MS_GRAPH_CLIENT_SECRET_EXPIRES=soon)
    )
    check("the secret value never appears in the warning text", not leaked)

print()
print(f"graph secret expiry: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
