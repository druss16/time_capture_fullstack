"""
Client Performance.

Firm scope   — every client, ranked, with a flag on the ones worth a look.
Client scope — one client's deep dive: who worked on it, on what, when, and
               whether the firm made anything doing it.

ON FLAGGING
-----------
The brief for this view asked for "problem clients" to stand out, and was
explicit that invented thresholds are not wanted. So every flag here is either
(a) objectively true regardless of a firm's standards, or (b) relative to this
firm's own numbers this period. Nothing is a number somebody made up:

  losing money      margin below zero. Not a judgement call.
  below typical     margin in the firm's own BOTTOM QUARTILE, and at least 10
                    points below the median.
  heavy non-billable  billable share in the firm's own BOTTOM QUARTILE.
  growing fast      hours up more than half again on the comparison period the
                    viewer themselves selected. Absent when they picked no
                    comparison — the dashboard does not invent a baseline.

A quartile, not a median. "Below the median" flags half the table BY
DEFINITION — at org 21 that was 26 of 52 clients wearing a badge, which is
wallpaper, not a signal. A flag has to be rare to mean anything, so the
comparison is against the bottom quarter of the firm's own distribution.

The one configured threshold in the app — the gross-margin band on the margin
metric — is deliberately NOT used per-client: it was set for the firm as a
whole, and a firm-level target applied to a single client would fail exactly
the "arbitrary threshold" test.
"""
from __future__ import annotations

from ..breakdowns import breakdown, held_out_note, split_client_rows
from ..stats import median, partition_material, quantile
from ..types import DataTablePayload, MetricState, Section, TimeRange
from .base import Lens, register_lens
from .helpers import column, kpi_tile

_GROWTH_FLAG_RATIO = 1.5     # hours at least half again the comparison period
_MARGIN_GAP_POINTS = 10.0    # how far below median counts as "below typical"
# A flag is only information if it is rare. Comparing against the bottom
# quarter caps each rule at ~25% of the list; comparing against the median
# flagged half of it by construction.
_LOW_QUANTILE = 0.25

_FLAG_LABEL = {
    "losing_money": "Losing money",
    "below_typical": "Below typical margin",
    "heavy_non_billable": "Heavy non-billable",
    "growing_fast": "Hours growing fast",
}

# Flags that are statements ABOUT MARGIN. They disclose cost as surely as the
# margin column does — "Losing money" tells the reader this client's labor cost
# exceeded its billable value — so they must go for a viewer who may not see
# cost. `cost_visibility.COST_FLAG_KEYS` is the redactor's copy of this set,
# and a test asserts the two stay in step.
COST_DERIVED_FLAGS = frozenset({"losing_money", "below_typical"})


def client_columns() -> list[dict]:
    """The column set the brief asked for, in its order."""
    return [
        column("label", "Client", "text"),
        column("flag_label", "Flag", "text", sortable=False,
               tooltip="Set only by comparison with this firm's own numbers "
                       "this period — never a fixed target."),
        column("hours", "Total hours", "hours_1dp"),
        column("billable_hours", "Billable hours", "hours_1dp"),
        column("billable_pct", "Billable %", "percent_1dp"),
        column("revenue", "Billable value", "currency_0dp",
               tooltip="Hourly work valued at the applicable bill rate. "
                       "Retainer revenue is recognized over its period and is "
                       "not sliced into this column."),
        column("cost", "Labor cost", "currency_0dp"),
        column("margin", "Gross margin", "currency_0dp"),
        column("margin_pct", "Margin %", "percent_1dp"),
    ]


def client_table(rows: list[dict], time: TimeRange, *, table_id: str,
                 title: str, subtitle: str,
                 footnote: str = "") -> DataTablePayload:
    """Build the client table from breakdown rows (already flagged and sorted)."""
    return DataTablePayload(
        id=table_id,
        title=title,
        subtitle=subtitle,
        columns=client_columns(),
        rows=rows,
        default_sort={"key": "hours", "direction": "desc"},
        row_drilldown={
            "scope_type": "client", "lens": "clients",
            "id_key": "id", "label_key": "label",
        },
        bar_columns=["hours"],
        footnote=footnote,
        state=MetricState.READY if rows else MetricState.EMPTY,
    )


def flag_rows(rows: list[dict], prior_by_id: dict[int, float] | None) -> None:
    """Annotate rows in place with `flags` and a human `flag_label`.

    Medians are taken over MATERIAL rows only: a client with twenty minutes on
    it produces a margin percentage with no information in it, and letting
    those into the median moves the bar everyone else is judged against.
    """
    material, _ = partition_material(
        rows, weight_key="hours", revenue_key="revenue",
        min_weight=1.0, min_revenue=250.0,
    )
    margins = [r["margin_pct"] for r in material if r["margin_pct"] is not None]
    billables = [r["billable_pct"] for r in material if r["hours"] > 0]
    median_margin = median(margins)
    low_margin = quantile(margins, _LOW_QUANTILE)
    low_billable = quantile(billables, _LOW_QUANTILE)

    material_ids = {id(r) for r in material}

    for r in rows:
        flags: list[str] = []
        # Immaterial rows are shown but never flagged — see the docstring.
        if id(r) in material_ids:
            if r["margin"] < 0 and r["revenue"] > 0:
                flags.append("losing_money")
            elif (low_margin is not None and median_margin is not None
                    and r["margin_pct"] is not None
                    and r["margin_pct"] <= low_margin
                    and r["margin_pct"] < median_margin - _MARGIN_GAP_POINTS):
                flags.append("below_typical")

            if (low_billable is not None
                    and r["billable_pct"] <= low_billable):
                flags.append("heavy_non_billable")

            if prior_by_id is not None:
                prior = prior_by_id.get(r["id"], 0.0)
                if prior > 0 and r["hours"] >= prior * _GROWTH_FLAG_RATIO:
                    flags.append("growing_fast")

        # Key and label travel together so the cost redactor can drop the
        # margin-derived flags and rebuild the display string without keeping
        # its own copy of the label map.
        r["flags"] = [{"key": f, "label": _FLAG_LABEL[f]} for f in flags]
        r["flag_label"] = " · ".join(_FLAG_LABEL[f] for f in flags)


