"""
Engagement economics — budget burn vs actual progress.

The metric that matters here is neither burn nor progress on its own. It's the
SPREAD: burn% − progress%. 65% of the budget spent is unremarkable at 70% done
and an emergency at 35% done, and only the difference tells you which one
you're looking at.

Everything is a live snapshot over open engagements — like WIP, these ignore
the dashboard's time window, because a job in trouble is in trouble today
regardless of which quarter you're looking at.
"""
from __future__ import annotations

from tracker.services.engagements import open_engagement_stats

from ..types import MetricState, MetricValue
from .base import Metric, register_metric

# A job burning this many points of budget ahead of its progress is flagged.
# 15 points is roughly "one phase behind where the spend says you should be" —
# inside normal noise for a small job, worth a look on a large one.
AT_RISK_OVERRUN_PTS = 15.0


def _scoped_stats(org, scope):
    """Open-engagement stats honouring client scope. Staff scope doesn't apply —
    an engagement belongs to a client, not a person."""
    client_ids = None
    if scope.type == "client":
        client_ids = list(scope.ids)
    elif scope.type == "composite":
        client_ids = list(scope.filters.get("client") or []) or None
    return open_engagement_stats(org, client_ids=client_ids)


@register_metric("engagement_overrun_dollars")
class EngagementOverrunDollarsMetric(Metric):
    label = "Projected Overrun"
    format = "currency_0dp"
    tooltip = (
        "Dollars of effort open jobs are on track to spend beyond budget, "
        "projected from how much budget each has burned per point of progress."
    )
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "down"

    def compute(self, org, scope, time):
        stats = _scoped_stats(org, scope)
        overruns = [
            s.projected_overrun_dollars for s in stats
            if s.projected_overrun_dollars and s.projected_overrun_dollars > 0
        ]
        if not overruns:
            # No overrun could mean "all healthy" or "nothing has a phase set".
            # Those are different, and saying so beats showing a confident $0.
            if not any(s.progress_pct is not None for s in stats):
                return MetricValue(
                    state=MetricState.EMPTY,
                    error_message="No engagement has a phase set yet",
                )
            return MetricValue(value=0.0)
        return MetricValue(
            value=round(sum(overruns), 2),
            secondary_value=len(overruns),
            secondary_label=f"across {len(overruns)} job{'' if len(overruns) == 1 else 's'}",
            secondary_format="integer",
        )


@register_metric("engagements_at_risk")
class EngagementsAtRiskMetric(Metric):
    label = "Jobs Over Pace"
    format = "integer"
    tooltip = (
        f"Open jobs that have burned more than {AT_RISK_OVERRUN_PTS:.0f} points "
        "more budget than they've completed. Reprice or reassign before billing."
    )
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "down"

    def compute(self, org, scope, time):
        stats = _scoped_stats(org, scope)
        measurable = [s for s in stats if s.overrun_pts is not None]
        if not measurable:
            return MetricValue(
                state=MetricState.EMPTY,
                error_message="Needs a budget and a phase on at least one job",
            )
        at_risk = [s for s in measurable if s.overrun_pts > AT_RISK_OVERRUN_PTS]
        return MetricValue(
            value=len(at_risk),
            secondary_value=len(measurable),
            secondary_label=f"of {len(measurable)} measurable jobs",
            secondary_format="integer",
        )


@register_metric("engagement_budget_coverage")
class EngagementBudgetCoverageMetric(Metric):
    label = "Jobs With a Budget"
    format = "percent_0dp"
    tooltip = (
        "Share of open jobs carrying a budget (derived from prior-year actuals "
        "or comparable jobs). Everything else is unmeasurable."
    )
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "up"

    def compute(self, org, scope, time):
        stats = _scoped_stats(org, scope)
        if not stats:
            return MetricValue(state=MetricState.EMPTY)
        with_budget = sum(1 for s in stats if s.budget_hours)
        with_phase = sum(1 for s in stats if s.progress_pct is not None)
        return MetricValue(
            value=round(with_budget / len(stats) * 100, 1),
            secondary_value=round(with_phase / len(stats) * 100, 1),
            secondary_label="have a phase set",
            secondary_format="percent_0dp",
        )
