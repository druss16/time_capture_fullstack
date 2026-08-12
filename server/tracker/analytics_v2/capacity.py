"""Available-capacity resolver — the utilization denominator.

`capacity_hours_map(org, user_ids, start, end)` returns each user's available
working hours over the window. When the org has a WorkCalendar it computes
scheduled hours net of non-working weekdays, firm holidays, the summer-Fridays
rule, and each person's time off. With no calendar it falls back to the legacy
`per-tier weekly hours × weeks` behaviour, so nothing changes until a firm
configures a calendar.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def capacity_hours_map(org, user_ids, start, end) -> dict[int, float]:
    from tracker.models import WorkCalendar, TimeOff

    user_ids = list(user_ids)
    if not user_ids:
        return {}

    cal = WorkCalendar.objects.filter(org=org).first()
    if cal is None:
        return _fallback_map(org, user_ids, start, end)

    hpd = _to_float(cal.hours_per_day) or 8.0

    working_days = _working_days(cal, start, end)
    gross = len(working_days) * hpd

    # Pro-rated PTO allowance (estimate) for people with no explicit TimeOff:
    # avg_pto_days × hours/day × (window working days ÷ this year's working days).
    avg_pto = _to_float(cal.avg_pto_days_per_year)
    pto_allowance = 0.0
    if avg_pto > 0 and working_days:
        from datetime import date as _date
        annual = len(_working_days(cal, _date(start.year, 1, 1), _date(start.year, 12, 31)))
        if annual > 0:
            pto_allowance = avg_pto * hpd * (len(working_days) / annual)

    to_by_user: dict[int, list] = defaultdict(list)
    for t in TimeOff.objects.filter(
        org=org, user_id__in=user_ids, start_date__lte=end, end_date__gte=start,
    ).only("user_id", "start_date", "end_date"):
        to_by_user[t.user_id].append((t.start_date, t.end_date))

    out: dict[int, float] = {}
    for uid in user_ids:
        if uid in to_by_user:
            # Explicit time off wins — count actual days in the window.
            off_hours = 0.0
            for ts, te in to_by_user[uid]:
                dd, last = max(ts, start), min(te, end)
                while dd <= last:
                    if dd in working_days:
                        off_hours += hpd
                    dd += timedelta(days=1)
        else:
            off_hours = pto_allowance
        out[uid] = max(0.0, gross - off_hours)
    return out


def _working_days(cal, start, end) -> set:
    """Set of working dates in [start, end]: schedule weekdays minus firm
    holidays minus the summer-Fridays rule."""
    working = set(cal.working_weekdays or [0, 1, 2, 3, 4])
    holidays = set(cal.holidays or [])
    s_lo, s_hi = cal.summer_start_month, cal.summer_end_month
    days: set = set()
    d = start
    while d <= end:
        wd = d.weekday()
        off = (wd not in working) or (d.isoformat() in holidays)
        if cal.summer_fridays_off and wd == 4 and s_lo <= d.month <= s_hi:
            off = True
        if not off:
            days.add(d)
        d += timedelta(days=1)
    return days


def _fallback_map(org, user_ids, start, end) -> dict[int, float]:
    """Legacy capacity: per-tier weekly hours (or org default) × weeks."""
    from .cost_rates import capacity_map

    caps = capacity_map(org)
    default_cap = _to_float(getattr(org, "capacity_hours_per_week", 40)) or 40.0
    days = (end - start).days + 1
    weeks = (days / 7.0) if days > 0 else 0.0
    return {uid: caps.get(uid, default_cap) * weeks for uid in user_ids}
