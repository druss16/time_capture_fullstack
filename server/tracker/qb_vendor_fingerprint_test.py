"""
Tests for telling same-named parishes apart by the vendors in their titles.

The whole idea rests on one claim: a vendor inside a QuickBooks title belongs
to THAT company file, so two sessions sharing a vendor are the same parish and
two sharing none are different parishes. These pin that, plus the ways it must
refuse to answer — because a wrong parish is worse than no parish, which is the
lesson of every other attempt at this problem.

    python server/tracker/qb_vendor_fingerprint_test.py
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
    split_title, is_identifying, find_generic_vendors, group_sessions,
    suggest_town,
)

QB = " - QuickBooks Accountant Desktop Plus 2024"

print("\n=== pulling the parts out of a real title ===")
c, s, p = split_title(f"St. Mary's Church{QB} - [Vendor Center: Clinton Agway]")
check("company", c == "St. Mary's Church")
check("screen", s == "Vendor Center")
check("vendor", p == "Clinton Agway")

c, s, p = split_title(f"St. Mary's Church (Primary){QB} - [Vendor Center: AT&T (5075)]")
check("(Primary) is stripped — it names the window, not the parish",
      c == "St. Mary's Church")
check("vendor survives its own parentheses", p == "AT&T (5075)")

c, s, p = split_title(f"St. Mary's Church{QB}")
check("no bracket -> company only, no screen", c == "St. Mary's Church" and s is None)
c, s, p = split_title("Make General Journal Entries")
check("a bare modal yields nothing", c is None and p is None)
check("empty title is safe", split_title("") == (None, None, None))
check("None title is safe", split_title(None) == (None, None, None))

print("\n=== only parties from inside the file count ===")
check("Vendor Center names a party", is_identifying("Vendor Center", "Clinton Agway"))
check("Customer Center too", is_identifying("Customer Center", "Bridget Parke"))
check("Employee Center too", is_identifying("Employee Center", "Moran, Dennis R"))
check("'Home' names a feature, not a party", not is_identifying("Home", "x"))
check("'Make Deposits' likewise", not is_identifying("Make Deposits", "Anything"))
check("'Chart of Accounts' likewise", not is_identifying("Chart of Accounts", "Cash"))

print("\n=== vendors every parish uses prove nothing ===")
for shared in ("Roman Catholic Diocese of Syracuse", "National Grid",
               "ADP, Inc.", "Church Mutual", "Key Bank"):
    check(f"{shared!r} rejected", not is_identifying("Vendor Center", shared))
check("a parish's own supplier is kept",
      is_identifying("Vendor Center", "Kerner & Merchant Pipe Organ Builders"))

print("\n=== and the statistical filter catches the ones no list anticipates ===")
seen = {
    'Clinton Agway': {"St. Mary's Church"},
    'Lou Ann Turner': {'St. James Church'},
    'Some Regional Supplier': {"St. Mary's Church", 'St. James Church',
                               'Sacred Heart'},
}
generic = find_generic_vendors(seen)
check("a vendor under 3 company names is shared", 'Some Regional Supplier' in generic)
check("a vendor under 1 company name is kept", 'Clinton Agway' not in generic)

print("\n=== THE POINT: one company name, two parishes ===")
# Verbatim shape of the real result: two groups sharing no vendor at all.
sessions = {
    ('mary', 'pc1', 'd1'): {'Clinton Agway', 'Abbey Press'},
    ('mary', 'pc1', 'd2'): {'Abbey Press', '4Promos LLC'},
    ('mary', 'pc2', 'd3'): {'Brianna Howe', 'B. R. Johnson, Inc.'},
    ('mary', 'pc2', 'd4'): {'B. R. Johnson, Inc.', 'Caitlin Recchio'},
}
groups = group_sessions(sessions)
check("splits into exactly two parishes", len(groups) == 2)
check("...of two sessions each", sorted(len(g) for g in groups) == [2, 2])
g_clinton = [g for g in groups if ('mary', 'pc1', 'd1') in g][0]
check("sessions linked through a SHARED vendor land together",
      ('mary', 'pc1', 'd2') in g_clinton)
check("...and the other parish's sessions do not",
      ('mary', 'pc2', 'd3') not in g_clinton)

print("\n=== a shared vendor would wrongly merge two parishes ===")
# Exactly why generic vendors must be filtered BEFORE grouping.
polluted = dict(sessions)
polluted[('mary', 'pc1', 'd1')] = {'Clinton Agway', 'Abbey Press', 'National Grid'}
polluted[('mary', 'pc2', 'd3')] = {'Brianna Howe', 'B. R. Johnson, Inc.',
                                   'National Grid'}
check("if a shared vendor slips through, the groups collapse into one",
      len(group_sessions(polluted)) == 1)

print("\n=== naming a group from its vendors ===")
TOWNS = ['Clinton', 'Hamilton', 'Baldwinsville', 'Rome', 'Minoa']
check("'Clinton Agway' names Clinton",
      suggest_town({'Clinton Agway', 'Abbey Press'}, TOWNS) == 'Clinton')
check("two towns named -> refuse to choose",
      suggest_town({'Clinton Agway', 'Rome Cable Co'}, TOWNS) is None)
check("no town named -> nothing", suggest_town({'Abbey Press'}, TOWNS) is None)
check("a town inside a longer word does not count",
      suggest_town({'Clintonville Supply Co'}, ['Clinton']) is None)

print("\n=== sessions with no vendor are not grouped at all ===")
check("empty session is excluded rather than merged with anything",
      group_sessions({('x', 'p', 'd'): set()}) == [])


print("\n=== absence of overlap is only evidence when overlap was LIKELY ===")
from tracker.services.qb_vendor_fingerprint import classify_groups  # noqa: E402

# The real shape: two rich sets that share nothing. If they were one file,
# 21 and 24 vendors would certainly have collided.
rich = {
    ('m', 'a', 1): {f'vendor A{i}' for i in range(8)},
    ('m', 'a', 2): {f'vendor A{i}' for i in range(4, 12)},
    ('m', 'b', 3): {f'vendor B{i}' for i in range(8)},
    ('m', 'b', 4): {f'vendor B{i}' for i in range(4, 12)},
}
conf, frag = classify_groups(group_sessions(rich), rich)
check("two well-evidenced groups are called distinct files", len(conf) == 2)
check("...and nothing is written off as a fragment", frag == [])

# The bug this guards: one session with one vendor overlaps nothing, so naive
# grouping called it a separate company file. It reported the firm's OWN books
# as four companies and one cemetery's five sessions as four.
sparse = dict(rich)
sparse[('m', 'c', 5)] = {'a lone vendor'}
conf2, frag2 = classify_groups(group_sessions(sparse), sparse)
check("a one-vendor session is NOT a new company file", len(conf2) == 2)
check("...it is reported as a fragment instead", len(frag2) == 1)
check("...and the fragment keeps its session so its time is visible",
      frag2[0][0] == [('m', 'c', 5)])

thin = {('m', 'd', 6): {'v1', 'v2'}}       # 1 session, 2 vendors
conf3, frag3 = classify_groups(group_sessions(thin), thin)
check("too few sessions AND too few vendors -> fragment",
      conf3 == [] and len(frag3) == 1)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
