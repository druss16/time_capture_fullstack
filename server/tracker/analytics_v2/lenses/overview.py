"""
Executive Overview — the landing view of Analytics.

What an owner should be able to answer without clicking anything:

    Are we capturing all our billable time?   → hours, billable mix, Insights
    What is the work worth?                   → Billable value, effective rate
    Are we making money on it?                → Labor cost, gross margin
    Which way is it moving?                   → Performance trend, vs comparison
    What should I look at?                    → Intelligent Insights, then the top tables

Everything below the fold is a PREVIEW that drills into a dedicated view — the
most and least efficient clients, the team, where the time went. The full tables live in the
`clients`, `team` and `distribution` lenses so that the landing page stays one
screen of decisions rather than four screens of data.

Realization is shown only when the firm has actually imported invoices. With
none, "realized revenue ÷ billable value" has no numerator, and a 0% tile reads
as catastrophic billing performance rather than as missing data.
"""
from __future__ import annotations

from ..series import trend_chart
from ..types import ChartCardPayload, MetricState, Section
from .base import Lens, register_lens
from .helpers import kpi_tile, safe_sparklines

# The seven numbers a managing partner runs a firm on, in reading order:
# volume, then the billable share of it, then what it is worth, then what it
# cost, then what is left.
_KPIS: list[tuple[str, str | None]] = [
    ("total_hours", None),
    ("billable_hours", "distribution"),
    ("billable_mix", "team"),
    ("revenue", "profitability"),
    ("effective_rate", "profitability"),
    ("labor_cost", "profitability"),
    ("gross_margin", "profitability"),
]

# Only offered once invoices exist; see the module docstring.
_REALIZATION_KPI = ("realization_dollar", "realization")

_PREVIEW_ROWS = 5


def _low_efficiency_chart(rows, time, tail) -> ChartCardPayload:
    """The least efficient clients as ranked bars, worst at the top.

    A chart rather than a second copy of the client table: the question here
    is "how far behind are they", which a bar length answers at a glance.
    Bar clicks don't drill; the subtitle points at Clients for the detail.
    """
    data = [{"label": r["label"], "margin_pct": r["margin_pct"]} for r in rows]
    return ChartCardPayload(
        id="overview_low_efficiency_clients",
        title="Low Efficiency Clients",
        subtitle=f"{time.label} · bottom {len(data)} by margin % · {tail}",
        chart_type="horizontal_bar",
        x_key="label",
        data=data,
        series=[{"key": "margin_pct", "label": "Margin %", "role": "primary"}],
        value_format="percent_1dp",
        state=MetricState.READY if data else MetricState.EMPTY,
    )


@register_lens("overview")
class OverviewLens(Lens):
    label = "Overview"

    def assemble(self, org, scope, time, compare=None):
        from ..metrics.base import get_metric
        from ..permissions import firm_invoices_here

        sections: list[Section] = []
        invoiceless = not firm_invoices_here(org)

        kpis = list(_KPIS)
        if not invoiceless:
            kpis.append(_REALIZATION_KPI)

        sparks = safe_sparklines(org, scope, time)
        tiles = [
            kpi_tile(mid, org, scope, time, compare, size="medium",
                     drilldown_lens=lens, sparklines=sparks)
            for mid, lens in kpis
            if scope.type in get_metric(mid).valid_scopes
        ]
        sections.append(Section(id="headline", type="kpi_row", children=tiles))

        insights = self._insights_section(org, scope, time, invoiceless)
        if insights:
            sections.append(insights)

        sections.append(Section(
            id="trend", type="section", title="Performance trend",
            children=[trend_chart(org, scope, time)],
        ))

        if scope.type in ("firm", "composite"):
            sections.extend(self._clients_preview(org, scope, time))
            sections.append(self._team_preview(org, scope, time))

        return sections

    # ── insights ────────────────────────────────────────────────────────────

    def _insights_section(self, org, scope, time, invoiceless) -> Section | None:
        """Plain-English observations, above the charts that evidence them.

        The engine already existed and was wired only to `pulse`, a lens that
        was dropped from the menu — so every insight it produced had been
        unreachable from the UI. This puts them back in front of the person
        they were written for.
        """
        from ..insights.engine import generate_pulse_insights

        cards = generate_pulse_insights(org, scope, time, invoiceless=invoiceless)
        if not cards:
            return None
        return Section(
            id="insights", type="section", title="Intelligent Insights",
            children=cards,
        )

    # ── previews ────────────────────────────────────────────────────────────

    def _clients_preview(self, org, scope, time) -> list[Section]:
        """The most and least efficient clients, by margin %.

        Ranked over MATERIAL clients only: twenty minutes on a client yields a
        margin % with no information in it, and would otherwise crowd both
        lists with noise. A client appears in one list at most — with fewer
        than ten material clients the two would otherwise overlap.
        """
        from ..breakdowns import breakdown, held_out_note, split_client_rows
        from ..stats import partition_material
        from .clients import client_table

        rows, unassigned, internal = split_client_rows(
            breakdown(org, scope, time, "client"))
        material, _ = partition_material(
            rows, weight_key="hours", revenue_key="revenue",
            min_weight=1.0, min_revenue=250.0,
        )
        ranked = [r for r in material if r["margin_pct"] is not None]
        ranked.sort(key=lambda r: (-r["margin_pct"], -r["hours"]))

        high = ranked[:_PREVIEW_ROWS]
        high_ids = {r["id"] for r in high}
        low = [r for r in reversed(ranked) if r["id"] not in high_ids][:_PREVIEW_ROWS]

        note = held_out_note(unassigned, internal)
        tail = "open Clients for the full list" + (f" · {note}" if note else "")

        sections = [Section(id="clients_preview", type="section", children=[
            client_table(
                high, time,
                table_id="overview_high_efficiency_clients",
                title="High Efficiency Clients",
                subtitle=f"{time.label} · top {_PREVIEW_ROWS} by margin % · {tail}",
                sort_key="margin_pct", sort_direction="desc",
            ),
        ])]
        if low:
            sections.append(Section(id="clients_low_preview", type="section", children=[
                _low_efficiency_chart(low, time, tail),
            ]))
        return sections

    def _team_preview(self, org, scope, time) -> Section:
        from ..breakdowns import breakdown
        from .team import team_table

        rows = breakdown(org, scope, time, "user")
        table = team_table(
            org, rows[:_PREVIEW_ROWS], time,
            table_id="overview_team",
            title="Team",
            subtitle=f"{time.label} · top {_PREVIEW_ROWS} by hours · "
                     "open Team for capacity and the full list",
        )
        return Section(id="team_preview", type="section", children=[table])
