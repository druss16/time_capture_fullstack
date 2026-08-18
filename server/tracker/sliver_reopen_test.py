"""
Regression tests for _should_reclassify_on_merge (tracker.services.compaction).

The bug it guards: compaction creates a block ~30 seconds into an activity and
classifies it right then. Finding no client, the sub-2-minute immaterial rule
COMMITS it as No-Client / non-billable so it won't nag. The block then grows —
sometimes to an hour — as more events merge in, and its window_title is rewritten
to the dominant activity, but nothing re-classifies a committed block. A
13-minute Outlook thread titled "RE: From Odett at Christ Our Light" ended up
filed as non-billable overhead, invisible in Daily Review's "Needs you".

The predicate re-opens exactly that case and nothing else. It is deliberately
narrow — it only ever touches blocks parked with NO client, so it can never
churn an attribution or a billing amount.

Run inside the app container:
    python manage.py shell -c "import tracker.sliver_reopen_test"
or standalone where Django is configured:
    python tracker/sliver_reopen_test.py

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


def blk(**kw):
    """A block as it stands BEFORE a merge writes the new minutes/title."""
    d = dict(
        client_id=None,             # parked with nobody
        categorized_by='ai',        # a machine put it there
        classification_state='committed',
        is_categorized=True,
        invoiced=False,
        qb_time_activity_id=None,
        xero_invoice_id=None,
        minutes=1,                  # judged while it was still a sliver
        window_title='Untitled - Message (HTML)',
    )
    d.update(kw)
    return SimpleNamespace(**d)


try:
    from tracker.services.compaction import _should_reclassify_on_merge as reopen
    _ok = True
except Exception as e:  # ModuleNotFoundError / ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("sliver re-open:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    print("sliver re-open:")

    # --- the bug: a sliver verdict outliving the sliver -----------------------
    check("30s no-client sliver grows to 13m -> re-open",
          reopen(blk(minutes=1), 13, 'RE: From Odett at Christ Our Light - Message (HTML)') is True)

    check("title stops being a placeholder -> re-open even while small",
          reopen(blk(minutes=1, window_title='Untitled - Message (HTML)'),
                 1, 'St. John Evangelist Reports JUL26 - Message (HTML)') is True)

    # --- no material change: leave it alone -----------------------------------
    check("still a sliver, same title -> leave alone",
          reopen(blk(minutes=1), 1, 'Untitled - Message (HTML)') is False)

    check("already material when judged, just grows more -> leave alone",
          reopen(blk(minutes=13), 40, 'Untitled - Message (HTML)') is False)

    check("title differs only by surrounding whitespace -> leave alone",
          reopen(blk(minutes=1, window_title='Inbox - Outlook'),
                 1, '  Inbox - Outlook  ') is False)

    # --- never touch an attribution -------------------------------------------
    # A block booked to a client is out of scope in EVERY case: re-running the
    # classifier on it could silently move billable time. Title drift on those is
    # the mismatch lane's job, where a human decides.
    check("has a client -> never re-opened (no billing churn)",
          reopen(blk(client_id=199, minutes=1), 40, 'Somebody Else - QuickBooks') is False)

    # --- never overrule a person ----------------------------------------------
    # "No client" is a legitimate human answer (personal browsing, firm admin,
    # their own timesheet). Re-asking is the nagging this is meant to prevent.
    check("human filed it as No client -> final",
          reopen(blk(categorized_by='manual', minutes=1), 40, 'X') is False)
    check("human corrected it -> final",
          reopen(blk(categorized_by='correction', minutes=1), 40, 'X') is False)

    # --- immutable / not-applicable states ------------------------------------
    check("invoiced time -> never re-opened",
          reopen(blk(invoiced=True, minutes=1), 40, 'X') is False)
    check("synced to QuickBooks -> never re-opened",
          reopen(blk(qb_time_activity_id='42', minutes=1), 40, 'X') is False)
    check("synced to Xero -> never re-opened",
          reopen(blk(xero_invoice_id='inv-1', minutes=1), 40, 'X') is False)
    check("suppressed block -> left suppressed",
          reopen(blk(classification_state='suppressed', minutes=1), 40, 'X') is False)
    check("never judged at all (still captured) -> nothing to re-open",
          reopen(blk(is_categorized=False, classification_state='captured', minutes=1),
                 40, 'X') is False)

print()
print(f"sliver re-open: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
