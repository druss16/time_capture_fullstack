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

    print("Ambiguous groups — recency decides the leftmost button:")
    recent_first = build_groups([FakeBlock(1, 20, 0, [388, 790])], NAMES,
                                recent_client_ids=[790])
    check("recently-worked client is offered first",
          recent_first[0]['candidates'][0]['client_id'] == 790)
    check("and is marked as recent", recent_first[0]['candidates'][0]['recent'] is True)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
