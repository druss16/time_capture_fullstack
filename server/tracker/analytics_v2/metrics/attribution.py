"""
Attribution metrics — how the time data got made, and whether to believe it.

Every other metric in this package reports the firm's business. These four
report the *input* to that business: how much of the week was filed without
asking anyone, how often those filings were right, and what the asking cost.

Why that belongs in analytics at all: realization, utilization, margin-by-client
and WIP are unanswerable without per-client time, and every firm knows its
timesheets are reconstructed on a Friday. So the economics lenses are only worth
reading once the input has been shown to be sound. These metrics are that
showing.

The arithmetic is NOT reimplemented here. `tracker.services.accuracy` already
owns it — random sampling, Wilson intervals, the population definition, and the
trap where `categorized_by='correction'` means a person AGREED rather than
corrected. This module is a thin adapter from that service to the KPI tile
contract; if a number here disagrees with the Accuracy tab, this file is wrong.

Scope note: the accuracy service works at org + date-range granularity and has
no scope argument, so these are firm-scope metrics. Rather than silently
reporting firm numbers on a client page, they declare `valid_scopes = ("firm",)`
and the lens omits them elsewhere.
"""
from __future__ import annotations

from tracker.services import accuracy as acc

from ..types import MetricState, MetricValue
from .base import Metric, ThresholdRange, register_metric


def elapsed_days(time) -> int:
    """Days of the window that have actually happened.

    A "this quarter" range runs to the quarter's end, so dividing by its full
    length on day twelve reports a rate against sixty days that have not
    happened. Rates use this; totals still use the whole range.
    """
    from django.utils import timezone

    last = min(time.end, timezone.localdate())
    return max((last - time.start).days + 1, 1)


_NEEDS_YOU_TTL = 60.0
_needs_you_cache: dict = {}


def needs_you(org_id: int, time) -> tuple[int, float, int]:
    """Open Needs You items, their hours, and how many people own them.

    One definition shared by both burden metrics. They were computed apart and
    disagreed on screen — 737 items against 115.9 h — because one walked the
    Daily Review predicate and the other took coverage's `asked_minutes`, which
    also counts immaterial and idle blocks nobody is ever shown.

    Memoised briefly: the predicate is per-block Python, and two tiles plus a
    lens section ask for it inside one request.
    """
    import time as _time
    from django.db.models import Q
    from tracker.models import Block
    from tracker.views_reports import is_pending_review_block

    key = (org_id, time.start, time.end)
    hit = _needs_you_cache.get(key)
    if hit and (_time.monotonic() - hit[0]) < _NEEDS_YOU_TTL:
        return hit[1]

    # Prefilter in SQL so the predicate only judges plausible rows; it stays the
    # authority. Both arms of the OR are needed — a Stage-11 re-opened block is
    # `proposed` while still carrying is_categorized=True.
    candidates = (
        Block.objects
        .filter(org_id=org_id, day__gte=time.start, day__lte=time.end,
                deleted_at__isnull=True)
        .filter(Q(is_categorized=False) | Q(classification_state="proposed"))
        .exclude(classification_state="suppressed")
        .only("id", "user_id", "minutes", "classification_state",
              "is_categorized", "categorized_by", "proposed_client_id",
              "proposed_reasoning", "proposed_signals", "bundle_id",
              "category_hours")
    )
    items = 0
    minutes = 0
    owners: set = set()
    for b in candidates:
        if is_pending_review_block(b):
            items += 1
            minutes += (b.minutes or 0)
            owners.add(b.user_id)

    result = (items, minutes / 60.0, len(owners))
    _needs_you_cache[key] = (_time.monotonic(), result)
    return result


def sample_for_window(org_id: int, time) -> tuple[dict, tuple | None]:
    """The audit sample to quote for this window, and the period it came from.

    Prefers a sample drawn for exactly this range; otherwise falls back to the
    most recent one that closed by the end of it. Shared by the metric and the
    Trust lens so the tile and the chart can never quote different periods.
    """
    samp = acc.sampled_precision(org_id, time.start, time.end)
    if samp.get("drawn"):
        return samp, (time.start, time.end)
    period = acc.latest_sample_period(org_id, on_or_before=time.end)
    if not period:
        return samp, None
    return acc.sampled_precision(org_id, period[0], period[1]), period


@register_metric("attribution_autonomy")
class AttributionAutonomyMetric(Metric):
    """Share of recorded time filed to a client with nobody asked."""

    label = "Filed Without Asking"
    format = "percent_1dp"
    tooltip = (
        "Filed Without Asking = automatically filed minutes ÷ all decided-or-asked minutes\n\n"
        "The share of recorded time the software assigned on its own.\n"
        "Time it declined to guess on sits in the review queue and\n"
        "counts against this figure. Time judged not to be real activity\n"
        "is on neither side of the ratio."
    )
    valid_scopes = ("firm",)
    delta_good_when = "up"
    threshold = ThresholdRange(low=65, high=80, direction="higher_is_better")

    def compute(self, org, scope, time):
        cov = acc.coverage(org.id, time.start, time.end)
        if not cov.get("total_minutes"):
            return MetricValue(state=MetricState.EMPTY)
        filed_h = cov["filed_minutes"] / 60.0
        # percent_1dp does NOT multiply by 100 — a fraction renders as "0.8%".
        return MetricValue(
            value=round(cov["autonomy"] * 100, 1),
            secondary_value=round(filed_h, 1),
            secondary_label="Hours filed",
            secondary_format="hours_1dp",
        )


