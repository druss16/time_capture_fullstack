"""A partial match is not a second opinion to a complete one.

Run either way:
    python manage.py shell -c "import tracker.full_name_beats_partial_test"
    python tracker/full_name_beats_partial_test.py

No Django needed — client_name_match is pure.

WHAT THIS GUARDS
----------------
The ambiguity gate ranks on ABSOLUTE distinctive mass. That is right for
picking a winner and wrong for deciding whether a title is ambiguous: a long
name sharing a common prefix carries a lot of mass while naming almost none of
itself. Org 21 block 70787, straight off the production roster:

  "Church of Sacred Heart and St. Mary (Secondary) - QuickBooks …"
    abs  cov
  12.38 1.00  Sacred Heart & St. Mary's Church        <- every word present
   8.99 0.43  Basilica of The Sacred Heart of Jesus   = 73% -> gate trips
   8.84 0.60  Sacred Heart- Cicero
   8.84 0.65  Sacred Heart Parish-Rome

"Basilica", "Jesus", "Cicero", "Rome" appear nowhere in that title. None of the
three can win — they fail the coverage gate — yet together they were enough to
make the detector say the title names nobody. The firm reads that title and
sees an obvious answer; the machine saw four Sacred Hearts and shrugged.

THE TWO ABSTENTIONS THAT MUST SURVIVE are at the bottom: a bare family name,
where nobody reaches full coverage, and two clients BOTH named in full. If
either starts answering, this rule has begun inventing certainty and is worse
than the silence it replaced.

The roster below is the real one — those are org 21's actual client names,
taken from the scoring table above rather than invented. It reproduces the
failure at 70% against production's 73%.
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "cnm", os.path.join(os.path.dirname(__file__), "utils", "client_name_match.py"))
cnm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cnm)

FAILED = []


def check(label, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILED.append(label)


REAL = {
    # The magnets the first production run of this rule exposed: a short name
    # that is the generic form of a longer one, and a client whose whole
    # distinctive mass is a single word.
    1: "Christ our Hope Church-Boonville",
    2: "Christ our Hope Church",
    3: "St Patrick's Jordan Cemetery",
    4: "St. Patrick's Church",
    5: "St Patricks_St Anthony_Chadwicks",
    105: "Sacred Heart & St. Mary's Church",
    175: "Basilica of The Sacred Heart of Jesus",
    360: "Sacred Heart- Cicero",
    361: "Sacred Heart Parish-Rome",
    173: "Bakery & Tobacco Workers Local 116",
    397: "St. Anne Mother of Mary Church",
    395: "St. Mary's of the Assumption",
    388: "St Mary's Church- Clinton",
    790: "St. Mary's Church Baldwinsville",
    411: "St. Mary's of the Lake",
}
PAD = {1000 + i: n for i, n in enumerate([
    "Holy Cross Church", "St Joseph Church", "Our Lady of Lourdes",
    "St Ann Parish", "Blessed Sacrament", "St John the Evangelist",
    "Christ the King", "St Paul Church", "Immaculate Conception",
    "Transfiguration Parish", "St Rose Church", "Good Shepherd Parish",
    "St Cecilia Church", "Holy Family Parish", "St Lucy Church",
    "St Andrew Church", "Assumption Parish", "Nativity Parish",
    "Internal - Tax", "Internal - Accounting",
])}
NAMES = {**PAD, **REAL}
IDX = cnm.build_token_index(NAMES)

LIVE = ("Church of Sacred Heart and St. Mary (Secondary)  - QuickBooks "
        "Accountant Desktop Plus 2024 - [Vendor Center: Big O Bakery]")


def detect(title, flag=True):
    cnm.FULL_NAME_BEATS_PARTIAL = flag
    try:
        d = cnm.detect_title_client(title, IDX, NAMES)
    finally:
        cnm.FULL_NAME_BEATS_PARTIAL = False
    return d["client_id"] if d else None


def main():
    print("The failure reproduces off the real roster:")
    toks = set(cnm._tokenize(cnm.strip_app_chrome(LIVE)))
    sc = sorted(((cnm.score_title_against_client(toks, c, IDX), c)
                 for c in NAMES), key=lambda r: -r[0][2])
    (bcov, _, babs), bcid = sc[0]
    (rcov, _, rabs), _ = sc[1]
    check("the right client is the highest scorer", bcid == 105)
    check("…and the title contains its ENTIRE name", bcov >= cnm.FULLY_NAMED)
    check("…while the runner-up names less than half of itself", rcov < 0.55)
    check("…yet carries enough mass to trip the gate",
          rabs >= cnm.AMBIGUITY_RATIO * babs)
    check("so today the detector says nobody", detect(LIVE, False) is None)

    print("\nWith the rule, the obvious answer is the answer:")
    check("block 70787 resolves", detect(LIVE) == 105)

    print("\nEvery other family member still wins its OWN title:")
    check("Cicero", detect("Sacred Heart- Cicero payroll") == 360)
    check("Rome", detect("Sacred Heart Parish-Rome bills") == 361)
    check("the Basilica", detect("Basilica of The Sacred Heart of Jesus annual") == 175)

    print("\nTHE ABSTENTIONS THAT MUST SURVIVE:")
    check("a bare family name — nobody is fully named",
          detect("Sacred Heart - QuickBooks") is None)
    check("two clients BOTH named in full",
          detect("St Mary's Church- Clinton and St. Mary's of the Lake") is None)
    check("…and both of those are unchanged from today",
          detect("Sacred Heart - QuickBooks", False) is None
          and detect("St Mary's Church- Clinton and St. Mary's of the Lake",
                     False) is None)

    print("\nTHE MAGNETS — org 21's first run of this rule accused 35 rows,")
    print("and every one was one of these two shapes:")
    # 1. the winner is the rival's generic form
    check("'Christ our Hope Church' inside '…-Boonville' is a magnet",
          cnm._is_magnet(2, 1, IDX))
    check("'St. Patrick's Church' inside 'St Patrick's Jordan Cemetery' is too",
          cnm._is_magnet(4, 3, IDX))
    # 2. one distinctive word, so "fully named" is free
    check("a one-distinctive-word client is a magnet against anyone",
          cnm._is_magnet(4, 5, IDX))
    # …and the case the rule is FOR survives both
    check("Sacred Heart & St. Mary's is nobody's generic form",
          not cnm._is_magnet(105, 360, IDX)
          and not cnm._is_magnet(105, 175, IDX))

    print("\nSo the magnet rows go back to abstaining:")
    check("'Office - Christ Our Hope' names neither parish",
          detect("Office - Christ Our Hope - Office - Outlook") is None)
    check("'Christ Our Hope Church' still cannot pick Boonville from plain",
          detect("Christ Our Hope Church  - QuickBooks") is None)
    check("'St Patrick Chadwicks' does not become the bare St Patrick's",
          detect("St Patrick Chadwicks_P&L MTD_JUNE26.pdf") != 4)
    check("…while block 70787 still resolves", detect(LIVE) == 105)

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED:")
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("all full-name-beats-partial tests passed")


main()
