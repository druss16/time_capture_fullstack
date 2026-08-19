"""
Regression tests for _commit_if_immaterial (tracker.services.classification_service).

The bug it guards: the sub-2-minute materiality auto-commit (PR #109) lives at
the BOTTOM of _finalize_decision, but the three propose-only attributors —
co-open, sheet-tab, sandwich — each return before reaching it. So a 1-minute
scratch workbook that co-open confidently placed under a client still landed in
"Needs you". Observed live: block 63005, 'Book6 - Excel', 1m, proposed to client
412 with the reasoning "Open alongside St. Matthews Church's file ... in the same
Office session".

The helper re-applies the materiality rule at those three exits. It commits the
sliver to the client the stage named and leaves is_billable alone — this decides
REVIEW, not billability — and keeps the contradicting-signal guard so a genuinely
disputed sliver still gets a human look.

Run inside the app container:
    python manage.py shell -c "import tracker.immaterial_propose_stages_test"
or standalone where Django is configured:
    python tracker/immaterial_propose_stages_test.py

Exits non-zero if any assertion fails.
"""
import os
import sys
from types import SimpleNamespace

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
        ClassificationService, ClassificationDecision, Signal,
        IMMATERIAL_MAX_MINUTES,
    )
    _ok = True
except Exception as e:  # ModuleNotFoundError / ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("immaterial propose-only stages:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    print("immaterial propose-only stages:")

    # A stand-in `self`: the helper only ever reaches back for the (static)
    # contradiction guard, so there is no need to build a real service.
    _stub = SimpleNamespace(
        _has_contradicting_signal=ClassificationService._has_contradicting_signal
    )

    def commit(decision, minutes, signals=(), stage='co-open'):
        """Run the helper as the stage would; returns (converted, decision)."""
        block = SimpleNamespace(pk=63005, minutes=minutes)
        got = ClassificationService._commit_if_immaterial(
            _stub, decision, block, list(signals), stage
        )
        return got, decision

    def proposed(client_id=412, billable=True, needs_review=False):
        """A decision exactly as co-open/sheet-tab/sandwich leaves it."""
        return ClassificationDecision(
            client_id=client_id, is_billable=billable, confidence=0.62,
            recommended_state='proposed', needs_review=needs_review,
        )

    def sig(client_id, strength):
        return Signal(type='ai_client', strength=strength, evidence='',
                      detail={'client_id': client_id})

    # --- the bug: block 63005 ------------------------------------------------
    got, d = commit(proposed(), minutes=1)
    check("1m co-open sliver with a client -> committed, no 'Needs you'",
          got is True and d.recommended_state == 'committed')

    check("the auto-commit is auditable (signal names the stage)",
          any(s.type == 'auto_confirm_immaterial' and s.detail.get('stage') == 'co-open'
              for s in d.matched_signals))

    for _stage in ('sheet-tab', 'sandwich'):
        got, d = commit(proposed(), minutes=1, stage=_stage)
        check(f"{_stage} sliver auto-files the same way",
              got is True and d.recommended_state == 'committed')

    # --- billability is not this rule's business ------------------------------
    # The stage decided billable/non-billable from its own evidence; waiving the
    # review click must not silently re-price the minute in either direction.
    got, d = commit(proposed(billable=True), minutes=1)
    check("billable sliver stays billable", d.is_billable is True)
    got, d = commit(proposed(billable=False), minutes=1)
    check("non-billable sliver stays non-billable",
          got is True and d.is_billable is False)

    # --- material blocks are untouched ----------------------------------------
    got, d = commit(proposed(), minutes=IMMATERIAL_MAX_MINUTES)
    check("exactly at the threshold -> still proposed (human looks)",
          got is False and d.recommended_state == 'proposed')
    got, d = commit(proposed(), minutes=45)
    check("45m co-open guess -> still proposed (never auto-billed)",
          got is False and d.recommended_state == 'proposed')

    # --- guards ---------------------------------------------------------------
    got, d = commit(proposed(client_id=None), minutes=1)
    check("stage named nobody -> left alone for the tail rule to file",
          got is False and d.recommended_state == 'proposed')

    got, d = commit(proposed(), minutes=1, signals=[sig(999, 0.85)])
    check("another moderate-or-better signal names a different client -> human looks",
          got is False and d.recommended_state == 'proposed')

    got, d = commit(proposed(), minutes=1, signals=[sig(999, 0.55)])
    check("only a WEAK signal disagrees -> not a contradiction, still auto-files",
          got is True and d.recommended_state == 'committed')

    got, d = commit(proposed(), minutes=1, signals=[sig(412, 0.85)])
    check("a strong signal AGREEING is not a contradiction",
          got is True and d.recommended_state == 'committed')

    got, d = commit(proposed(needs_review=True), minutes=1)
    check("already flagged for review -> the flag wins",
          got is False and d.recommended_state == 'proposed')

    got, d = commit(proposed(), minutes=0)
    check("zero-minute block -> immaterial by definition", got is True)

    got, d = commit(proposed(), minutes=None)
    check("missing minutes -> treated as immaterial, not a crash", got is True)

print()
print(f"immaterial propose-only stages: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
