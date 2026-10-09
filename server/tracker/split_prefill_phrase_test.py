"""
Regression tests for the split pre-fill's phrase matcher
(tracker.views_block_evidence._phrase_client_for_label).

The bug it guards: org 44, block 83421 ("Design-Project_Folder-TEMPLATE -
Dropbox", Easterns) was split, and its "0074_Easterns-Auto-Group - Dropbox"
slice was pre-filled with Matthews Auto Group, Inc. The longest contiguous run
of any client's name in that label was "auto group" — the generic TAIL of
"Matthews Auto Group" — while "Easterns Automotive Group" only matched one
word at a time ("auto" is not "automotive"). The agent had read the same title
as Easterns at 0.85.

A run now has to start at the client name's first word, and later words may
be shortened ("Auto" for "Automotive").

Pure function, no database:
    docker exec time_api python manage.py shell -c "import tracker.split_prefill_phrase_test"
"""
import sys

from tracker.utils.client_name_match import build_token_index
from tracker.views_block_evidence import _phrase_client_for_label

FAILURES = []


def check(label, cond):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def pick(label, names):
    return _phrase_client_for_label(label, names, build_token_index(names))


# Org 44's live names that bear on the case.
AGENCY = {
    1124: "Easterns Automotive Group",
    1345: "Matthews Auto Group, Inc.",
    1559: "Vehicle Acquisition Network",
    1314: "ASOTU Inc",
    1401: "Tom Gill Chevrolet",
    1402: "Tom Gill Buick GMC",
}

print("\n1. The live misfile")
check("'0074_Easterns-Auto-Group - Dropbox' is Easterns, not Matthews",
      pick("0074_Easterns-Auto-Group - Dropbox", AGENCY) == 1124)
check("a shared generic tail names nobody ('Auto Group Planning')",
      pick("Auto Group Planning Deck", AGENCY) is None)
check("Matthews still matches its own folder",
      pick("0102_Matthews-Auto-Group - Dropbox", AGENCY) == 1345)
check("a shortened folder name reads its client ('Easterns-Auto')",
      pick("0074_2026-09_Easterns-Auto_Collision-Flyer", AGENCY) == 1124)
check("'Tom Gill' alone names neither Tom Gill client",
      pick("Tom Gill October Offers for Creative - Google Docs", AGENCY) is None)
check("'Tom Gill Buick GMC' names its own",
      pick("Tom Gill Buick GMC Offers October 2026.pdf", AGENCY) == 1402)

# The church cases the phrase matcher was built for (org 21, block 56650).
CHURCHES = {
    404: "St. John the Baptist Church",
    413: "St. Paul's Catholic Church",
    414: "St. Peters Church",
    393: "St Peter's Cemetery",
    105: "Sacred Heart Church",
    175: "Sacred Heart",
}

print("\n2. Church files still pre-fill their parish")
check("St. John the Baptist bills",
      pick("St. John the Baptist Rome bills.pdf", CHURCHES) == 404)
check("St. Paul's bills",
      pick("St. Paul's Church bills.pdf", CHURCHES) == 413)
check("a cemetery file goes to the cemetery, not the church",
      pick("St Peter's Cemetery deeds.xlsx", CHURCHES) == 393)
check("an ambiguous same-family label still abstains",
      pick("Sacred Heart bills.pdf", CHURCHES) is None)

# Names that open with filler ("The Church of", "St.") — the run must carry the
# first DISTINCTIVE word, not the literal first one. Found by diffing the old
# and new matcher over 14 days of org 21 titles.
PARISHES = {
    1: "The Church of St. Anthony &St. Agnes",
    2: "St. John the Evangelist",
    3: "Church of Our Lady of The Rosary",
    4: "Transfiguration Church",
    5: "Barados on the Water",
    6: "Revive Hope and Healing Ministries, Inc",
    7: "St. Francis Xavier Church",
    8: "St. Mary's Church",
    9: "St. Peter's Church",
    # As in org 21, "Our Lady" is a family, so "Rosary" is what identifies 3.
    10: "Our Lady of Pompei",
    11: "Our Lady of Hope",
    12: "Spirit of Hope Catholic Comm",
    13: "St Margarets Church-Homer",
}

print("\n3. Filler-led names still match; shared filler alone does not")
check("'St.Anthony & St. Agnes Church' is The Church of St. Anthony",
      pick("St.Anthony & St. Agnes Church  - QuickBooks Accountant Desktop Plus 2024", PARISHES) == 1)
check("'John the Evangelist' (no St.) is St. John the Evangelist",
      pick("Office - John the Evangelist - Office - Outlook", PARISHES) == 2)
check("'our lady of the rosary' is the Rosary parish",
      pick("feast of our lady of the rosary - Google Search", PARISHES) == 3)
check("'Transfiguration of Our Lord' is not Our Lady of the Rosary",
      pick("Transfiguration of Our Lord Church  - QuickBooks Accountant Desktop", PARISHES) != 3)
check("'... on the US ...' is not Barados on the Water",
      pick("Trump's tariff tactic against Canada has backfired on the US", PARISHES) is None)
check("'Spirit of Hope Parish' is Spirit of Hope Catholic Comm",
      pick("Spirit of Hope Parish  - QuickBooks Accountant Desktop Plus 2024", PARISHES) == 12)
check("a trailing town is not required ('St. Margaret's Church' is -Homer)",
      pick("St. Margaret's Church  - QuickBooks Accountant Desktop Plus 2024", PARISHES) == 13)
check("'hope and love' is not Revive Hope and Healing",
      pick("ICON Ministry | Bringing the hope and love of Christ to the nations", PARISHES) is None)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("split_prefill_phrase_test: all checks passed")
