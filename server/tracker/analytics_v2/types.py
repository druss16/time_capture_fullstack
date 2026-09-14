"""
Core types for analytics v2.

These are the shape of the API contract. The frontend has matching TypeScript
interfaces in `types/analytics.ts` (drop 2). DO NOT change field names here
without coordinating that file — JSON keys are the API.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional


# ---------------------------------------------------------------------------
# Metric state machine
# ---------------------------------------------------------------------------

class MetricState(str, Enum):
    """
    State of a computed metric. The frontend renders each state differently:
      READY        → show the value
      LOADING      → skeleton (frontend-only, never returned from backend)
      EMPTY        → "No data" with optional CTA
      CALIBRATING  → preview value + "stabilizes after N days" message
      ERROR        → quiet error tile with retry
    """
    READY = "ready"
    EMPTY = "empty"
    CALIBRATING = "calibrating"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Time + scope value objects (parsed from the request body, validated)
# ---------------------------------------------------------------------------

ScopeType = Literal["firm", "client", "staff", "service", "engagement", "composite"]
LensKey = Literal[
    # Executive dashboard (the default landing experience)
    "overview", "clients", "team", "distribution",
    # Focused lenses
    "pulse", "trust", "review", "profitability", "utilization", "wip",
    "realization", "trends", "engagements",
]


@dataclass(frozen=True)
class TimeRange:
    """A resolved absolute date window. Relative time expressions like 'this_quarter'
    are resolved to dates at request-parse time."""
    start: date
    end: date
    label: str                 # Human-readable: "Q2 2026", "This week", etc.
    relative_expr: Optional[str] = None  # "this_quarter" if originally relative
    
    def days(self) -> int:
        return (self.end - self.start).days + 1
    
    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "label": self.label,
            "relative_expr": self.relative_expr,
        }


@dataclass(frozen=True)
class Scope:
    """
    A resolved query scope. Always references concrete IDs after permission resolution.
    Composite scope (e.g. 'Wendy's tax work') stores ids in `ids` and extra filters
    in `filters`.
    """
    type: ScopeType
    ids: tuple[int, ...] = ()
    filters: dict = field(default_factory=dict)
    label: str = ""           # Human-readable: "Wendy", "St. James Church", etc.
    
    def is_firm(self) -> bool:
        return self.type == "firm"
    
    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "ids": list(self.ids),
            "filters": dict(self.filters),
            "label": self.label,
        }


# ---------------------------------------------------------------------------
# Metric value — what each compute() returns
# ---------------------------------------------------------------------------

@dataclass
class MetricValue:
    """Result of computing a single metric for a (scope, time) pair."""
    state: MetricState = MetricState.READY
    value: Optional[float] = None
    
    # Optional: secondary value (e.g. realization has both hours and dollar variants)
    secondary_value: Optional[float] = None
    secondary_label: Optional[str] = None
    # Format for the secondary value when it differs from the tile's primary
    # format (e.g. a "Margin $" dollar amount under a percent tile). Falls back
    # to the tile format on the frontend when None.
    secondary_format: Optional[str] = None
    
    # Comparison delta (when comparison time range was provided)
    delta_value: Optional[float] = None
    delta_unit: Optional[str] = None    # "pts", "%", "$", etc.
    delta_direction: Optional[Literal["up", "down", "flat"]] = None
    delta_good: Optional[bool] = None   # Is this delta direction good for this metric?
    
    # Calibration metadata (only when state=CALIBRATING)
    preview_value: Optional[float] = None
    days_in: Optional[int] = None
    days_needed: Optional[int] = None
    
    # Data quality (Option B — for realization and any metric that depends on
    # explicit BillingRate vs org default fallback)
    data_quality: Optional[float] = None      # 0..1, share of value from explicit data
    data_quality_note: Optional[str] = None   # Human explanation if quality < 0.75
    
    # Trend for sparkline rendering (~7-12 buckets)
    sparkline: Optional[list[float]] = None
    # Aspiration/north-star line drawn on the sparkline (e.g. the firm's target),
    # so a firm-relative baseline doesn't hide "your normal is below where you
    # want to be."
    benchmark: Optional[float] = None

    # Threshold visualization
    threshold_low: Optional[float] = None
    threshold_high: Optional[float] = None
    threshold_zone: Optional[Literal["good", "watch", "bad"]] = None
    
    # Error info (when state=ERROR)
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Drop None fields to keep payload small."""
        raw = asdict(self)
        if isinstance(raw.get("state"), Enum):
            raw["state"] = raw["state"].value
        elif raw.get("state") is not None and not isinstance(raw["state"], str):
            raw["state"] = str(raw["state"])
        # Already a string from MetricState(str, Enum) — but be defensive
        return {k: v for k, v in raw.items() if v is not None}


# ---------------------------------------------------------------------------
# Frontend-facing tile/section primitives
# ---------------------------------------------------------------------------

TileSize = Literal["small", "medium", "large"]
SectionType = Literal["kpi_row", "section", "chart_card", "data_table", "insight_card"]
NumberFormat = Literal[
    "percent_1dp", "percent_0dp", "currency_0dp", "currency_2dp",
    "hours_1dp", "days_1dp", "integer", "decimal_1dp", "decimal_2dp",
    "text", "phase_picker",
]


@dataclass
class KPITile:
    """A single KPI tile in the rendered response."""
    id: str
    label: str
    size: TileSize = "medium"
    format: NumberFormat = "decimal_1dp"
    tooltip: str = ""
    metric: MetricValue = field(default_factory=MetricValue)
    drilldown: Optional[dict] = None  # {scope: {...}, lens: "realization"} for click-through
    
    def to_dict(self) -> dict:
        return {
            "type": "kpi_tile",
            "id": self.id,
            "label": self.label,
            "size": self.size,
            "format": self.format,
            "tooltip": self.tooltip,
            "metric": self.metric.to_dict(),
            "drilldown": self.drilldown,
        }


@dataclass
class ChartCardPayload:
    """A chart card. The `data` shape varies by chart_type but is always JSON-serializable."""
    id: str
    title: str
    subtitle: str = ""
    chart_type: Literal[
        "line", "area", "bar", "horizontal_bar", "stacked_bar",
        "pie", "wip_aging", "sparkline", "proportion_bar", "dot_matrix"
    ] = "line"
    data: list[dict] = field(default_factory=list)
    series: list[dict] = field(default_factory=list)  # [{key, label, color}]
    # Optional client-side toggle. One card carries several readings of the same
    # window; the viewer switches between them without a round trip. Each view
    # names the series it shows, so a cost view can be dropped wholesale by the
    # cost redactor without disturbing the others.
    #   [{"key": "hours", "label": "Total hours", "series": ["hours"],
    #     "format": "hours_1dp", "chart_type": "area"}]
    toggle_views: list[dict] = field(default_factory=list)
    toggle_label: str = ""
    # How to render values in axes and tooltips on a card with no toggle.
    # Without it the frontend has to guess from magnitude, which renders 1,800
    # hours as "$1.8k".
    value_format: str = ""
    # X-axis key for cartesian charts; the frontend falls back to "label".
    x_key: str = ""
    state: MetricState = MetricState.READY
    error_message: Optional[str] = None
    # A single figure the chart exists to make credible, printed large above it.
    # The alternative is an insight card underneath restating the chart in a
    # paragraph, which reads as homework and gets skipped.
    hero: Optional[str] = None
    hero_label: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "type": "chart_card",
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "chart_type": self.chart_type,
            "hero": self.hero,
            "hero_label": self.hero_label,
            "data": self.data,
            "series": self.series,
            "toggle_views": self.toggle_views,
            "toggle_label": self.toggle_label,
            "value_format": self.value_format,
            "x_key": self.x_key,
            "state": self.state.value if isinstance(self.state, Enum) else self.state,
            "error_message": self.error_message,
        }


