"""
qb_vendor_fingerprint.py — tell two same-named parishes apart by their vendors.

THE PROBLEM THIS SOLVES
-----------------------
QuickBooks Desktop puts its Company Name in the window title and nothing else.
Fourteen of one firm's company files answer to some form of "St. Mary's Church",
and the town that distinguishes them lives only in the filename on disk — which
QuickBooks never displays, and which the agent cannot read (QuickBooks runs
elevated; four machines confirmed the handle read is refused).

But QuickBooks also puts the OPEN SCREEN in the title:

    "St. Mary's Church  - QuickBooks Accountant Desktop Plus 2024
                                        - [Vendor Center: Clinton Agway]"

That bracket is content from INSIDE the company file. Clinton Agway is a farm
supplier in Clinton, New York. A parish in Hamilton does not buy from it.
Vendor, customer and employee names are exactly what one parish's books have
and another's do not — so they fingerprint the file that the company name
cannot.

Measured over real data: 29% of QuickBooks titles carry a bracket, and the
vendor sets PARTITION cleanly — "St. Mary's Church" splits into one group of
eight sessions and another of seven that share no vendor at all. Two parishes,
one name, told apart with no filename and no permissions.

WHAT THIS DOES NOT DO
---------------------
It does not name the groups. Vendors prove two files are DIFFERENT; they do not
say which is Clinton. Naming needs either a vendor that carries a town, or one
human answer per group — and a group is many sessions, so that is a handful of
questions, not one per block.

Django-free so it is testable on its own:
    python server/tracker/qb_vendor_fingerprint_test.py
"""
import re

# Screens whose bracket names a party in the company file's own records. Other
# screens ("Home", "Make Deposits", "Chart of Accounts") name a feature and say
# nothing about which parish is open.
IDENTIFYING_SCREENS = ('vendor center', 'customer center', 'employee center')

# Vendors every parish uses, so they prove nothing about which one this is.
# Kept deliberately short: the real filter is statistical (see is_generic),
# because a hand-written list can never anticipate a firm's shared suppliers.
_GENERIC_RE = re.compile(
    r'diocese|national ?grid|verizon|spectrum|charter communications|key ?bank|'
    r'staples|amazon|\bups\b|fedex|paychex|\badp\b|\birs\b|\bnys\b|'
    r'church mutual|the hartford|\breta\b|\bbas\b|op ?cit',
    re.IGNORECASE)

# A vendor seen under this many DIFFERENT company names is shared plumbing, not
# a parish's own supplier. Two is deliberate: a genuinely parish-specific vendor
# should appear under exactly one company name.
GENERIC_COMPANY_THRESHOLD = 2

MIN_VENDOR_LEN = 4

_QB_TITLE_RE = re.compile(r'^(?P<c>.+?)\s+[-–]\s+quickbooks\b', re.IGNORECASE)
_PAREN_RE = re.compile(r'\s*\((primary|secondary)\)\s*', re.IGNORECASE)


def split_title(title):
    """QuickBooks title -> (company, screen, party).

    "St. Mary's Church - QuickBooks ... - [Vendor Center: Clinton Agway]"
        -> ("St. Mary's Church", "Vendor Center", "Clinton Agway")

    Any part may be None. The (Primary)/(Secondary) markers are stripped: they
    say which of two open files this is, not which parish.
    """
    if not title:
        return None, None, None
    head, sep, tail = title.rpartition(' - [')
    screen = party = None
    if sep:
        bracket = tail.rstrip(']').strip()
        if ':' in bracket:
            s, _, p = bracket.partition(':')
            screen, party = s.strip(), p.strip()
        else:
            screen = bracket
    else:
        head = title

    m = _QB_TITLE_RE.match(_PAREN_RE.sub(' ', head).strip())
    if not m:
        return None, screen, party
    company = m.group('c').strip().strip('-–').strip()
    if len(company) < 4 or company.lower().startswith(('quickbooks', 'intuit')):
        company = None
    return company, screen, party


def is_identifying(screen, party):
    """True if this bracket names a party from inside the company file."""
    if not screen or not party:
        return False
    if (screen or '').strip().lower() not in IDENTIFYING_SCREENS:
        return False
    party = party.strip()
    if len(party) < MIN_VENDOR_LEN:
        return False
    return not _GENERIC_RE.search(party)


def find_generic_vendors(vendor_companies):
    """Vendors that appear under several company names — shared, not identifying.

    `vendor_companies` maps vendor -> set of company names it was seen under.
    Statistical rather than hand-listed, because every firm has its own shared
    suppliers and a fixed list would silently miss them.
    """
    return {v for v, comps in vendor_companies.items()
            if len(comps) >= GENERIC_COMPANY_THRESHOLD}


def group_sessions(session_vendors):
    """Merge sessions that share any vendor. Returns a list of session-key lists.

    Sessions sharing a vendor are the same company file; sessions sharing none
    are — on this evidence — different files. Plain connected components, which
    is what "shares a vendor with" means transitively.
    """
    keys = [k for k, v in session_vendors.items() if v]
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Index by vendor so this is linear-ish rather than comparing every pair.
    by_vendor = {}
    for k in keys:
        for v in session_vendors[k]:
            by_vendor.setdefault(v, []).append(k)
    for members in by_vendor.values():
        first = members[0]
        for other in members[1:]:
            ra, rb = find(first), find(other)
            if ra != rb:
                parent[ra] = rb

    groups = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return sorted(groups.values(), key=len, reverse=True)


def suggest_town(vendors, towns):
    """A town named by these vendors, if exactly one is.

    "Clinton Agway" names Clinton. Returns None when several towns appear or
    none does — a vendor list mentioning two towns is not evidence for either.
    """
    hits = set()
    for v in vendors:
        low = (v or '').lower()
        for town in towns:
            t = (town or '').lower().strip()
            if len(t) >= 4 and re.search(r'\b' + re.escape(t) + r'\b', low):
                hits.add(town)
    return hits.pop() if len(hits) == 1 else None
