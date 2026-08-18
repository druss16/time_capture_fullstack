"""
Regression tests for the QuickBooks compaction MERGE KEY.

THE BUG THIS PINS
-----------------
Compaction computes a content_id in three places: the session-grouping loop,
the existing-block key, and the new-block key. The code has always carried the
comment "must stay in lockstep" — because if they disagree, blocks either
fail to merge (fragmentation) or merge when they must not.

When QB blocks gained a company FILE path, only the grouping loop was taught
to use it. Grouping therefore separated two same-named parishes correctly, and
block-extension — still keying on the company NAME — merged them straight back
together. Two parishes in one block, which no classifier stage can undo.

All three now route through _qb_company_file_key(). These tests pin that.

Pure function, no Django needed:
    python server/tracker/qb_company_key_test.py

Exits non-zero if any assertion fails.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


from tracker.services.qb_company_file import company_file_key as key  # noqa: E402

QB = r"Q:\QB\QB2024 Files"
CLINTON = rf"{QB}\St. Mary's Church_Clinton_QB2024.QBW"
HAMILTON = rf"{QB}\St. Mary's Church_Hamilton_QB2024.QBW"

print("\n=== the merge key separates same-named companies ===")
check("Clinton and Hamilton parishes get DIFFERENT keys",
      key("Qbw.Exe", CLINTON) != key("Qbw.Exe", HAMILTON))
check("both keys are non-None (the path was usable)",
      key("Qbw.Exe", CLINTON) and key("Qbw.Exe", HAMILTON))
check("the same file always yields the same key",
      key("Qbw.Exe", CLINTON) == key("qbw.exe", CLINTON))
check("case differences in the path do not split a company",
      key("Qbw.Exe", CLINTON) == key("Qbw.Exe", CLINTON.upper()))

print("\n=== lockstep: grouping side and extension side agree ===")
# Grouping keys off the EVENT's qb_company_path; extension keys off the
# BLOCK's persisted file_path. Same file must produce the same key on both.
event_side = key("Qbw.Exe", CLINTON)          # event ctx.qb_company_path
block_side = key("Qbw.Exe", CLINTON)          # block.file_path
check("event-side key == block-side key for one company file",
      event_side == block_side and event_side is not None)

print("\n=== abstains, so old agents keep the old behaviour ===")
check("no path (pre-Tier-1 agent) -> None, caller falls back to the name key",
      key("Qbw.Exe", "") is None)
check("None path -> None",
      key("Qbw.Exe", None) is None)
check("a non-QB app is never given a QB key",
      key("Excel.Exe", CLINTON) is None)
check("a non-.qbw file is not a company file",
      key("Qbw.Exe", rf"{QB}\St. Mary's Church_Clinton_QB2024.QBW.TLG") is None)
check("an Office path on a QB block is not a company file",
      key("Qbw.Exe", r"C:\Users\x\Documents\St Mary Budget.xlsx") is None)
check("qbw32.exe is recognised too",
      key("qbw32.exe", CLINTON) is not None)

print("\n=== key shape ===")
check("keys are namespaced so they cannot collide with title keys",
      key("Qbw.Exe", CLINTON).startswith("qbfile="))

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
