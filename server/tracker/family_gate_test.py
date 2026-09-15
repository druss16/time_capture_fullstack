"""
Tests for the look-alike client machinery: who a title could mean
(tracker/services/client_families.py) and the folding of gated blocks into one
question per work session (tracker/services/ambiguous_groups.py).

The behaviour under test is a refusal, which makes the negative cases the
important ones. A picker that appears when the title DID say which parish is
worse than no picker at all — it trains people to click the first button.

Needs the app on the path (imports classification_service, which pulls in
Django models); if unavailable (bare python), the cases are SKIPPED, not failed.
Run inside the app container:

    python manage.py shell -c "import tracker.family_gate_test"
or standalone where Django is configured:
    python tracker/family_gate_test.py

Exits non-zero if any assertion fails.
"""
import os
import sys
from datetime import datetime, timedelta, timezone as dt_timezone

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
    from tracker.services.ambiguous_groups import build_groups, is_open_question
    _ok = True
except Exception as e:  # ModuleNotFoundError / ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("Look-alike clients:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    class FakeClient:
        def __init__(self, cid, name, aliases=None):
            self.id = cid
            self.name = name
            self.aliases = aliases or []

    # A slice of org 21's real roster — the shapes that actually break things.
    ROSTER = [
        FakeClient(130, "St. Patrick's Church", ['St Pats Chitt']),
        FakeClient(390, "St Patrick's Church-Jordan"),
        FakeClient(391, "St Patrick's Jordan Cemetery"),
        FakeClient(392, "St Patrick's Taberg"),
        FakeClient(388, "St Mary's Church- Clinton"),
        FakeClient(409, "St. Mary's Church-Hamilton"),
        FakeClient(790, "St. Mary's Church Baldwinsville"),
        FakeClient(791, "St. Mary's School Baldwinsville"),
        FakeClient(300, 'Mary Rodman'),
        FakeClient(270, 'Inventory Plus, Inc'),
        FakeClient(500, 'Halvorsen Machining LLC'),
        # Clients that share nothing but an everyday word. None of these groups
        # is a family, and each one was a question in org 21's review queue.
        FakeClient(216, 'Crescendo Music'),
        FakeClient(309, 'Music School of CNY , Inc.'),
        FakeClient(274, 'James H Michel Estate'),
        FakeClient(294, 'Linda M Vescio Estate'),
        FakeClient(362, 'Sager Real Estate Inc'),
        FakeClient(600, 'Spierit Management Services'),
        FakeClient(601, 'Victory Development Management'),
        FakeClient(414, 'St. Peters Church'),
        FakeClient(330, 'Peter Dugan'),
        # A real client whose name is nothing but everyday words.
        FakeClient(602, 'S&A Creative Designs LLC'),
    ]
    L = client_families.ClientLookalikes(ROSTER)
    W = client_families.text_words

    QB = ' - QuickBooks Accountant Desktop Plus 2024'

    print("Look-alike clients — application chrome is not evidence:")
    check("QuickBooks chrome doesn't make 'Inventory Plus' a candidate",
          270 not in L.candidates_for(W("St. Mary's Church" + QB)))
    check("'Desktop Plus 2024' alone names nobody",
          L.candidates_for(W('Some Window' + QB)) == [])
    check("trailing app name is stripped from a filename",
          L.resolve(W('St. Mary Baldwinsville Church Budget.xlsx - Excel')) == 790)

    print("Look-alike clients — resolve() names one, or admits it can't:")
    check("a deciding word resolves: Taberg",
          L.resolve(W("St. Patrick's Church-Taberg" + QB)) == 392)
    check("a deciding word resolves: Jordan",
          L.resolve(W("St Patrick's Church-Jordan" + QB)) == 390)
    check("bare 'St. Patrick's Church' resolves to NOBODY",
          L.resolve(W("St. Patrick's Church" + QB)) is None)
    check("bare 'St. Mary's Church' resolves to NOBODY",
          L.resolve(W("St. Mary's Church" + QB)) is None)
    check("a client with no look-alike still resolves",
          L.resolve(W('Halvorsen Machining LLC' + QB)) == 500)

    print("Look-alike clients — the entity class separates church from school:")
    check("'St. Mary's School' is the school, not the church",
          L.resolve(W("St. Mary's School" + QB)) == 791)
    check("an Academy file is the school (academy folds to school)",
          L.resolve(W('St Mary Baldwinsville Academy Balance Sheet.pdf')) == 791)
    check("a Cemetery title excludes the Church client",
          130 not in L.candidates_for(W("St Patrick's Jordan Cemetery" + QB)))

    print("Look-alike clients — buttons carry only the deciding word:")
    bare_mary = W("St. Mary's Church" + QB)
    check("sibling button reads 'Clinton'", L.short_name(388, bare_mary) == 'Clinton')
    check("sibling button reads 'Baldwinsville'",
          L.short_name(790, bare_mary) == 'Baldwinsville')
    check("hyphenated sibling reads 'Hamilton'",
          L.short_name(409, bare_mary) == 'Hamilton')
    check("a client the title fully covers keeps its whole name",
          L.short_name(130, W("St. Patrick's Church" + QB)) == "St. Patrick's Church")

    print("Look-alike clients — ranking puts the likely answer first:")
    ranked = L.rank(L.candidates_for(bare_mary), bare_mary)
    check("a person does not lead a 'Church' title", ranked[0] != 300)
    check("recently-worked client leads when known",
          L.rank(L.candidates_for(bare_mary), bare_mary, recent=[409])[0] == 409)

    print("Look-alike clients — a shared word is not yet a family:")
    check("a bare 'St. Mary's Church' IS a family",
          len(L.family_for(W("St. Mary's Church" + QB))) >= 2)
    check("a Pandora tab is not a question about clients with 'Music' in them",
          L.family_for(W('Listen to Your Favorite Music, Podcasts, and Radio '
                         'Stations for Free! - Work - Microsoft Edge')) == [])
    check("an estate-planning newsletter names no family",
          L.family_for(W('Gift and estate planning: connecting the pieces '
                         '- Message (HTML)')) == [])
    check("'Management' in two unrelated firm names is not a family",
          L.family_for(W('Homepage - Tarbell Management Group and 3 more '
                         'pages - Work - Microsoft Edge')) == [])
    check("a person who shares a first name with a parish is not its look-alike",
          L.family_for(W('Peter Dugan 2026 letter.pdf')) == [])
    # "peter" is the most specific root here (two candidates) but it dissolves:
    # St. Peters Church and Peter Dugan are not confusable. The real question
    # is the St. Mary's behind it, and it must survive the dissolved root.
    _two_parishes = L.family_for(W("St. Mary - St. Peter's Church" + QB))
    check("a root that dissolves doesn't take the real question with it",
          len(_two_parishes) >= 2 and 330 not in _two_parishes)

    print("Look-alike clients — the row has to say WHERE it read the name:")
    JORDAN = [390, 391]     # Church-Jordan vs Jordan Cemetery
    _dialog = L.named_by(
        JORDAN,
        'Save Print Output As',
        "\\\\tlwall-dc-01\\Company Data\\Client File Notes\\St Patrick's "
        "Jordan\\2026-2027\\St Patricks P&L Budget Overview FINAL 09-14-26.xlsx")
    check("a dialog title defers to the folder that carries the name",
          _dialog == {'source': 'folder', 'text': "St Patrick's Jordan"})
    check("a title that names the group speaks for itself",
          (L.named_by(JORDAN, "St Patrick's Jordan" + QB) or {}).get('source') == 'title')
    check("...and the app chrome is not part of what it said",
          (L.named_by(JORDAN, "St Patrick's Jordan" + QB) or {})
          .get('text') == "St Patrick's Jordan")
    check("a file that carries the name more fully than its folder wins",
          L.named_by(JORDAN, 'Save Print Output As',
                     "\\\\srv\\Clients\\2026\\St Patricks Jordan Budget.xlsx")
          == {'source': 'file', 'text': 'St Patricks Jordan Budget.xlsx'})
    check("nothing named them -> no reason to show",
          L.named_by(JORDAN, 'Find and Replace') is None)
    check("an empty family names nobody", L.named_by([], 'anything') is None)

    print("Look-alike clients — ONE everyday word names nobody:")
    check("'estate' alone doesn't make an estate client a candidate",
          274 not in L.candidates_for(W('Gift and estate planning')))
    check("...but the name still does",
          274 in L.candidates_for(W('Michel estate 1041 draft.pdf')))
    check("'management' alone doesn't make a firm a candidate",
          600 not in L.candidates_for(W('Cable Clips Cord Holder Cable '
                                        'Management Finisher')))
    check("a client whose whole name is everyday words still finds its own file",
          602 in L.candidates_for(W('S&A Creative Designs, LLC' + QB)))
    check("...but one of those words on its own does not",
          602 not in L.candidates_for(W('Creative Cloud Desktop')))
    # "music" is in nobody's stoplist and never will be — the roster is what
    # decides. Two clients answering to it is what the family test is for.
    check("'music' still makes a music client a candidate",
          309 in L.candidates_for(W('Music School of CNY recital budget.xlsx')))

    print("Look-alike clients — has_lookalikes:")
    check("a parish in a group has look-alikes", L.has_lookalikes(388) is True)
    check("a one-of-a-kind client does not", L.has_lookalikes(500) is False)

    # ── grouping ────────────────────────────────────────────────────────────
    class FakeBlock:
        def __init__(self, bid, minutes, offset_min, candidates, title="St. Mary's Church"):
            base = datetime(2026, 9, 8, 9, 0, tzinfo=dt_timezone.utc)
            self.id = bid
            self.user_id = 1
            self.window_title = title
            self.title = title
            self.minutes = minutes
            self.start = base + timedelta(minutes=offset_min)
            self.end = self.start + timedelta(minutes=minutes)
            self.category_hours = {'Accounting/Bookkeeping': minutes / 60}
            self.proposed_signals = [{
                'type': 'family_ambiguous',
                'detail': {
                    'candidate_client_ids': candidates,
                    'candidate_labels': {str(c): f'c{c}' for c in candidates},
                },
            }]

    NAMES = {c.id: c.name for c in ROSTER}

    print("Picker labels — two buttons must never read the same:")
    _t = W("St Patrick's Church Cemetery Fund  - QuickBooks")
    _cands = [390, 391]   # Church-Jordan  vs  Jordan Cemetery
    check("without the candidate set the two labels collide",
          L.short_name(390, _t) == L.short_name(391, _t))
    check("given the set, each button says what makes IT unique",
          L.short_name(390, _t, _cands) != L.short_name(391, _t, _cands))

    print("Ambiguous groups — one question per sitting, not per block:")
    run = [FakeBlock(1, 20, 0, [388, 790]), FakeBlock(2, 5, 25, [388, 790]),
           FakeBlock(3, 15, 35, [388, 790])]
    groups = build_groups(run, NAMES)
    check("three blocks in one sitting fold into ONE row", len(groups) == 1)
    check("the row carries every block", groups and groups[0]['block_ids'] == [1, 2, 3])
    check("the row sums the minutes", groups and groups[0]['minutes'] == 40)

    apart = [FakeBlock(1, 20, 0, [388, 790]), FakeBlock(2, 20, 400, [388, 790])]
    check("work hours apart stays two questions",
          len(build_groups(apart, NAMES)) == 2)

    disjoint = [FakeBlock(1, 20, 0, [388, 790]), FakeBlock(2, 20, 25, [390, 392])]
    check("adjacent blocks about DIFFERENT groups don't merge",
          len(build_groups(disjoint, NAMES)) == 2)

    narrowing = [FakeBlock(1, 10, 0, [388, 790, 409]), FakeBlock(2, 10, 15, [388, 790])]
    narrowed = build_groups(narrowing, NAMES)
    check("a run narrows to what every block agrees on",
          len(narrowed) == 1
          and {c['client_id'] for c in narrowed[0]['candidates']} == {388, 790})

    print("Ambiguous groups — only gated blocks appear:")
    plain = FakeBlock(9, 30, 0, [388, 790])
    plain.proposed_signals = [{'type': 'agent_inference', 'detail': {}}]
    check("a block with no Stage-11 signal is ignored",
          build_groups([plain], NAMES) == [])
    check("no gated blocks -> no rows", build_groups([], NAMES) == [])

    print("Stored candidates are re-narrowed at render time:")
    from tracker.services.ambiguous_groups import narrow_to_live_family, _signal

    class _StubRoster:
        """for_org is patched to this so the test needs no database."""
        @staticmethod
        def for_org(_org_id, use_cache=True):
            return L

    wide = FakeBlock(21, 20, 0, [388, 409, 790, 791, 300], title='St Mary Baldwinsville Notes')
    wide.client_id, wide.file_path, wide.url = 790, '', ''
    import tracker.services.client_families as _cf
    _real_for_org = _cf.for_org
    _cf.for_org = _StubRoster.for_org
    try:
        narrow_to_live_family([wide], 21)
    finally:
        _cf.for_org = _real_for_org
    _after = (_signal(wide).get('detail') or {}).get('candidate_client_ids', [])
    check("a five-candidate signal narrows to the real question",
          set(_after) == {790, 791})
    check("...and the block's own client survives the narrowing", 790 in _after)

    unattributed = FakeBlock(23, 20, 0, [388, 409, 790, 791, 300],
                             title='St Mary Baldwinsville Notes')
    unattributed.client_id, unattributed.file_path, unattributed.url = None, '', ''
    _cf.for_org = _StubRoster.for_org
    try:
        narrow_to_live_family([unattributed], 21)
        _ids = (_signal(unattributed).get('detail') or {}).get('candidate_client_ids', [])
        _ok = None not in _ids
    except Exception:
        _ok = False
    finally:
        _cf.for_org = _real_for_org
    check("a block with NO client doesn't put None in the candidate list", _ok)

    tight = FakeBlock(22, 20, 0, [388, 790], title="St. Mary's Church")
    tight.client_id, tight.file_path, tight.url = 790, '', ''
    narrow_to_live_family([tight], 21)
    check("an already-tight signal is left alone",
          (_signal(tight).get('detail') or {}).get('candidate_client_ids') == [388, 790])

    print("Still an open question — what Confirm-all must not answer:")
    gated = FakeBlock(11, 30, 0, [388, 790])
    check("a gated block is an open question", is_open_question(gated) is True)
    plain2 = FakeBlock(12, 30, 0, [388, 790])
    plain2.proposed_signals = [{'type': 'agent_inference', 'detail': {}}]
    check("an ungated block is not", is_open_question(plain2) is False)
    answered = FakeBlock(13, 30, 0, [388, 790])
    answered.proposed_signals = answered.proposed_signals + [
        {'type': 'qb_company_file', 'detail': {}},
    ]
    check("gated but since answered by the QuickBooks file is not",
          is_open_question(answered) is False)
    agent_from_file = FakeBlock(14, 30, 0, [388, 790])
    agent_from_file.proposed_signals = agent_from_file.proposed_signals + [
        {'type': 'agent_inference',
         'detail': {'inference_evidence_sources': ['qb_company_file']}},
    ]
    check("...and so is an agent inference drawn from that file",
          is_open_question(agent_from_file) is False)

    print("The gate stops a client commit — and nothing else:")
    from tracker.services.classification_service import (
        ClassificationDecision, ClassificationService,
    )

    def _gate(state, client_id=None, title="St. Mary's Church" + QB):
        """Run Stage 11 over a decision without touching the database."""
        svc = ClassificationService.__new__(ClassificationService)
        svc._lookalikes = L            # set, so the roster is never fetched
        block = FakeBlock(99, 10, 0, [], title=title)
        block.file_path = block.url = ''
        block.client_id = client_id
        block.proposed_signals = []
        decision = ClassificationDecision(
            client_id=client_id, recommended_state=state,
            # FIX 6 in _finalize_decision: no client means not billable.
            is_billable=client_id is not None)
        return svc._gate_family_ambiguity(block, decision)

    def _asked(decision):
        return any(s.type == 'family_ambiguous' for s in decision.matched_signals)

    _personal = _gate(
        'committed',
        title='Listen to Your Favorite Music, Podcasts, and Radio Stations '
              'for Free! - Work - Microsoft Edge')
    check("a settled non-billable commit is not re-opened",
          _personal.recommended_state == 'committed' and not _personal.needs_review)
    _overhead = _gate('committed')     # no client, but the title names a family
    check("...even when the title does name a look-alike family",
          _overhead.recommended_state == 'committed' and not _asked(_overhead))
    _unattributed = _gate('captured')
    check("an unattributed block still gets its shortlist", _asked(_unattributed))
    _guess = _gate('committed', client_id=790)
    check("a client committed on thin evidence is still downgraded",
          _guess.recommended_state == 'proposed' and _asked(_guess))

    print("Ambiguous groups — recency decides the leftmost button:")
    recent_first = build_groups([FakeBlock(1, 20, 0, [388, 790])], NAMES,
                                recent_client_ids=[790])
    check("recently-worked client is offered first",
          recent_first[0]['candidates'][0]['client_id'] == 790)
    check("and is marked as recent", recent_first[0]['candidates'][0]['recent'] is True)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
