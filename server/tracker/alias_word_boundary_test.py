"""
Regression test: alias phrase matching must respect WORD boundaries.

The bug this locks down, observed live on org 21 (block 70360, 1.1h billable):

    "Smart Sourcing - Accounting Manager/Corporate Tax Preparer Candidates
     in Syracuse, NY 13212 - Indeed for Employers ..."
    attributed to client "N. Syracuse Fire Department"

That is an Indeed job ad for the FIRM's own staff opening. It was billed to a
fire department for 67 minutes.

Cause: `_alias_matches_safely` tested three phrases with a bare `needle in
haystack` on space-joined normalized tokens. The client normalizes to
"n syracuse fire department", and its two-token leading prefix "n syracuse" is
a SUBSTRING of "candidates i[n syracuse] ny 13212". The preposition's trailing
letter supplied the client's initial.

The test is that precise: change "in" to "at" and the match disappears. And it
generalizes badly — any client whose name begins with an initial ("N.", "J.",
"T.") is a magnet for every sentence containing a word ending in that letter,
and the tab never flags it because no RIVAL client is named. The mismatch
detector is blind to this shape by construction: it only fires when two clients
disagree, never when one client is quietly wrong on its own.

Fix: pad both sides with spaces before the containment test. `_normalize_name`
emits single-space-separated tokens, so that is an exact word-boundary test.

Run inside the app container (this one needs Django — the matcher lives on
ClassificationService):
    docker exec time_api python manage.py shell -c "import tracker.alias_word_boundary_test"
"""
import sys

from tracker.services.classification_service import ClassificationService as CS

FAILURES = []


def check(label, cond):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


FIRE = "N. Syracuse Fire Department"

print("\n1. The live false attribution is gone")
check("an Indeed ad for the firm's own vacancy is not fire-department work",
      not CS._alias_matches_safely(
          FIRE,
          "Smart Sourcing - Accounting Manager/Corporate Tax Preparer "
          "Candidates in Syracuse, NY 13212 - Indeed for Employers"))
check("minimal reproduction: 'jobs in Syracuse' names no client",
      not CS._alias_matches_safely(FIRE, "jobs in Syracuse"))
check("nor does any other sentence that happens to contain 'in Syracuse'",
      not CS._alias_matches_safely(FIRE, "best places to eat in Syracuse tonight"))

print("\n2. The client still matches its own work")
check("its literal name",
      CS._alias_matches_safely(FIRE, "N. Syracuse Fire Department invoice"))
check("its spelled-out form",
      CS._alias_matches_safely(FIRE, "North Syracuse Fire Department payroll"))
check("inside a QuickBooks title",
      CS._alias_matches_safely(
          FIRE, "N. Syracuse Fire Department - QuickBooks Accountant Desktop Plus 2024"))

print("\n3. The boundary rule is general, not a patch for one client")
# Any leading initial is the same magnet: a title word ENDING in that letter,
# followed by the client's second word, forges the prefix across the space.
#
# Each case is self-proving. It asserts BOTH that the unanchored substring is
# genuinely there — so the old code really would have matched it — and that the
# matcher now refuses. Without the first half these would silently degrade into
# tests of nothing the day someone rewrote the normalizer.
#
# Only ONE of the client's own words is in each title, which is what keeps the
# token fallback out of it. That is the real shape: the phantom prefix is the
# only thing carrying the match, exactly as with "N. Syracuse Fire Department".
for alias, title, why in (
    ("D. Hartford Supply",  "the second hartford location closed", "secon[d hartford]"),
    ("E. Rochester Diner",  "the store rochester branch closed", "stor[e rochester]"),
    ("N. Syracuse Fire Department",
     "candidates in Syracuse, NY 13212",                          "i[n syracuse]"),
):
    alias_n = CS._normalize_name(alias.lower())
    prefix = " ".join(alias_n.split()[:2])
    check(f"{why} really does contain the phantom prefix {prefix!r}",
          prefix in CS._normalize_name(title))
    check(f"…and {alias!r} no longer matches it",
          not CS._alias_matches_safely(alias, title))

print("\n4. Ordinary multi-word matching is untouched")
check("a full contiguous name still matches",
      CS._alias_matches_safely("Sacred Heart Church", "Sacred Heart Church 2025.qbw"))
check("the filler-collapsed retry still matches",
      CS._alias_matches_safely("Church Of Annunciation",
                               "The Church of THE Annunciation - Clark Mills, NY"))
check("a genuine leading prefix still matches",
      CS._alias_matches_safely("CNY Coin & Silver, Inc.",
                               "CNY Coin Client Information - Excel"))
check("an unrelated title still does not",
      not CS._alias_matches_safely("Sacred Heart Church", "Quarterly Payroll Report.xlsx"))

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("alias_word_boundary_test: all checks passed")
