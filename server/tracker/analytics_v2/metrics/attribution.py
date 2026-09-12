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
    threshold = ThresholdRange(low=0.70, high=0.90, direction="higher_is_better")

    def compute(self, org, scope, time):
        cov = acc.coverage(org.id, time.start, time.end)
        if not cov.get("total_minutes"):
            return MetricValue(state=MetricState.EMPTY)
        filed_h = cov["filed_minutes"] / 60.0
        return MetricValue(
            value=cov["autonomy"],
            secondary_value=round(filed_h, 1),
            secondary_label="hours filed automatically",
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
        "a sample estimate, not a guarantee."
    )
    valid_scopes = ("firm",)
    delta_good_when = "up"
    threshold = ThresholdRange(low=0.85, high=0.95, direction="higher_is_better")

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
            window = f" · measured {period[0]:%-d %b}–{period[1]:%-d %b}"
        return MetricValue(
            value=samp.get("precision") or (samp["correct"] / decided),
            secondary_value=float(decided),
            secondary_label=(f"blocks judged · 95% CI "
                             f"{lo * 100:.1f}–{hi * 100:.1f}%{window}"),
            secondary_format="integer",
            threshold_low=lo,
            threshold_high=hi,
        )


@register_metric("review_burden")
class ReviewBurdenMetric(Metric):
    """Human decisions per day — what the accuracy above costs the firm."""

    label = "Decisions a Day"
    format = "decimal_1dp"
    tooltip = (
        "Decisions a Day = human classification decisions ÷ days in range\n\n"
        "Every time a person told the software which client a block\n"
        "belonged to, across the whole firm. This is the running cost of\n"
        "the numbers above — the lower it is for a given accuracy, the\n"
        "less the firm is paying in attention."
    )
    valid_scopes = ("firm",)
    delta_good_when = "down"

    def compute(self, org, scope, time):
        from tracker.models import ClassificationAudit

        days = max((time.end - time.start).days + 1, 1)
        n = ClassificationAudit.objects.filter(
            block__org_id=org.id,
            block__day__gte=time.start,
            block__day__lte=time.end,
            source="manual",
        ).count()
        if not n:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(
            value=round(n / days, 1),
            secondary_value=float(n),
            secondary_label=f"decisions over {days} days",
            secondary_format="integer",
        )


@register_metric("hours_per_decision")
class HoursPerDecisionMetric(Metric):
    """Recorded hours bought per human decision — the leverage ratio."""

    label = "Hours per Decision"
    format = "hours_1dp"
    tooltip = (
        "Hours per Decision = all decided-or-asked hours ÷ human decisions\n\n"
        "How much attributed time each human decision produced. This is the\n"
        "single clearest answer to 'is it worth the hassle' — it rises when\n"
        "the software gets better and falls when it starts leaning on people."
    )
    valid_scopes = ("firm",)
    delta_good_when = "up"

    def compute(self, org, scope, time):
        from tracker.models import ClassificationAudit

        cov = acc.coverage(org.id, time.start, time.end)
        total_h = (cov.get("total_minutes") or 0) / 60.0
        n = ClassificationAudit.objects.filter(
            block__org_id=org.id,
            block__day__gte=time.start,
            block__day__lte=time.end,
            source="manual",
        ).count()
        if not total_h or not n:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(
            value=round(total_h / n, 1),
            secondary_value=round(total_h, 1),
            secondary_label=f"hours from {n} decisions",
            secondary_format="hours_1dp",
        )
