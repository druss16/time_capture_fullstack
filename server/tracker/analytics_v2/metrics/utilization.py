"""
Utilization metrics — share of tracked hours that are billable.

Utilization = billable_hours / total_tracked_hours × 100
"""
from __future__ import annotations

from django.db.models import Sum
from django.db.models.functions import Coalesce

from ..types import MetricState, MetricValue, to_float
from .base import Metric, ThresholdRange, register_metric


@register_metric("billable_utilization")
class BillableUtilizationMetric(Metric):
    label = "Billable Utilization"
    format = "percent_1dp"
    tooltip = "Billable hours ÷ total tracked hours × 100. Benchmarked against your firm's target utilization (Settings → Organization)."
    # in_band: too low = under-utilized, too high = burnout/can't sustain.
    # The band is resolved per-org from Organization.target_utilization in compute().
    threshold = ThresholdRange(low=75, high=85, direction="in_band")
    calibration_days = 14
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "up"

    def _org_threshold(self, org) -> ThresholdRange:
        """Band around the firm's target: [target, target+10], capped at 100."""
        target = to_float(getattr(org, "target_utilization", 0)) or 75.0
        low = max(0.0, min(target, 100.0))
        high = min(low + 10.0, 100.0)
        return ThresholdRange(low=round(low, 1), high=round(high, 1), direction="in_band")

    def compute(self, org, scope, time):
        # Resolve the good/watch/bad band from the firm's configured target.
        # safe_compute() reads self.threshold after compute(); metrics are
        # instantiated per request, so mutating self here is safe.
        self.threshold = self._org_threshold(org)

        qs = self._block_qs(org, scope, time)
        total_min = to_float(qs.aggregate(s=Sum("minutes"))["s"])
        billable_min = to_float(qs.filter(is_billable=True).aggregate(s=Sum("minutes"))["s"])

        if total_min == 0:
            return MetricValue(state=MetricState.EMPTY)

        util = (billable_min / total_min) * 100
        calib = self._check_calibration(org, scope, util)
        if calib:
            return calib
        return MetricValue(value=round(util, 1))


@register_metric("billable_hours")
class BillableHoursMetric(Metric):
    label = "Billable Hours"
    format = "hours_1dp"
    tooltip = "Total hours marked as billable in this scope and time range."
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        qs = self._block_qs(org, scope, time, billable_only=True)
        total_min = to_float(qs.aggregate(s=Sum("minutes"))["s"])
        if total_min == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total_min / 60.0, 1))


@register_metric("total_hours")
class TotalHoursMetric(Metric):
    label = "Total Hours"
    format = "hours_1dp"
    tooltip = "All tracked hours (billable + non-billable) in this scope and time range."
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        qs = self._block_qs(org, scope, time)
        total_min = to_float(qs.aggregate(s=Sum("minutes"))["s"])
        if total_min == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total_min / 60.0, 1))
