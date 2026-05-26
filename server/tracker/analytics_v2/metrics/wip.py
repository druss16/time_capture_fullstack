"""
WIP (Work In Progress) metrics — approved time that hasn't been invoiced yet.

WIP is NOT time-windowed the way other metrics are. WIP is a snapshot of
"as of now, what's sitting uninvoiced." For Pulse / dashboard views, the
time window is essentially ignored (or used only for "WIP that became 60+ days
during this window" type comparisons).
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from tracker.models import Block

from ..types import MetricState, MetricValue, to_float
from .base import Metric, register_metric


def _wip_qs(org, scope, metric_self):
    """All approved-but-not-invoiced billable blocks for this scope."""
    qs = Block.objects.filter(
        org=org,
        approved=True,
        invoiced=False,
        is_billable=True,
    )
    return metric_self._apply_scope(qs, scope)


def _block_amount(b, default_rate: float) -> float:
    """Resolve the dollar amount for a block, with default fallback."""
    amount = to_float(b.billing_amount)
    if amount:
        return amount
    hours = to_float(b.minutes) / 60.0
    rate = to_float(b.billing_rate) or default_rate
    return hours * rate


def _block_age_days(b, now) -> int:
    """How long has this block been sitting as approved-but-uninvoiced?"""
    ref = b.approved_at or b.start
    if not ref:
        return 0
    if timezone.is_naive(ref):
        ref = timezone.make_aware(ref)
    return max(0, (now - ref).days)


@register_metric("wip_total")
class WipTotalMetric(Metric):
    label = "WIP Total"
    format = "currency_0dp"
    tooltip = "Total dollar value of approved time that hasn't been invoiced yet."
    valid_scopes = ("firm", "client", "staff", "composite")
    delta_good_when = "down"  # Lower WIP = faster billing = better cash flow
    
    def compute(self, org, scope, time):
        # time is ignored for WIP — it's a "now" snapshot
        qs = _wip_qs(org, scope, self)
        default = to_float(getattr(org, "billing_rate_default", 0))
        total = 0.0
        for b in qs.only("minutes", "billing_amount", "billing_rate"):
            total += _block_amount(b, default)
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total, 2))


@register_metric("wip_aged_60_plus")
class WipAged60PlusMetric(Metric):
    label = "WIP Aged 60+"
    format = "currency_0dp"
    tooltip = "WIP sitting in the 60+ day band. Risk of write-off — prioritize billing."
    valid_scopes = ("firm", "client", "staff", "composite")
    delta_good_when = "down"
    
    def compute(self, org, scope, time):
        qs = _wip_qs(org, scope, self)
        now = timezone.now()
        default = to_float(getattr(org, "billing_rate_default", 0))
        total = 0.0
        for b in qs.only("minutes", "billing_amount", "billing_rate", "approved_at", "start"):
            age = _block_age_days(b, now)
            if age >= 60:
                total += _block_amount(b, default)
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total, 2))


def compute_wip_aging_bands(org, scope, metric_self):
    """
    Return the aging breakdown for the wip_aging chart. Used by the
    wip lens to populate its chart card. Not a Metric itself — chart helper.
    """
    qs = _wip_qs(org, scope, metric_self)
    now = timezone.now()
    default = to_float(getattr(org, "billing_rate_default", 0))
    bands = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    
    for b in qs.only("minutes", "billing_amount", "billing_rate", "approved_at", "start"):
        age = _block_age_days(b, now)
        amt = _block_amount(b, default)
        if age <= 30:
            bands["0_30"] += amt
        elif age <= 60:
            bands["31_60"] += amt
        elif age <= 90:
            bands["61_90"] += amt
        else:
            bands["90_plus"] += amt
    
    return {k: round(v, 2) for k, v in bands.items()}
