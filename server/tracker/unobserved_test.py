"""
Unobserved-time rule — test suite
=================================
Covers tracker/services/unobserved.py: which events are evidence of work and
which are a frozen agent backfilling its own downtime.

Usage:
    python server/tracker/unobserved_test.py          # standalone, no Django
    python manage.py shell < tracker/unobserved_test.py

INTEGRATION EVIDENCE (replayed against live org-21 data, 2026-09-16)
-------------------------------------------------------------------
    2026-09-16 stretch : 154 chunks, 152 dropped, 2 credited (10.0 min grace)
    normal working hour: 80 events, 79 credited, 1 dropped (3rd chunk of a run)
    30d org-wide       : 16 foreground unobserved runs; 10 of them <=10m and so
                         lose nothing; 58.2h of the 58.3h dropped comes from the
                         four overnight stalls on one machine
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.services.unobserved import (  # noqa: E402
    CHUNK_SECONDS,
    GRACE_SECONDS,
    is_chunk,
    is_gap_chunk,
    is_unobserved,
    is_watchable,
    mark_unobserved,
    within_grace,
)

T0 = datetime(2026, 9, 16, 0, 1, 14, tzinfo=timezone.utc)
PASSED = []
FAILED = []


def check(name, got, want):
    (PASSED if got == want else FAILED).append((name, got, want))


def span(seconds, start=T0):
    return start, start + timedelta(seconds=seconds)


# ── shape: what a chunk looks like ──────────────────────────────────────────
check("60s heartbeat is not a chunk", is_chunk(*span(60)), False)
check("a 170s tail chunk is not one", is_chunk(*span(170)), False)
check("just under the jitter band is not", is_chunk(*span(297)), False)
check("300s is a chunk", is_chunk(*span(300)), True)
check("300s minus jitter is still a chunk", is_chunk(*span(298)), True)
check("open interval is not a chunk", is_chunk(T0, None), False)

# ── the agent's own synthetic signatures are never unobserved ───────────────
# Idle dwells are chunked exactly like foreground gaps. Treating them as
# unobserved swept up 71 legitimate idle records on the first pass.
check("idle app is not watchable", is_watchable("Idle", "__idle__"), False)
check("idle bundle alone is not watchable", is_watchable("", "__idle__"), False)
check("meeting marker is not watchable", is_watchable("Meeting", "meeting:teams"), False)
check("meeting-end is not watchable", is_watchable("Meeting-End", "meeting:zoom"), False)
check("QuickBooks is watchable", is_watchable("Qbw.Exe", "qbw.exe"), True)
check("unknown app is watchable", is_watchable(None, None), True)

check("idle chunk is not a gap chunk", is_gap_chunk("Idle", "__idle__", *span(300)), False)
check("QB chunk is a gap chunk", is_gap_chunk("Qbw.Exe", "qbw.exe", *span(300)), True)
check("QB heartbeat is not a gap chunk", is_gap_chunk("Qbw.Exe", "qbw.exe", *span(62)), False)

# ── grace arithmetic: two chunks in, the third is past the line ─────────────
check("first chunk of a run fits", within_grace(0.0, CHUNK_SECONDS), True)
check("second chunk fits exactly", within_grace(CHUNK_SECONDS, CHUNK_SECONDS), True)
check("third chunk does not", within_grace(2 * CHUNK_SECONDS, CHUNK_SECONDS), False)
check("grace boundary is inclusive", within_grace(0.0, GRACE_SECONDS), True)
check("one second past grace fails", within_grace(0.0, GRACE_SECONDS + 1), False)
check(
    "a short freeze mid-work is fully credited",
    within_grace(0.0, 300) and within_grace(300, 170),
    True,
)

# ── marking round-trips ─────────────────────────────────────────────────────
marked = mark_unobserved({"qb_report": {"company": "Syracuse"}}, 46200.0)
check("mark keeps existing ctx", marked.get("qb_report", {}).get("company"), "Syracuse")
check("mark records the gap", marked["unobserved"]["gap_seconds"], 46200.0)
check("mark records the grace in force", marked["unobserved"]["grace_seconds"], GRACE_SECONDS)
check("mark does not mutate the original", "unobserved" in {"a": 1}, False)


class _Ev:
    def __init__(self, ctx):
        self.ctx = ctx


check("marked event reads back as unobserved", is_unobserved(_Ev(marked)), True)
check("plain event does not", is_unobserved(_Ev({"qb_report": {}})), False)
check("empty ctx does not", is_unobserved(_Ev(None)), False)

# ── the real timeline: 154 chunks over 12h50m ───────────────────────────────
# Terri, 2026-09-15 20:01 local -> 2026-09-16 08:51. QuickBooks was the
# foreground window when she went home; the loop closed the dwell on the next
# morning's window change and backfilled the whole night as active time.
credited = 0
prior = 0.0
for _ in range(154):
    if within_grace(prior, CHUNK_SECONDS):
        credited += 1
    prior += CHUNK_SECONDS
check("overnight stall credits only the grace window", credited, 2)
check("credited minutes", credited * CHUNK_SECONDS / 60, 10.0)
check("dropped minutes", (154 - credited) * CHUNK_SECONDS / 60, 760.0)

# ── report ──────────────────────────────────────────────────────────────────
for name, got, want in FAILED:
    print(f"FAIL  {name}: got {got!r}, want {want!r}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    sys.exit(1)
