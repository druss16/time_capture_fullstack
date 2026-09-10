"""
Tests for the firm's Customer/Company list: reading the sheet
(management/commands/import_qb_company_map.py) and applying it
(ClassificationService._stage_4_7_qb_company_roster).

The list is the strongest QuickBooks evidence there is — it commits at 0.95
without a human — so the cases that matter are the ones where it must NOT fire:
a company name naming two clients, two company files open at once, a client the
firm no longer works with, and a direct read of the open file disagreeing.

Both DB touch-points in the stage are memoized (_qb_company_map_cache on the
service, _qb_companies_cache on the block), which is what lets these tests run
the real method with no database at all.

    python manage.py shell -c "import tracker.qb_company_roster_test"
or standalone where Django is configured:
    python tracker/qb_company_roster_test.py

Exits non-zero if any assertion fails.
"""
import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


# ── reading the sheet ───────────────────────────────────────────────────────
# Pure python: no Django, so this half runs everywhere.
print("Reading the sheet — the columns are found by name, not position:")
try:
    from tracker.management.commands.import_qb_company_map import _read_rows
    _read_ok = True
except Exception as e:
    _read_ok = False
    print(f"  SKIP  could not import the command ({type(e).__name__})")

if _read_ok:
    def _csv(rows):
        fh = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, newline='')
        csv.writer(fh).writerows(rows)
        fh.close()
        return fh.name

    # The real export leads with a blank spacer column and a title row.
    path = _csv([
        ['', '', ''],
        ['', 'Customer-Company List', ''],
        ['', 'Customer', 'Company'],
        ['', "St Mary's Church- Clinton", "St. Mary's Church"],
        ['', 'Cameza LLC', 'Cameza, LLC'],
    ])
    rows = _read_rows(path)
    check("a leading spacer column doesn't shift the read",
          rows == [("St Mary's Church- Clinton", "St. Mary's Church"),
                   ('Cameza LLC', 'Cameza, LLC')])
    os.unlink(path)

    path = _csv([['Company', 'Customer'],
                 ['Acme Books', 'Acme Industries']])
    check("the columns work in either order",
          _read_rows(path) == [('Acme Industries', 'Acme Books')])
    os.unlink(path)

    path = _csv([['Customer', 'Company'],
                 ['Has None', 'None'],
                 ['Has Blank', ''],
                 ['Real Co', 'Real Company']])
    check("rows with no company are dropped, 'None' included",
          _read_rows(path) == [('Real Co', 'Real Company')])
    os.unlink(path)

    path = _csv([['Client', 'File'], ['a', 'b']])
    try:
        _read_rows(path)
        check("a sheet without the two columns is refused", False)
    except Exception as e:
        check("a sheet without the two columns is refused",
              'Customer' in str(e))
    os.unlink(path)

# ── applying the list ───────────────────────────────────────────────────────
try:
    from tracker.services.classification_service import (
        ClassificationService, ClassificationDecision, Signal)
    _app_ok = True
