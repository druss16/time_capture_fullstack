"""
Regression test for the "No client" card that had minutes but no rows.

Daily Review showed TOTAL 1h25m over a single 7m client, and underneath it
"You're all caught up — 100% sorted". The missing 1h18m was no-client time.

It was not lost on the way in. `compute_totals` counted it: `_aggregate` folds
sub-2-minute non-billable time into `total_hours` as `immaterial_min`. It was
lost on the way OUT, in two steps:

  1. `compute_client_cards` added immaterial non-billable minutes to the
     client's ledger total and then `continue`d, so they produced no category
     row. Fine while such a sliver garnished a client with material rows of its
     own — fatal once a whole client consisted of nothing else.
  2. The "No client" card therefore arrived with `total_hours` set and
     `categories: []`, and the lane builder drops any client it can build no
     rows for (`dailyReviewLanes.ts`: `if (!rows.length) continue`).

So the header counted the time and no row beneath it did. This is the sequel to
the fix that created the pile in the first place (PR #499): committing those
slivers put the minutes into the total, and this puts them on the screen.

The arithmetic must not move — that is the other half of what is checked here.

Run:
    python manage.py shell -c "import tracker.no_client_card_test"
or with any settings module that configures Django:
    DJANGO_SETTINGS_MODULE=... python tracker/no_client_card_test.py

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
    from tracker.services import billing_totals
    from tracker.views_reports import _aggregate
    _ok = True
except (ImportError, ImproperlyConfigured) as e:
    _ok = False
    _skipped = 1
    print("no-client card:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}: {e})")

if _ok:
    print("no-client card:")

    _next_id = [1]
    _user = SimpleNamespace(id=1, username='dan',
                            get_full_name=lambda: 'Dan Russell')

    def blk(minutes, client=None, billable=False,
            category='Personal/Non-Billable', title='localhost:3000'):
        """A committed block as the card builder reads it."""
        _next_id[0] += 1
        return SimpleNamespace(
            id=_next_id[0], pk=_next_id[0],
            classification_state='committed', is_categorized=True,
            minutes=minutes, start=None, end=None,
            client_id=(client.id if client else None), client=client,
            user_id=1, user=_user,
            is_billable=billable, category='',
            category_hours={category: round(minutes / 60.0, 2)},
            app_name='Safari', window_title=title, url='', bundle_id='',
            proposed_signals=[], corrected_by_user=False,
        )

    def cards(blocks):
        """Run the real compute_client_cards over an in-memory block list."""
        real = billing_totals.committed_block_qs
        billing_totals.committed_block_qs = lambda *a, **k: blocks
        try:
            return billing_totals.compute_client_cards(
                None, None, None, user_id=1, can_see_all=False)
        finally:
            billing_totals.committed_block_qs = real

    def card_named(cs, name):
        return next((c for c in cs if c['client'] == name), None)

    # The day from the screenshot: one small real client, and a pile of
    # one-minute no-client slivers that PR #499 committed.
    mavops = SimpleNamespace(id=7, name='MAVOPS')
    day = [blk(1, client=mavops, billable=True, category='General Client Work'),
           blk(6, client=mavops, billable=False, category='Internal')]
    day += [blk(1, title=f'tab-{i}') for i in range(78)]

    cs = cards(day)
    unassigned = card_named(cs, 'Unassigned')

    check("the no-client card exists at all",
          unassigned is not None)
    check("...carries the 78m",
          unassigned is not None
          and round(unassigned['total_hours'] * 60) == 78)
    check("...and now has rows to show for it (the bug: categories was [])",
          bool(unassigned and unassigned['categories']))
    check("...whose minutes reconcile with the card total",
          unassigned is not None
          and round(sum(c['hours'] for c in unassigned['categories']) * 60) == 78)
    check("...booked as non-billable, not billable",
          unassigned is not None
          and unassigned['non_billable_hours'] == unassigned['total_hours']
          and unassigned['billable_hours'] == 0.0)

    # The lane builder drops any client it can build no rows for. That is
    # correct for a client whose blocks were all pulled into Needs-you, and it
    # is what silently ate this one. Rows are what keeps it on screen.
    check("a lane builder that drops row-less clients now keeps this one",
          bool(unassigned and unassigned['categories']
               and any(c['block_count'] > 0 for c in unassigned['categories'])))

    # --- the arithmetic must not move ---------------------------------------
    totals = _aggregate(day, 'employee')['totals']
    check("the header total is unchanged (85m = 1h25m)",
          round(totals['total_hours'] * 60) == 85)
    check("...and immaterial time is still OUT of utilization "
          "(_aggregate's fold still stands)",
          round(totals['immaterial_hours'] * 60) == 78)
    check("cards and header still reconcile",
          round(sum(c['total_hours'] for c in cs) * 60)
          == round(totals['total_hours'] * 60))

    # --- what it must not disturb -------------------------------------------
    real_client = card_named(cs, 'MAVOPS')
    check("the real client's split is untouched (1m billable, 6m non-bill)",
          real_client is not None
          and round(real_client['billable_hours'] * 60) == 1
          and round(real_client['non_billable_hours'] * 60) == 6)

    idle = cards([blk(1, category='Idle'), blk(1, category='Uncategorized')])
    check("idle / uncategorized noise is still dropped, not promoted to rows",
          not idle)

print(f"\n  {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
