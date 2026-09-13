"""
Team Performance.

Objective operational data per person: what they tracked, how much of it was
billable, what it was worth, what it cost, and what was left. No ranking
language, no scoring, no "top performer" — the brief was explicit, and it is
also the only honest reading: a person on internal work by assignment is not
underperforming, and this table cannot tell the difference.

CAPACITY
--------
The capacity bar answers a different question from the billable-share column
and the two are easy to confuse, so both are shown:

    Billable %   billable ÷ tracked.     Of the time we saw, how much billed?
    Capacity %   billable ÷ scheduled.   Of the time available, how much billed?

Someone can be at 90% billable and 40% of capacity — fully billable on the work
they did, and only half-booked. That gap is the whole point of the section, and
one number cannot show it.

Staff whose cost tier is flagged non-chargeable (admin, ops) are listed but
held out of the firm utilization roll-up, matching the utilization lens.
"""
from __future__ import annotations

from ..breakdowns import breakdown
from ..types import (
    ChartCardPayload, DataTablePayload, MetricState, Section, TimeRange,
)
from .base import Lens, register_lens
from .helpers import column, kpi_tile


def team_columns() -> list[dict]:
    return [
        column("label", "Employee", "text"),
        column("hours", "Total hours", "hours_1dp"),
        column("billable_hours", "Billable hours", "hours_1dp"),
        column("billable_pct", "Billable %", "percent_1dp",
               tooltip="Billable hours ÷ tracked hours."),
        column("capacity_pct", "Capacity %", "percent_1dp",
               tooltip="Billable hours ÷ scheduled capacity for the period, "
                       "from the work calendar and time off."),
        column("revenue", "Billable value", "currency_0dp"),
        # Key must stay `cost` / `margin`: those are the names the cost
        # redactor strips for non-owners. A prettier key like
        # `contribution_margin` would sail straight past it.
        column("cost", "Estimated cost", "currency_0dp"),
        column("margin", "Contribution margin", "currency_0dp",
               tooltip="Billable value − estimated labor cost for this "
                       "person's own time."),
    ]


def team_table(org, rows: list[dict], time: TimeRange, *, table_id: str,
               title: str, subtitle: str) -> DataTablePayload:
    """Build the team table, adding capacity to the breakdown rows."""
    _add_capacity(org, rows, time)
    return DataTablePayload(
        id=table_id,
        title=title,
        subtitle=subtitle,
        columns=team_columns(),
        rows=rows,
        default_sort={"key": "hours", "direction": "desc"},
        row_drilldown={
            "scope_type": "staff", "lens": "team",
            "id_key": "id", "label_key": "label",
        },
        bar_columns=["hours"],
        state=MetricState.READY if rows else MetricState.EMPTY,
    )


def _add_capacity(org, rows: list[dict], time: TimeRange) -> None:
    """Annotate rows in place with `capacity_hours` and `capacity_pct`."""
    from ..capacity import capacity_hours_map

    ids = [r["id"] for r in rows if r["id"] is not None]
    caps = capacity_hours_map(org, ids, time.start, time.end) if ids else {}
    for r in rows:
        cap = caps.get(r["id"], 0.0)
        r["capacity_hours"] = round(cap, 1)
        # None rather than 0 when we don't know someone's schedule: a 0% here
        # would read as "did no billable work", when it means "we have no
        # calendar for this person to measure against".
        r["capacity_pct"] = (
            round(r["billable_hours"] / cap * 100, 1) if cap > 0 else None
        )


@register_lens("team")
class TeamLens(Lens):
    label = "Team"

    def assemble(self, org, scope, time, compare=None):
        from ..metrics.base import get_metric

        sections: list[Section] = []

        tiles = [
            kpi_tile(mid, org, scope, time, compare, size="medium")
            for mid in ("total_hours", "billable_hours", "billable_mix",
                        "billable_utilization", "revenue", "labor_cost")
            if scope.type in get_metric(mid).valid_scopes
        ]
        sections.append(Section(id="headline", type="kpi_row", children=tiles))

        if scope.type == "staff":
            return sections + self._person_detail(org, scope, time)

        rows = breakdown(org, scope, time, "user")
        table = team_table(
            org, rows, time,
            table_id="team_rows",
            title="By person",
            subtitle=f"{time.label} · {len(rows)} people",
        )
        sections.append(Section(
            id="team_table", type="section", title="Team performance",
            children=[self._capacity_chart(rows, time), table],
        ))
        return sections

    # ── capacity picture ────────────────────────────────────────────────────

    def _capacity_chart(self, rows: list[dict], time: TimeRange) -> ChartCardPayload:
        """Billable vs the rest of tracked time, one bar per person.

        A ranked bar, not a donut: the question is "who has room and who is
        full", which is a comparison between people, and a stacked bar answers
        it at a glance where a ring of wedges does not.
        """
        data = [
            {
                "label": r["label"],
                "billable_hours": r["billable_hours"],
                "other_hours": round(max(r["hours"] - r["billable_hours"], 0), 2),
                "capacity_hours": r.get("capacity_hours") or 0,
            }
            for r in sorted(rows, key=lambda x: -x["hours"])
        ]
        return ChartCardPayload(
            id="team_capacity",
            title="Where each person's tracked time went",
            subtitle=f"{time.label} · billable vs everything else tracked",
            chart_type="stacked_bar",
            x_key="label",
            data=data,
            series=[
                {"key": "billable_hours", "label": "Billable"},
                {"key": "other_hours", "label": "Other tracked"},
            ],
            value_format="hours_1dp",
            state=MetricState.READY if data else MetricState.EMPTY,
        )

    # ── one person ──────────────────────────────────────────────────────────

    def _person_detail(self, org, scope, time) -> list[Section]:
        from ..breakdowns import held_out_note, split_client_rows
        from ..series import trend_chart
        from .clients import client_table, flag_rows

        sections = [Section(
            id="person_trend", type="section", title="Over time",
            children=[trend_chart(org, scope, time, card_id="person_trend")],
        )]

        rows, unassigned, internal = split_client_rows(
            breakdown(org, scope, time, "client"))
        if rows:
            flag_rows(rows, None)
            subtitle = f"{time.label} · this person's time only"
            note = held_out_note(unassigned, internal)
            if note:
                subtitle += f" · {note}"
            sections.append(Section(
                id="person_clients", type="section", title="Clients worked on",
                children=[client_table(
                    rows, time,
                    table_id="person_clients_table",
                    title="Clients",
                    subtitle=subtitle,
                )],
            ))

        cat = breakdown(org, scope, time, "category")
        if cat:
            sections.append(Section(
                id="person_categories", type="section", title="Categories",
                children=[DataTablePayload(
                    id="person_by_category",
                    title="What they worked on",
                    subtitle=time.label,
                    columns=[
                        column("label", "Category", "text"),
                        column("hours", "Hours", "hours_1dp"),
                        column("share", "Share", "percent_1dp"),
                        column("billable_pct", "Billable %", "percent_1dp"),
                    ],
                    rows=cat,
                    default_sort={"key": "hours", "direction": "desc"},
                    bar_columns=["hours"],
                    state=MetricState.READY,
                )],
            ))
        return sections
