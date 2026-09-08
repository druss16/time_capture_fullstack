"""
WIP lens — uninvoiced billable work, aged from the work date.
"""
from __future__ import annotations

from collections import defaultdict

from django.utils import timezone

from ..metrics.wip import (
    TIER_BILLABLE_READY, TIER_UNREVIEWED, WIP_FIELDS, block_age_days,
    block_amount, compute_wip_aging_bands, default_rate_for, unassigned_qs,
    wip_qs,
)
from ..types import (
    ChartCardPayload, DataTablePayload, MetricState, Scope, Section, TimeRange,
)
from .base import Lens, register_lens
from .helpers import column, headline_row


@register_lens("wip")
class WipLens(Lens):
    label = "WIP"

    def assemble(self, org, scope, time, compare=None):
        sections: list[Section] = []

        sections.append(headline_row(
            ["wip_total", "wip_unreviewed", "wip_aged_60_plus"],
            org, scope, time, compare,
            section_id="headline",
        ))

        sections.append(self._aging_chart_section(org, scope))

        if scope.is_firm() or scope.type == "composite":
            sections.append(self._top_clients_section(org, scope))
            # Billable time with no client can't be invoiced, so it isn't WIP —
            # but it mustn't disappear either. Only shown when there's something
            # to clear.
            unassigned = self._unassigned_section(org, scope)
            if unassigned is not None:
                sections.append(unassigned)

        return sections

    def _aging_chart_section(self, org, scope) -> Section:
        bands = compute_wip_aging_bands(org, scope)
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
            subtitle=f"Total ${total:,.0f} · aged from work date",
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
        default = default_rate_for(org)
        today = timezone.localdate()
        per_client: dict[int, dict] = defaultdict(
            lambda: {"name": "Unassigned", "wip": 0.0, "unreviewed": 0.0,
                     "oldest_days": 0}
        )

        def walk(tier: str, bucket: str, track_age: bool):
            qs = wip_qs(org, scope, tier).select_related("client").only(
                "client_id", "client__name", *WIP_FIELDS
            )
            for b in qs:
                cid = b.client_id or 0
                row = per_client[cid]
                row["name"] = b.client.name if b.client else "Unassigned"
                row[bucket] += block_amount(b, default)
                if track_age:
                    row["oldest_days"] = max(
                        row["oldest_days"], block_age_days(b, today)
                    )

        walk(TIER_BILLABLE_READY, "wip", track_age=True)
        walk(TIER_UNREVIEWED, "unreviewed", track_age=False)

        rows = [
            {
                "client_id": cid,
                "client_name": d["name"],
                "wip": round(d["wip"], 2),
                "unreviewed": round(d["unreviewed"], 2),
                "oldest_days": d["oldest_days"],
            }
            for cid, d in per_client.items()
        ]
        rows.sort(key=lambda r: -(r["wip"] + r["unreviewed"]))
        rows = rows[:20]

        table = DataTablePayload(
            id="wip_by_client",
            title="WIP by client",
            subtitle="Top 20",
            columns=[
                column("client_name", "Client", "text"),
                column("wip", "WIP $", "currency_0dp"),
                column("unreviewed", "Unreviewed $", "currency_0dp",
                       tooltip="Captured but not yet confirmed in Daily Review"),
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

    def _unassigned_section(self, org, scope) -> Section | None:
        """Who has billable time with no client attached.

        This is the backlog `wip_qs` correctly refuses to count as money owed.
        Grouped by person because that's who can fix it.
        """
        from django.contrib.auth import get_user_model

        default = default_rate_for(org)
        today = timezone.localdate()
        per_user: dict[int, dict] = defaultdict(
            lambda: {"amount": 0.0, "minutes": 0.0, "blocks": 0, "oldest_days": 0}
        )

        for b in unassigned_qs(org, scope).only("user_id", *WIP_FIELDS):
            row = per_user[b.user_id]
            row["amount"] += block_amount(b, default)
            row["minutes"] += float(b.minutes or 0)
            row["blocks"] += 1
            row["oldest_days"] = max(row["oldest_days"], block_age_days(b, today))

        if not per_user:
            return None

        User = get_user_model()
        names = {
            u.id: (f"{u.first_name} {u.last_name}".strip() or u.username)
            for u in User.objects.filter(id__in=per_user.keys())
            .only("id", "first_name", "last_name", "username")
        }

        rows = [
            {
                "user_id": uid,
                "staff_name": names.get(uid, f"User {uid}"),
                "amount": round(d["amount"], 2),
                "hours": round(d["minutes"] / 60.0, 2),
                "blocks": d["blocks"],
                "oldest_days": d["oldest_days"],
            }
            for uid, d in per_user.items()
        ]
        rows.sort(key=lambda r: -r["amount"])

        total = sum(r["amount"] for r in rows)
        hours = sum(r["hours"] for r in rows)
        blocks = sum(r["blocks"] for r in rows)

        table = DataTablePayload(
            id="wip_unassigned_by_staff",
            title="Billable time with no client",
            subtitle=(f"${total:,.0f} · {hours:,.1f} h · {blocks} blocks — "
                      f"not counted in WIP, because it can't be invoiced until "
                      f"someone assigns it"),
            columns=[
                column("staff_name", "Staff", "text"),
                column("amount", "Value $", "currency_0dp",
                       tooltip="What it would be worth once assigned"),
                column("hours", "Hours", "hours_1dp"),
                column("blocks", "Blocks", "number_0dp"),
                column("oldest_days", "Oldest", "days_1dp"),
            ],
            rows=rows,
            default_sort={"key": "amount", "direction": "desc"},
            state=MetricState.READY,
        )
        return Section(
            id="unassigned",
            type="section",
            title="Needs a Client",
            collapsible=True,
            children=[table],
        )
