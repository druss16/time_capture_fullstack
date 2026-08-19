"""
Tests for interpreting the agent's raw QuickBooks report (ctx.qb_report).

WHY THIS EXISTS
---------------
Four agent-side mechanisms shipped and four failed. The last one failed for an
avoidable reason: it filtered candidate files by the company name in the title,
and most QuickBooks samples are modals ("Make General Journal Entries") that
carry no company — the very problem the module was written to solve. It threw
away every candidate before comparing anything and reported zero.

So the agent now reports observations and the SERVER decides, because the
server has what the agent lacks: every event in the block. One main-window
sample anywhere in the block supplies the company name that the modals cannot.

Pure functions, no Django:
    python server/tracker/qb_report_test.py
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


from tracker.services.qb_company_file import (  # noqa: E402
    pick_recent_company_file as pick, extract_qb_company as company,
)

CLINTON = "st. mary's church_clinton_qb2024.qbw"
BVILLE = "st mary's church_baldwinsville.qbw"
CADD = "cadd systems_qb2024.qbw"

print("\n=== company name out of a QuickBooks title ===")
check("main window title",
      company("St. Mary's Church  - QuickBooks Accountant Desktop Plus 2024")
      == "St. Mary's Church")
check("(Primary) marker is stripped — it names the window, not the client",
      company("St. Mary's Church (Primary)  - QuickBooks Accountant Desktop Plus 2024")
      == "St. Mary's Church")
check("screen bracket is stripped",
      company("St. Mary's Church  - QuickBooks Accountant Desktop Plus 2024 - [Make Deposits]")
      == "St. Mary's Church")
check("a modal carries no company", company("Make General Journal Entries") is None)
check("bare product chrome carries no company",
      company("QuickBooks Accountant Desktop Plus 2024") is None)

print("\n=== THE FIELD CASE: modal samples, one main-window sample ===")
# Every event reports the same share listing; only one event's title had a company.
reports = [{'recent': [{'f': CLINTON, 'age': 12}, {'f': CADD, 'age': 90_000},
                       {'f': BVILLE, 'age': 90_001}]}] * 4
picked, via = pick(reports, {"St. Mary's Church"})
check("resolves to the Clinton file", picked == CLINTON)
check("...by name match, not by raw freshness", via == 'named')

print("\n=== a colleague's fresher file cannot steal the block ===")
# Someone else is hammering Cadd Systems; this block is St. Mary's work.
reports2 = [{'recent': [{'f': CADD, 'age': 3}, {'f': CLINTON, 'age': 200},
                        {'f': BVILLE, 'age': 90_000}]}]
picked2, via2 = pick(reports2, {"St. Mary's Church"})
check("the freshest file overall is IGNORED — wrong company", picked2 != CADD)
check("the block's own company wins", picked2 == CLINTON)

print("\n=== two same-family files, name matches both -> freshest wins ===")
reports3 = [{'recent': [{'f': BVILLE, 'age': 20}, {'f': CLINTON, 'age': 4_000}]}]
picked3, _ = pick(reports3, {"St. Mary's Church"})
check("picks Baldwinsville, the one actually being written", picked3 == BVILLE)

print("\n=== no company name anywhere -> demand a decisive lead ===")
lead = [{'recent': [{'f': CLINTON, 'age': 5}, {'f': CADD, 'age': 9_000}]}]
picked4, via4 = pick(lead, set())
check("a clear leader is accepted", picked4 == CLINTON and via4 == 'lead')
close = [{'recent': [{'f': CLINTON, 'age': 5}, {'f': CADD, 'age': 30}]}]
picked5, via5 = pick(close, set())
check("two files both warm -> ABSTAIN (could be a colleague's work)",
      picked5 is None and via5 == 'ambiguous')

print("\n=== an exact read always wins ===")
ex = [{'exact': [r"Q:\QB\QB2024 Files\St. Mary's Church_Clinton_QB2024.QBW"],
       'recent': [{'f': CADD, 'age': 1}]}]
picked6, via6 = pick(ex, set())
check("handle/command-line read beats every heuristic",
      picked6.endswith("St. Mary's Church_Clinton_QB2024.QBW") and via6 == 'exact')

print("\n=== safety ===")
check("no reports -> abstain", pick([], {"St. Mary's Church"})[0] is None)
check("stale-only files -> abstain",
      pick([{'recent': [{'f': CLINTON, 'age': 999_999}]}], {"St. Mary's Church"})[0] is None)
check("company matching nothing on the share -> abstain",
      pick([{'recent': [{'f': CADD, 'age': 10}]}], {"St. Mary's Church"})[0] is None)
check("malformed report -> abstain, does not raise",
      pick([{'recent': [{'nope': 1}]}, None, 'junk'], set())[0] is None)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
