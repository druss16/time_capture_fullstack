"""
Regression tests for the bucketing in tracker.services.mail_coverage.

What this guards: the 'gap' bucket is the number someone will quote in a
customer conversation about widening mailbox scope. Every way of landing in it
by accident inflates an argument for reading more of people's email, so each
boundary is pinned here.

The three that matter most:

  * A block that happened BEFORE the user connected a mailbox is 'no_mailbox',
    never 'gap'. Mail could not have fired; folder scope had nothing to do with
    it. Miss this and a firm that connected mail last week looks like it has a
    catastrophic evidence gap across the whole window.
  * A block with no recorded signals is 'unmeasured', never 'gap'. Absence of
    evidence about the classifier is not evidence the classifier failed.
  * A block carrying a client on strong non-mail evidence is 'other_evidence'.
    Mail would have been redundant there, so it is not a reason to read more.

Run inside the app container:
    python manage.py shell -c "import tracker.mail_coverage_test"

Exits non-zero if any assertion fails.
"""
import os
import sys
from datetime import datetime, timedelta
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
    from tracker.services import mail_coverage as mc
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("mail coverage:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


T0 = datetime(2026, 9, 10, 10, 0)
# user 7 connected a mailbox on Sept 1; user 9 has never connected one.
CONNECTED = {7: datetime(2026, 9, 1)}


def blk(sigs, client_id=None, user_id=7, start=T0, minutes=30, span=30):
    return SimpleNamespace(
        proposed_signals=sigs,
        client_id=client_id,
        user_id=user_id,
        start=start,
        end=start + timedelta(minutes=span),
        minutes=minutes,
    )


def sig(t):
    return {'type': t, 'strength': 0.7}


if _ok:
    print("mail coverage:")

    # --- covered ------------------------------------------------------------
    check("a mail signal wins regardless of what else ran",
          mc._bucket_for(blk([sig('mail'), sig('agent_current_client')],
                             client_id=5), CONNECTED) == mc.MAIL_USED)
    check("client on strong non-mail evidence -> other_evidence",
          mc._bucket_for(blk([sig('file_path_structure')], client_id=5),
                         CONNECTED) == mc.OTHER_EVIDENCE)

    # --- not the gap's fault ------------------------------------------------
    check("no mailbox ever connected -> no_mailbox, not gap",
          mc._bucket_for(blk([sig('agent_current_client')], client_id=5, user_id=9),
                         CONNECTED) == mc.NO_MAILBOX)
    check("block predates the mailbox connect -> no_mailbox, not gap",
          mc._bucket_for(blk([sig('agent_current_client')], client_id=5,
                             start=datetime(2026, 8, 20)),
                         CONNECTED) == mc.NO_MAILBOX)
    check("no recorded signals -> unmeasured, not gap",
          mc._bucket_for(blk([], client_id=5), CONNECTED) == mc.UNMEASURED)
    check("signal entries that aren't dicts -> unmeasured, no crash",
          mc._bucket_for(blk([None, 'garbage'], client_id=5),
                         CONNECTED) == mc.UNMEASURED)

    # --- the ceiling --------------------------------------------------------
    check("only agent stickiness -> gap",
          mc._bucket_for(blk([sig('agent_current_client')], client_id=5),
                         CONNECTED) == mc.GAP)
    check("only prior_block + agent_inference -> gap",
          mc._bucket_for(blk([sig('prior_block'), sig('agent_inference')], client_id=5),
                         CONNECTED) == mc.GAP)
    check("strong evidence but no client attached -> gap",
          mc._bucket_for(blk([sig('file_path_structure')], client_id=None),
                         CONNECTED) == mc.GAP)

    # --- duration ------------------------------------------------------------
    check("null minutes falls back to end - start",
          mc._block_minutes(blk([], minutes=None, span=30)) == 30.0)
    check("no minutes and no span -> 0.0, never negative",
          mc._block_minutes(SimpleNamespace(minutes=None, start=None, end=None)) == 0.0)

    # --- the prefilter must stay a superset of the real predicate -------------
    check("weak signal set is exactly the three inheritance signals",
          mc.WEAK_SIGNAL_TYPES == frozenset(
              {'agent_current_client', 'agent_inference', 'prior_block'}))

print()
print(f"mail coverage: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
