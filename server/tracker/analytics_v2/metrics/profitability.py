"""
Profitability and rate metrics.

Two flavors of profit:
  - Block-based (estimate): Block.billing_amount - Block.cost_amount
  - Invoice-based (actual): Invoice.amount - sum of block costs for that client
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

from tracker.models import EmployeeCostRate, Invoice

from ..types import MetricState, MetricValue, to_float
from .base import Metric, ThresholdRange, register_metric
from .revenue_sources import (
    flat_fee_client_ids, flat_fee_revenue_for, non_billable_client_ids,
)


def _cost_rates_map(org) -> dict[int, float]:
    """Resolved cost rate per user (per-person override > cost tier > default)."""
    from ..cost_rates import cost_rate_map
    return cost_rate_map(org)


@register_metric("revenue")
class RevenueMetric(Metric):
    """Estimated revenue across all billing models: hourly time value + pro-rated
    flat-fee/retainer revenue. Flat-fee and non-billable clients are excluded from
    the hourly estimate so the two revenue sources never double-count."""
    label = "Revenue"
    format = "currency_0dp"
    tooltip = (
        "Estimated revenue: hourly time value (billing_amount) plus pro-rated "
        "flat-fee/retainer fees. For invoiced truth, see Invoiced Revenue."
    )
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "up"

    def compute(self, org, scope, time):
        from ..cost_rates import bill_rate_map
        # Keep flat-fee + non-billable clients out of the hourly estimate; their
        # revenue is added separately (flat fee) or is zero (non-billable).
        exclude_ids = flat_fee_client_ids(org) | non_billable_client_ids(org)
        qs = self._block_qs(org, scope, time, billable_only=True)
        if exclude_ids:
            qs = qs.exclude(client_id__in=exclude_ids)
        amount = to_float(qs.aggregate(a=Coalesce(Sum("billing_amount"), Decimal("0")))["a"])
        # Un-rated blocks (no billing_amount): value each member's time at their
        # tier bill rate when set, else the org default.
        default_rate = to_float(getattr(org, "billing_rate_default", 0))
        bill_rates = bill_rate_map(org)
        unrated = (qs.filter(billing_amount__isnull=True)
                     .values("user_id")
                     .annotate(m=Coalesce(Sum("minutes"), 0)))
        for row in unrated:
            amount += (to_float(row["m"]) / 60.0) * bill_rates.get(row["user_id"], default_rate)
        # Pro-rated flat-fee / retainer revenue for the window
        amount += flat_fee_revenue_for(org, scope, time)

        if amount == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(amount, 2))


def recognized_revenue(org, scope, time) -> tuple[float, str]:
    """Best available revenue for a scope/window.

    Prefers invoiced truth; falls back to the estimate (hourly time value +
    pro-rated retainers) when the firm hasn't imported invoices. This is what
    makes margin/leakage populate for firms that don't push invoices into the
    tool. Returns (amount, basis) with basis in {"invoiced","estimated","none"}.
    """
    inv = InvoicedRevenueMetric().compute(org, scope, time)
    if inv.state == MetricState.READY and inv.value:
        return inv.value, "invoiced"
    est = RevenueMetric().compute(org, scope, time)
    if est.state == MetricState.READY and est.value:
        return est.value, "estimated"
    return 0.0, "none"


@register_metric("invoiced_revenue")
class InvoicedRevenueMetric(Metric):
    """Actual invoiced revenue (Invoice.amount). Truth source for profitability."""
    label = "Invoiced Revenue"
    format = "currency_0dp"
    tooltip = "Actual invoiced revenue from imported invoices."
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        qs = Invoice.objects.filter(
            org=org,
            invoice_date__gte=time.start,
            invoice_date__lte=time.end,
        )
        if scope.type == "client":
            qs = qs.filter(client_id__in=scope.ids)
        elif scope.type == "composite" and "client" in scope.filters:
            qs = qs.filter(client_id__in=scope.filters["client"])
        
        total = to_float(qs.aggregate(s=Coalesce(Sum("amount"), Decimal("0")))["s"])
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total, 2))


@register_metric("labor_cost")
class LaborCostMetric(Metric):
    """Total labor cost (hours × EmployeeCostRate)."""
    label = "Labor Cost"
    format = "currency_0dp"
    tooltip = "Loaded labor cost for hours worked, using EmployeeCostRate per user."
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "down"
    
    def compute(self, org, scope, time):
        qs = self._block_qs(org, scope, time, billable_only=True)
        rates = _cost_rates_map(org)
        default = to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
        
        total = 0.0
        for b in qs.only("minutes", "user_id"):
            hours = to_float(b.minutes) / 60.0
            total += hours * rates.get(b.user_id, default)
        
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total, 2))


@register_metric("gross_margin")
class GrossMarginMetric(Metric):
    """Margin % using recognized revenue (invoiced truth, or the estimate when the
    firm hasn't imported invoices) and labor cost."""
    label = "Gross Margin"
    format = "percent_1dp"
    tooltip = (
        "(Recognized revenue − labor cost) ÷ recognized revenue × 100. "
        "Uses invoiced revenue when available, otherwise estimated revenue "
        "(hourly time value + pro-rated retainers)."
    )
    threshold = ThresholdRange(low=20, high=40, direction="higher_is_better")
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "up"

    def compute(self, org, scope, time):
        rev_v, basis = recognized_revenue(org, scope, time)
        if rev_v <= 0:
            return MetricValue(state=MetricState.EMPTY)

        cost = LaborCostMetric().compute(org, scope, time)
        cost_v = cost.value if cost.value is not None else 0.0
        margin = ((rev_v - cost_v) / rev_v) * 100
        return MetricValue(
            value=round(margin, 1),
            secondary_value=round(rev_v - cost_v, 2),
            secondary_label="Margin $" + ("" if basis == "invoiced" else " (est.)"),
            secondary_format="currency_0dp",
        )


@register_metric("overhead_cost")
class OverheadCostMetric(Metric):
    """Labor cost of NON-chargeable staff — the firm's overhead / SG&A.

    Everyone in a cost tier flagged counts_toward_utilization=False (admin, ops,
    non-charging partners). Unlike direct delivery cost (LaborCostMetric, which
    is billable-only), overhead counts ALL of these people's tracked time —
    they aren't expected to bill, so their whole cost is overhead. Zero (EMPTY)
    until a firm flags an overhead tier in Settings → Cost Tiers."""
    label = "Overhead Cost"
    format = "currency_0dp"
    tooltip = (
        "Labor cost of non-chargeable staff (tiers marked not billable). "
        "The firm's overhead, separate from the direct cost of billable delivery."
    )
    valid_scopes = ("firm", "composite")
    delta_good_when = "down"

    def compute(self, org, scope, time):
        from ..cost_rates import non_utilization_user_ids
        overhead_ids = non_utilization_user_ids(org)
        if not overhead_ids:
            return MetricValue(state=MetricState.EMPTY)
        # ALL tracked time of overhead staff (not billable_only) × cost rate.
        qs = self._block_qs(org, scope, time).filter(user_id__in=overhead_ids)
        rates = _cost_rates_map(org)
        default = to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
        total = 0.0
        for b in qs.only("minutes", "user_id"):
            total += (to_float(b.minutes) / 60.0) * rates.get(b.user_id, default)
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total, 2))


