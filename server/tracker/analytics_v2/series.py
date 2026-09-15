"""
Time series for the Performance Trend chart.

WHY THIS MODULE EXISTS
----------------------
The overview needs one chart the viewer can retune between hours, billable
hours, billable value, labor cost, margin and utilization — six readings of the
same window, switched client-side with no round trip. Computing that by calling
each Metric once per bucket would be correct but costs roughly
(buckets x metrics x queries-per-metric) round trips; at 26 weekly buckets that
is several hundred.

So the series is built from grouped SQL instead — a handful of queries total.
The risk that buys is drift: a chart whose Q3 bars quietly add up to something
other than the Q3 tile above them. Two things hold that shut.

  1. Every rule here is IMPORTED from the same helpers the metrics use —
     `confirmed_qs` for the basis, `billable_q` for the billing rule,
     `working_qs` for the utilization basis, `bill_rate_map` / `cost_rate_map`
     for the rate ladders, `apply_scope` for scope and filters. None of it is
     restated locally.
  2. `tests/test_series_reconciliation.py` asserts the summed series equals the
     metric for the same window. If someone changes one side, that test fails
     rather than the dashboard silently disagreeing with itself.

Flat-fee / retainer revenue is deliberately NOT spread across buckets: it is
recognized pro-rata over a period, so slicing it daily invents a shape the
underlying contract does not have. The trend therefore charts HOURLY billable
value, and says so in its subtitle. The Billable Value KPI tile above it,
which does include retainers, is the complete number.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, Q, Sum
from django.utils import timezone
from django.db.models.functions import Coalesce

from tracker.models import Block

from .types import Scope, TimeRange, to_float

# Bucket the window so a chart never has to render more points than a person
# can read, and never so few that a quarter looks like three dots.
_DAILY_MAX_DAYS = 31        # a month or less reads naturally day by day
_WEEKLY_MAX_DAYS = 240      # up to ~8 months stays weekly; beyond that, monthly


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def choose_grain(time: TimeRange) -> str:
    """'day' | 'week' | 'month', from the length of the window."""
    span = time.days()
    if span <= _DAILY_MAX_DAYS:
        return "day"
    if span <= _WEEKLY_MAX_DAYS:
        return "week"
    return "month"


def quarter_start(d: date) -> date:
    """First day of the calendar quarter containing `d`."""
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _bucket_start(d: date, grain: str) -> date:
    if grain == "day":
        return d
    if grain == "week":
        return d - timedelta(days=d.weekday())   # Monday
    if grain == "quarter":
        return quarter_start(d)
    return d.replace(day=1)


def _next_bucket(d: date, grain: str) -> date:
    if grain == "day":
        return d + timedelta(days=1)
    if grain == "week":
        return d + timedelta(days=7)
    if grain == "quarter":
        return quarter_start(d.replace(day=1) + timedelta(days=100))
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _bucket_label(d: date, grain: str) -> str:
    if grain == "day":
        return d.strftime("%-d %b")
    if grain == "week":
        return f"w/c {d.strftime('%-d %b')}"
    if grain == "quarter":
        return f"Q{(d.month - 1) // 3 + 1} {d.year}"
    return d.strftime("%b %Y")


def bucket_starts(time: TimeRange, grain: str) -> list[date]:
    """Every bucket start covering the window, including empty ones.

    Gaps are filled so a quiet week reads as a dip rather than vanishing and
    letting the line jump straight over it.
    """
    out: list[date] = []
    cur = _bucket_start(time.start, grain)
    while cur <= time.end:
        out.append(cur)
        cur = _next_bucket(cur, grain)
    return out


def _is_partial(bucket: date, time: TimeRange, grain: str, today: date) -> bool:
    """Is this bucket clipped, or still being filled?

    Three ways a bucket under-counts, and all three make it dip:

      clipped at the start  "This quarter" from 1 Jul gets a first WEEKLY
          bucket beginning Monday 29 Jun; two of its days are outside the
          window and were never counted.
      clipped at the end    the last weekly bucket runs to the coming Sunday,
          of which only the days so far exist.
      still running         the bucket containing today, at any grain. Today is
          not over, so a daily series ends on a half-day for the same reason a
          weekly one ends on a half-week.

    Plotted beside whole buckets each reads as a slump the firm never had.
    """
    end = _next_bucket(bucket, grain) - timedelta(days=1)
    return bucket < time.start or end > time.end or end >= today


def whole_buckets(buckets: list[date], time: TimeRange, grain: str,
                  keep_at_least: int = 2, today: date | None = None) -> list[date]:
    """`buckets` with the clipped ones at either end removed.

    Only the ENDS are dropped: a partial bucket in the middle is impossible,
    and a genuinely quiet week in the middle is real data that must stay.

    Falls back to the full list when trimming would leave too little to draw —
    a one-week window is entirely "partial" by this definition, and showing
    nothing is worse than showing a short bar the label already explains.
    """
    ref = today or timezone.now().date()
    whole = [b for b in buckets if not _is_partial(b, time, grain, ref)]
    return whole if len(whole) >= keep_at_least else buckets


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _money() -> DecimalField:
    return DecimalField(max_digits=14, decimal_places=2)


def _grouped(qs, grain: str, extra: dict) -> list[dict]:
    """Group a Block queryset by (bucket, user) and aggregate `extra`.

    Grouping by user as well as bucket is what lets the per-person rate ladders
    be applied in Python without a query per person: each row already carries
    the user whose bill/cost rate applies to it.
    """
    from django.db.models.functions import TruncMonth, TruncQuarter, TruncWeek

    if grain == "day":
        qs = qs.annotate(bucket=F("day"))
    elif grain == "week":
        qs = qs.annotate(bucket=TruncWeek("day"))
    elif grain == "quarter":
        qs = qs.annotate(bucket=TruncQuarter("day"))
    else:
        qs = qs.annotate(bucket=TruncMonth("day"))

    return list(
        qs.values("bucket", "user_id").annotate(**extra).order_by()
    )


def _as_date(v) -> date | None:
    if v is None:
        return None
    return v.date() if hasattr(v, "date") else v


def build_series(org, scope: Scope, time: TimeRange,
                 grain: str | None = None) -> tuple[list[dict], str]:
    """Return (points, grain).

    Each point carries every measure for one bucket:

        {bucket, label, hours, billable_hours, revenue, cost,
         margin, margin_pct, utilization}

    `revenue` is hourly billable value (see the module docstring on retainers),
    `cost` is labor cost on the same billable hours the cost metric charges,
    and `utilization` is the billable share of tracked working time — the
    definition the "Utilization" KPI uses, not capacity utilization.
    """
    from tracker.services.billing_totals import billable_block_q

    from .blocks import billable_q, confirmed_qs, working_qs
    from .cost_rates import bill_rate_map, cost_rate_map, default_cost_rate
    from .metrics.base import apply_scope
    from .metrics.revenue_sources import flat_fee_client_ids, non_billable_client_ids

    grain = grain or choose_grain(time)
    # Clipped buckets at either end are dropped: they under-count by
    # construction and read as a slump. See `whole_buckets`.
    buckets = whole_buckets(bucket_starts(time, grain), time, grain)

    base = apply_scope(
        Block.objects.filter(org=org, day__gte=time.start, day__lte=time.end),
        scope,
    )
    confirmed = confirmed_qs(base)

    # Two rules, matching the two the tiles use — see the same note in
    # breakdowns.py. `billable` is the utilization numerator (canonical rule
    # PLUS billable-effort clients such as Internal-Tax); `billing` is the
    # canonical rule alone, which is what Revenue and Labor Cost charge.
    # The Billable hours line ties to the Billable Hours tile; the Billable
    # value, Labor cost and Gross margin lines tie to the money tiles.
    billable = billable_q(org)
    billing = billable_block_q(org)

    # Hourly revenue excludes flat-fee and non-billable clients, exactly as
    # RevenueMetric does, so the two never double-count a retainer.
    rev_exclude = flat_fee_client_ids(org) | non_billable_client_ids(org)
    rev_qs = confirmed.filter(billing)
    if rev_exclude:
        rev_qs = rev_qs.exclude(client_id__in=rev_exclude)

    bill_rates = bill_rate_map(org)
    cost_rates = cost_rate_map(org)
    default_bill = to_float(getattr(org, "billing_rate_default", 0))
    default_cost = default_cost_rate(org)

    # 1) Total and billable minutes per bucket.
    hours_rows = _grouped(confirmed, grain, {
        "total_min": Coalesce(Sum("minutes"), 0),
        "billable_min": Coalesce(Sum("minutes", filter=billable), 0),
    })

    # 2) Rated value + un-rated minutes per bucket, for the revenue ladder.
    rev_rows = _grouped(rev_qs, grain, {
        "rated": Coalesce(Sum("billing_amount"), Decimal("0"), output_field=_money()),
        "unrated_min": Coalesce(
            Sum("minutes", filter=Q(billing_amount__isnull=True)), 0),
    })

    # 3) Labor cost rides the same blocks the cost metric charges — the
    #    canonical billing rule, so an internal-work bucket shows no cost
    #    against income it never earned.
    cost_rows = _grouped(confirmed.filter(billing), grain, {
        "billable_min": Coalesce(Sum("minutes"), 0),
    })

    # 4) Utilization has its own basis: idle and retainer/internal clients out.
    util_rows = _grouped(working_qs(base, org), grain, {
        "tracked_min": Coalesce(Sum("minutes"), 0),
        "billable_min": Coalesce(Sum("minutes", filter=billable), 0),
    })

    acc: dict[date, dict] = {
        b: {"hours": 0.0, "billable_hours": 0.0, "revenue": 0.0, "cost": 0.0,
            "_util_tracked": 0.0, "_util_billable": 0.0}
        for b in buckets
    }

    def slot(raw) -> dict | None:
        return acc.get(_as_date(raw))

    for r in hours_rows:
        s = slot(r["bucket"])
        if s is None:
            continue
        s["hours"] += to_float(r["total_min"]) / 60.0
        s["billable_hours"] += to_float(r["billable_min"]) / 60.0

    for r in rev_rows:
        s = slot(r["bucket"])
        if s is None:
            continue
        rate = bill_rates.get(r["user_id"], default_bill)
        s["revenue"] += to_float(r["rated"])
        s["revenue"] += (to_float(r["unrated_min"]) / 60.0) * rate

    for r in cost_rows:
        s = slot(r["bucket"])
        if s is None:
            continue
        rate = cost_rates.get(r["user_id"], default_cost)
        s["cost"] += (to_float(r["billable_min"]) / 60.0) * rate

    for r in util_rows:
        s = slot(r["bucket"])
        if s is None:
            continue
        s["_util_tracked"] += to_float(r["tracked_min"]) / 60.0
        s["_util_billable"] += to_float(r["billable_min"]) / 60.0

    points: list[dict] = []
    for b in buckets:
        s = acc[b]
        revenue, cost = s["revenue"], s["cost"]
        margin = revenue - cost
        tracked = s["_util_tracked"]
        points.append({
            "bucket": b.isoformat(),
            "label": _bucket_label(b, grain),
            "hours": round(s["hours"], 2),
            "billable_hours": round(s["billable_hours"], 2),
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "margin": round(margin, 2),
            # Margin % is None, not 0, in a bucket that earned nothing. Zero
            # would draw the line down to the floor as though the firm worked
            # at no margin, when in fact it billed nothing that week.
            "margin_pct": round(margin / revenue * 100, 1) if revenue > 0 else None,
            "utilization": (
                round(s["_util_billable"] / tracked * 100, 1) if tracked > 0 else None
            ),
        })
    return points, grain


# ---------------------------------------------------------------------------
# Chart card
# ---------------------------------------------------------------------------

# Series key -> the toggle view that charts it. Order is the order of the
# toggle. `series` names the data keys the view draws, which is also what the
# cost redactor strips by name: drop "cost" and "margin" and the Labor cost and
# Gross margin views disappear with them, leaving the other four intact.
_TREND_VIEWS = [
    {"key": "hours", "label": "Total hours", "series": ["hours"],
     "format": "hours_1dp", "chart_type": "area"},
    {"key": "billable_hours", "label": "Billable hours", "series": ["billable_hours"],
     "format": "hours_1dp", "chart_type": "area"},
    {"key": "revenue", "label": "Billable value", "series": ["revenue"],
     "format": "currency_0dp", "chart_type": "area"},
    {"key": "cost", "label": "Labor cost", "series": ["cost"],
     "format": "currency_0dp", "chart_type": "area"},
    {"key": "margin", "label": "Gross margin", "series": ["margin"],
     "format": "currency_0dp", "chart_type": "area"},
    {"key": "utilization", "label": "Utilization", "series": ["utilization"],
     "format": "percent_1dp", "chart_type": "line"},
]

_GRAIN_NOUN = {"day": "day", "week": "week", "month": "month",
               "quarter": "quarter"}

# How far back a coarse grain reaches. One quarter is one dot, so asking for
# quarter buckets is really asking to see this quarter among its neighbours:
# the CHART window widens to this many quarters ending with the selected one.
# Nothing else on the page moves — the tiles, tables and insights stay on the
# period in the control bar, and the subtitle says so.
_QUARTERS_BACK = 8

# Below this span "By quarter" is not offered: next to "Today" or "This week",
# a control that silently swaps in two years of history is a trap rather than
# a view. A month is the shortest window for which quarterly context reads as
# a deliberate zoom out.
_MIN_DAYS_FOR_QUARTER = 28


def quarter_window(time: TimeRange) -> TimeRange:
    """`time` widened to the last `_QUARTERS_BACK` quarters ending with its own.

    Quarter buckets over a single quarter would be one dot. What a viewer means
    by "show me quarters" is this quarter among the ones before it, so the
    chart — and only the chart — reaches back far enough to draw that.
    """
    last = quarter_start(time.end)
    first = last
    for _ in range(_QUARTERS_BACK - 1):
        first = quarter_start(first - timedelta(days=1))
    return replace(
        time,
        start=first,
        end=max(time.end, _next_bucket(last, "quarter") - timedelta(days=1)),
        label=f"{_bucket_label(first, 'quarter')} → {_bucket_label(last, 'quarter')}",
    )


def _grain_options(time: TimeRange, auto_grain: str) -> list[dict]:
    """The bucketings worth offering for this window, or [] for none.

    Returned by the server rather than hard-coded in the frontend because only
    the server knows what the window can support: "By quarter" over a single
    week is not a view, it is two years of history arriving unannounced.
    """
    options = [{"key": "auto", "label": f"By {_GRAIN_NOUN[auto_grain]}"}]
    if auto_grain != "quarter" and time.days() >= _MIN_DAYS_FOR_QUARTER:
        # Just "By quarter" — the subtitle prints the actual range it covers,
        # so putting the count in the button too is noise on a header that is
        # already carrying six measure buttons.
        options.append({"key": "quarter", "label": "By quarter"})
    return options if len(options) > 1 else []


def trend_chart(org, scope: Scope, time: TimeRange, card_id: str = "performance_trend"):
    """The Performance Trend card: one window, six readings, switched client-side.

    The bucketing is the one exception to "switched client-side": a different
    grain is different rows, not a different reading of the same rows, so it
    goes back through the query. `time.grain` carries the viewer's choice.
    """
    from .types import ChartCardPayload, MetricState

    auto_grain = choose_grain(time)
    want = (time.grain or "auto").lower()
    options = _grain_options(time, auto_grain)
    # An unusable choice — "quarter" left in the URL while the period is now a
    # single week — falls back to auto rather than drawing one bar.
    if want not in {o["key"] for o in options}:
        want = "auto"

    window = quarter_window(time) if want == "quarter" else time
    points, grain = build_series(org, scope, window,
                                 grain=None if want == "auto" else want)
    has_data = any(p["hours"] > 0 for p in points)

    # Say what is missing. The last bucket is normally the one in progress and
    # is dropped, so the line stops before "now" — a reader who expects a point
    # for this week should be told why there isn't one, not left to wonder.
    noun = _GRAIN_NOUN[grain]
    full = bucket_starts(window, grain)
    trimmed = len(full) - len(points)
    parts = [f"By {noun}", window.label]
    if want != "auto":
        # The chart is now showing a wider window than the tiles above it. Not
        # saying so would leave two different periods on one screen both
        # looking like "the period".
        parts.append(f"wider than {time.label} above")
    if trimmed:
        parts.append(f"the current (part-){noun} is not plotted")
    parts.append("billable value is hourly work only — retainers are "
                 "recognized over their period, not per day")

    return ChartCardPayload(
        id=card_id,
        title="Performance trend",
        subtitle=" · ".join(parts),
        chart_type="area",
        x_key="label",
        data=points,
        series=[{"key": "hours", "label": "Total hours"}],
        toggle_views=_TREND_VIEWS,
        toggle_label="Measure",
        grain_options=options,
        grain=want,
        state=MetricState.READY if has_data else MetricState.EMPTY,
    )


# ---------------------------------------------------------------------------
# Sparklines
# ---------------------------------------------------------------------------

# KPI metric -> the series key that traces it over the window. A metric absent
# from this map simply gets no sparkline; nothing invents a shape for a figure
# whose history we cannot draw.
_SPARK_SERIES = {
    "total_hours": "hours",
    "billable_hours": "billable_hours",
    "revenue": "revenue",
    "labor_cost": "cost",
    "gross_margin": "margin_pct",
    "billable_mix": "utilization",
    "billable_utilization": "utilization",
}


def sparklines_for(org, scope: Scope, time: TimeRange) -> dict[str, list[float]]:
    """{metric_id: [value per bucket]} for the tiles in one KPI row.

    Built from ONE `build_series` pass and shared across the row, rather than
    each metric running its own trend query — a row of seven tiles would
    otherwise be seven more trips for data that all comes from the same
    grouped aggregate.

    `Metric.sparkline()` has existed on the base class since the dashboard was
    written and was never called by `safe_compute` and never implemented by any
    metric, so `MetricValue.sparkline` was always None and the frontend's
    sparkline branch was dead. This is what fills it.

    Buckets with no value (a week that billed nothing, so margin % is None) are
    dropped rather than plotted as zero: a gap in the record is not a crash to
    the floor.
    """
    points, _ = build_series(org, scope, time)
    if len(points) < 3:
        return {}

    out: dict[str, list[float]] = {}
    for metric_id, key in _SPARK_SERIES.items():
        values = [p[key] for p in points if p.get(key) is not None]
        if len(values) >= 3:
            out[metric_id] = [round(float(v), 2) for v in values]

    # Effective rate is not a series key — it is the ratio of two that are, so
    # it is derived here rather than carried through the whole aggregate.
    rates = [
        round(p["revenue"] / p["billable_hours"], 2)
        for p in points
        if p.get("billable_hours") and p["billable_hours"] > 0
    ]
    if len(rates) >= 3:
        out["effective_rate"] = rates

    return out
