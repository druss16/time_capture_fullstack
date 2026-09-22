"""
When a Clio anchor knows the matter, may it rewrite the client?

A clio_anchor hit is tier 0 — "knowledge, not inference". It reads the matter
id the browser extension took straight off the Clio tab, so it knows the
matter, and a matter has exactly one client. Previously only Block.project was
written, which left blocks internally contradictory: matter "00001-Ridgeline
Holdings LLC" sitting on client "MAVOPS", because the classifier had guessed
the client from a window title while the anchor knew the answer outright.

The rule below is the whole safety argument for letting it correct the client,
so it is named, separate, and tested rather than inline in a loop:

    a machine guess may be corrected; a person's decision may not.

DATABASE-FREE — these run via `manage.py shell`, which in this deployment is
wired to the live production database.

    python manage.py shell -c "import tracker.matter_anchor_client_test"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def check(label, cond, extra=''):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label} {extra}")


try:
    from tracker.services.matter_attribution import (
        HUMAN_SET_CLIENT,
        may_correct_client,
    )
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print(f"  SKIP  app deps unavailable ({type(e).__name__})")

if _ok:
    print("a person's decision is never overruled:")
    check("manual entry is protected", not may_correct_client('manual'))
    check("a user's correction is protected", not may_correct_client('correction'))
    check("...and those are exactly the protected set",
          set(HUMAN_SET_CLIENT) == {'manual', 'correction'}, HUMAN_SET_CLIENT)

    print("\na machine guess may be corrected:")
    check("the classifier's guess", may_correct_client('ai'))
    check("a learned pattern", may_correct_client('pattern'))
    check("an import", may_correct_client('import'))
    check("the mismatch agent", may_correct_client('mismatch_agent'))

    print("\nunset means never decided, so correctable:")
    check("None", may_correct_client(None))
    check("empty string", may_correct_client(''))

    print("\nan unknown source defaults to CORRECTABLE, not protected:")
    # A new automated source must not become immune to correction merely by
    # being new. Protection is opt-in and explicit; that is the safer default
    # here precisely because the alternative fails silently — a block would
    # quietly keep a wrong client forever with nothing to indicate why.
    check("a future value", may_correct_client('some_future_source'))
    check("a stray value", may_correct_client('xyz'))

    print("\ncase is significant (these are stored choice keys, not free text):")
    check("'Manual' is NOT treated as manual", may_correct_client('Manual'))

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
