"""
Trends lens — Executive-plan only.

Headline: revenue, hours, invoice count
Chart:    monthly trend over the time window
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce, TruncMonth

from tracker.models import Invoice

from ..types import (
    ChartCardPayload, MetricState, Scope, Section, TimeRange, to_float,
)
from .base import Lens, register_lens
from .helpers import headline_row


@register_lens("trends")
class TrendsLens(Lens):
    label = "Trends"
    required_plan = "executive"
    
    def assemble(self, org, scope, time, compare=None):
        sections: list[Section] = []
        
        sections.append(headline_row(
            ["invoiced_revenue", "billable_hours"],
            org, scope, time, compare,
            section_id="headline",
        ))
        
        sections.append(self._monthly_trend_section(org, scope, time))
        return sections
    
    def _monthly_trend_section(self, org, scope, time) -> Section:
        qs = Invoice.objects.filter(
            org=org,
            invoice_date__gte=time.start,
            invoice_date__lte=time.end,
        )
        if scope.type == "client":
            qs = qs.filter(client_id__in=scope.ids)
        elif scope.type == "composite" and "client" in scope.filters:
            qs = qs.filter(client_id__in=scope.filters["client"])
        
        monthly = (
            qs.annotate(month=TruncMonth("invoice_date"))
            .values("month")
            .annotate(
                revenue=Coalesce(Sum("amount"), Decimal("0")),
                hours=Coalesce(Sum("hours_billed"), Decimal("0")),
                count=Count("id"),
            )
            .order_by("month")
        )
        
        # Backfill months with no invoices
        months = _months_between(time.start, time.end)
        by_month: dict[date, dict] = {}
        for r in monthly:
            m = r["month"]
            key = m.date() if hasattr(m, "date") else m
            by_month[key] = r
        
        data = []
        for m in months:
            r = by_month.get(m, {})
            data.append({
                "month": m.strftime("%Y-%m"),
                "month_label": m.strftime("%b %Y"),
                "revenue": round(to_float(r.get("revenue")), 2),
                "hours": round(to_float(r.get("hours")), 2),
                "invoice_count": r.get("count", 0) or 0,
            })
        
        has_data = any(d["revenue"] > 0 for d in data)
        chart = ChartCardPayload(
            id="revenue_trend",
            title="Monthly invoiced revenue",
            subtitle=time.label,
            chart_type="area",
            data=data,
            series=[{"key": "revenue", "label": "Revenue"}],
            state=MetricState.READY if has_data else MetricState.EMPTY,
        )
        return Section(
            id="trend",
            type="section",
            title="Monthly Trend",
            children=[chart],
        )


def _months_between(start: date, end: date) -> list[date]:
    result = []
    cur = start.replace(day=1)
    while cur <= end:
        result.append(cur)
        # Advance to first of next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return result
