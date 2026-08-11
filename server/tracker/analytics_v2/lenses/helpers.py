"""
Helpers used by multiple lenses to assemble Section trees.
"""
from __future__ import annotations

from typing import Optional

from tracker.models import Organization

from ..metrics import get_metric
from ..types import (
    ChartCardPayload, DataTablePayload, KPITile, MetricState, MetricValue,
    Scope, Section, TileSize, TimeRange,
)


def kpi_tile(
    metric_id: str,
    org: Organization,
    scope: Scope,
    time: TimeRange,
    compare: Optional[TimeRange] = None,
    size: TileSize = "medium",
    drilldown_lens: Optional[str] = None,
) -> KPITile:
    """Build a KPITile by looking up the metric, computing, wiring up the drilldown."""
    metric = get_metric(metric_id)
    value = metric.safe_compute(org, scope, time, compare)
    drilldown = None
    if drilldown_lens:
        drilldown = {
            "scope": scope.to_dict(),
            "lens": drilldown_lens,
        }
    return KPITile(
        id=metric_id,
        label=metric.label,
        size=size,
        format=metric.format,
        tooltip=metric.tooltip,
        metric=value,
        drilldown=drilldown,
    )


def headline_row(
    metric_ids: list[str],
    org: Organization,
    scope: Scope,
    time: TimeRange,
    compare: Optional[TimeRange] = None,
    section_id: str = "headline",
) -> Section:
    """Build a KPI row from a list of metric IDs."""
    tiles = [
        kpi_tile(mid, org, scope, time, compare, size="large")
        for mid in metric_ids
    ]
    return Section(id=section_id, type="kpi_row", children=tiles)


# ---------------------------------------------------------------------------
# Standard format helpers
# ---------------------------------------------------------------------------

def column(key: str, label: str, fmt: str = "decimal_1dp", sortable: bool = True,
           tooltip: str | None = None) -> dict:
    col = {"key": key, "label": label, "format": fmt, "sortable": sortable}
    if tooltip:
        col["tooltip"] = tooltip
    return col
