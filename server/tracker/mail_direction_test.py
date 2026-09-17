"""
Regression tests for _classify_direction (tracker.tasks_mail).

The bug it guards: direction is decided by comparing domains against the
connected mailbox's domain. Connect a PERSONAL mailbox — mavops1@outlook.com —
and user_domain becomes "outlook.com", so every other outlook.com/hotmail user
on earth reads as a colleague. Their mail is classified 'internal' and dropped
at sync, never reaching MailSignal. A self-addressed test thread in that
mailbox produced zero rows, and the Daily Review block for the time spent
reading it stayed "second-pass: unrecognized" with nothing to attribute from.

A real firm domain (@df-cpas.com) must keep the old behavior exactly: colleague
mail is still internal and still dropped. Only the public-domain case changes,
and there identity becomes the address instead of the domain.

Addresses are used for the comparison ONLY. The caller persists the domain and
nothing else — MailSignal's privacy guarantee is untouched.

Run inside the app container:
    python manage.py shell -c "import tracker.mail_direction_test"
or standalone (no Django needed):
    python tracker/mail_direction_test.py

Exits non-zero if any assertion fails.
"""
import os
import sys

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
    from tracker.tasks_mail import _classify_direction as classify
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("mail direction:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


def firm(sender, recipients):
    """A firm mailbox on its own domain: wayne@df-cpas.com."""
    return classify(
        sender_domain=sender.split('@')[-1],
        recipient_domains=[r.split('@')[-1] for r in recipients],
        user_domain='df-cpas.com',
        sender_email=sender,
        recipient_emails=list(recipients),
        user_email='wayne@df-cpas.com',
    )


def personal(sender, recipients):
    """A personal mailbox on a public domain: mavops1@outlook.com."""
    return classify(
        sender_domain=sender.split('@')[-1],
        recipient_domains=[r.split('@')[-1] for r in recipients],
        user_domain='outlook.com',
        sender_email=sender,
        recipient_emails=list(recipients),
        user_email='mavops1@outlook.com',
    )


if _ok:
    print("mail direction:")

    # --- the bug: a public mailbox is not an org ------------------------------
    # The exact thread that went missing: read in the browser, billed as
    # unrecognized, never stored because both ends were @outlook.com.
    check("stranger on outlook.com -> inbound, not internal",
          personal('someone@outlook.com', ['mavops1@outlook.com'])
          == ('inbound', 'outlook.com'))
    check("sent to another outlook.com address -> outbound",
          personal('mavops1@outlook.com', ['client@outlook.com'])
          == ('outbound', 'outlook.com'))
    check("hotmail sender into an outlook.com mailbox -> inbound",
          personal('x@hotmail.com', ['mavops1@outlook.com'])
          == ('inbound', 'hotmail.com'))

    # --- but the user mailing only themselves really is internal --------------
    check("self to self -> internal",
          personal('mavops1@outlook.com', ['mavops1@outlook.com']) == ('internal', ''))
    check("self to self, case and padding ignored",
          personal('  MavOps1@Outlook.com ', ['MAVOPS1@OUTLOOK.COM']) == ('internal', ''))

    # --- a real firm domain keeps the old behavior verbatim -------------------
    check("colleague to colleague -> internal (unchanged)",
          firm('wayne@df-cpas.com', ['terri@df-cpas.com']) == ('internal', ''))
    check("client writes the firm -> inbound (unchanged)",
          firm('bob@acmecorp.com', ['wayne@df-cpas.com']) == ('inbound', 'acmecorp.com'))
    check("firm writes a client -> outbound (unchanged)",
          firm('wayne@df-cpas.com', ['bob@acmecorp.com']) == ('outbound', 'acmecorp.com'))
    check("firm mails a client with a colleague cc'd -> outbound to the client",
          firm('wayne@df-cpas.com', ['bob@acmecorp.com', 'terri@df-cpas.com'])
          == ('outbound', 'acmecorp.com'))
    check("outbound to several -> dominant external domain wins",
          firm('wayne@df-cpas.com',
               ['a@acmecorp.com', 'b@acmecorp.com', 'c@other.com'])
          == ('outbound', 'acmecorp.com'))
    check("a firm colleague on outlook.com is still external to the firm",
          firm('wayne@df-cpas.com', ['someone@outlook.com'])
          == ('outbound', 'outlook.com'))

    # --- refusals: guess nothing ---------------------------------------------
    check("no mailbox domain -> unknown",
          classify(sender_domain='x.com', recipient_domains=['y.com'],
                   user_domain='') == ('unknown', ''))
    check("public mailbox with no address to compare -> unknown, never internal",
          classify(sender_domain='outlook.com', recipient_domains=['outlook.com'],
                   user_domain='outlook.com') == ('unknown', ''))
    check("no sender at all -> unknown",
          firm('', []) == ('unknown', ''))

    # --- the old signature still works (callers that pass domains only) -------
    check("domain-only call on a firm domain still classifies",
          classify(sender_domain='acmecorp.com', recipient_domains=['df-cpas.com'],
                   user_domain='df-cpas.com') == ('inbound', 'acmecorp.com'))

print()
print(f"mail direction: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
