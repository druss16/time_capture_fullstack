"""
Regression tests for the Stage-3 SUBSTRING-DOMINATION rule.

When a shorter client's whole name is embedded as a contiguous run inside a
longer, more-specific client's name AND both matched the title, the longer
client is the real subject and the shorter (embedded) one is dropped before the
tie / clear-winner logic. This prevents the "Assumption Church" (169) vs
"St. Mary of the Assumption Church" (395) misroute.

CRITICAL invariant: it must fire ONLY on proper contiguous token-subsequence
containment, never on shared-token OVERLAP — otherwise same-family collisions
(Sacred Heart siblings, St Patrick Jordan vs Taberg) would stop deferring and
silently mis-bill.

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
    from tracker.services.classification_service import (
        _is_proper_contiguous_subsequence as subseq,
        ClassificationService,
    )
    _ok = True
except Exception as e:  # ModuleNotFoundError / ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("Stage-3 substring-domination:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    N = ClassificationService._normalize_name

    def dominated(a_names, b_names):
        """Mirror of the Stage-3 filter's per-client test: is client A (a_names)
        dominated by client B (b_names)?"""
        A = [N(x).split() for x in a_names if N(x)]
        B = [N(x).split() for x in b_names if N(x)]
        return any(subseq(an, bn) for an in A for bn in B)

    print("Stage-3 substring-domination — predicate:")
    check("contiguous proper subseq -> True",
          subseq(['assumption', 'church'],
                 ['saint', 'mary', 'of', 'the', 'assumption', 'church']) is True)
    check("equal length (not proper) -> False",
          subseq(['sacred', 'heart'], ['sacred', 'heart']) is False)
    check("non-contiguous tokens -> False",
          subseq(['mary', 'church'], ['mary', 'of', 'the', 'church']) is False)
    check("shared-token overlap, neither embedded -> False",
          subseq(['sacred', 'heart', 'cicero'],
                 ['sacred', 'heart', 'rome']) is False)
    check("empty -> False", subseq([], ['a', 'b']) is False)

    # Real org-21 family names (name + relevant aliases).
    C = {
        169: ['Assumption Church', 'Franciscan Church of the Assumption'],
        395: ["St. Mary's of the Assumption", 'St. Mary of the Assumption Church',
              'St Mary of the Assumption'],
        175: ['Basilica of The Sacred Heart of Jesus'],
        361: ['Sacred Heart Parish-Rome'],
        360: ['Sacred Heart- Cicero'],
        390: ["St Patrick's Church-Jordan"],
        391: ["St Patrick's Jordan Cemetery"],
        392: ["St Patrick's Taberg"],
        130: ["St. Patrick's Church"],
    }

    def dom(a, b):
        return dominated(C[a], C[b])

    print("Stage-3 substring-domination — the fix:")
    check("169 'Assumption Church' dominated by 395 -> dropped",
          dom(169, 395) is True)
    check("395 NOT dominated by 169", dom(395, 169) is False)

    print("Stage-3 substring-domination — same-family deferrals MUST NOT break:")
    check("Sacred Heart Cicero NOT dominated by Basilica", dom(360, 175) is False)
    check("Sacred Heart Cicero NOT dominated by Rome", dom(360, 361) is False)
    check("Basilica NOT dominated by a sibling", dom(175, 360) is False)
    check("St Patrick Jordan NOT dominated by Taberg", dom(390, 392) is False)
    check("St Patrick Jordan-Church NOT dominated by Jordan-Cemetery",
          dom(390, 391) is False)

    print("Stage-3 substring-domination — generic beaten only by a real superset:")
    check("generic 'St Patrick Church' dominated by 'Church-Jordan'",
          dom(130, 390) is True)
    check("generic 'St Patrick Church' NOT dominated by 'Taberg'",
          dom(130, 392) is False)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
