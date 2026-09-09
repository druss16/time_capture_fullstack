"""
Regression tests for BROWSER-CHROME stripping in the distinctive-token matcher.

The bug this locks down, observed live on org 21 (block 69368):

    "9-8-2026 St. Mary's Cemetery bills etc_ (002).pdf and 1 more page
     - Work - Microsoft<U+200B> Edge"     booked to "St. Joseph's Church"

The Mismatches tab reported ZERO client mismatches over 4,232 committed blocks
while that sat in the data — a false clean bill of health, which is worse than a
miss, because it is read as proof the book is clean.

`strip_app_chrome` only ever stripped QuickBooks banners, so the browser banner
survived into scoring and the word "edge" matched a real client named "Cutting
Edge Decks, Inc" for 5.8 distinctive mass. Not enough to WIN — the correct
target scored 7.4 — but `AMBIGUITY_RATIO` is 0.65, and 5.8 >= 0.65 * 7.4, so the
detector concluded the title named two clients and suppressed itself.

That is the shape worth remembering: chrome noise does not have to beat the
right answer to destroy it. It only has to look like a second opinion.

Compounding it, Edge writes a ZERO-WIDTH SPACE (U+200B) inside its own banner,
so even a literal "Microsoft Edge" pattern would have missed. Both halves are
tested here.

Pure module — no Django needed. Run inside the app container or bare:
    python tracker/browser_chrome_strip_test.py
"""
import importlib.util
import os
import string
import sys

# Load the matcher straight off disk rather than as `tracker.utils.<mod>`.
# Importing the package would run tracker/utils/__init__.py, which reaches
# tracker.models and therefore needs a configured Django. The matcher itself
# needs none of that, and this keeps the test runnable with bare python.
_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "utils", "client_name_match.py"
)
_spec = importlib.util.spec_from_file_location("_client_name_match", _MODULE_PATH)
_cnm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cnm)

build_token_index = _cnm.build_token_index
detect_mismatch = _cnm.detect_mismatch
strip_app_chrome = _cnm.strip_app_chrome
_tokenize = _cnm._tokenize

# ── Fixture ──────────────────────────────────────────────────────────────────
# Token weights here are IDF-like, so they depend on the SIZE and SHAPE of the
# roster, not just the names in it. A six-client toy roster makes "cemetery"
# look common and scores the right answer at 0.536 coverage — just under the
# 0.55 gate — so the end-to-end assertion would fail against a correct matcher.
#
# This fixture reproduces production exactly: the 26 real org-21 names in the
# saint/cemetery family that caused the bug, padded to the real roster size of
# 330 with inert filler. It yields the same weights the live index does
# (bville 5.802, cemetery 4.010, mary 3.237, st 0.150).
#
# The filler carries NO DIGITS on purpose. The first attempt numbered it
# ("Redacted Holding 002") and that name promptly matched the "(002)" in the
# test's own filename for 5.8 mass and re-suppressed the detection — the exact
# bug being fixed, reproduced by accident in its own fixture. Which is the point:
# any stray token that scores can silently veto a correct match.
_FAMILY = [
    "Cutting Edge Decks, Inc",          # the decoy: matched "Edge" from the banner
    "Joseph Murray", "Mary Driscoll-Ingraham", "Mary Rodman",
    "North Syracuse Cemetery", "Pine Plains Cemetery Association",
    "Sacred Heart & St. Mary's Church", "St John Cemetery-Rome",
    "St Mary's Church- Clinton", "St Mary's Oswego", "St Patrick's Jordan Cemetery",
    "St Peter's Cemetery", "St. Anne Mother of Mary Church",
    "St. John the Baptist Church", "St. John the Evangelist", "St. John's Church",
    "St. John's Episcopal Church", "St. Joseph's Church",
    "St. Joseph's Church-Oriskany falls", "St. Mary's Cemetery Bville",
    "St. Mary's Church Baldwinsville", "St. Mary's Church-Hamilton",
    "St. Mary's Church-Minoa", "St. Mary's School Baldwinsville",
    "St. Mary's of the Assumption", "St. Mary's of the Lake",
]
ROSTER_SIZE = 330

ROSTER = {1000 + i: name for i, name in enumerate(_FAMILY)}
_letters = string.ascii_lowercase
_n = 0
for _a in _letters:
    for _b in _letters:
        if _n >= ROSTER_SIZE - len(_FAMILY):
            break
        ROSTER[2000 + _n] = f"Filler{_a.upper()}{_b} Holdings"
        _n += 1
    if _n >= ROSTER_SIZE - len(_FAMILY):
        break

