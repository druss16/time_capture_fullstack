"""
Tests for the order the Daily Review suggestion trusts its evidence.

The rule under test is a precedence, not a match: **when the block's own text
names a client, the temporal tiers do not get to speak.** A PDF called
"St Francis 6-21 & 6-28.pdf" plainly names a client. The roster holds two St.
Francises, so nothing can say which — and the old code answered anyway, with
"right before this you were working on St Patricks_St Anthony_Chadwicks", a
different parish that merely happened to be open beforehand.

So the important cases here are the refusals: a title that names a family must
produce NO suggested client and the members as candidates, and must not fall
through to the neighbour. Run inside the app container:

    python manage.py shell -c "import tracker.title_tier_test"

Exits non-zero if any assertion fails.
"""
import os
import sys

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


try:
    from tracker.services import client_families
    from tracker import views_block_evidence as ev
    _ok = True
except Exception as e:  # ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("Title-before-temporal:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    class FakeClient:
        def __init__(self, cid, name, aliases=None):
            self.id, self.name, self.aliases = cid, name, aliases or []

    class FakeBlock:
        def __init__(self, title, app_name="AcroRd32.exe"):
            self.window_title = title
            self.title = title
            self.app_name = app_name
            self.file_path = ""
            self.url = ""

    # A slice of org 21's roster: two St. Francises (nothing can tell them
    # apart), and the St Patrick's group whose bare member is a prefix magnet.
    ROSTER = [
        FakeClient(399, 'St. Francis of Assisi Church'),
        FakeClient(400, 'St. Francis Xavier Church'),
        FakeClient(130, "St. Patrick's Church"),
        FakeClient(129, 'St Patricks_St Anthony_Chadwicks'),
        FakeClient(500, 'Halvorsen Machining LLC'),
        FakeClient(600, 'All Round Repair & Sales Corp'),
        FakeClient(270, 'Inventory Plus, Inc'),
        FakeClient(700, 'Church Of Annunciation'),
        # Share the word "home" and nothing else — a shell window saying "Home"
        # must not turn into a question about which of them it belongs to.
        FakeClient(810, 'Krueger Funeral Home Inc'),
        FakeClient(811, 'Closer Look Home Inspections Inc'),
    ]
    L = client_families.ClientLookalikes(ROSTER)

    # Both roster lookups are the only things in this path that touch the DB.
    ev._lookalikes_cached = lambda org_id: L
    # The strict whole-name matcher: on this roster it is the magnet — it says
    # "St. Patrick's Church" for a title that plainly says Chadwicks.
    ev._client_forms_cached = lambda org_id: [
        (130, "St. Patrick's Church", {"saint patrick"}, {"patrick"}),
    ]

    NEIGHBOUR = {'before': {'client_id': 129, 'client_name': 'St Patricks_St Anthony_Chadwicks'}}

    def suggest(title, surrounding=NEIGHBOUR, app_name="AcroRd32.exe"):
        block = FakeBlock(title, app_name)
        tc, fam = ev._title_who(block, 21)
        sentence, tier, sid, sname = ev._compose_why(
            "", None, surrounding, title_client=tc, title_family=fam)
        return {'tier': tier, 'client_id': sid, 'sentence': sentence,
                'candidates': [c['client_id'] for c in (fam or {}).get('candidates', [])]}

    print("Title-before-temporal — the title names a FAMILY:")
    r = suggest('St Francis 6-21 & 6-28.pdf - Adobe Acrobat Reader (64-bit)')
    check("does not answer with the neighbour", r['client_id'] != 129)
    check("suggests nobody at all", r['client_id'] is None)
    check("reports the family tier", r['tier'] == 'family')
    check("offers both St. Francises as candidates", sorted(r['candidates']) == [399, 400])
    check("names the shared part back to the user", 'St. Francis' in r['sentence'])

    print("Title-before-temporal — the title names ONE member:")
    r = suggest('St Patricks Chadwicks Client Information.xlsx - Excel')
    check("resolves to the parish the title actually says", r['client_id'] == 129)
    check("not the bare prefix-magnet client", r['client_id'] != 130)
    check("reports the title tier", r['tier'] == 'title')

    r = suggest('Halvorsen Machining 2026 payroll.xlsx - Excel')
    check("a client with no look-alikes still resolves", r['client_id'] == 500)

    print("Title-before-temporal — one incidental word is not a name:")
    r = suggest('Quarterly Sales tax - Message (HTML)')
    check("'Sales tax' doesn't name All Round Repair & Sales", r['client_id'] != 600)
    check("...it falls through to the neighbour", r['tier'] == 'neighbor')
    r = suggest(' QuickBooks Accountant Desktop Plus 2024')
    check("bare QuickBooks chrome doesn't name Inventory Plus", r['client_id'] != 270)
    r = suggest('Office - Annunciation - Office - Outlook')
    check("a one-word client name IS named when the text says it", r['client_id'] == 700)

    print("Title-before-temporal — one shared word is not a family:")
    r = suggest('Home - File Explorer', app_name="explorer.exe")
    check("a shell window doesn't ask which 'Home' client it is", r['tier'] != 'family')
    check("...and doesn't name one either", r['tier'] == 'neighbor')

    print("Title-before-temporal — the title names NOBODY:")
    r = suggest('Inbox - Outlook')
    check("falls through to the temporal neighbour", r['client_id'] == 129)
    check("reports the neighbour tier", r['tier'] == 'neighbor')

    r = suggest('St Francis 6-21 & 6-28.pdf - Adobe Acrobat Reader (64-bit)', surrounding={})
    check("family question survives an empty neighbourhood", r['tier'] == 'family')

    print("Title-before-temporal — a co-open client FILE still outranks the title:")
    block = FakeBlock('St Francis 6-21 & 6-28.pdf - Adobe Acrobat Reader (64-bit)')
    tc, fam = ev._title_who(block, 21)
    _, tier, sid, _ = ev._compose_why(
        "", {'client_id': 500, 'client_name': 'Halvorsen Machining LLC', 'file': 'x.qbw'},
        NEIGHBOUR, title_client=tc, title_family=fam)
    check("co-open file wins", (tier, sid) == ('co_open', 500))

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
