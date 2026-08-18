"""
Regression tests for Stage 4.5 — QuickBooks company FILE attribution.

QuickBooks Desktop puts its Company Name field in the window title, never the
filename. Those names are not unique: one production directory holds 135 .qbw
company files, 14 of them some variant of "St. Mary's ...", and the ONLY thing
separating a parish from its cemetery, its school, or the same-saint parish in
the next town is the filename. The agent reads that filename off qbw.exe's open
handle; these tests pin the path → client resolution.

CRITICAL invariants:
  1. Most-specific wins — 'St. Mary's Church Clinton' beats 'St. Mary's Church'
     when both are contained in the filename.
  2. ABSTAIN over guess — a filename that fits two clients equally well returns
     nothing. Filing a parish's books to its cemetery is the exact failure this
     stage exists to remove; a wrong answer is worse than the status quo.
  3. Version years and working-copy dates are not identity —
     'Cadd Systems_03042025' and 'Cadd Systems_022626' are one client.

Filenames below are verbatim from the client's Q:\\QB\\QB2024 Files listing.

Pure functions, no Django needed:
    python server/tracker/qb_company_file_test.py

Exits non-zero if any assertion fails.
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


from tracker.services.qb_company_file import (  # noqa: E402
    clean_stem as clean,
    match_stem as match,
    norm,
)

QB_DIR = r"Q:\QB\QB2024 Files"


def path(name):
    return f"{QB_DIR}\\{name}"


# The same-saint cluster that motivated the whole feature. Client names as the
# firm has them; ids are arbitrary but stable within this file.
PARISH_CLIENTS = [
    (1, "St. Mary's Church - Clinton"),
    (2, "St. Mary's Cemetery - Clinton"),
    (3, "St. Mary's Cemetery Rome"),
    (4, "St. Mary's Assumption Minoa"),
    (5, "St. Mary's Assumption Cemetery Minoa"),
    (6, "St. Mary's Assumption Oswego"),
    (7, "Mary Mother of Our Savior Utica"),
    (8, "Church of Sacred Heart & St. Mary NY Mills"),
    (9, "Cadd Systems"),
    (10, "Harrington Homes of Jamesville"),
    (11, "Krueger Funeral Home"),
]


def candidates(clients=None):
    return [(cid, name, name) for cid, name in (clients or PARISH_CLIENTS)]


def resolves_to(filename, expected_id, clients=None):
    got = match(path(filename), candidates(clients))
    return got is not None and got[0] == expected_id


def abstains(filename, clients=None):
    return match(path(filename), candidates(clients)) is None


print("\n=== stem cleaning ===")
check("strips _QB2024 version suffix",
      clean(path("St. Mary's Church_Clinton_QB2024.QBW")) == "St. Mary's Church_Clinton")
check("strips lowercase .qbw extension",
      clean(path("st mary's church_Baldwinsville.qbw")) == "st mary's church_Baldwinsville")
check("strips _qbw2024 variant",
      clean(path("Midnight Express Towing & Recovery_qbw2024.qbw"))
      == "Midnight Express Towing & Recovery")
check("strips year with no separator (H&B MarketingQB2024)",
      clean(path("H&B MarketingQB2024.qbw")) == "H&B Marketing")
check("strips trailing working-copy date",
      clean(path("Cadd Systems_03042025.qbw")) == "Cadd Systems")
check("strips dotted trailing date",
      clean(path("keegan-osbelt-knight funeral home, inc.01212026.qbw"))
      == "keegan-osbelt-knight funeral home, inc")
check("strips fixed_ prefix and trailing date+letter",
      clean(path("fixed_harrington homes of jamesville01142026b.qbw"))
      == "harrington homes of jamesville")
check("strips stacked date then version",
      clean(path("Krueger Funeral Home_01222025_QB2024.QBW")) == "Krueger Funeral Home")
check("handles a bare filename with no directory",
      clean("Cadd Systems.qbw") == "Cadd Systems")
check("empty path is empty, not a crash",
      clean("") == "")

print("\n=== the fourteen St. Mary files resolve distinctly ===")
check("Clinton church → the Clinton PARISH, not the Clinton cemetery",
      resolves_to("St. Mary's Church_Clinton_QB2024.QBW", 1))
check("Clinton cemetery → the Clinton CEMETERY, not the parish",
      resolves_to("St. Mary's Cemetery Clinton_QB2024.QBW", 2))
check("Rome cemetery → Rome, not Clinton",
      resolves_to("St. Mary's Cemetery Rome_QB2024.qbw", 3))
check("Minoa Assumption → the parish",
      resolves_to("St. Mary's Assumption Minoa_QB2024.QBW", 4))
check("Minoa Assumption CEMETERY → the cemetery, not the parish (most specific wins)",
      resolves_to("St. Mary's Assumption Cemetery Minoa_QB2024.QBW", 5))
check("Oswego Assumption → Oswego, not Minoa",
      resolves_to("St. Mary's Assumption Oswego_QB2024.qbw", 6))
check("Mary Mother of Our Savior Utica → its own client",
      resolves_to("Mary Mother of Our Savior Utica_QB2024.qbw", 7))
check("Sacred Heart & St. Mary NY Mills → the NY Mills parish",
      resolves_to("Church of Sacred Heart & St. Mary NY Mills_QB2024.QBW", 8))

print("\n=== most-specific-wins (substring domination) ===")
GENERIC_PLUS_SPECIFIC = [
    (100, "St. Mary's Church"),          # generic — contained in the filename
    (1, "St. Mary's Church - Clinton"),  # specific — the real subject
]
check("generic 'St. Mary's Church' loses to 'St. Mary's Church - Clinton'",
      resolves_to("St. Mary's Church_Clinton_QB2024.QBW", 1, GENERIC_PLUS_SPECIFIC))
check("generic client still wins when it is the only match",
      resolves_to("St. Mary's Church_QB2024.QBW", 100, GENERIC_PLUS_SPECIFIC))

print("\n=== abstention: never guess between same-family clients ===")
# Duplicate client records are real (a firm's list picks up "St Marys Church,
# Clinton" alongside "St. Mary's Church - Clinton"). Both normalize identically,
# so neither is more specific — pick neither.
TIED = [
    (200, "St. Mary's Church - Clinton"),
    (201, "St Marys Church, Clinton"),
]
check("two client records that normalize identically → abstain",
      abstains("St. Mary's Church_Clinton_QB2024.QBW", TIED))
check("a file for a client we do not have → abstain",
      abstains("Barado's on the Water_QB2024.QBW"))
check("junk/working file with no client identity → abstain",
      abstains("atu__loc30d_040626.qbw"))
check("Baldwinsville parish does NOT resolve to the Clinton parish",
      abstains("st mary's church_Baldwinsville.qbw"))
check("Baldwinsville school does NOT resolve to any Clinton/Rome client",
      abstains("st mary's school_bville.qbw"))

print("\n=== date/version noise is not identity ===")
check("Cadd Systems_03042025 → Cadd Systems",
      resolves_to("Cadd Systems_03042025.qbw", 9))
check("Cadd Systems_022626 → the SAME client",
      resolves_to("Cadd Systems_022626.qbw", 9))
check("plain Cadd Systems.qbw → the same client again",
      resolves_to("Cadd Systems.qbw", 9))
check("fixed_ working copy → Harrington Homes",
      resolves_to("fixed_harrington homes of jamesville01142026b.qbw", 10))
check("Restored_ copy → Krueger Funeral Home",
      resolves_to("Restored_Krueger Funeral Home_01222025_QB2024.QBW", 11))

print("\n=== coverage floor: a generic record cannot claim a specific file ===")
# org21 really carries both a bare "Sacred Heart" and specific parish records.
# 'sacredheart' IS contained in the NY Mills filename, and most-specific-wins
# cannot save us: the specific client is not contained there at all (word order
# differs). Only a coverage floor catches this.
SACRED = [(105, "Sacred Heart"), (175, "Sacred Heart Church")]
check("bare 'Sacred Heart' does NOT claim the NY Mills parish file",
      abstains("Church of Sacred Heart & St. Mary NY Mills_QB2024.QBW", SACRED))
check("a file that really is Sacred Heart Church still resolves",
      resolves_to("Sacred Heart Church_QB2024.QBW", 175, SACRED))
check("the floor does not break the Clinton parish match",
      resolves_to("St. Mary's Church_Clinton_QB2024.QBW", 1))

print("\n=== directory-listing parsing ===")
from tracker.services.qb_company_file import parse_listing  # noqa: E402

DIR_OUTPUT = """
    Directory: Q:\\QB\\QB2024 Files

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a----          1/15/2025  10:32 AM      113582080 100 Maconi Ave., LLC_QB2024.QBW
-a----          1/15/2025  10:32 AM            432 100 Maconi Ave., LLC_QB2024.ND
-a----          1/15/2025  10:32 AM      124452864 100 Maconi Ave., LLC_QB2024.QBW.TLG
-a----          2/02/2025  09:14 AM       74145792 St. Mary's Church_Clinton_QB2024.QBW
-a----          2/02/2025  09:14 AM            400 St. Mary's Church_Clinton_QB2024.QBW.ND
-a----          2/02/2025  09:14 AM             87 St. Mary's Church_Clinton_QB2024.SDS
d-----          2/02/2025  09:14 AM                Restored_St. Mary's Church_Clinton_QB2024_Files
"""
parsed = parse_listing(DIR_OUTPUT)
check("dir output yields exactly the company files, not the sidecars",
      parsed == ["100 Maconi Ave., LLC_QB2024.QBW",
                 "St. Mary's Church_Clinton_QB2024.QBW"])
# A leading street number is client identity. A naive size-strip ate it and
# silently renamed the client to "Maconi Ave., LLC".
check("a leading street number survives the size column strip",
      clean(parse_listing("113582080 100 Maconi Ave., LLC_QB2024.QBW")[0])
      == "100 Maconi Ave., LLC")
check("1819 Lemoyne survives too",
      clean(parse_listing("94371840 1819 Lemoyne Avenue LLC_QB2024.qbw")[0])
      == "1819 Lemoyne Avenue LLC")
check("a plain one-name-per-line list parses",
      parse_listing("Cadd Systems.qbw\nKrueger Funeral Home01212026.QBW")
      == ["Cadd Systems.qbw", "Krueger Funeral Home01212026.QBW"])
check(".qbw.SearchIndex is not mistaken for a company file",
      parse_listing("St. Mary's Church_Clinton_QB2024.QBW.SearchIndex") == [])
check("empty input is empty, not a crash", parse_listing("") == [])

print("\n=== short-alias safety ===")
check("a 4-char alias cannot claim a file",
      match(path("St. Mary's Church_Clinton_QB2024.QBW"), [(300, "SMCC", "SMCC")]) is None)
check("normalizer strips punctuation and case",
      norm("St. Mary's Church– Clinton") == "stmaryschurchclinton")

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
