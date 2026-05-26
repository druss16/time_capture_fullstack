"""
Timesheet compliance and invoice cycle time metrics.
Mirrors v1's _calc_timesheet_compliance and _calc_invoice_cycle_time.
"""
from __future__ import annotations

from datetime import timedelta

from tracker.models import Block, Timesheet

from ..types import MetricState, MetricValue, to_float
from .base import Metric, ThresholdRange, register_metric


GRACE_DAYS = 2  # Matches v1


@register_metric("timesheet_compliance")
class TimesheetComplianceMetric(Metric):
    label = "Timesheet Compliance"
    format = "percent_1dp"
    tooltip = f"% of timesheets submitted within {GRACE_DAYS} days of week-end."
    threshold = ThresholdRange(low=80, high=95, direction="higher_is_better")
    valid_scopes = ("firm", "staff", "composite")
    delta_good_when = "up"
    
    def compute(self, org, scope, time):
        qs = Timesheet.objects.filter(
            org=org,
            week_start__gte=time.start,
            week_start__lte=time.end,
        ).exclude(status="draft")
        
        if scope.type == "staff":
            qs = qs.filter(user_id__in=scope.ids)
        elif scope.type == "composite" and "staff" in scope.filters:
            qs = qs.filter(user_id__in=scope.filters["staff"])
        
        total = qs.count()
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        
        compliant = 0
        for ts in qs.only("week_start", "submitted_at"):
            deadline = ts.week_start + timedelta(days=6 + GRACE_DAYS)
            if ts.submitted_at:
                sub_date = (ts.submitted_at.date()
                            if hasattr(ts.submitted_at, "date")
                            else ts.submitted_at)
                if sub_date <= deadline:
                    compliant += 1
        
        return MetricValue(value=round(compliant / total * 100, 1))


@register_metric("invoice_cycle_time")
class InvoiceCycleTimeMetric(Metric):
    label = "Invoice Cycle Time"
    format = "days_1dp"
    tooltip = "Avg days from timesheet approval to invoice creation. Target: under 7 days."
    threshold = ThresholdRange(low=7, high=14, direction="lower_is_better")
    valid_scopes = ("firm", "client", "composite")
    delta_good_when = "down"
    
    def compute(self, org, scope, time):
        qs = Block.objects.filter(
            org=org,
            day__gte=time.start,
            day__lte=time.end,
            invoiced=True,
            invoiced_at__isnull=False,
            timesheet__isnull=False,
            timesheet__approved_at__isnull=False,
        ).select_related("timesheet")
        
        qs = self._apply_scope(qs, scope)
        
        times = []
        for b in qs.only("invoiced_at", "timesheet__approved_at"):
            if b.timesheet and b.timesheet.approved_at and b.invoiced_at:
                days = (b.invoiced_at - b.timesheet.approved_at).days
                if 0 <= days <= 365:
                    times.append(days)
        
        if not times:
            return MetricValue(state=MetricState.EMPTY)
        
        avg = sum(times) / len(times)
        return MetricValue(value=round(avg, 1))
