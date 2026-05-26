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


def _cost_rates_map(org) -> dict[int, float]:
    """Most recent cost rate per user. Mirrors v1 _calc_profitability."""
    rates: dict[int, float] = {}
    for cr in (
        EmployeeCostRate.objects
        .filter(organization=org)
        .order_by("user_id", "-effective_date")
    ):
        if cr.user_id not in rates:
            rates[cr.user_id] = to_float(cr.cost_rate)
    return rates


@register_metric("revenue")
class RevenueMetric(Metric):
    """Estimated revenue from time blocks (uses block.billing_amount)."""
    label = "Revenue"
    format = "currency_0dp"
    tooltip = "Estimated revenue from time blocks (billing_amount). For invoiced revenue, see Invoiced."
    valid_scopes = ("firm", "client", "staff", "service", "engagement", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        qs = self._block_qs(org, scope, time, billable_only=True)
        # Aggregate via SQL where possible, but billing_amount can be null —
        # for null rows, recompute on the fly
        from django.db.models import Q
        agg = qs.aggregate(
            amount=Coalesce(Sum("billing_amount"), Decimal("0")),
            mins_no_amount=Coalesce(
                Sum("minutes", filter=Q(billing_amount__isnull=True)),
                0,
            ),
        )
        default_rate = to_float(getattr(org, "billing_rate_default", 0))
        amount = to_float(agg["amount"])
        # Approximate the un-rated portion with org default
        amount += (to_float(agg["mins_no_amount"]) / 60.0) * default_rate
        
        if amount == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(amount, 2))


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
    """Margin % using invoiced revenue (truth) and labor cost."""
    label = "Gross Margin"
    format = "percent_1dp"
    tooltip = "(Invoiced revenue − labor cost) ÷ invoiced revenue × 100."
    threshold = ThresholdRange(low=20, high=40, direction="higher_is_better")
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        rev_metric = InvoicedRevenueMetric()
        cost_metric = LaborCostMetric()
        rev = rev_metric.compute(org, scope, time)
        cost = cost_metric.compute(org, scope, time)
        
        if rev.state != MetricState.READY or rev.value is None or rev.value == 0:
            return MetricValue(state=MetricState.EMPTY)
        
        cost_v = cost.value if cost.value is not None else 0.0
        margin = ((rev.value - cost_v) / rev.value) * 100
        return MetricValue(value=round(margin, 1), secondary_value=round(rev.value - cost_v, 2),
                          secondary_label="Margin $")


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
        )
