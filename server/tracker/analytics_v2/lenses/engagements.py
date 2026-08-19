"""
Engagements lens — budget burn against real progress, worst first.

This is the worklist view of "which jobs are going to lose money", answered
while the work is still open rather than at billing.
"""
from __future__ import annotations

from tracker.models_engagements import ladder_for
from tracker.services.engagements import open_engagement_stats

from ..metrics.engagements import AT_RISK_OVERRUN_PTS
from ..types import ChartCardPayload, DataTablePayload, MetricState, Section
from .base import Lens, register_lens
from .helpers import column, headline_row

MAX_ROWS = 50


@register_lens("engagements")
class EngagementsLens(Lens):
    label = "Engagements"

    def assemble(self, org, scope, time, compare=None):
        stats = self._stats(org, scope)
        return [
            headline_row(
                ["engagement_overrun_dollars", "engagements_at_risk",
                 "engagement_budget_coverage"],
                org, scope, time, compare,
                section_id="headline",
            ),
            self._pace_section(stats),
            self._table_section(stats),
        ]

    def _stats(self, org, scope):
        client_ids = None
        if scope.type == "client":
            client_ids = list(scope.ids)
        elif scope.type == "composite":
            client_ids = list(scope.filters.get("client") or []) or None
        return open_engagement_stats(org, client_ids=client_ids)

    def _pace_section(self, stats) -> Section:
        """Burn vs progress, bucketed. A job at 0 is exactly on pace."""
        measurable = [s for s in stats if s.overrun_pts is not None]
        buckets = [
            ("Ahead of pace", lambda v: v <= -10),
            ("On pace", lambda v: -10 < v <= AT_RISK_OVERRUN_PTS),
            ("Over pace", lambda v: AT_RISK_OVERRUN_PTS < v <= 50),
            ("Badly over", lambda v: v > 50),
        ]
        data = [
            {"band": label, "value": sum(1 for s in measurable if test(s.overrun_pts))}
            for label, test in buckets
        ]

        chart = ChartCardPayload(
            id="engagement_pace",
            title="Budget burned vs work completed",
            subtitle=(
                f"{len(measurable)} jobs with both a budget and a phase"
                if measurable else "Needs budgets and phases"
            ),
            chart_type="bar",
            data=data,
            series=[{"key": "value", "label": "Jobs"}],
            state=MetricState.READY if measurable else MetricState.EMPTY,
        )
        return Section(
            id="pace", type="section", title="Pace",
            collapsible=False, children=[chart],
        )

    def _table_section(self, stats) -> Section:
        rows = []
        for s in stats[:MAX_ROWS]:
            row = s.to_row()
            # Powers the inline phase dropdown (DataTable's `phase_picker`
            # format). Progress is the one thing captured time can't tell us,
            # so the ask lives right next to the number it corrects.
            row["phase_options"] = [
                {"value": key, "label": label, "progress": round(weight * 100)}
                for key, label, weight in ladder_for(s.engagement.engagement_type)
            ]
            rows.append(row)

        table = DataTablePayload(
            id="engagement_pace_table",
            title="Open jobs",
            subtitle=(
                f"Worst overrun first · showing {len(rows)} of {len(stats)}"
                if len(stats) > len(rows) else "Worst overrun first"
            ),
            columns=[
                column("client_name", "Client", "text"),
                column("engagement", "Job", "text"),
                column("phase", "Phase", "phase_picker", sortable=False,
                       tooltip="Set by the preparer. 'Not set' means progress is unknown."),
                column("actual_hours", "Spent", "hours_1dp"),
                column("budget_hours", "Budget", "hours_1dp"),
                column("burn_pct", "Burned", "percent_0dp"),
                column("progress_pct", "Done", "percent_0dp"),
                column("overrun_pts", "Over pace", "decimal_1dp",
                       tooltip="Burned % minus done %. Positive means the spend is "
                               "running ahead of the work."),
                column("projected_overrun_dollars", "Projected over $", "currency_0dp",
                       tooltip="At this pace, dollars of effort beyond budget by delivery."),
            ],
            rows=rows,
            default_sort={"key": "projected_overrun_dollars", "direction": "desc"},
            state=MetricState.READY if rows else MetricState.EMPTY,
        )
        return Section(
            id="open_jobs", type="section", title="Open Jobs",
            collapsible=False, children=[table],
        )
