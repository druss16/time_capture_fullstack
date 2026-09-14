"""
Helpers used by multiple lenses to assemble Section trees.
"""
from __future__ import annotations

import logging
from typing import Optional

from tracker.models import Organization

from ..metrics import get_metric
from ..types import (
    ChartCardPayload, DataTablePayload, KPITile, MetricState, MetricValue,
    Scope, Section, TileSize, TimeRange,
)

logger = logging.getLogger(__name__)


def kpi_tile(
    metric_id: str,
    org: Organization,
    scope: Scope,
    time: TimeRange,
    compare: Optional[TimeRange] = None,
    size: TileSize = "medium",
    drilldown_lens: Optional[str] = None,
    sparklines: Optional[dict] = None,
) -> KPITile:
    """Build a KPITile by looking up the metric, computing, wiring up the drilldown.

    `sparklines` is the shared {metric_id: [values]} map from
    `series.sparklines_for`, computed once per KPI row — see that function for
    why it does not go through `Metric.sparkline()`.
    """
    metric = get_metric(metric_id)
    value = metric.safe_compute(org, scope, time, compare)
    if sparklines and value.state == MetricState.READY:
        value.sparkline = sparklines.get(metric_id)
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
    """Build a KPI row from a list of metric IDs, with shared sparklines."""
    sparks = safe_sparklines(org, scope, time)
    tiles = [
        kpi_tile(mid, org, scope, time, compare, size="large", sparklines=sparks)
        for mid in metric_ids
    ]
    return Section(id=section_id, type="kpi_row", children=tiles)


def safe_sparklines(org: Organization, scope: Scope, time: TimeRange) -> dict:
    """Sparklines for a KPI row, or {} if they can't be built.

    A trend that fails must never take the row's numbers down with it: the
    figures are the point, the little line behind them is decoration.
    """
    from ..series import sparklines_for
    try:
        return sparklines_for(org, scope, time)
    except Exception:
        logger.exception("[ANALYTICS_V2] Sparklines failed for org=%s", org.id)
        return {}


# ---------------------------------------------------------------------------
# Standard format helpers
# ---------------------------------------------------------------------------

def column(key: str, label: str, fmt: str = "decimal_1dp", sortable: bool = True,
           tooltip: str | None = None) -> dict:
    col = {"key": key, "label": label, "format": fmt, "sortable": sortable}
    if tooltip:
        col["tooltip"] = tooltip
    return col
