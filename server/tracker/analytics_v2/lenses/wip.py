"""
WIP lens — approved-but-uninvoiced work, aged.
"""
from __future__ import annotations

from collections import defaultdict
from django.utils import timezone

from tracker.models import Block

from ..metrics.wip import compute_wip_aging_bands
from ..types import (
    ChartCardPayload, DataTablePayload, MetricState, Scope, Section, TimeRange,
    to_float,
)
from .base import Lens, register_lens
from .helpers import column, headline_row


@register_lens("wip")
class WipLens(Lens):
    label = "WIP"
    
    def assemble(self, org, scope, time, compare=None):
        sections: list[Section] = []
        
        sections.append(headline_row(
            ["wip_total", "wip_aged_60_plus"],
            org, scope, time, compare,
            section_id="headline",
        ))
        
        sections.append(self._aging_chart_section(org, scope))
        
        if scope.is_firm() or scope.type == "composite":
            sections.append(self._top_clients_section(org, scope))
        
        return sections
    
    def _aging_chart_section(self, org, scope) -> Section:
        from .base import Lens as _L
        # We need a Metric-style object to apply scope; reuse the base helper
        class _Helper:
            def _apply_scope(self, qs, scope_):
                from ..metrics.base import Metric as _M
                return _M()._apply_scope(qs, scope_)
        
        bands = compute_wip_aging_bands(org, scope, _Helper())
        total = sum(bands.values())
        
        data = [
            {"band": "0-30 days", "value": bands["0_30"]},
            {"band": "31-60 days", "value": bands["31_60"]},
            {"band": "61-90 days", "value": bands["61_90"]},
            {"band": "90+ days", "value": bands["90_plus"]},
        ]
        
        chart = ChartCardPayload(
            id="wip_aging",
            title="WIP aging",
            subtitle=f"Total ${total:,.0f}",
            chart_type="wip_aging",
            data=data,
            series=[{"key": "value", "label": "Amount"}],
            state=MetricState.READY if total > 0 else MetricState.EMPTY,
        )
        return Section(
            id="aging",
            type="section",
            title="Aging",
            collapsible=False,
            children=[chart],
        )
    
    def _top_clients_section(self, org, scope) -> Section:
        qs = Block.objects.filter(
            org=org, approved=True, invoiced=False, is_billable=True,
        )
        # Apply non-firm filters if any (composite mode)
        if scope.type == "composite":
            for dim, ids in scope.filters.items():
                if not ids:
                    continue
                if dim == "client":
                    qs = qs.filter(client_id__in=ids)
                elif dim == "staff":
                    qs = qs.filter(user_id__in=ids)
        
        default = to_float(getattr(org, "billing_rate_default", 0))
        now = timezone.now()
        per_client: dict[int, dict] = defaultdict(
            lambda: {"name": "Unassigned", "total": 0.0, "oldest_days": 0}
        )
        
        for b in qs.select_related("client").only(
            "client_id", "client__name", "minutes", "billing_amount",
            "billing_rate", "approved_at", "start"
        ):
            cid = b.client_id or 0
            name = b.client.name if b.client else "Unassigned"
            amount = to_float(b.billing_amount)
            if not amount:
                hours = to_float(b.minutes) / 60.0
                rate = to_float(b.billing_rate) or default
                amount = hours * rate
            ref = b.approved_at or b.start
            if ref:
                if timezone.is_naive(ref):
                    ref = timezone.make_aware(ref)
                age = max(0, (now - ref).days)
            else:
                age = 0
            per_client[cid]["name"] = name
            per_client[cid]["total"] += amount
            per_client[cid]["oldest_days"] = max(per_client[cid]["oldest_days"], age)
        
        rows = []
        for cid, d in per_client.items():
            rows.append({
                "client_id": cid,
                "client_name": d["name"],
                "wip": round(d["total"], 2),
                "oldest_days": d["oldest_days"],
            })
        rows.sort(key=lambda r: -r["wip"])
        rows = rows[:20]
        
        table = DataTablePayload(
            id="wip_by_client",
            title="WIP by client",
            subtitle="Top 20",
            columns=[
                column("client_name", "Client", "text"),
                column("wip", "WIP $", "currency_0dp"),
                column("oldest_days", "Oldest", "days_1dp"),
            ],
            rows=rows,
            default_sort={"key": "wip", "direction": "desc"},
            state=MetricState.READY if rows else MetricState.EMPTY,
        )
        return Section(
            id="by_client",
            type="section",
            title="By Client",
            collapsible=True,
            children=[table],
        )
