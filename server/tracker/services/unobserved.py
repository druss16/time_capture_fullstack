# tracker/services/unobserved.py
"""
Unobserved time — stop a frozen agent from billing its own sleep.

BACKGROUND
==========
A live agent emits a heartbeat event every HEARTBEAT_INTERVAL_S (60s), so every
event produced by a loop that is actually watching is ~60s long. When the loop
stops iterating — machine sleep, thread freeze, a blocked syscall — nothing is
observed and the open dwell is simply left open. `mouse_idle_seconds()` is polled
inside that same loop, so idle detection cannot fire either. Whenever the loop
finally comes back, the dwell is closed over the entire gap and the agent's
chunker slices it into MAX_EVENT_DURATION_S (300s) pieces, all shipped as active
time.

So an event of ~300s is not evidence of work. It is the signature of a stretch
the agent did not watch.

TL Wall, 2026-09-16: one dwell opened at 20:01 local on QuickBooks and was closed
at 08:51 the next morning by a window change. 154 chunks, 12h50m, of which 8h50m
landed as committed billable time on Syracuse Firefighters Assoc Local 280 —
because QuickBooks happened to be the foreground window when she went home. A
30-day scan found four such stretches on that machine, 58.8h wall clock, 20.05h
committed billable, $1,493.75.

THE RULE
========
Credit an unobserved stretch for at most GRACE_SECONDS — what idle detection
would have credited had it been able to run — and drop the remainder. Past that
point the agent has no evidence anyone was at the keyboard.

Events beyond the grace are still stored: they are the only record that an agent
froze, and `unobserved_events()` reads them back for fleet health. They are
marked in `ctx` and excluded from block minutes, and compaction refuses to build
blocks out of them.

windows_agent/main.py enforces the same rule at the emit site (UNOBSERVED_GAP_S)
so the events are never created in the first place. This module is what protects
the agents that have not taken that build yet.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

# windows_agent MAX_EVENT_DURATION_S. The agent never emits a longer event, so
# an event at (or slightly over) this length is a chunk of a backfilled gap
# rather than an observed interval. Small tolerance for clock jitter.
CHUNK_SECONDS = 300
CHUNK_TOLERANCE = 2.0

# windows_agent MOUSE_IDLE_PAUSE_S — how long a user may sit still before the
# agent stops counting. Same number here, so a gap the loop failed to watch is
# credited exactly as much as a gap it watched and called idle.
GRACE_SECONDS = 600

# Two chunks fill the grace window, so a third consecutive chunk is already past
# it. Four rows of look-back is one more than needed to find the last observed
# event behind any creditable chunk.
LOOKBACK_ROWS = 4

# Abutment tolerance when deciding whether two events belong to the same
# unobserved stretch. Chunks are written cursor-to-cursor and abut exactly.
ABUT_TOLERANCE = timedelta(seconds=2)


# The agent chunks its IDLE dwells too: once the loop enters IDLE_SIG it stops
# heartbeating and emits the whole idle span on exit, sliced the same way. That
# is a correct and deliberate record of time the user was away — already
# non-billable — not a stretch the agent failed to watch. Meeting markers are
# synthetic one-second events for the same reason. Neither is ever unobserved.
IDLE_APPS = {"idle"}
IDLE_BUNDLES = {"__idle__"}
MEETING_APPS = {"meeting", "meeting-end"}


def is_watchable(app_name, bundle_id) -> bool:
    """False for the agent's own synthetic signatures (idle, meeting markers)."""
    app = (app_name or "").strip().lower()
    bundle = (bundle_id or "").strip().lower()
    if app in IDLE_APPS or app in MEETING_APPS:
        return False
    if bundle in IDLE_BUNDLES or bundle.startswith("meeting:"):
        return False
    return True


def is_chunk(start_ts, end_ts) -> bool:
    """True if this interval has the shape of a backfilled chunk, not a heartbeat."""
    if not start_ts or not end_ts:
        return False
    return (end_ts - start_ts).total_seconds() >= CHUNK_SECONDS - CHUNK_TOLERANCE


