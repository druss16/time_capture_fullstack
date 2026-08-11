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
    label = "Capacity Utilization"
    format = "percent_1dp"
    tooltip = "Billable hours ÷ available capacity × 100. NOTE: tracked time excludes idle/away time, so against a full wall-clock capacity this reads low — it's a secondary signal. See Utilization (billable ÷ tracked) for the headline efficiency number. Capacity = each person's weekly hours (Settings → Cost Tiers)."
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

        # Chargeable-population filter: at the firm/composite level, drop members
        # whose tier is flagged non-chargeable (admin/ops/non-charging partners)
        # from BOTH numerator and denominator, so their idle capacity doesn't
        # poison the firm number. When the user explicitly scopes to a person
        # ("staff"), we DON'T exclude — you asked to see that individual.
        exclude_ids: set[int] = set()
        if scope.type in ("firm", "composite"):
            from ..cost_rates import non_utilization_user_ids
            exclude_ids = non_utilization_user_ids(org)
            if exclude_ids:
                qs = qs.exclude(user_id__in=exclude_ids)

        billable_min = to_float(qs.filter(is_billable=True).aggregate(s=Sum("minutes"))["s"])
        billable_hours = billable_min / 60.0

        # Denominator: available capacity for firm/staff scopes (billable ÷ available);
        # for a client/service/engagement scope, capacity is meaningless, so fall back
        # to tracked time (billable ÷ tracked).
        if scope.type in ("firm", "staff"):
            denom_hours = self._capacity_hours(org, scope, time, exclude_ids)
        else:
            denom_hours = to_float(qs.aggregate(s=Sum("minutes"))["s"]) / 60.0

        if denom_hours <= 0:
            return MetricValue(state=MetricState.EMPTY)

        util = (billable_hours / denom_hours) * 100
        calib = self._check_calibration(org, scope, util)
        if calib:
            return calib
        return MetricValue(value=round(util, 1))

    def _capacity_hours(self, org, scope, time, exclude_ids: set[int] | None = None) -> float:
        """Available working hours over the window for the people active in scope:
        Σ (each person's weekly capacity × weeks in the window).

        ``exclude_ids`` drops non-chargeable members so their capacity never
        enters the firm denominator (keeps it symmetric with the numerator)."""
        from ..cost_rates import capacity_map
        caps = capacity_map(org)
        default_cap = to_float(getattr(org, "capacity_hours_per_week", 40)) or 40.0
        days = (time.end - time.start).days + 1
        weeks = (days / 7.0) if days > 0 else 0.0
        # .order_by() clears any inherited ordering so DISTINCT dedupes on
        # user_id alone (otherwise the order column joins the SELECT DISTINCT and
        # every block counts as its own "user", inflating capacity ~1000x).
        active = (self._block_qs(org, scope, time)
                  .order_by().values_list("user_id", flat=True).distinct())
        exclude_ids = exclude_ids or set()
        total = 0.0
        for uid in active:
            if uid in exclude_ids:
                continue
            total += caps.get(uid, default_cap) * weeks
        return total


@register_metric("billable_mix")
class BillableMixMetric(Metric):
    """Billable ÷ tracked (active) time — the headline utilization for an
    activity tracker. Because the agent excludes idle/away time from tracked
    totals, both numerator and denominator are active-at-computer time, so this
    is the honest 'how billable is their working time' number (unlike capacity
    utilization, which divides active time by wall-clock hours)."""
    label = "Utilization"
    format = "percent_1dp"
    tooltip = ("Billable ÷ tracked (active) time. Of the time actually spent at "
               "the computer, how much was billable. Idle/away time is excluded "
               "from tracked time, so this is the true efficiency number.")
    threshold = ThresholdRange(low=55, high=75, direction="higher_is_better")
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "up"

    def compute(self, org, scope, time):
        qs = self._block_qs(org, scope, time)
        # Same chargeable-population filter as capacity utilization: drop
        # non-chargeable staff (admin/ops) from the firm/composite number.
        if scope.type in ("firm", "composite"):
            from ..cost_rates import non_utilization_user_ids
            excl = non_utilization_user_ids(org)
            if excl:
                qs = qs.exclude(user_id__in=excl)
        total_min = to_float(qs.aggregate(s=Sum("minutes"))["s"])
        if total_min == 0:
            return MetricValue(state=MetricState.EMPTY)
        bill_min = to_float(qs.filter(is_billable=True).aggregate(s=Sum("minutes"))["s"])
        return MetricValue(value=round(bill_min / total_min * 100, 1))


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
