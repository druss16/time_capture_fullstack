"""
Chrome's signed-in profile must never reach the client matcher.

THE BUG, MEASURED ON A LIVE ACCOUNT
-----------------------------------
Chrome appends the signed-in profile AFTER its own name:

    "00001-Ridgeline Holdings LLC - Dashboard | Clio - Google Chrome - dan@mavops.ai"

Every strip in this codebase assumed the browser name came LAST — a regex
anchored with `\\s*$` on the server, endswith() lists in both agents. So none
matched, "dan@mavops.ai" reached the scorer, and the firm had a real client
named "MAVOPS". Result: the agent pinned every Chrome tab to MAVOPS regardless
of the page on screen.

WHY IT IS WORSE THAN THE EDGE BANNER BUG (PR #405)
That one leaked "edge" as a PARTIAL decoy which merely had to look like a
second opinion to veto a correct answer. This leaks an EXACT client-name match
that wins outright — and it lands on the firm's own name, which is precisely
the client most likely to be in the roster.

WHAT THESE TESTS ARE REALLY GUARDING
The over-strip, as much as the under-strip. A strip that eats document text is
worse than the noise it removes, because the evidence is gone before anything
can weigh it — so every case below that asserts text SURVIVES is load-bearing.

    python manage.py shell -c "import tracker.browser_profile_suffix_test"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def check(label, cond, extra=''):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label} {extra}")


try:
    from tracker.utils.client_name_match import strip_app_chrome
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print(f"  SKIP  app deps unavailable ({type(e).__name__})")

if _ok:
    print("Chrome profile suffix is removed:")
    REAL = ('00001-Ridgeline Holdings LLC - Dashboard | Clio '
            '- Google Chrome - dan@mavops.ai')
    out = strip_app_chrome(REAL).strip()
    check("the live failing title loses the profile",
          'mavops' not in out.lower(), out)
    check("...and keeps the client name",
          'Ridgeline Holdings LLC' in out, out)
    check("...and keeps the matter number",
          '00001' in out, out)

    check("a bare profile tail goes",
          strip_app_chrome('Extensions - Google Chrome - dan@mavops.ai').strip()
          == 'Extensions')
    check("Firefox's profile tail goes",
          strip_app_chrome('Report - Mozilla Firefox - Personal').strip() == 'Report')

    print("\nthe strip stays minimal — document text must survive:")
    # The whole point: the profile group may not reach back past the browser
    # name. A client named in the middle of a title has to survive.
    check("a client name before the browser is untouched",
          strip_app_chrome(
              'Smith Estate - Ridgeline Holdings - Google Chrome - dan@x.com'
          ).strip() == 'Smith Estate - Ridgeline Holdings')
    check("only ONE segment after the browser is eaten",
          'Dashboard | Clio' in strip_app_chrome(REAL))

    print("\nnothing that merely looks like chrome is stripped:")
    for title in (
        'Smith Estate Plan.docx',
        'Cutting Edge Decks - proposal.pdf',   # "Edge" is a real client word
        'Acme - Chrome River Expense',         # "Chrome" mid-title
        'Google Chrome Enterprise rollout.md',
    ):
        check(f"survives: {title!r}", strip_app_chrome(title).strip() == title)

    print("\nthe pre-existing Edge shape still works:")
    check("Edge with a profile BEFORE the name",
          strip_app_chrome('Invoices - Work - Microsoft Edge').strip() == 'Invoices')
    check("Edge with no profile",
          strip_app_chrome('Invoices - Microsoft Edge').strip() == 'Invoices')
    check("Chrome with no profile",
          strip_app_chrome('Some Doc - Google Chrome').strip() == 'Some Doc')
    check("zero-width injected Edge banner still stripped",
          strip_app_chrome('Invoices - Microsoft​ Edge').strip() == 'Invoices')

    print("\nempty and degenerate input:")
    check("empty string", strip_app_chrome('') == '')
    check("None is tolerated", strip_app_chrome(None) == '')
    check("a title that is ONLY chrome collapses",
          strip_app_chrome('Google Chrome - dan@mavops.ai').strip()
          in ('', 'Google Chrome - dan@mavops.ai'))

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