@register_metric("operating_margin")
class OperatingMarginMetric(Metric):
    """Operating margin = (revenue − direct labor − overhead) ÷ revenue × 100.

    Where gross margin (contribution margin) ignores overhead, operating margin
    charges it: direct labor = chargeable staff's billable cost; overhead =
    non-chargeable staff's full cost. With no overhead tier flagged, overhead is
    0 and this equals gross margin — it diverges once a firm marks its admin/ops
    tier not-billable in Settings → Cost Tiers."""
    label = "Operating Margin"
    format = "percent_1dp"
    tooltip = (
        "(Recognized revenue − direct billable labor − overhead labor) ÷ revenue. "
        "The bottom line after the cost of running the firm, not just delivery. "
        "Flag your admin/ops tier as non-billable for this to reflect overhead."
    )
    threshold = ThresholdRange(low=10, high=25, direction="higher_is_better")
    valid_scopes = ("firm", "composite")
    delta_good_when = "up"

    def compute(self, org, scope, time):
        rev_v, basis = recognized_revenue(org, scope, time)
        if rev_v <= 0:
            return MetricValue(state=MetricState.EMPTY)

        from ..cost_rates import non_utilization_user_ids
        overhead_ids = non_utilization_user_ids(org)
        rates = _cost_rates_map(org)
        default = to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0

        # Direct labor = billable cost of CHARGEABLE staff (exclude overhead
        # staff so their time isn't double-counted — it's in overhead below).
        direct_qs = self._block_qs(org, scope, time, billable_only=True)
        if overhead_ids:
            direct_qs = direct_qs.exclude(user_id__in=overhead_ids)
        direct = 0.0
        for b in direct_qs.only("minutes", "user_id"):
            direct += (to_float(b.minutes) / 60.0) * rates.get(b.user_id, default)

        overhead = OverheadCostMetric().compute(org, scope, time)
        overhead_v = overhead.value if overhead.value is not None else 0.0

        margin = ((rev_v - direct - overhead_v) / rev_v) * 100
        return MetricValue(
            value=round(margin, 1),
            secondary_value=round(overhead_v, 2),
            secondary_label="Overhead" + ("" if basis == "invoiced" else " (est. rev)"),
            secondary_format="currency_0dp",
        )