@dataclass
class DataTablePayload:
    """A sortable data table."""
    id: str
    title: str
    subtitle: str = ""
    columns: list[dict] = field(default_factory=list)  # [{key, label, format, sortable}]
    rows: list[dict] = field(default_factory=list)
    default_sort: Optional[dict] = None  # {key, direction}
    state: MetricState = MetricState.READY
    error_message: Optional[str] = None
    # Makes rows clickable. The row supplies the ids under `id_key`; the
    # frontend builds {scope: {type: scope_type, ids: [id], label: row[label_key]},
    # lens: lens} and navigates. Rows without an id stay inert.
    row_drilldown: Optional[dict] = None  # {scope_type, lens, id_key, label_key}
    # Columns worth reading as a share of the table, not just a number. The
    # frontend paints an in-cell bar behind these, scaled to the column max.
    bar_columns: list[str] = field(default_factory=list)
    # Number the rows in their default order. A ranking that says "top 20 by
    # hours" should show the rank, not leave the reader counting.
    ranked: bool = False
    # Rendered above the table as context the rows alone do not carry.
    footnote: str = ""
    
    def to_dict(self) -> dict:
        return {
            "type": "data_table",
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "columns": self.columns,
            "rows": self.rows,
            "default_sort": self.default_sort,
            "row_drilldown": self.row_drilldown,
            "bar_columns": self.bar_columns,
            "ranked": self.ranked,
            "footnote": self.footnote,
            "state": self.state.value if isinstance(self.state, Enum) else self.state,
            "error_message": self.error_message,
        }


@dataclass
class InsightCardPayload:
    """A 'needs attention' card (Pulse) or AI commentary card."""
    id: str
    severity: Literal["info", "good", "watch", "bad"]
    headline: str
    body: str = ""
    evidence: list[dict] = field(default_factory=list)
    source: Literal["rule", "threshold", "ai"] = "threshold"
    drilldown: Optional[dict] = None
    dismissible: bool = True
    
    def to_dict(self) -> dict:
        return {
            "type": "insight_card",
            "id": self.id,
            "severity": self.severity,
            "headline": self.headline,
            "body": self.body,
            "evidence": self.evidence,
            "source": self.source,
            "drilldown": self.drilldown,
            "dismissible": self.dismissible,
        }


@dataclass
class Section:
    """A logical group of tiles/charts/tables within a lens."""
    id: str
    type: SectionType
    title: str = ""
    collapsible: bool = False
    # Start folded. For a long tail nobody reads by default — the low-materiality
    # client list, say — showing it expanded buries the section under it.
    collapsed: bool = False
    # Render children as tabs rather than stacked, labelled by each child's
    # own title. For sections that are one question asked of several
    # dimensions — where did the time go, by client / project / category —
    # where stacking four charts makes the viewer scroll to compare readings
    # that are alternatives to each other.
    tabbed: bool = False
    children: list[Any] = field(default_factory=list)  # KPITile | ChartCardPayload | DataTablePayload
    
    def to_dict(self) -> dict:
        # KPI rows flatten their children; sections nest them.
        if self.type == "kpi_row":
            return {
                "type": "kpi_row",
                "id": self.id,
                "tiles": [c.to_dict() for c in self.children],
            }
        return {
            "type": "section",
            "id": self.id,
            "title": self.title,
            "collapsible": self.collapsible,
            "collapsed": self.collapsed,
            "tabbed": self.tabbed,
            "children": [c.to_dict() for c in self.children],
        }


# ---------------------------------------------------------------------------
# Decimal helper — many models use Decimal, JSON wants floats
# ---------------------------------------------------------------------------

def to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
