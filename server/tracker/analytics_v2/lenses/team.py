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

NEEDS REVIEW
------------
A manager's first question about a person's time is often not "how billable"
but "are they behind on reviewing it". Every person row carries their open
Needs You count, the Team view charts it, and narrowing to people (a staff
scope or an Employee filter) lists the items themselves, oldest first. The
items are counted by `metrics.attribution` with the same predicate Daily Review
uses, so the number here is the number that person sees.
"""
from __future__ import annotations

from ..breakdowns import breakdown
from ..types import (
    ChartCardPayload, DataTablePayload, KPITile, MetricState, MetricValue,
    Section, TimeRange,
)
from .base import Lens, register_lens
from .helpers import column, kpi_tile, safe_sparklines


# Rings read well side by side up to about two rows of them.
_RING_MAX_PEOPLE = 8


def team_columns() -> list[dict]:
    return [
        column("label", "Employee", "text"),
        # Same basis as the Total Hours / Utilization tiles (see breakdowns).
        column("hours", "Total hours", "hours_1dp",
               tooltip="Confirmed working time. Idle/lock time and internal, "
                       "flat-fee and non-billable client time excluded, as in "
                       "the Total Hours tile."),
        column("billable_hours", "Billable hours", "hours_1dp"),
        column("billable_pct", "Billable %", "percent_1dp",
               tooltip="Billable hours ÷ total hours — the same as the "
                       "Utilization tile, per person."),
        column("capacity_pct", "Capacity %", "percent_1dp",
               tooltip="Billable hours ÷ scheduled capacity for the period, "
                       "from the work calendar and time off."),
        column("needs_review", "Needs review", "integer",
               tooltip="Open Needs You items in this period — time the person "
                       "still has to confirm in Daily Review."),
        column("needs_review_hours", "Hours waiting", "hours_1dp",
               tooltip="Hours of those open Needs You items — the per-person "
                       "share of the Hours Waiting on You tile."),
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
    """Build the team table, adding capacity and open review items to the rows."""
    _add_capacity(org, rows, time)
    _add_needs_review(org, rows, time)
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


def _add_needs_review(org, rows: list[dict], time: TimeRange) -> None:
    """Annotate rows in place with `needs_review` (open Needs You items) and
    `needs_review_hours` (their hours).

    None when the queue can't be measured (too large for the window): a blank
    cell, not a reassuring 0.
    """
    from ..metrics.attribution import needs_you, needs_you_hours_by_user

    try:
        by_user = needs_you(org.id, time)[3]
        hours = needs_you_hours_by_user(org.id, time)
    except Exception:
        for r in rows:
            r["needs_review"] = None
            r["needs_review_hours"] = None
        return
    for r in rows:
        r["needs_review"] = by_user.get(r["id"], 0)
        r["needs_review_hours"] = round(hours.get(r["id"], 0.0), 2)


def scoped_user_ids(scope) -> set[int] | None:
    """The people a view is narrowed to — a staff scope or an Employee filter —
    or None when it covers everyone."""
    if scope.type == "staff":
        return set(scope.ids)
    staff = (scope.filters or {}).get("staff")
    return set(staff) if staff else None


def needs_review_chart(org, scope, time: TimeRange) -> ChartCardPayload | None:
    """Open Needs You items per person, most behind first."""
    from ..breakdowns import _label_users
    from ..metrics.attribution import needs_you, needs_you_hours_by_user

    try:
        by_user = needs_you(org.id, time)[3]
        hours = needs_you_hours_by_user(org.id, time)
    except Exception:
        return None
    only = scoped_user_ids(scope)
    if only is not None:
        by_user = {u: n for u, n in by_user.items() if u in only}
    acc = {uid: {"label": None} for uid in by_user}
    _label_users(org, acc)
    data = sorted(
        ({"label": acc[uid]["label"] or f"User {uid}",
          "items": n, "hours": round(hours.get(uid, 0.0), 1)}
         for uid, n in by_user.items()),
        key=lambda d: -d["items"],
    )
    # One person is a number, not a chart: a single full-width bar says
    # nothing the stat tiles above it don't. The chart is for comparing people.
    if len(data) < 2:
        return None
    total = sum(d["items"] for d in data)
    return ChartCardPayload(
        id="team_needs_review",
        title="Waiting for review, by person",
        subtitle=(f"{time.label} · {total:,} open Needs You item"
                  f"{'' if total == 1 else 's'} · most behind first"
                  if data else f"{time.label} · nothing waiting — everyone is caught up"),
        chart_type="horizontal_bar",
        x_key="label",
        data=data,
        series=[{"key": "items", "label": "Items to review", "role": "primary"}],
        value_format="integer",
        # Five tiny items and one three-hour block are different kinds of
        # behind; the toggle lets a manager rank by either.
        toggle_views=[
            {"key": "items", "label": "Items", "series": ["items"],
             "format": "integer", "role": "primary"},
            {"key": "hours", "label": "Hours", "series": ["hours"],
             "format": "hours_1dp", "role": "primary"},
        ],
        toggle_label="Measure",
        state=MetricState.READY if data else MetricState.EMPTY,
    )


def needs_review_items_table(org, scope, time: TimeRange) -> DataTablePayload | None:
    """The open items themselves, for a view narrowed to specific people."""
    from ..breakdowns import _label_users
    from ..metrics.attribution import needs_you_items

    only = scoped_user_ids(scope)
    if not only:
        return None
    try:
        rows, total = needs_you_items(org.id, time, only)
    except Exception:
        return None
    multi = len(only) > 1
    if multi:
        acc = {uid: {"label": None} for uid in only}
        _label_users(org, acc)
        for r in rows:
            r["person"] = acc.get(r["user_id"], {}).get("label") or ""
    hours = sum(r["hours"] for r in rows)
    shown = (f"showing the oldest {len(rows):,} of {total:,}" if total > len(rows)
             else f"{total:,} item{'' if total == 1 else 's'} · {hours:,.1f} h")
    cols = ([column("person", "Employee", "text")] if multi else []) + [
        column("day", "Day", "text"),
        column("time", "Start", "text"),
        column("app", "App", "text"),
        column("what", "Window / file", "text"),
        column("hours", "Hours", "hours_1dp"),
        column("suggested", "Suggested client", "text",
               tooltip="TimeTracker's best guess, waiting for a yes."),
    ]
    return DataTablePayload(
        id="team_needs_review_items",
        title="What's waiting for review",
        subtitle=(f"{time.label} · {shown} · oldest first · "
                  "click a row to see their Daily Review for that day"),
        columns=cols,
        rows=rows,
        # No default sort: the rows arrive oldest first, and "Day" is display
        # text that would sort alphabetically.
        default_sort=None,
        row_link_key="href",
        state=MetricState.READY if rows else MetricState.EMPTY,
    )


def needs_review_stats(org, scope, time: TimeRange) -> Section | None:
    """The headline numbers: items and hours waiting, and how many of those
    already have a suggestion (a one-tap confirm) — summed over the people the
    view covers."""
    from ..metrics.attribution import (
        needs_you, needs_you_hours_by_user, needs_you_suggested_by_user,
    )

    try:
        by_user = needs_you(org.id, time)[3]
        hours = needs_you_hours_by_user(org.id, time)
        suggested = needs_you_suggested_by_user(org.id, time)
    except Exception:
        return None
    only = scoped_user_ids(scope)

    def total(d):
        return sum(v for u, v in d.items() if only is None or u in only)

    items, hrs, sug = total(by_user), total(hours), total(suggested)
    rate = round(sug / items * 100, 1) if items else None

    def tile(tid, label, fmt, value, tooltip):
        return KPITile(id=tid, label=label, format=fmt, tooltip=tooltip,
                       metric=MetricValue(value=value))

    return Section(id="needs_review_stats", type="kpi_row", title="Needs review", children=[
        tile("needs_review_items", "Items waiting", "integer", items,
             "Open Needs You items — time still to confirm in Daily Review."),
        tile("needs_review_hours", "Hours waiting", "hours_1dp", round(hrs, 1),
             "Hours of those open items."),
        tile("needs_review_suggested", "With a suggestion", "integer", sug,
             "Waiting items where TimeTracker already has a client guess — "
             "each one is a single tap to confirm."),
        tile("needs_review_suggestion_rate", "Suggestion rate", "percent_1dp", rate,
             "With a suggestion ÷ items waiting. The rest need a person to "
             "pick the client."),
    ])


def needs_review_sections(org, scope, time: TimeRange) -> list[Section]:
    """Who is behind on review, and — narrowed to people — on what.

    Shared by Team and Overview so the two can't show different numbers.
    """
    out: list[Section] = []
    stats = needs_review_stats(org, scope, time)
    if stats:
        out.append(stats)
    children = [c for c in (needs_review_chart(org, scope, time),
                            needs_review_items_table(org, scope, time)) if c]
    if children:
        out.append(Section(id="team_needs_review", type="section", children=children))
    return out


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

        sparks = safe_sparklines(org, scope, time)
        tiles = [
            kpi_tile(mid, org, scope, time, compare, size="medium",
                     sparklines=sparks)
            for mid in ("total_hours", "billable_hours", "billable_mix",
                        "billable_utilization", "revenue", "labor_cost")
            if scope.type in get_metric(mid).valid_scopes
        ]
        sections.append(Section(id="headline", type="kpi_row", children=tiles))

        if scope.type == "staff":
            return sections + self._review_sections(org, scope, time) \
                + self._person_detail(org, scope, time)

        rows = breakdown(org, scope, time, "user")
        table = team_table(
            org, rows, time,
            table_id="team_rows",
            title="By person",
            subtitle=f"{time.label} · {len(rows)} {'person' if len(rows) == 1 else 'people'}",
        )
        sections.append(Section(
            id="team_table", type="section", title="Team performance",
            children=[self._capacity_chart(rows, time), table],
        ))
        return sections + self._review_sections(org, scope, time)

    def _review_sections(self, org, scope, time) -> list[Section]:
        return needs_review_sections(org, scope, time)

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
            # A ring per person (the TimeTracker mark) while there are few
            # enough to read side by side; past that, stacked bars compare
            # better. One person as a stacked bar was a single wall of colour.
            chart_type="ring" if len(data) <= _RING_MAX_PEOPLE else "stacked_bar",
            x_key="label",
            data=data,
            # One measure and its remainder, not two peers — so the chart is
            # painted with the emphasis pair rather than two categorical hues.
            series=[
                {"key": "billable_hours", "label": "Billable", "role": "primary"},
                {"key": "other_hours", "label": "Other tracked", "role": "muted"},
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
