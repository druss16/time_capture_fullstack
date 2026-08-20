"""
Tests for Stage 4.6 — resolving a QuickBooks parish from its vendors.

The stage exists because QuickBooks shows only its Company Name, and two of
this firm's parishes both answer to "St. Mary's Church". Six agent releases
established the filename cannot be read: QuickBooks runs elevated and refuses
the handle read on every machine.

What CAN be read is the open screen, and a vendor belongs to one parish's
books. These pin the decision logic — above all the refusals, because the
pattern this replaces sent eight hours to a parish eight miles from the right
one, and a confident wrong answer is worse than none.

Pure logic, no Django:
    python server/tracker/qb_vendor_stage_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


from tracker.services.qb_vendor_fingerprint import (  # noqa: E402
    split_title, is_identifying)

QB = " - QuickBooks Accountant Desktop Plus 2024"


def vendors_in(titles):
    """What the stage extracts from a block's titles."""
    out = set()
    for t in titles:
        _c, screen, party = split_title(t)
        if is_identifying(screen, party):
            out.add(party)
    return out


def resolve(titles, mapping):
    """The stage's decision: one client, or abstain."""
    found = vendors_in(titles)
    hits = {mapping[v] for v in found if v in mapping}
    return hits.pop() if len(hits) == 1 else None


MAP = {
    'Clinton Agway': 'Clinton',
    'New Hartford Safe & Lock, LLC': 'Clinton',
    'Solvay UFSD': 'Baldwinsville',
    'FACTS Grant and Aid Assessment': 'Baldwinsville',
}

print("\n=== THE POINT: an ambiguous title resolved by its vendors ===")
check("bare company name + a Clinton vendor -> Clinton",
      resolve([f"St. Mary's Church{QB} - [Vendor Center: Clinton Agway]"], MAP)
      == 'Clinton')
check("the identical title + a Baldwinsville vendor -> Baldwinsville",
      resolve([f"St. Mary's Church{QB} - [Vendor Center: Solvay UFSD]"], MAP)
      == 'Baldwinsville')
check("the company NAME itself never decides it — only the vendor does",
      resolve([f"St. Mary's Church{QB} - [Vendor Center: Clinton Agway]"], MAP)
      != resolve([f"St. Mary's Church{QB} - [Vendor Center: Solvay UFSD]"], MAP))

print("\n=== a modal in the block does not hide the vendor ===")
# Most QuickBooks samples are nameless modals; the stage reads every title in
# the block, so one vendor screen anywhere is enough.
check("vendor found among modals",
      resolve(["Make General Journal Entries",
               "Select Checks to Print",
               f"St. Mary's Church{QB} - [Vendor Center: Clinton Agway]",
               "Print Checks"], MAP) == 'Clinton')

print("\n=== two vendors from the SAME parish agree ===")
check("multiple vendors, one client -> resolves",
      resolve([f"St. Mary's Church{QB} - [Vendor Center: Clinton Agway]",
               f"St. Mary's Church{QB} - [Vendor Center: New Hartford Safe & Lock, LLC]"],
              MAP) == 'Clinton')

print("\n=== and the refusals, which matter more ===")
check("vendors from TWO parishes -> abstain, never pick",
      resolve([f"St. Mary's Church{QB} - [Vendor Center: Clinton Agway]",
               f"St. Mary's Church{QB} - [Vendor Center: Solvay UFSD]"], MAP) is None)
check("an unknown vendor -> abstain",
      resolve([f"St. Mary's Church{QB} - [Vendor Center: Somebody New]"], MAP) is None)
check("no vendor at all -> abstain",
      resolve([f"St. Mary's Church{QB}", "Make Deposits"], MAP) is None)
check("a feature screen is not a vendor",
      resolve([f"St. Mary's Church{QB} - [Chart of Accounts]"], MAP) is None)
check("a shared supplier is never mapped, so cannot decide",
      resolve([f"St. Mary's Church{QB} - [Vendor Center: National Grid]"], MAP) is None)
check("empty block -> abstain", resolve([], MAP) is None)

print("\n=== the vendor is read, not the company name ===")
check("even a DIFFERENT company name resolves by its vendor",
      resolve([f"Some Other Parish{QB} - [Vendor Center: Clinton Agway]"], MAP)
      == 'Clinton')

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