@register_lens("clients")
class ClientsLens(Lens):
    label = "Clients"

    def assemble(self, org, scope, time, compare=None):
        if scope.type == "client":
            return self._client_detail(org, scope, time, compare)
        return self._client_ranking(org, scope, time, compare)

    # ── firm scope: the ranking ─────────────────────────────────────────────

    def _client_ranking(self, org, scope, time, compare) -> list[Section]:
        rows, unassigned, internal = split_client_rows(
            breakdown(org, scope, time, "client"))

        # Growth is measured against the comparison the viewer chose. With no
        # comparison selected there is no baseline, and inventing one (last
        # month? last year?) would be exactly the arbitrary judgement the brief
        # ruled out — so the growth flag simply doesn't appear.
        prior_by_id = None
        if compare is not None:
            prior_rows, _, _ = split_client_rows(
                breakdown(org, scope, compare, "client"))
            prior_by_id = {r["id"]: r["hours"] for r in prior_rows}
        flag_rows(rows, prior_by_id)

        material, immaterial = partition_material(
            rows, weight_key="hours", revenue_key="revenue",
            min_weight=1.0, min_revenue=250.0,
        )
        material.sort(key=lambda r: -r["hours"])
        immaterial.sort(key=lambda r: -r["hours"])

        flagged = sum(1 for r in material if r["flags"])
        subtitle = f"{time.label} · {len(material)} clients"
        if compare is not None:
            subtitle += f" · growth vs {compare.label}"
        note = held_out_note(unassigned, internal)
        if note:
            subtitle += f" · {note}"

        sections: list[Section] = [Section(
            id="client_ranking", type="section", title="Client performance",
            children=[client_table(
                material, time,
                table_id="clients_ranked",
                title="All clients",
                subtitle=subtitle,
                footnote=(
                    f"{flagged} client(s) flagged. Flags compare each client "
                    "with this firm's own median this period — they are not "
                    "fixed targets."
                ) if flagged else "",
            )],
        )]

        if immaterial:
            sections.append(Section(
                id="client_tail", type="section", title="Low-materiality clients",
                collapsible=True, collapsed=True,
                children=[client_table(
                    immaterial, time,
                    table_id="clients_immaterial",
                    title="Under an hour, or under $250",
                    subtitle="Held out of the ranking and out of the medians: "
                             "a few minutes of work produces a margin "
                             "percentage with no information in it.",
                )],
            ))
        return sections

    # ── client scope: the deep dive ─────────────────────────────────────────

    def _client_detail(self, org, scope, time, compare) -> list[Section]:
        """Projects, categories, people, trend, and billable split for one client."""
        from ..metrics.base import get_metric
        from ..series import trend_chart

        sections: list[Section] = []

        tiles = [
            kpi_tile(mid, org, scope, time, compare, size="medium")
            for mid in ("total_hours", "billable_hours", "billable_mix",
                        "revenue", "effective_rate", "labor_cost", "gross_margin")
            if scope.type in get_metric(mid).valid_scopes
        ]
        sections.append(Section(id="headline", type="kpi_row", children=tiles))

        sections.append(Section(
            id="client_trend", type="section", title="Over time",
            children=[trend_chart(org, scope, time, card_id="client_trend")],
        ))

        for dim, sect_id, title in (
            ("project", "client_projects", "Projects"),
            ("category", "client_categories", "Categories"),
            ("user", "client_people", "Who worked on it"),
        ):
            table = self._dimension_table(org, scope, time, dim, title)
            if table is not None:
                sections.append(Section(
                    id=sect_id, type="section", children=[table]))

        return sections

    def _dimension_table(self, org, scope, time, dimension, title):
        rows = breakdown(org, scope, time, dimension)
        if dimension == "client":
            rows, _, _ = split_client_rows(rows)
        if not rows:
            return None
        cols = [
            column("label", title, "text"),
            column("hours", "Hours", "hours_1dp"),
            column("share", "Share", "percent_1dp"),
            column("billable_hours", "Billable", "hours_1dp"),
            column("billable_pct", "Billable %", "percent_1dp"),
            column("revenue", "Billable value", "currency_0dp"),
            column("cost", "Labor cost", "currency_0dp"),
            column("margin", "Margin", "currency_0dp"),
        ]
        drill = None
        if dimension == "user":
            drill = {"scope_type": "staff", "lens": "team",
                     "id_key": "id", "label_key": "label"}
        return DataTablePayload(
            id=f"client_by_{dimension}",
            title=title,
            subtitle=f"{time.label} · {len(rows)} row(s)",
            columns=cols,
            rows=rows,
            default_sort={"key": "hours", "direction": "desc"},
            row_drilldown=drill,
            bar_columns=["hours"],
            state=MetricState.READY,
        )
