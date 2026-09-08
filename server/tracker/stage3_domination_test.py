"""
Regression tests for the Stage-3 SPECIFICITY-DOMINATION rule.

When two clients both match a piece of text, and the text says everything it
says about client A and MORE about client B, A is the less specific reading of
the same words and is dropped before the tie / clear-winner logic.

Evidence is compared in two tiers (see ClassificationService._text_evidence):

  core   — distinctive words present in the text ("taberg", "baldwinsville")
  entity — entity-class words present in the text ("church", "cemetery")

Core decides; entity only breaks a core tie. That split is load-bearing in BOTH
directions and each half has a real misroute behind it:

  * entity must NOT count as core, or the boilerplate "Church" in client 130's
    name ("St. Patrick's Church") outvotes the sibling that actually owns the
    title, and "St. Patrick's Church-Taberg" books to the wrong parish.
  * entity must still count as a tiebreak, or "St Peter's Church" and
    "St Peter's Cemetery" — two separate clients whose only difference IS the
    head noun — tie forever and defer.

CRITICAL invariant: domination fires only on the TEXT's own evidence, never on
client-name shape. A bare title that names the family but no member must leave
every member standing so the collision path can defer — the predecessor rule
compared names to each other and silently booked bare "Christ Our Hope Church"
to its "-Boonville" sibling.

Needs the app on the path (imports classification_service, which pulls in
Django models); if unavailable (bare python), the cases are SKIPPED, not failed.
Run inside the app container:

    python manage.py shell -c "import tracker.stage3_domination_test"
or standalone where Django is configured:
    python tracker/stage3_domination_test.py

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
    from tracker.services.classification_service import ClassificationService
    _ok = True
except Exception as e:  # ModuleNotFoundError / ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("Stage-3 specificity-domination:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    N = ClassificationService._normalize_name

    class FakeClient:
        """Stands in for a Client row — _text_evidence reads name + aliases."""

        def __init__(self, name, aliases=None):
            self.name = name
            self.aliases = aliases or []

    # Real org-21 family names (name + the aliases that matter here).
    C = {
        169: FakeClient('Assumption Church', ['Franciscan Church of the Assumption']),
        395: FakeClient("St. Mary's of the Assumption",
                        ['St. Mary of the Assumption Church',
                         'St Mary of the Assumption']),
        175: FakeClient('Basilica of The Sacred Heart of Jesus'),
        361: FakeClient('Sacred Heart Parish-Rome'),
        360: FakeClient('Sacred Heart- Cicero'),
        390: FakeClient("St Patrick's Church-Jordan"),
        391: FakeClient("St Patrick's Jordan Cemetery"),
        392: FakeClient("St Patrick's Taberg"),
        130: FakeClient("St. Patrick's Church"),
        197: FakeClient('Christ our Hope Church'),
        198: FakeClient('Christ our Hope Church-Boonville',
                        ['Christ our Hope Church']),
        393: FakeClient("St Peter's Cemetery"),
        414: FakeClient('St. Peters Church'),
        790: FakeClient("St. Mary's Church Baldwinsville"),
        791: FakeClient("St. Mary's School Baldwinsville"),
    }

    def dominated(a, b, text):
        """Mirror of the Stage-3 filter: does client `a` lose to client `b`
        given this text? Lexicographic — core decides, entity breaks ties."""
        toks = set(N(text).split())
        ca, ea = ClassificationService._text_evidence(C[a], toks)
        cb, eb = ClassificationService._text_evidence(C[b], toks)
        if ca != cb:
            return ca < cb
        return ea < eb

    print("Stage-3 specificity-domination — evidence tiers:")
    core, entity = ClassificationService._text_evidence(
        C[392], set(N("St. Patrick's Church-Taberg - QuickBooks").split()))
    check("distinctive word lands in core", core == {'patrick', 'taberg'})
    check("Taberg client contributes no entity word", entity == set())
    core, entity = ClassificationService._text_evidence(
        C[130], set(N("St. Patrick's Church-Taberg - QuickBooks").split()))
    check("generic client's 'church' lands in entity, not core",
          core == {'patrick'} and entity == {'church'})
    core, _ = ClassificationService._text_evidence(
        C[392], set(N("St. Patrick's Church - QuickBooks").split()))
    check("absent distinguishing word is not evidence", core == {'patrick'})

    print("Stage-3 specificity-domination — the generic-family magnet:")
    T_TABERG = "St. Patrick's Church-Taberg  - QuickBooks Accountant Desktop Plus 2024"
    check("generic 130 loses to 392 when 'taberg' is in the title",
          dominated(130, 392, T_TABERG) is True)
    check("392 does NOT lose to generic 130", dominated(392, 130, T_TABERG) is False)
    T_JORDAN = "St Patrick's Church-Jordan  - QuickBooks"
    check("generic 130 loses to 390 when 'jordan' is in the title",
          dominated(130, 390, T_JORDAN) is True)

    T_SH_BASILICA = 'Sacred Heart Basilica  - QuickBooks'
    check("Cicero loses to Basilica when 'basilica' is in the title",
          dominated(360, 175, T_SH_BASILICA) is True)
    check("Basilica does NOT lose to Cicero on its own title",
          dominated(175, 360, T_SH_BASILICA) is False)

    print("Stage-3 specificity-domination — the fix it inherited:")
    T_ASSUMP = 'ST. MARY OF THE ASSUMPTION CHURCH  - QuickBooks'
    check("169 'Assumption Church' loses to 395", dominated(169, 395, T_ASSUMP) is True)
    check("395 does NOT lose to 169", dominated(395, 169, T_ASSUMP) is False)

    print("Stage-3 specificity-domination — entity words break a core tie:")
    T_CEM = "St Peter's Cemetery - QuickBooks"
    check("church 414 loses to cemetery 393 on a cemetery title",
          dominated(414, 393, T_CEM) is True)
    T_CHURCH = 'St. Peters Church - QuickBooks'
    check("cemetery 393 loses to church 414 on a church title",
          dominated(393, 414, T_CHURCH) is True)
    T_BVILLE = "St. Mary's Church Baldwinsville - QuickBooks"
    check("school 791 loses to church 790 on a church title",
          dominated(791, 790, T_BVILLE) is True)

    print("Stage-3 specificity-domination — ambiguity MUST still defer:")
    T_BARE_HOPE = 'Christ Our Hope Church  - QuickBooks Accountant Desktop Plus 2024'
    check("bare title: 197 does NOT lose to its -Boonville sibling",
          dominated(197, 198, T_BARE_HOPE) is False)
    check("bare title: 198 does NOT lose to 197 either",
          dominated(198, 197, T_BARE_HOPE) is False)
    T_BARE_PAT = "St. Patrick's Church  - QuickBooks"
    check("bare title: generic 130 does NOT lose to Taberg",
          dominated(130, 392, T_BARE_PAT) is False)
    check("bare title: generic 130 does NOT lose to Jordan",
          dominated(130, 390, T_BARE_PAT) is False)
    T_SH_BARE = 'Sacred Heart  - QuickBooks Accountant Desktop Plus 2024'
    check("family stem only: Cicero does NOT lose to Basilica",
          dominated(360, 175, T_SH_BARE) is False)
    check("family stem only: Cicero does NOT lose to Rome",
          dominated(360, 361, T_SH_BARE) is False)
    check("family stem only: Basilica does NOT lose to Cicero",
          dominated(175, 360, T_SH_BARE) is False)
    T_JC = "St Patricks Jordan.xlsx"
    check("St Patrick Jordan church does NOT lose to Jordan cemetery",
          dominated(390, 391, T_JC) is False)
    T_NOTES = 'St Mary Baldwinsville Client Notes.xlsx - Excel'
    check("no head noun in text: church 790 does NOT lose to school 791",
          dominated(790, 791, T_NOTES) is False)
    check("no head noun in text: school 791 does NOT lose to church 790",
          dominated(791, 790, T_NOTES) is False)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
