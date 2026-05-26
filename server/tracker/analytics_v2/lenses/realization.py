"""
Realization lens — billing efficiency.
Headline is dollar realization (AICPA standard); secondary tile shows hours realization.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

from tracker.models import Block, Invoice

from ..types import (
    ChartCardPayload, DataTablePayload, MetricState, Scope, Section, TimeRange,
    to_float,
)
from .base import Lens, register_lens
from .helpers import column, headline_row


@register_lens("realization")
class RealizationLens(Lens):
    label = "Realization"
    
    def assemble(self, org, scope, time, compare=None):
        # If the firm has no invoices, realization is structurally undefined.
        # Frontend renders EmptyStateInvoiceless component off the meta.invoiceless flag.
        # Return empty sections so the frontend can take over the layout.
        from ..permissions import firm_invoices_here
        if not firm_invoices_here(org):
            return []
        
        sections: list[Section] = []
        
        sections.append(headline_row(
            ["realization_dollar", "realization_hours", "effective_rate"],
            org, scope, time, compare,
            section_id="headline",
        ))
        
        if scope.is_firm() or (scope.type == "composite"):
            sections.append(self._by_client_section(org, scope, time))
        
        return sections
    
    def _by_client_section(self, org, scope, time) -> Section:
        # Build per-client realization rows
        # Worked side
        default_rate = to_float(getattr(org, "billing_rate_default", 0))
        worked: dict[int, dict] = defaultdict(
            lambda: {"name": "", "hours": 0.0, "value": 0.0}
        )
        block_qs = (Block.objects
                    .filter(org=org, day__gte=time.start, day__lte=time.end,
                            is_billable=True, client__isnull=False)
                    .select_related("client"))
        for b in block_qs.only("client_id", "client__name", "minutes", "billing_amount", "billing_rate"):
            hours = to_float(b.minutes) / 60.0
            amount = to_float(b.billing_amount)
            if not amount:
                rate = to_float(b.billing_rate) or default_rate
                amount = hours * rate
            worked[b.client_id]["name"] = b.client.name if b.client else f"Client {b.client_id}"
            worked[b.client_id]["hours"] += hours
            worked[b.client_id]["value"] += amount
        
        # Invoiced side
        inv_qs = (Invoice.objects
                  .filter(org=org, invoice_date__gte=time.start,
                          invoice_date__lte=time.end, client__isnull=False)
                  .values("client_id", "client__name")
                  .annotate(
                      hours=Coalesce(Sum("hours_billed"), Decimal("0")),
                      amount=Coalesce(Sum("amount"), Decimal("0")),
                  ))
        invoiced: dict[int, dict] = {
            r["client_id"]: {
                "name": r["client__name"],
                "hours": to_float(r["hours"]),
                "amount": to_float(r["amount"]),
            } for r in inv_qs
        }
        
        rows = []
        for cid in set(invoiced) | set(worked):
            name = (invoiced.get(cid, {}).get("name")
                    or worked.get(cid, {}).get("name")
                    or f"Client {cid}")
            wh = worked.get(cid, {}).get("hours", 0.0)
            wv = worked.get(cid, {}).get("value", 0.0)
            bh = invoiced.get(cid, {}).get("hours", 0.0)
            ba = invoiced.get(cid, {}).get("amount", 0.0)
            
            hours_realiz = (bh / wh * 100) if wh > 0 else None
            dollar_realiz = (ba / wv * 100) if wv > 0 else None
            
            rows.append({
                "client_id": cid,
                "client_name": name,
                "worked_hours": round(wh, 2),
                "billed_hours": round(bh, 2),
                "worked_value": round(wv, 2),
                "billed_amount": round(ba, 2),
                "hours_realiz": round(hours_realiz, 1) if hours_realiz is not None else None,
                "dollar_realiz": round(dollar_realiz, 1) if dollar_realiz is not None else None,
                "gap_hours": round(wh - bh, 2),
            })
        
        # Sort by largest negative gap (worst leakage) at top
        rows.sort(key=lambda r: -((r["gap_hours"] or 0)))
        
        table = DataTablePayload(
            id="clients_realization",
            title="Realization by client",
            subtitle=time.label,
            columns=[
                column("client_name", "Client", "text"),
                column("worked_hours", "Worked", "hours_1dp"),
                column("billed_hours", "Billed", "hours_1dp"),
                column("gap_hours", "Gap", "hours_1dp"),
                column("hours_realiz", "Hours %", "percent_1dp"),
                column("dollar_realiz", "Dollar %", "percent_1dp"),
            ],
            rows=rows,
            default_sort={"key": "gap_hours", "direction": "desc"},
        )
        return Section(
            id="by_client",
            type="section",
            title="By Client",
            collapsible=True,
            children=[table],
        )