@register_metric("attribution_precision")
class AttributionPrecisionMetric(Metric):
    """Share of automatically filed blocks a human audit judged correct."""

    label = "Measured Correct"
    format = "percent_1dp"
    tooltip = (
        "Measured Correct = correct ÷ (correct + wrong) on a random audit sample\n\n"
        "Blocks drawn at random from what we filed automatically, then\n"
        "judged one at a time against the underlying evidence. Draws that\n"
        "could not be settled either way are excluded from the ratio and\n"
        "reported separately. Shown with a 95% confidence interval — it is\n"
        "a sample estimate, not a guarantee. Counting every undecided draw\n"
        "as wrong gives the worst case, which the chart subtitle carries."
    )
    valid_scopes = ("firm",)
    delta_good_when = "up"
    threshold = ThresholdRange(low=80, high=90, direction="higher_is_better")

    def compute(self, org, scope, time):
        samp, period = sample_for_window(org.id, time)
        decided = (samp.get("correct") or 0) + (samp.get("wrong") or 0)
        if not decided:
            # A drawn-but-unjudged sample is a different story from no sample at
            # all, and the lens says which. The tile stays empty either way.
            return MetricValue(
                state=MetricState.EMPTY,
                error_message=(
                    "Sample drawn but not yet judged"
                    if samp.get("drawn") else "No audit sample drawn yet"
                ),
            )
        lo = samp.get("ci_low") or 0.0
        hi = samp.get("ci_high") or 0.0
        # Quoting a measurement from a different window is fine; quoting it
        # without saying so is not. The window goes in the label.
        window = ""
        if period and (period[0] != time.start or period[1] != time.end):
            window = f", {period[0]:%-d %b}–{period[1]:%-d %b}"
        precision = samp.get("precision") or (samp["correct"] / decided)
        return MetricValue(
            value=round(precision * 100, 1),
            secondary_value=float(decided),
            secondary_label=f"Blocks judged{window}",
            secondary_format="integer",
            threshold_low=round(lo * 100, 1),
            threshold_high=round(hi * 100, 1),
        )


@register_metric("review_burden")
class ReviewBurdenMetric(Metric):
    """How many items are sitting in one person's Needs You. Lower is better."""

    label = "Waiting on Each Person"
    format = "integer"
    tooltip = (
        "Waiting on Each Person = open Needs You items ÷ people\n\n"
        "Exactly the rows Daily Review puts in front of someone: a client\n"
        "guess to confirm, a mismatch, a split, or a look-alike to pick\n"
        "between. Gated on the same predicate Daily Review and the reports\n"
        "use, so this number and that screen can never disagree.\n\n"
        "It is NOT every unreviewed block — work already filed, and the\n"
        "legacy pile that is categorised but never surfaced, are not in\n"
        "anyone's queue and are not counted here.\n"
        "Lower is better."
    )
    valid_scopes = ("firm",)
    delta_good_when = "down"
    # A screen someone can clear in a sitting vs. a backlog they will avoid.
    threshold = ThresholdRange(low=15, high=40, direction="lower_is_better")

    def compute(self, org, scope, time):
        items, _hours, owners = needs_you(org.id, time)
        if not items:
            return MetricValue(value=0.0, secondary_value=0.0,
                               secondary_label="Nothing waiting",
                               secondary_format="integer")
        people = _people_in(org.id, time) or owners or 1
        return MetricValue(
            value=round(items / people),
            secondary_value=float(items),
            secondary_label=f"Across {people} people",
            secondary_format="integer",
        )


@register_metric("hours_waiting")
class HoursWaitingMetric(Metric):
    """Time the software declined to guess on, still unanswered. Lower is better."""

    label = "Hours Waiting on You"
    format = "hours_1dp"
    tooltip = (
        "Hours Waiting on You = hours of the open Needs You items\n\n"
        "The same pile as the tile beside it, measured in time instead of\n"
        "rows. Work the matcher would not guess a client for.\n"
        "It is not lost and it is not wrong — it is the one pile on this page\n"
        "that converts directly into booked hours when someone looks at it.\n"
        "Lower is better."
    )
    valid_scopes = ("firm",)
    delta_good_when = "down"

    def compute(self, org, scope, time):
        # Same pile as the tile beside it, by construction.
        _items, hours, _owners = needs_you(org.id, time)
        total = (acc.coverage(org.id, time.start, time.end)
                 .get("total_minutes") or 0) / 60.0
        if not total:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(
            value=round(hours, 1),
            secondary_value=round(hours / total * 100, 1),
            secondary_label="Share of recorded time",
            secondary_format="percent_1dp",
        )


def _people_in(org_id: int, time) -> int:
    from tracker.models import Block

    return (Block.objects.filter(
        org_id=org_id, deleted_at__isnull=True,
        day__gte=time.start, day__lte=time.end,
    ).values("user_id").distinct().count())
