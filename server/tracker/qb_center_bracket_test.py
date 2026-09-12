"""
Regression tests for the QuickBooks Vendor/Customer Center bracket.

The false positive this locks down, observed live on org 21 (block 50031):

    "St. Mary's Church  - QuickBooks Accountant Desktop Plus 2024
     - [Vendor Center: Integrated Marketing Services, Inc.]"   booked to
    "St. Mary's Church-Minoa"

reported as a CLIENT mismatch against "H & B Marketing". Nothing was wrong with
the block. The bracket names a VENDOR of St. Mary's Church, and the firm
happens to have a client whose name shares a word with it.

The bracket is deliberately not stripped — Stage 4.6 reads the vendor as a
fingerprint, looking it up in a vendor->client map to tell same-named parishes
apart, and dropping it cost 25 detections when that was tried. But a
fingerprint and a name are different things. The bracket can never name the
CLIENT of a QuickBooks block, because the company file already does: whatever
screen is open inside St. Mary's books, the work is in St. Mary's books.

So the rule is narrow. The segment stays in the text for every other purpose
and is refused only as a mismatch TARGET. Measured before it was written:
across every org over 180 days there is exactly ONE client-bucket detection on
a bracket-carrying title, and it is that false positive.

The shape is the same one browser chrome taught (see browser_chrome_strip_test):
text that rides along in a window title and is not the work's identity must not
be allowed to speak about identity. There it suppressed a right answer; here it
manufactures a wrong one.

Pure module — no Django needed:
    python tracker/qb_center_bracket_test.py
"""
import importlib.util
import os
import sys

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "utils", "client_name_match.py"
)
_spec = importlib.util.spec_from_file_location("_cnm", _MODULE_PATH)
cnm = importlib.util.module_from_spec(_spec)
sys.modules["_cnm"] = cnm
_spec.loader.exec_module(cnm)

QB = " - QuickBooks Accountant Desktop Plus 2024"

NAMES = {
    1: "St. Mary's Church-Minoa",
    2: "H & B Marketing",
    3: "Clinton Agway Feed Store",
    4: "St. Francis of Assisi Church",
}
INDEX = cnm.build_token_index(NAMES)

FAILURES = []


def check(label, cond):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


print("\n1. The live false positive is gone")
title = f"St. Mary's Church {QB} - [Vendor Center: Integrated Marketing Services, Inc.]"
m = cnm.detect_mismatch(title, 1, INDEX, NAMES)
check("a vendor sharing a word with a client no longer accuses the booking",
      m is None)

print("\n2. …and the reconcile path agrees with the detector")
# These two must never disagree: reconcile re-derives the target from the title,
# so a target the detector refuses must not be somewhere the fix button sends
# the block anyway.
det = cnm.detect_title_client(title, INDEX, NAMES)
check("detect_title_client will not reroute to the vendor's look-alike either",
      det is None or det["client_id"] != 2)

print("\n3. A vendor that IS a client by name is still refused as a target")
title3 = f"St. Mary's Church {QB} - [Vendor Center: Clinton Agway Feed Store]"
m3 = cnm.detect_mismatch(title3, 1, INDEX, NAMES)
check("buying feed from a client does not move the work to that client",
      m3 is None)

print("\n4. The bracket is still THERE — refused as a target, not deleted")
check("strip_app_chrome leaves the vendor segment intact for Stage 4.6",
      "Vendor Center" in cnm.strip_app_chrome(title3))
check("and the vendor's words survive tokenisation",
      "agway" in set(cnm._tokenize(cnm.strip_app_chrome(title3))))

print("\n5. A real mismatch OUTSIDE the bracket still fires")
# Same window, but the document being worked names another parish outright.
title5 = (f"St. Francis of Assisi Church 2025 reconciliation {QB}"
          f" - [Vendor Center: Integrated Marketing Services, Inc.]")
m5 = cnm.detect_mismatch(title5, 1, INDEX, NAMES)
check("the bracket does not immunise a title that names a rival elsewhere",
      m5 is not None and m5["looks_like_client_id"] == 4)

print("\n6. Titles with no bracket are untouched")
m6 = cnm.detect_mismatch(f"St. Francis of Assisi Church payroll {QB}", 1, INDEX, NAMES)
check("ordinary detection is unaffected",
      m6 is not None and m6["looks_like_client_id"] == 4)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("qb_center_bracket_test: all checks passed")
