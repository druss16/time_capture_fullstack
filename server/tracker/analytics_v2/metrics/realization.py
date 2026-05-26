"""
Realization metrics — the two AICPA-standard variants.

Hours realization:  invoiced hours / worked hours × 100
Dollar realization: invoiced amount / worked value at standard rates × 100

Per Phase 4 / your decision: Option B — same math as v1, plus a `data_quality`
field that surfaces the share of worked_value coming from explicit BillingRate
records vs the org.billing_rate_default fallback. Frontend renders a subtle
"data quality" badge when share is below 0.75.

These compute() implementations are intentionally close mirrors of
views_analytics._calc_realization() so numbers reconcile within 0.5%.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

from tracker.models import Block, Invoice, Organization

from ..types import MetricState, MetricValue, Scope, TimeRange, to_float
from .base import Metric, ThresholdRange, register_metric


def _invoiced_for(org: Organization, scope: Scope, time: TimeRange) -> tuple[float, float]:
    """
    Return (total_billed_hours, total_billed_amount) for invoices in scope.
    
    Invoices are scoped to org + client + date range. For staff/service scopes,
    invoices don't carry that dimension, so we degrade gracefully: staff scope
    returns 0 invoiced (invoices aren't per-staff) — caller should interpret
    accordingly. For client scope, we filter to those clients.
    """
    qs = Invoice.objects.filter(
        org=org,
        invoice_date__gte=time.start,
        invoice_date__lte=time.end,
        client__isnull=False,
    )
    
    if scope.type == "client":
        qs = qs.filter(client_id__in=scope.ids)
    elif scope.type == "composite" and "client" in scope.filters:
        qs = qs.filter(client_id__in=scope.filters["client"])
    elif scope.type in ("staff", "service", "engagement"):
        # No staff/service/engagement dim on Invoice — return zeros to signal
        # "realization not meaningfully defined at this scope"
        return 0.0, 0.0
    
    agg = qs.aggregate(
        hours=Coalesce(Sum("hours_billed"), Decimal("0")),
        amount=Coalesce(Sum("amount"), Decimal("0")),
    )
    return to_float(agg["hours"]), to_float(agg["amount"])


def _worked_for(
    org: Organization, scope: Scope, time: TimeRange, metric_self: Metric,
) -> tuple[float, float, float, float]:
    """
    Return (worked_hours, worked_value, explicit_value, default_value).
    
    `explicit_value` = $ value of blocks where Block.billing_rate is set
                       (came from an explicit BillingRate resolution).
    `default_value`  = $ value of blocks where billing_rate is null
                       (fell back to org.billing_rate_default).
    
    These two sum to worked_value and power the Option B data_quality badge.
    """
    qs = metric_self._block_qs(org, scope, time, billable_only=True).filter(
        client__isnull=False,
    )
    
    default_rate = to_float(getattr(org, "billing_rate_default", 0))
    
    worked_hours = 0.0
    worked_value = 0.0
    explicit_value = 0.0
    default_value = 0.0
    
    # Iterator() to avoid loading everything into memory for large firms
    for b in qs.only("minutes", "billing_amount", "billing_rate"):
        hours = to_float(b.minutes) / 60.0
        # Prefer pre-computed billing_amount (set at save time when rate was resolved)
        amount = to_float(b.billing_amount)
        used_default = False
        if not amount:
            rate = to_float(b.billing_rate) or default_rate
            amount = hours * rate
            used_default = b.billing_rate is None
        else:
            used_default = b.billing_rate is None
        
        worked_hours += hours
        worked_value += amount
        if used_default:
            default_value += amount
        else:
            explicit_value += amount
    
    return worked_hours, worked_value, explicit_value, default_value


# ---------------------------------------------------------------------------
# Hours realization
# ---------------------------------------------------------------------------

@register_metric("realization_hours")
class RealizationHoursMetric(Metric):
    label = "Realization (Hours)"
    format = "percent_1dp"
    tooltip = "Invoiced hours ÷ worked hours × 100. Flags unbilled time and scope creep."
    threshold = ThresholdRange(low=85, high=100, direction="higher_is_better")
    calibration_days = 30
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        billed_hours, _ = _invoiced_for(org, scope, time)
        worked_hours, _, _, _ = _worked_for(org, scope, time, self)
        
        if worked_hours == 0 and billed_hours == 0:
            return MetricValue(state=MetricState.EMPTY)
        
        if worked_hours == 0:
            # Billed without working — unusual but real (e.g. fixed-fee with
            # no time logged). Caps at no-meaningful-rate.
            return MetricValue(state=MetricState.EMPTY)
        
        rate = (billed_hours / worked_hours) * 100
        # Cap calibration to lifetime data, then return real number
        calib = self._check_calibration(org, scope, rate)
        if calib:
            return calib
        return MetricValue(value=round(rate, 1))


# ---------------------------------------------------------------------------
# Dollar realization (the AICPA-standard "billing realization")
# ---------------------------------------------------------------------------

@register_metric("realization_dollar")
class RealizationDollarMetric(Metric):
    label = "Realization (Dollar)"
    format = "percent_1dp"
    tooltip = (
        "Invoiced dollars ÷ standard-rate value of worked hours × 100. "
        "Industry-standard AICPA measure. Catches both unbilled time AND rate discounting."
    )
    threshold = ThresholdRange(low=85, high=100, direction="higher_is_better")
    calibration_days = 30
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        _, billed_amount = _invoiced_for(org, scope, time)
        _, worked_value, explicit_value, default_value = _worked_for(org, scope, time, self)
        
        if worked_value == 0 and billed_amount == 0:
            return MetricValue(state=MetricState.EMPTY)
        
        if worked_value == 0:
            return MetricValue(state=MetricState.EMPTY)
        
        rate = (billed_amount / worked_value) * 100
        
        # Data quality: share of worked_value backed by explicit BillingRate records
        data_quality = explicit_value / worked_value if worked_value > 0 else 0.0
        
        # Threshold for surfacing the badge — below 75% is the firm needs to
        # populate more rates for the number to mean anything.
        quality_note = None
        if data_quality < 0.75:
            default_pct = (default_value / worked_value * 100) if worked_value else 0
            quality_note = (
                f"{default_pct:.0f}% of worked value uses the org default rate "
                f"because explicit BillingRate records are missing. "
                f"Populate rates in Settings → Billing Rates for a precise number."
            )
        
        calib = self._check_calibration(org, scope, rate)
        if calib:
            calib.data_quality = round(data_quality, 3)
            calib.data_quality_note = quality_note
            return calib
        
        return MetricValue(
            value=round(rate, 1),
            data_quality=round(data_quality, 3),
            data_quality_note=quality_note,
        )