def is_gap_chunk(app_name, bundle_id, start_ts, end_ts) -> bool:
    """A chunk covering real foreground time the loop did not watch."""
    return is_watchable(app_name, bundle_id) and is_chunk(start_ts, end_ts)


def within_grace(prior_seconds: float, span_seconds: float) -> bool:
    """Does an unobserved stretch of `prior` plus `span` still fit the grace?"""
    return prior_seconds + span_seconds <= GRACE_SECONDS


def is_unobserved(event) -> bool:
    """True if this stored event was marked past the grace window at ingest."""
    ctx = getattr(event, "ctx", None) or {}
    return bool(ctx.get("unobserved"))


def mark_unobserved(ctx: Optional[dict], gap_seconds: float) -> dict:
    """Stamp an event's ctx as unobserved. Returns the ctx for chaining."""
    ctx = dict(ctx or {})
    ctx["unobserved"] = {
        "reason": "agent_loop_gap",
        "gap_seconds": round(gap_seconds, 1),
        "grace_seconds": GRACE_SECONDS,
    }
    return ctx


def gap_before(user, start_ts, hostname: Optional[str] = None) -> Optional[float]:
    """
    How long the agent had already been failing to observe when an event
    starting at `start_ts` began — measured back to the end of the last event
    that looks like a real heartbeat.

    Returns None when the immediately preceding event is itself an observed
    heartbeat (no unobserved stretch in progress).

    Walks back at most LOOKBACK_ROWS rows: past that the stretch is longer than
    the grace window no matter what came before, so the exact figure stops
    mattering and the cap is reported as the look-back depth.
    """
    from tracker.models import RawEvent

    qs = (
        RawEvent.objects.filter(user=user, end_ts__lte=start_ts + ABUT_TOLERANCE)
        .order_by("-end_ts")
    )
    if hostname:
        qs = qs.filter(hostname=hostname)

    cursor = start_ts
    walked = 0
    for prev in qs.only("start_ts", "end_ts", "app_name", "bundle_id")[:LOOKBACK_ROWS]:
        # A break in the chain ends the stretch here, whatever came before.
        if prev.end_ts < cursor - ABUT_TOLERANCE:
            break
        if not is_gap_chunk(prev.app_name, prev.bundle_id, prev.start_ts, prev.end_ts):
            # The last thing the agent actually watched — an idle dwell counts,
            # because entering idle means the loop was alive and saw it.
            return (start_ts - prev.end_ts).total_seconds()
        cursor = prev.start_ts
        walked += 1

    if walked == 0:
        # Nothing abutting behind this event — the stretch starts here.
        return 0.0

    # Ran out of look-back with chunks all the way: at least this long.
    return (start_ts - cursor).total_seconds()


def creditable(user, start_ts, end_ts, app_name=None, bundle_id=None,
               hostname: Optional[str] = None) -> bool:
    """
    Should this incoming event count as worked time?

    Observed heartbeats and the agent's own idle/meeting signatures always
    count. A foreground chunk counts only while the unobserved stretch it
    belongs to — including its own span — still fits inside the grace window.
    """
    if not is_gap_chunk(app_name, bundle_id, start_ts, end_ts):
        return True

    prior = gap_before(user, start_ts, hostname=hostname)
    if prior is None:
        prior = 0.0
    return within_grace(prior, (end_ts - start_ts).total_seconds())


def unobserved_events(user=None, since=None, hostname: Optional[str] = None):
    """Stored events that were dropped past the grace window — fleet health read."""
    from tracker.models import RawEvent

    qs = RawEvent.objects.filter(ctx__unobserved__isnull=False)
    if user:
        qs = qs.filter(user=user)
    if since:
        qs = qs.filter(start_ts__gte=since)
    if hostname:
        qs = qs.filter(hostname=hostname)
    return qs.order_by("start_ts")
