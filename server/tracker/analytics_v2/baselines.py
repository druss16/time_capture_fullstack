"""Firm-relative baselines — the WHOOP model for firm metrics.

Instead of judging utilization against a generic textbook target, we learn the
firm's OWN normal from its recent history and flag deviations from that. A 56%
that's dead-center for how a firm operates should read as healthy, not alarming.

`weekly_mix_series` builds the trailing weekly billable-mix series (same
definition as the live metric: idle/internal excluded, billable-effort counted).
`band` turns a series into the firm's normal range.
"""
from __future__ import annotations

import statistics as _st
from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import TruncWeek


def weekly_mix_series(org, scope, end, weeks: int = 13) -> list[tuple]:
    """Return [(week_start_date, mix_pct), …] over the trailing `weeks`, scoped
    the same way the utilization metric is. Uses the shared working_qs /
    billable_q so it stays consistent with the headline number."""
    from tracker.models import Block
    from .blocks import working_qs, billable_q
    from .cost_rates import non_utilization_user_ids

    start = end - timedelta(weeks=weeks)
    qs = Block.objects.filter(org=org, day__gte=start, day__lte=end)
    if scope.type == "client":
        qs = qs.filter(client_id__in=scope.ids)
    elif scope.type == "staff":
        qs = qs.filter(user_id__in=scope.ids)
    elif scope.type == "service":
        qs = qs.filter(task_type_id__in=scope.ids)
    if scope.type in ("firm", "composite"):
        ex = non_utilization_user_ids(org)
        if ex:
            qs = qs.exclude(user_id__in=ex)
    qs = working_qs(qs, org)

    tot = {r["w"]: (r["t"] or 0) for r in
           qs.annotate(w=TruncWeek("day")).values("w").annotate(t=Sum("minutes"))}
    bil = {r["w"]: (r["b"] or 0) for r in
           qs.filter(billable_q(org)).annotate(w=TruncWeek("day")).values("w").annotate(b=Sum("minutes"))}
    return [(w, round(bil.get(w, 0) / tot[w] * 100, 1)) for w in sorted(tot) if tot[w]]


def band(values: list[float]) -> dict | None:
    """Firm normal range from a value series. Drops the last (current, partial)
    week. Returns None until there's enough history to be meaningful."""
    complete = values[:-1]
    if len(complete) < 4:
        return None
    s = sorted(complete)
    return {
        "baseline": round(_st.mean(complete), 1),
        "p25": round(s[len(s) // 4], 1),
        "p75": round(s[(3 * len(s)) // 4], 1),
        "min": round(s[0], 1),
        "max": round(s[-1], 1),
        "n": len(complete),
    }
