"""
Regression test for the sub-2-minute NO-CLIENT sliver with no qualifying signal.

The gap it guards: such a block had no path to being committed, and so fell out
of the product entirely.

  * `_commit_if_immaterial` returns early on `decision.client_id is None`.
  * The existing `auto_confirm_immaterial_noclient` branch is reached only when
    `moderate_or_better` is non-empty.
  * The tail of `_finalize_decision` then sets 'captured' when weak signals
    exist and otherwise leaves the default — either way `is_categorized` stays
    False.

A minute of untraceable activity — a browser tab on an unrecognised host, a
terminal window — has no client and no qualifying signal, so it hit all three.
It was then invisible in BOTH directions: `compute_totals` counts only
confirmed blocks, so it was not time; and `is_pending_review_block` requires
`_is_material` (>= 2 min), so it was not a question either.

Measured on a live Mac agent: 56 of 62 captured minutes sat in that gap while
the dashboard read 6 minutes and Needs You said "nothing — you're done".

This drives the REAL `ClassificationService._finalize_decision` and the REAL
`is_pending_review_block`, not a copy of them, so it fails if the branch is
removed or its guards drift.

Run:
    python manage.py shell -c "import tracker.immaterial_noclient_test"
or with any settings module that configures Django:
    DJANGO_SETTINGS_MODULE=... python tracker/immaterial_noclient_test.py

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
    from django.core.exceptions import ImproperlyConfigured
except ImportError:                       # Django itself is absent
    class ImproperlyConfigured(Exception):
        pass

try:
    import django
    from django.apps import apps as _apps
    if not _apps.ready:          # already True under manage.py shell
        django.setup()
    from tracker.services.classification_service import (
        ClassificationService, ClassificationDecision, Signal,
        IMMATERIAL_MAX_MINUTES,
    )
    # Canonical Needs-Review predicate; services/billing_totals re-exports it.
    from tracker.views_reports import is_pending_review_block, _aggregate
    _ok = True
except (ImportError, ImproperlyConfigured) as e:
    _ok = False
    _skipped = 1
    print("immaterial no-client slivers:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}: {e})")

if _ok:
    print("immaterial no-client slivers:")

    def finalize(minutes=1, signals=(), bundle_id="", needs_review=False,
                 app_name="Safari", window_title="localhost:3000"):
        """Drive the real _finalize_decision on a bare in-memory block.

        The service is built without __init__ so no database is touched; the
        two attributes the function reads off `self` outside the signal paths
        are supplied directly. `_sandwich_enabled=False` keeps the one branch
        that would need a live user/org out of the way.
        """
        svc = ClassificationService.__new__(ClassificationService)
        svc._clients = []
        svc._sandwich_enabled = False
        svc.org = None
        block = SimpleNamespace(
            pk=1, minutes=minutes, bundle_id=bundle_id, window_title=window_title,
            url='', file_path='', app_name=app_name, category='',
            proposed_signals=[], user_id=1, start=None, end=None,
        )
        decision = ClassificationDecision(needs_review=needs_review)
        decision.matched_signals = list(signals)
        return ClassificationService._finalize_decision(svc, decision, block)

    def weak(strength=0.2):
        return Signal(type='prior_block', strength=strength,
                      evidence='adjacent block', detail={})

    def new_branch_fired(d):
        return any(s.type == 'auto_confirm_immaterial_noclient'
                   and s.detail.get('no_signals') is not None
                   for s in d.matched_signals)

    # --- the gap ------------------------------------------------------------
    d = finalize(minutes=1)
    check("1m no-client sliver with NO signals -> committed (was invisible)",
          d.recommended_state == 'committed')
    check("...and non-billable, not billable time",
          d.is_billable is False)
    check("...and auditable",
          new_branch_fired(d))

    d = finalize(minutes=1, signals=[weak(0.2)])
    check("1m no-client sliver with only WEAK signals -> committed too",
          d.recommended_state == 'committed' and new_branch_fired(d))

    # --- things it must NOT swallow -----------------------------------------
    d = finalize(minutes=5)
    check(f"a 5m no-client block is material (>= {IMMATERIAL_MAX_MINUTES}m) "
          f"-> left alone",
          d.recommended_state != 'committed' and not new_branch_fired(d))

    d = finalize(minutes=1, bundle_id='__idle__')
    check("idle is never booked as work",
          not new_branch_fired(d))

    d = finalize(minutes=1, needs_review=True)
    check("an explicit needs_review is respected",
          not new_branch_fired(d))

    strong = Signal(type='title_match_title_alias', strength=0.95,
                    evidence='client name in title',
                    detail={'client_id': 412})
    d = finalize(minutes=1, signals=[strong])
    check("a sliver WITH a client is left to the existing immaterial rules",
          not new_branch_fired(d))

    # --- the real Needs-Review predicate ------------------------------------
    def saved(state, is_categorized, categorized_by=''):
        """A stored Block as the predicate sees it: 1 minute, no client."""
        return SimpleNamespace(
            classification_state=state, is_categorized=is_categorized,
            categorized_by=categorized_by, minutes=1, bundle_id='',
            proposed_signals=[], client_id=None, category='',
            corrected_by_user=False, category_hours={}, start=None, end=None,
        )

    check("a committed sliver does not become a pending question",
          is_pending_review_block(saved('committed', True, 'auto')) is False)

    check("and the OLD state was indeed invisible to Needs Review "
          "(so it counted as neither time nor question)",
          is_pending_review_block(saved('captured', False)) is False)

    # --- the payoff: the minutes actually reach the dashboard ----------------
    # Being 'committed' is only half of it. _aggregate skips any block whose
    # dominant category is idle/uncategorized unless it is billable WITH a
    # client, so a committed sliver with empty category_hours would STILL be
    # invisible. `apply()` writes {decision.category: hours}, and the
    # fix6_default path sets that to 'Personal/Non-Billable', which survives.
    def stored(minutes, category_hours):
        return SimpleNamespace(
            classification_state='committed', is_categorized=True,
            categorized_by='auto', minutes=minutes, bundle_id='',
            proposed_signals=[], client_id=None, client=None, user_id=None,
            user=None, category='', corrected_by_user=False,
            category_hours=category_hours, start=None, end=None,
            is_billable=False,
        )

    t = _aggregate([stored(56, {'Personal/Non-Billable': 0.93})],
                   'employee')['totals']
    check("56m of committed no-client slivers show up as Total time",
          t['total_hours'] == 0.93)
    check("...and land in Non-billable, not Billable",
          t['non_billable_hours'] == 0.93 and t['billable_hours'] == 0.0)

    t = _aggregate([stored(56, {})], 'employee')['totals']
    check("...whereas an empty category_hours would still be dropped "
          "(why the category write is load-bearing)",
          t['total_hours'] == 0.0)

print(f"\n  {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