@register_metric("revenue_leakage")
class RevenueLeakageMetric(Metric):
    """Standard-rate value of billable HOURLY time that hasn't been billed or
    committed yet — money on the table.

    This is our wedge: because the agent auto-captures true time, we can see the
    gap between what was worked and what will actually be billed. Flat-fee and
    non-billable clients are excluded (their retainer economics show as "retainer
    health" in the by-client table, not as leakage). Suppressed blocks are ignored.

    leakage = worked_value_at_standard_rate − billed_value
      billed_value = invoiced revenue if imported, else value of COMMITTED blocks
    """
    label = "Revenue Leakage"
    format = "currency_0dp"
    tooltip = (
        "Standard-rate value of billable time not yet billed or committed. "
        "The gap between time worked and time that will actually be billed."
    )
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "down"

    def compute(self, org, scope, time):
        exclude_ids = flat_fee_client_ids(org) | non_billable_client_ids(org)
        qs = (self._block_qs(org, scope, time, billable_only=True)
              .filter(client__isnull=False)
              .exclude(classification_state="suppressed"))
        if exclude_ids:
            qs = qs.exclude(client_id__in=exclude_ids)

        default_rate = to_float(getattr(org, "billing_rate_default", 0))
        from ..cost_rates import bill_rate_map
        bill_rates = bill_rate_map(org)
        worked_value = 0.0
        committed_value = 0.0
        for b in qs.only("minutes", "billing_amount", "billing_rate", "classification_state", "user_id"):
            hours = to_float(b.minutes) / 60.0
            amount = to_float(b.billing_amount)
            if not amount:
                rate = to_float(b.billing_rate) or bill_rates.get(b.user_id, default_rate)
                amount = hours * rate
            worked_value += amount
            if b.classification_state == "committed":
                committed_value += amount

        if worked_value == 0:
            return MetricValue(state=MetricState.EMPTY)

        inv = InvoicedRevenueMetric().compute(org, scope, time)
        billed = inv.value if (inv.state == MetricState.READY and inv.value) else committed_value
        leakage = max(worked_value - billed, 0.0)
        pct = (leakage / worked_value * 100) if worked_value else 0.0
        return MetricValue(
            value=round(leakage, 2),
            secondary_value=round(pct, 1),
            secondary_label="of worked value",
            secondary_format="percent_1dp",
        )


@register_metric("effective_rate")
class EffectiveRateMetric(Metric):
    """Effective hourly rate = revenue / billable hours."""
    label = "Effective Rate"
    format = "currency_0dp"
    tooltip = "Total billing amount ÷ total billable hours. Your actual blended rate."
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        qs = self._block_qs(org, scope, time, billable_only=True)
        agg = qs.aggregate(
            amount=Coalesce(Sum("billing_amount"), Decimal("0")),
            mins=Coalesce(Sum("minutes"), 0),
        )
        mins = to_float(agg["mins"])
        amount = to_float(agg["amount"])
        if mins == 0:
            return MetricValue(state=MetricState.EMPTY)
        
        hours = mins / 60.0
        rate = amount / hours if hours > 0 else 0.0
        standard = to_float(getattr(org, "billing_rate_default", 0))
        variance = rate - standard
        
        return MetricValue(
            value=round(rate, 2),
            secondary_value=round(variance, 2) if standard > 0 else None,
            secondary_label=f"vs ${standard:.0f} standard" if standard > 0 else None,
            secondary_format="currency_0dp",
        )
