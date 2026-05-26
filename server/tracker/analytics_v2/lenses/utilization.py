"""
Utilization lens — staff billable share of tracked time.
"""
from __future__ import annotations

from collections import defaultdict
from django.contrib.auth import get_user_model
from django.db.models import Sum

from tracker.models import Block

from ..types import (
    ChartCardPayload, DataTablePayload, MetricState, Scope, Section, TimeRange,
    to_float,
)
from .base import Lens, register_lens
from .helpers import column, headline_row

User = get_user_model()


@register_lens("utilization")
class UtilizationLens(Lens):
    label = "Utilization"
    
    def assemble(self, org, scope, time, compare=None):
        sections: list[Section] = []
        sections.append(headline_row(
            ["billable_utilization", "billable_hours", "total_hours"],
            org, scope, time, compare,
            section_id="headline",
        ))
        
        # Always show per-staff breakdown unless scoped to a single staff
        if scope.type != "staff" or len(scope.ids) > 1:
            sections.append(self._by_staff_section(org, scope, time))
        
        return sections
    
    def _by_staff_section(self, org, scope, time) -> Section:
        qs = Block.objects.filter(org=org, day__gte=time.start, day__lte=time.end)
        
        # Apply scope minus the staff dimension (we want the per-staff breakdown)
        if scope.type == "client":
            qs = qs.filter(client_id__in=scope.ids)
        elif scope.type == "service":
            qs = qs.filter(task_type_id__in=scope.ids)
        elif scope.type == "composite":
            for dim, ids in scope.filters.items():
                if not ids:
                    continue
                if dim == "client":
                    qs = qs.filter(client_id__in=ids)
                elif dim == "service":
                    qs = qs.filter(task_type_id__in=ids)
        elif scope.type == "staff":
            qs = qs.filter(user_id__in=scope.ids)
        
        per_user: dict[int, dict] = defaultdict(lambda: {"billable": 0.0, "total": 0.0})
        for b in qs.only("user_id", "minutes", "is_billable"):
            mins = to_float(b.minutes)
            per_user[b.user_id]["total"] += mins
            if b.is_billable:
                per_user[b.user_id]["billable"] += mins
        
        names = {u.id: (f"{u.first_name} {u.last_name}".strip() or u.username)
                 for u in User.objects.filter(id__in=per_user.keys())
                 .only("id", "first_name", "last_name", "username")}
        
        rows = []
        for uid, d in per_user.items():
            bh = d["billable"] / 60.0
            th = d["total"] / 60.0
            util = (bh / th * 100) if th > 0 else 0.0
            rows.append({
                "user_id": uid,
                "name": names.get(uid, f"User {uid}"),
                "billable_hours": round(bh, 2),
                "total_hours": round(th, 2),
                "utilization": round(util, 1),
            })
        rows.sort(key=lambda r: -r["utilization"])
        
        table = DataTablePayload(
            id="staff_utilization",
            title="Utilization by staff",
            subtitle=time.label,
            columns=[
                column("name", "Name", "text"),
                column("billable_hours", "Billable", "hours_1dp"),
                column("total_hours", "Total", "hours_1dp"),
                column("utilization", "Utilization", "percent_1dp"),
            ],
            rows=rows,
            default_sort={"key": "utilization", "direction": "desc"},
            state=MetricState.READY if rows else MetricState.EMPTY,
        )
        return Section(
            id="by_staff",
            type="section",
            title="By Staff",
            collapsible=True,
            children=[table],
        )
