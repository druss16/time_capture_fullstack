"""
tracker/services/capture.py

How much of the work that happened did the agent actually see.

This is NOT utilization, and the difference is the denominator. Utilization asks
what fraction of the capacity a firm PAYS for turned into billable work, so idle
capacity belongs in the denominator — that gap is the entire signal, and
`analytics_v2.capacity.capacity_hours_map` is right for it. Capture asks
something narrower: of the time somebody actually worked, how much reached us.
Scheduled capacity is the wrong denominator for that question, and at org 21 it
was wrong in ways that accused people:

  · eileen worked 8 days in August at about 5.9h each. Measured against 17
    scheduled days she read 33% captured, as though her agent were broken. On
    the days she was actually here it is 65%.
  · terri has activity on 24 days against 17 scheduled — weekends and a few
    minutes here and there. Counting every one of those as a full working day
    drags her down; counting none of them throws away real work.
  · kbarnes is part-time admin, already excluded from utilization by her tier,
    and was still being measured as though she owed the firm eight hours a day.

So: a person's denominator is the days they were genuinely working, times the
firm's own standard day. A day they did not work does not count against them,
and a day with four minutes on it is not a working day.

WHAT 100% WOULD MEAN
--------------------
Not "every hour of the day". `working_qs` already drops idle, lock, non-billable
and internal-client time, so the ceiling is a full day of client-facing work with
no lunch, no admin and no interruption. Nobody hits it: org 21's best-captured
person in August was emily at 76%, and the firm sits at 57%. Read the number as
"how much of a standard working day reached us", and every figure built on it as
a floor.
"""
from __future__ import annotations

from django.db.models import Sum

# A day with less than this on it was not a working day — a Saturday glance at
# the inbox, a laptop opened to check one thing. Counting it as a full day of
# expected work punishes people for looking.
MIN_PRESENT_HOURS = 1.0

# Fallback when the firm has no work calendar.
DEFAULT_HOURS_PER_DAY = 8.0


def standard_day_hours(org) -> float:
    """The firm's own idea of a working day."""
    from tracker.models import WorkCalendar

    cal = WorkCalendar.objects.filter(org=org).first()
    if cal is not None:
        try:
            hpd = float(cal.hours_per_day or 0)
        except (TypeError, ValueError):
            hpd = 0.0
        if hpd > 0:
            return hpd
    try:
        weekly = float(getattr(org, "capacity_hours_per_week", 0) or 0)
    except (TypeError, ValueError):
        weekly = 0.0
    return (weekly / 5.0) if weekly > 0 else DEFAULT_HOURS_PER_DAY


def capture_by_user(org, user_ids, start_d, end_d) -> dict[int, float]:
    """{user_id: 0..1} — captured hours over the days each person actually worked.

    Non-chargeable staff are left out entirely: their tier says the firm does
    not expect chargeable days from them, and including them accuses the one
    person already excluded from every other measure.
    """
    from tracker.analytics_v2.blocks import working_qs
    from tracker.analytics_v2.cost_rates import non_utilization_user_ids
    from tracker.models import Block

    excluded = non_utilization_user_ids(org)
    user_ids = [u for u in user_ids if u and u not in excluded]
    if not user_ids:
        return {}

    hpd = standard_day_hours(org)
    if hpd <= 0:
        return {}

    per_day: dict[int, list[float]] = {}
    rows = (
        working_qs(
            Block.objects.filter(
                org=org, user_id__in=user_ids, day__gte=start_d, day__lte=end_d
            ),
            org,
        )
        .values("user_id", "day")
        .annotate(minutes=Sum("minutes"))
    )
    for r in rows:
        hours = (r["minutes"] or 0) / 60.0
        if hours >= MIN_PRESENT_HOURS:
            per_day.setdefault(r["user_id"], []).append(hours)

    out: dict[int, float] = {}
    for uid, days in per_day.items():
        if days:
            out[uid] = min(1.0, sum(days) / (len(days) * hpd))
    return out


def firm_capture(org, user_ids, start_d, end_d) -> float | None:
    """One number for the firm: captured hours over worked days, pooled.

    Pooled rather than averaged per person, so a colleague who worked two days
    does not weigh as much as one who worked twenty.
    """
    from tracker.analytics_v2.blocks import working_qs
    from tracker.analytics_v2.cost_rates import non_utilization_user_ids
    from tracker.models import Block

    excluded = non_utilization_user_ids(org)
    user_ids = [u for u in user_ids if u and u not in excluded]
    if not user_ids:
        return None

    hpd = standard_day_hours(org)
    if hpd <= 0:
        return None

    tracked = 0.0
    days = 0
    rows = (
        working_qs(
            Block.objects.filter(
                org=org, user_id__in=user_ids, day__gte=start_d, day__lte=end_d
            ),
            org,
        )
        .values("user_id", "day")
        .annotate(minutes=Sum("minutes"))
    )
    for r in rows:
        hours = (r["minutes"] or 0) / 60.0
        if hours >= MIN_PRESENT_HOURS:
            tracked += hours
            days += 1
    if not days:
        return None
    return min(1.0, tracked / (days * hpd))
