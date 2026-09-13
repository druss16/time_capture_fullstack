"""
Where Time Goes — the firm's time distributed across the dimensions that
explain it: client, project, category, and billable vs not.

Ranked horizontal bars, not pie charts. The question is "what is biggest, and
by how much" — a ranked bar answers that by length, reading top to bottom, at
any number of rows. A pie answers it by angle, which people read badly beyond
about five wedges, and a CPA firm has three hundred clients.

The one exception is the billable split, which genuinely is a part-to-whole
with two parts. That gets a single proportion bar, because the whole question
there is "how much of the total", and the ranking framing has nothing to rank.
"""
from __future__ import annotations

from ..breakdowns import breakdown, held_out_note, split_client_rows
from ..types import (
    ChartCardPayload, DataTablePayload, MetricState, Section,
)
from .base import Lens, register_lens
from .helpers import column

# Rows in a ranked bar before the tail is folded into one row. Past this a bar
# chart stops being scannable and the table underneath is the better tool.
_BAR_ROWS = 12

_DIMENSIONS = [
    ("client", "By client", "Client", "clients", "client"),
    ("project", "By project", "Project", None, None),
    ("category", "By category", "Category", None, None),
]


@register_lens("distribution")
class DistributionLens(Lens):
    label = "Where time goes"

    def assemble(self, org, scope, time, compare=None):
        # Each dimension is aggregated once and used twice — the bar chart and
        # the table below it are two renderings of the same rows.
        rows_by_dim = {
            dim: breakdown(org, scope, time, dim)
            for dim, *_ in _DIMENSIONS
        }
        # Neither "No client assigned" nor the firm's own internal work is a
        # client, so both are held out here exactly as in the Clients view.
        # "No project" and "Uncategorized" DO stay: unlike a missing client
        # they are ordinary states for real work, and on a "where does the time
        # go" page they are part of the answer.
        rows_by_dim["client"], unassigned, internal = split_client_rows(
            rows_by_dim["client"])
        self._held_out_note = held_out_note(unassigned, internal)

        children = [
            self._dimension_card(dim, tab_title, noun, rows_by_dim[dim], time)
            for dim, tab_title, noun, _, _ in _DIMENSIONS
        ]
        children.append(self._billable_card(org, scope, time))

        return [
            Section(
                id="where_time_goes", type="section", title="Where time goes",
                tabbed=True, children=children,
            ),
            # The table under the tabs carries the numbers the bars only imply.
            Section(
                id="where_time_goes_detail", type="section", tabbed=True,
                children=[
                    self._dimension_table(dim, tab_title, noun,
                                          rows_by_dim[dim], time,
                                          drill_lens, drill_scope)
                    for dim, tab_title, noun, drill_lens, drill_scope in _DIMENSIONS
                ],
            ),
        ]

    # ── ranked bars ─────────────────────────────────────────────────────────

    def _dimension_card(self, dim, tab_title, noun, rows, time) -> ChartCardPayload:
        top = rows[:_BAR_ROWS]
        tail = rows[_BAR_ROWS:]
        data = [{"label": r["label"], "hours": r["hours"],
                 "billable_hours": r["billable_hours"],
                 "share": r["share"]} for r in top]
        if tail:
            # Kept as a row rather than dropped: the tail is often a large
            # share of the total, and a chart that silently omits it invites
            # the reader to add the visible bars up and believe the answer.
            tail_hours = round(sum(r["hours"] for r in tail), 2)
            data.append({
                "label": f"+ {len(tail)} more",
                "hours": tail_hours,
                "billable_hours": round(
                    sum(r["billable_hours"] for r in tail), 2),
                "share": round(sum(r["share"] for r in tail), 1),
            })

        total = round(sum(r["hours"] for r in rows), 1)
        subtitle = (f"{time.label} · {len(rows)} {noun.lower()}(s) · "
                    f"{total:,.1f} h total")
        note = getattr(self, "_held_out_note", "") if dim == "client" else ""
        if note:
            subtitle += f" · {note}"
        return ChartCardPayload(
            id=f"where_{dim}",
            title=tab_title,
            subtitle=subtitle,
            chart_type="horizontal_bar",
            x_key="label",
            data=data,
            series=[{"key": "hours", "label": "Hours"}],
            value_format="hours_1dp",
            state=MetricState.READY if data else MetricState.EMPTY,
        )

    def _dimension_table(self, dim, tab_title, noun, rows, time,
                         drill_lens, drill_scope) -> DataTablePayload:
        drill = None
        if drill_lens and drill_scope:
            drill = {"scope_type": drill_scope, "lens": drill_lens,
                     "id_key": "id", "label_key": "label"}
        note = getattr(self, "_held_out_note", "") if dim == "client" else ""
        return DataTablePayload(
            id=f"where_{dim}_table",
            title=tab_title,
            subtitle=f"{time.label} · {note}" if note else time.label,
            columns=[
                column("label", noun, "text"),
                column("hours", "Hours", "hours_1dp"),
                column("share", "Share of time", "percent_1dp"),
                column("billable_hours", "Billable", "hours_1dp"),
                column("billable_pct", "Billable %", "percent_1dp"),
                column("people", "People", "integer"),
            ],
            rows=rows,
            default_sort={"key": "hours", "direction": "desc"},
            row_drilldown=drill,
            bar_columns=["hours"],
            state=MetricState.READY if rows else MetricState.EMPTY,
        )

    # ── billable split ──────────────────────────────────────────────────────

    def _billable_card(self, org, scope, time) -> ChartCardPayload:
        """Billable vs non-billable, and what the non-billable half actually is.

        "Non-billable" on its own is not actionable — a firm cannot tell from
        one number whether it is losing money or running itself. Splitting it
        by category is what turns it into a decision.
        """
        from ..blocks import billable_q, confirmed_qs
        from ..metrics.base import apply_scope
        from django.db.models import Sum
        from django.db.models.functions import Coalesce
        from tracker.models import Block
        from ..types import to_float

        qs = confirmed_qs(apply_scope(
            Block.objects.filter(org=org, day__gte=time.start, day__lte=time.end),
            scope,
        ))
        rows = (qs.values("task_type__name")
                  .annotate(
                      billable_min=Coalesce(Sum("minutes", filter=billable_q(org)), 0),
                      total_min=Coalesce(Sum("minutes"), 0))
                  .order_by())

        billable_h = non_billable_h = 0.0
        non_billable_by_cat: dict[str, float] = {}
        for r in rows:
            b = to_float(r["billable_min"]) / 60.0
            nb = (to_float(r["total_min"]) - to_float(r["billable_min"])) / 60.0
            billable_h += b
            non_billable_h += nb
            if nb > 0:
                name = r["task_type__name"] or "Uncategorized"
                non_billable_by_cat[name] = non_billable_by_cat.get(name, 0.0) + nb

        total = billable_h + non_billable_h
        data = [
            {"label": "Billable", "hours": round(billable_h, 2),
             "share": round(billable_h / total * 100, 1) if total else 0.0},
            {"label": "Non-billable", "hours": round(non_billable_h, 2),
             "share": round(non_billable_h / total * 100, 1) if total else 0.0},
        ]
        data += [
            {"label": f"  ↳ {name}", "hours": round(h, 2),
             "share": round(h / total * 100, 1) if total else 0.0}
            for name, h in sorted(non_billable_by_cat.items(),
                                  key=lambda kv: -kv[1])[:_BAR_ROWS]
        ]

        return ChartCardPayload(
            id="where_billable",
            title="Billable vs non-billable",
            subtitle=f"{time.label} · non-billable broken out by category",
            chart_type="horizontal_bar",
            x_key="label",
            data=data,
            series=[{"key": "hours", "label": "Hours"}],
            value_format="hours_1dp",
            hero=f"{(billable_h / total * 100):.1f}%" if total else None,
            hero_label="of tracked time is billable",
            state=MetricState.READY if total > 0 else MetricState.EMPTY,
        )
