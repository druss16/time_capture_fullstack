"""
Executive Overview — the landing view of Analytics.

What an owner should be able to answer without clicking anything:

    Are we capturing all our billable time?   → hours, billable mix, Insights
    What is the work worth?                   → Billable value, effective rate
    Are we making money on it?                → Labor cost, gross margin
    Which way is it moving?                   → Performance trend, vs comparison
    What should I look at?                    → Insights, then the top tables

Everything below the fold is a PREVIEW that drills into a dedicated view — the
top five clients, the team, where the time went. The full tables live in the
`clients`, `team` and `distribution` lenses so that the landing page stays one
screen of decisions rather than four screens of data.

Realization is shown only when the firm has actually imported invoices. With
none, "realized revenue ÷ billable value" has no numerator, and a 0% tile reads
as catastrophic billing performance rather than as missing data.
"""
from __future__ import annotations

from ..series import trend_chart
from ..types import Section
from .base import Lens, register_lens
from .helpers import kpi_tile

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

        tiles = [
            kpi_tile(mid, org, scope, time, compare, size="medium",
                     drilldown_lens=lens)
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
            sections.append(self._clients_preview(org, scope, time))
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
            id="insights", type="section", title="What to look at",
            children=cards,
        )

    # ── previews ────────────────────────────────────────────────────────────

    def _clients_preview(self, org, scope, time) -> Section:
        from ..breakdowns import breakdown, split_unassigned, unassigned_note
        from .clients import client_table

        rows, unassigned = split_unassigned(breakdown(org, scope, time, "client"))
        subtitle = (f"{time.label} · top {_PREVIEW_ROWS} by hours · "
                    "open Clients for the full list")
        note = unassigned_note(unassigned)
        if note:
            subtitle += f" · {note}"
        table = client_table(
            rows[:_PREVIEW_ROWS], time,
            table_id="overview_top_clients",
            title="Busiest clients",
            subtitle=subtitle,
        )
        return Section(id="clients_preview", type="section", children=[table])

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