BOOKED_CHURCH = next(k for k, v in ROSTER.items() if v == "St. Joseph's Church")
CEMETERY = next(k for k, v in ROSTER.items() if v == "St. Mary's Cemetery Bville")

ZWSP = "\u200b"
INDEX = build_token_index(ROSTER)

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


def tokens(title):
    return set(_tokenize(strip_app_chrome(title)))


# ── 1. The banner comes off, document text does not ──────────────────────────
check(
    "Edge banner with profile segment + zero-width space",
    strip_app_chrome(
        f"9-8-2026 St. Mary's Cemetery bills etc_ (002).pdf and 1 more page "
        f"- Work - Microsoft{ZWSP} Edge"
    ).strip(),
    "9-8-2026 St. Mary's Cemetery bills etc_ (002).pdf and 1 more page",
)
check(
    "Chrome banner, no profile segment",
    strip_app_chrome("Q3 payroll summary.pdf - Google Chrome").strip(),
    "Q3 payroll summary.pdf",
)
check(
    "Firefox banner",
    strip_app_chrome("Trial balance - Mozilla Firefox").strip(),
    "Trial balance",
)

# The banner is the ONLY thing that goes. A dashed document name survives it.
check(
    "dashed document name is preserved",
    strip_app_chrome("St. Mary's Church-Hamilton - 2026 audit - Work - Microsoft Edge").strip(),
    "St. Mary's Church-Hamilton - 2026 audit",
)
# No banner, nothing to do — and a client whose NAME ends in a browser word must
# never be truncated.
check(
    "no banner: title untouched",
    strip_app_chrome("Cutting Edge Decks invoice.pdf"),
    "Cutting Edge Decks invoice.pdf",
)
check(
    "QuickBooks stripping still works",
    strip_app_chrome("St. Joseph's Church - QuickBooks Accountant Desktop Plus 2024").strip(),
    "St. Joseph's Church",
)

# ── 2. Zero-width characters never survive into tokens ───────────────────────
check(
    "zero-width space inside a name does not split the token",
    tokens(f"Mary{ZWSP}s Cemetery bills.pdf"),
    {"marys", "cemetery", "bills", "pdf"},
)
check(
    "browser word is gone from the token set",
    "edge" in tokens(f"St. Mary's Cemetery bills.pdf - Work - Microsoft{ZWSP} Edge"),
    False,
)

# ── 3. The detection the bug suppressed now fires ────────────────────────────
LIVE_TITLE = (
    f"9-8-2026 St. Mary's Cemetery bills etc_ (002).pdf and 1 more page "
    f"- Work - Microsoft{ZWSP} Edge"
)
hit = detect_mismatch(LIVE_TITLE, BOOKED_CHURCH, INDEX, ROSTER, None)
check("block 69368 is detected at all", hit is not None, True)
if hit:
    check("…and names the cemetery, not a church", hit["looks_like_client_id"], CEMETERY)
    check("…as a billing-impacting client mismatch", hit["bucket"], "client")

# A second real case surfaced by the same 30-day sweep — booked to the cemetery,
# title naming St John Cemetery-Rome — is deliberately NOT asserted here. Whether
# it clears the ambiguity gate depends on how many St-John clients the roster
# holds, so it is a property of the live book rather than of this fix, and
# pinning it would make the test fail on a correct matcher after a roster change.

# ── 4. The gates still hold — this must not become a false-positive machine ──
# A title that genuinely names the client it is booked to stays silent.
check(
    "correctly booked block stays silent",
    detect_mismatch(
        f"St. Joseph's Church bulletin.pdf - Work - Microsoft{ZWSP} Edge",
        BOOKED_CHURCH, INDEX, ROSTER, None,
    ),
    None,
)
# A bare same-family name still abstains: "St. Mary's" alone cannot choose
# between the cemetery and the Baldwinsville church.
check(
    "ambiguous same-family title still abstains",
    detect_mismatch(
        f"St. Mary's bills.pdf - Work - Microsoft{ZWSP} Edge",
        BOOKED_CHURCH, INDEX, ROSTER, None,
    ),
    None,
)
# Stripping chrome must not invent a detection out of a title that is nothing
# but chrome.
check(
    "chrome-only title detects nothing",
    detect_mismatch(f"Work - Microsoft{ZWSP} Edge", BOOKED_CHURCH, INDEX, ROSTER, None),
    None,
)

if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print(f"  ✗ {f}")
    sys.exit(1)
print("browser_chrome_strip_test: all checks passed")
