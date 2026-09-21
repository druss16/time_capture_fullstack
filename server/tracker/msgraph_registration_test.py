"""
Regression tests for _graph_credentials (tracker.integrations.msgraph).

Mail and calendar shared one Azure app registration. The consent PROMPT was
always honest — the mail flow requests Mail.ReadBasic + User.Read and nothing
else — but the app object carries Calendars.Read too, so a tenant admin who
grants consent for the app grants both. A customer's IT asked to consent to
mail alone, which needs a registration holding only the mail permissions.

What this guards: the two settings move TOGETHER. Falling back field by field
would pair the mail registration's client ID with the calendar registration's
secret the moment someone sets one env var and not the other — a combination
that authenticates as neither app, and whose AADSTS error names a client ID
that looks correct. A blank secret alongside a set ID must stay blank so the
failure is "you didn't finish configuring the mail app", not a puzzle.

Run inside the app container:
    python manage.py shell -c "import tracker.msgraph_registration_test"

Exits non-zero if any assertion fails.
"""
import os
import sys
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
    from tracker.integrations import msgraph
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("msgraph registration:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


def creds(client, mail_id='', mail_secret=''):
    """Resolve credentials against a stubbed settings object."""
    real = msgraph.settings
    msgraph.settings = SimpleNamespace(
        MS_GRAPH_CLIENT_ID='cal-id',
        MS_GRAPH_CLIENT_SECRET='cal-secret',
        MS_GRAPH_MAIL_CLIENT_ID=mail_id,
        MS_GRAPH_MAIL_CLIENT_SECRET=mail_secret,
    )
    try:
        return msgraph._graph_credentials(client)
    finally:
        msgraph.settings = real


if _ok:
    print("msgraph registration:")

    # --- unconfigured: nothing changes for anyone -----------------------------
    check("mail with no mail registration falls back to the calendar app",
          creds('mail') == ('cal-id', 'cal-secret'))
    check("calendar with no mail registration uses the calendar app",
          creds('calendar') == ('cal-id', 'cal-secret'))

    # --- configured: mail moves to its own app --------------------------------
    check("mail with its own registration uses it",
          creds('mail', 'mail-id', 'mail-secret') == ('mail-id', 'mail-secret'))
    check("calendar is untouched by the mail registration",
          creds('calendar', 'mail-id', 'mail-secret') == ('cal-id', 'cal-secret'))

    # --- the mixing trap: the pair never splits -------------------------------
    check("mail ID set, secret blank -> blank secret, NOT the calendar's",
          creds('mail', 'mail-id', '') == ('mail-id', ''))
    check("mail secret set, ID blank -> falls back as a pair, no half-switch",
          creds('mail', '', 'mail-secret') == ('cal-id', 'cal-secret'))

    # --- default argument -----------------------------------------------------
    check("no client argument means calendar",
          msgraph._graph_credentials.__defaults__ == ('calendar',))

print()
print(f"msgraph registration: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