except Exception as e:
    _app_ok = False
    _skipped = 1
    print("\nApplying the list:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _app_ok:
    QB = ' - QuickBooks Accountant Desktop Plus 2024'

    class FakeBlock:
        def __init__(self, title, companies=None, app='qbw.exe'):
            self.app_name = app
            self.window_title = title
            self.title = title
            self.file_path = ''
            self.url = ''
            if companies is not None:
                # Stand in for the RawEvent scan: (own title, everything seen).
                self._qb_companies_cache = companies

    def service_with(map_rows):
        """A service that answers _qb_company_map() from a literal, no DB."""
        svc = ClassificationService.__new__(ClassificationService)
        svc._qb_company_map_cache = {
            ClassificationService._normalize_name(name): (cid, cname)
            for name, cid, cname in map_rows
        }
        svc._clients = []          # tests that care set their own roster
        return svc

    ROSTER = [
        ("St. Mary's Church", 388, "St Mary's Church- Clinton"),
        ('Cameza, LLC', 793, 'CAMEZA_Champions Fitness'),
    ]

    def run(block, svc=None, signals=()):
        svc = svc or service_with(ROSTER)
        d = ClassificationDecision()
        d.matched_signals = list(signals)
        ClassificationService._stage_4_7_qb_company_roster(svc, block, d)
        return [s for s in d.matched_signals if s.type == 'qb_company_roster']

    print("\nApplying the list — a name on the list resolves outright:")
    hit = run(FakeBlock("St. Mary's Church" + QB))
    check("the bare company name the title bar shows names its client",
          len(hit) == 1 and hit[0].detail['client_id'] == 388)
    check("...and commits without a human (>= 0.85)",
          hit and hit[0].strength >= 0.85)
    check("...outranking the picked-file read (0.93) and the vendor (0.91)",
          hit and hit[0].strength > 0.93)
    check("a screen bracket doesn't hide the company",
          len(run(FakeBlock(
              "Cameza, LLC" + QB + " - [Write Checks]"))) == 1)
    check("QuickBooks' (Primary) window marker is not part of the name",
          len(run(FakeBlock("St. Mary's Church (Primary)" + QB))) == 1)

    print("\nApplying the list — it stays out of everything else:")
    check("a non-QuickBooks window is not this stage's business",
          run(FakeBlock("St. Mary's Church" + QB, app='EXCEL.EXE')) == [])
    check("a company that isn't on the list gets no signal",
          run(FakeBlock('Z-Loupes Inc' + QB)) == [])
    check("an empty list is a no-op",
          run(FakeBlock("St. Mary's Church" + QB), svc=service_with([])) == [])
    check("a client no longer on the active roster is not in the map",
          run(FakeBlock("St. Mary's Church" + QB),
              svc=service_with([])) == [])

    print("\nApplying the list — a live read of the open file wins:")
    direct = Signal(type='qb_company_file', strength=0.93,
                    evidence='', detail={'client_id': 409, 'via': 'direct'})
    check("a direct handle read is left to decide alone",
          run(FakeBlock("St. Mary's Church" + QB), signals=[direct]) == [])
    picked = Signal(type='qb_company_file', strength=0.93,
                    evidence='', detail={'client_id': 409, 'via': 'picked'})
    got = run(FakeBlock("St. Mary's Church" + QB), signals=[picked])
    check("an INFERRED file (the dialog MRU) does not outrank the list",
          len(got) == 1 and got[0].strength > picked.strength)

    print("\nApplying the list — two company files open is unanswerable:")
    two = FakeBlock('QuickBooks Accountant Desktop Plus 2024',
                    companies=(None, ["St. Mary's Church", 'Cameza, LLC']))
    check("no company on this block's title and two seen -> abstain",
          run(two) == [])
    same = FakeBlock('QuickBooks Accountant Desktop Plus 2024',
                     companies=(None, ["St. Mary's Church", "St Mary's Church"]))
    check("two spellings of ONE client's file is not a contradiction",
          len(run(same, svc=service_with(
              ROSTER + [("St Mary's Church", 388, "St Mary's Church- Clinton")]
          ))) == 1)
    modal = FakeBlock('Write Checks',
                      companies=(None, ["St. Mary's Church"]))
    check("a modal block borrows the one company its samples saw",
          len(run(modal)) == 1)
    front = FakeBlock("Cameza, LLC" + QB,
                      companies=('Cameza, LLC', ["St. Mary's Church", 'Cameza, LLC']))
    check("the block's OWN title decides when it has one",
          run(front)[0].detail['client_id'] == 793)

    print("\nSpelling — both sides of this were typed by people:")
    from tracker.services.qb_company_file import typo_match
    N = ClassificationService._normalize_name

    def tm(seen, *sheet):
        return typo_match(N(seen), [N(x) for x in sheet])

    check("a typo in a long word is still the same company",
          tm('R&G Transportation Servives LLC',
             'R&G Transportoration Services LLC') is not None)
    check("punctuation and '&' vs 'and' are not a difference",
          tm('CNY Coin and Silver, Inc', 'CNY Coin & Silver, Inc.') is not None)
    check("a stray comma in 'St,' does not hide the name",
          tm('St. John the Evangelist', 'St, John the Evangelist') is not None)
    check("an extra generic word changes nothing",
          tm('St. Anne Mother of Mary Catholic Church',
             'St. Anne Mother of Mary Church') is not None)

    print("\nSpelling — an extra WORD is information, not a typo:")
    check("'St. Patrick's Cemetery' is not the Jordan one",
          tm("St. Patrick's Cemetery", "St Patrick's Jordan Cemetery") is None)
    check("a town in the sheet name and not on screen blocks the match",
          tm('Transfiguration Church', 'Transfiguration Church-Rome') is None)
    check("the church is not the school, however alike the words",
          tm("St. Mary's Church", "St. Mary's School") is None)
    check("two sheet names equally close means the question is still open",
          tm("St. Mary's Church", "St. Mary's Church-Hamilton",
             "St. Mary's Church- Minoa") is None)
    check("a name with no identifying word matches nothing",
          tm('The Church', 'St Marys Church') is None)

    print("\nSpelling — an exact answer that already exists is not guessed at:")

    def cameza_service():
        svc = service_with([('Cameze LLC', 190, 'Cameze LLC')])
        svc._clients = [
            type('C', (), {'id': 793, 'name': 'CAMEZA_Champions Fitness',
                           'aliases': ['Champions Fitness', 'Cameza, LLC']})(),
            type('C', (), {'id': 190, 'name': 'Cameze LLC',
                           'aliases': ['Cameze']})(),
        ]
        return svc

    # One character apart: 793 has 218 blocks and a person mapped this alias
    # by hand; 190 has never had a block. The typo tier must not move it.
    check("a company name that IS somebody's alias is left alone",
          run(FakeBlock('Cameza, LLC' + QB), svc=cameza_service()) == [])
    check("...and with no such alias on the roster, the typo tier does fire",
          len(run(FakeBlock('Cameza, LLC' + QB),
                  svc=service_with([('Cameze LLC', 190, 'Cameze LLC')]))) == 1)
    got = run(FakeBlock('R&G Transportation Servives LLC' + QB),
              svc=service_with([('R&G Transportoration Services LLC', 344,
                                 'R&G Transportation services LLC')]))
    check("a spelling match ranks BELOW a verbatim one",
          len(got) == 1 and got[0].strength == 0.90)
    check("...and says which list entry it matched",
          got and got[0].detail['matched_spelling'])

    print("\nApplying the list — the family picker stands down for it:")
    check("qb_company_roster is identifying evidence",
          ClassificationService._is_identifying(
              {'type': 'qb_company_roster', 'detail': {}}) is True)
    check("...so a block it answered is no longer an open question",
          ClassificationService._is_identifying(
              Signal(type='qb_company_roster', strength=0.95,
                     evidence='', detail={'client_id': 388})) is True)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
