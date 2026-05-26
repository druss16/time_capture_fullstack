"""
Profitability lens.

Firm scope:    By-client table + service line mix chart
Client scope:  Single client deep dive (services breakdown, staff allocation)
Staff scope:   Per-staff contribution (revenue, hours, margin contributed)
"""
from __future__ import annotations

from collections import defaultdict

from django.db.models import Sum
from django.db.models.functions import Coalesce
from decimal import Decimal

from tracker.models import Block, EmployeeCostRate, Invoice

from ..types import (
    ChartCardPayload, DataTablePayload, MetricState, Scope, Section, TimeRange,
    to_float,
)
from .base import Lens, register_lens
from .helpers import column, headline_row, kpi_tile


@register_lens("profitability")
class ProfitabilityLens(Lens):
    label = "Profitability"
    
    def assemble(self, org, scope, time, compare=None):
        sections: list[Section] = []
        
        # Headline: revenue, margin, labor cost
        sections.append(headline_row(
            ["invoiced_revenue", "gross_margin", "labor_cost"],
            org, scope, time, compare,
            section_id="headline",
        ))
        
        if scope.is_firm():
            sections.append(self._by_client_section(org, scope, time))
        elif scope.type == "client":
            sections.append(self._client_detail_section(org, scope, time))
        elif scope.type == "staff":
            sections.append(self._by_staff_section(org, scope, time))
        
        return sections
    
    # ------------------------------------------------------------------------
    # By-client table (firm scope)
    # ------------------------------------------------------------------------
    
    def _by_client_section(self, org, scope, time) -> Section:
        table = self._build_client_profit_table(org, time)
        return Section(
            id="by_client",
            type="section",
            title="By Client",
            collapsible=True,
            children=[table],
        )
    
    def _build_client_profit_table(self, org, time) -> DataTablePayload:
        # Rate maps
        cost_rates: dict[int, float] = {}
        for cr in (EmployeeCostRate.objects
                   .filter(organization=org)
                   .order_by("user_id", "-effective_date")):
            if cr.user_id not in cost_rates:
                cost_rates[cr.user_id] = to_float(cr.cost_rate)
        default_cost = to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
        
        # Worked cost + hours per client
        worked: dict[int, dict] = defaultdict(lambda: {"name": "", "cost": 0.0, "hours": 0.0})
        block_qs = (Block.objects
                    .filter(org=org, day__gte=time.start, day__lte=time.end,
                            is_billable=True, client__isnull=False)
                    .select_related("client"))
        for b in block_qs.only("client_id", "client__name", "minutes", "user_id"):
            hours = to_float(b.minutes) / 60.0
            cost = hours * cost_rates.get(b.user_id, default_cost)
            worked[b.client_id]["name"] = b.client.name if b.client else f"Client {b.client_id}"
            worked[b.client_id]["hours"] += hours
            worked[b.client_id]["cost"] += cost
        
        # Invoiced revenue per client
        inv_qs = (Invoice.objects
                  .filter(org=org, invoice_date__gte=time.start,
                          invoice_date__lte=time.end, client__isnull=False)
                  .values("client_id", "client__name")
                  .annotate(amount=Coalesce(Sum("amount"), Decimal("0"))))
        invoiced: dict[int, dict] = {
            r["client_id"]: {
                "name": r["client__name"],
                "amount": to_float(r["amount"]),
            } for r in inv_qs
        }
        
        # Merge
        rows = []
        all_ids = set(invoiced) | set(worked)
        for cid in all_ids:
            name = (invoiced.get(cid, {}).get("name")
                    or worked.get(cid, {}).get("name")
                    or f"Client {cid}")
            rev = invoiced.get(cid, {}).get("amount", 0.0)
            hours = worked.get(cid, {}).get("hours", 0.0)
            cost = worked.get(cid, {}).get("cost", 0.0)
            margin = rev - cost
            margin_pct = (margin / rev * 100) if rev > 0 else None
            rows.append({
                "client_id": cid,
                "client_name": name,
                "revenue": round(rev, 2),
                "hours": round(hours, 2),
                "cost": round(cost, 2),
                "margin": round(margin, 2),
                "margin_pct": round(margin_pct, 1) if margin_pct is not None else None,
            })
        
        rows.sort(key=lambda r: -(r["revenue"] or 0))
        
        return DataTablePayload(
            id="clients_profit",
            title="Client profitability",
            subtitle=time.label,
            columns=[
                column("client_name", "Client", "text"),
                column("revenue", "Invoiced", "currency_0dp"),
                column("hours", "Hours", "hours_1dp"),
                column("cost", "Cost", "currency_0dp"),
                column("margin", "Margin $", "currency_0dp"),
                column("margin_pct", "Margin %", "percent_1dp"),
            ],
            rows=rows,
            default_sort={"key": "revenue", "direction": "desc"},
        )
    
    # ------------------------------------------------------------------------
    # Single-client deep dive
    # ------------------------------------------------------------------------
    
    def _client_detail_section(self, org, scope, time) -> Section:
        # Service line breakdown for this client
        service_chart = self._service_breakdown_chart(org, scope, time)
        return Section(
            id="service_breakdown",
            type="section",
            title="By Service Line",
            collapsible=True,
            children=[service_chart],
        )
    
    def _service_breakdown_chart(self, org, scope, time) -> ChartCardPayload:
        qs = (Block.objects
              .filter(org=org, day__gte=time.start, day__lte=time.end,
                      is_billable=True, client_id__in=scope.ids)
              .select_related("task_type"))
        
        by_service: dict[str, float] = defaultdict(float)
        for b in qs.only("task_type__name", "minutes"):
            svc = b.task_type.name if b.task_type else "General"
            by_service[svc] += to_float(b.minutes) / 60.0
        
        data = [{"service": k, "hours": round(v, 1)} for k, v in sorted(
            by_service.items(), key=lambda x: -x[1]
        )]
        
        return ChartCardPayload(
            id="service_breakdown",
            title="Hours by service line",
            subtitle=time.label,
            chart_type="horizontal_bar",
            data=data,
            series=[{"key": "hours", "label": "Hours"}],
            state=MetricState.READY if data else MetricState.EMPTY,
        )
    
    # ------------------------------------------------------------------------
    # By-staff table
    # ------------------------------------------------------------------------
    
    def _by_staff_section(self, org, scope, time) -> Section:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        cost_rates: dict[int, float] = {}
        for cr in (EmployeeCostRate.objects
                   .filter(organization=org)
                   .order_by("user_id", "-effective_date")):
            if cr.user_id not in cost_rates:
                cost_rates[cr.user_id] = to_float(cr.cost_rate)
        default_cost = to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
        
        qs = (Block.objects
              .filter(org=org, day__gte=time.start, day__lte=time.end,
                      user_id__in=scope.ids, is_billable=True))
        
        per_user: dict[int, dict] = defaultdict(lambda: {"revenue": 0.0, "hours": 0.0, "cost": 0.0})
        for b in qs.only("user_id", "minutes", "billing_amount", "billing_rate"):
            hours = to_float(b.minutes) / 60.0
            amount = to_float(b.billing_amount)
            if not amount:
                rate = to_float(b.billing_rate) or to_float(getattr(org, "billing_rate_default", 0))
                amount = hours * rate
            per_user[b.user_id]["hours"] += hours
            per_user[b.user_id]["revenue"] += amount
            per_user[b.user_id]["cost"] += hours * cost_rates.get(b.user_id, default_cost)
        
        # Look up names
        names = {u.id: (f"{u.first_name} {u.last_name}".strip() or u.username)
                 for u in User.objects.filter(id__in=per_user.keys())
                 .only("id", "first_name", "last_name", "username")}
        
        rows = []
        for uid, d in per_user.items():
            margin = d["revenue"] - d["cost"]
            rows.append({
                "user_id": uid,
                "name": names.get(uid, f"User {uid}"),
                "hours": round(d["hours"], 2),
                "revenue": round(d["revenue"], 2),
                "cost": round(d["cost"], 2),
                "margin": round(margin, 2),
            })
        rows.sort(key=lambda r: -r["revenue"])
        
        table = DataTablePayload(
            id="staff_contribution",
            title="Per-staff contribution",
            subtitle=time.label,
            columns=[
                column("name", "Name", "text"),
                column("hours", "Hours", "hours_1dp"),
                column("revenue", "Revenue", "currency_0dp"),
                column("cost", "Cost", "currency_0dp"),
                column("margin", "Margin", "currency_0dp"),
            ],
            rows=rows,
            default_sort={"key": "revenue", "direction": "desc"},
        )
        return Section(
            id="by_staff",
            type="section",
            title="By Staff",
            collapsible=True,
            children=[table],
        )
