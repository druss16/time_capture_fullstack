/**
 * TypeScript interfaces matching the backend /api/analytics/query/ response.
 * Mirrors tracker/analytics_v2/types.py — keep these in sync.
 */

// ─── Scope + time ─────────────────────────────────────────────────────────────

export type ScopeType =
  | "firm" | "client" | "staff" | "service" | "engagement" | "composite";

export type LensKey =
  // Executive dashboard
  | "overview" | "clients" | "team" | "distribution"
  // Focused lenses
  | "pulse" | "trust" | "review" | "profitability" | "utilization" | "wip" | "realization" | "trends"
  | "engagements";

/** Dimensions the control bar can narrow the whole dashboard by. */
export type FilterDim = "client" | "staff" | "service" | "engagement";

export type BillableFilter = "all" | "billable" | "non_billable";

export interface ScopeFilters {
  client?: number[];
  staff?: number[];
  /** TaskType ids — "Category" in the UI. */
  service?: number[];
  /** Project ids — "Project" in the UI. */
  engagement?: number[];
  billable?: BillableFilter;
}

export interface Scope {
  type: ScopeType;
  ids: number[];
  filters?: ScopeFilters | undefined;
  label?: string | undefined;
}

export interface TimeRange {
  start: string;             // ISO date
  end: string;               // ISO date
  label: string;             // "Q2 2026", "This week"
  relative_expr?: string | null;
}

// ─── Metric value (matches MetricValue dataclass) ────────────────────────────

export type MetricState = "ready" | "empty" | "calibrating" | "error";

export type DeltaDirection = "up" | "down" | "flat";

export type ThresholdZone = "good" | "watch" | "bad";

export interface MetricValue {
  state: MetricState;
  value?: number | null;

  secondary_value?: number | null;
  secondary_label?: string | null;
  secondary_format?: NumberFormat | null;

  delta_value?: number | null;
  delta_unit?: string | null;
  delta_direction?: DeltaDirection | null;
  delta_good?: boolean | null;

  preview_value?: number | null;
  days_in?: number | null;
  days_needed?: number | null;

  data_quality?: number | null;          // 0..1
  data_quality_note?: string | null;

  sparkline?: number[] | null;
  benchmark?: number | null;

  threshold_low?: number | null;
  threshold_high?: number | null;
  threshold_zone?: ThresholdZone | null;

  error_message?: string | null;
}

// ─── Format and tile types ───────────────────────────────────────────────────

export type NumberFormat =
  | "percent_1dp" | "percent_0dp"
  | "currency_0dp" | "currency_2dp"
  | "hours_1dp" | "days_1dp"
  | "integer" | "decimal_1dp" | "decimal_2dp"
  | "text"
  // Interactive: renders a phase dropdown that writes back to the engagement.
  // The row must carry `engagement_id` and `phase_options`.
  | "phase_picker";

export type TileSize = "small" | "medium" | "large";

export interface KPITilePayload {
  type: "kpi_tile";
  id: string;
  label: string;
  size: TileSize;
  format: NumberFormat;
  tooltip: string;
  metric: MetricValue;
  drilldown?: { scope: Scope; lens: LensKey } | null;
}

export type ChartType =
  | "line" | "area" | "bar" | "horizontal_bar" | "stacked_bar"
  | "pie" | "wip_aging" | "sparkline" | "proportion_bar" | "dot_matrix";

export interface ChartSeries {
  key: string;
  label: string;
  color?: string;
}

/**
 * One reading of a chart's data, selected client-side. `series` names the data
 * keys this view draws — which is also how the backend's cost redactor removes
 * a whole cost view for a viewer who may not see cost.
 */
export interface ChartToggleView {
  key: string;
  label: string;
  series: string[];
  format?: NumberFormat | undefined;
  chart_type?: ChartType | undefined;
}

export interface ChartCardPayload {
  type: "chart_card";
  id: string;
  title: string;
  subtitle: string;
  chart_type: ChartType;
  data: Array<Record<string, any>>;
  series: ChartSeries[];
  /** Non-empty when the card offers a measure toggle. */
  toggle_views?: ChartToggleView[] | undefined;
  toggle_label?: string | undefined;
  /** Value format for a card with no toggle (axes + tooltips). */
  value_format?: NumberFormat | "" | undefined;
  /** X-axis key for cartesian charts; falls back to "label". */
  x_key?: string | undefined;
  // hero/hero_label belong to the CARD, not to a series. They used to be
  // declared inside the series element type, which meant `card.hero` — what
  // ChartCard actually reads — was not on the type at all.
  hero?: string | null;
  hero_label?: string | null;
  state: MetricState;
  error_message?: string | null;
}

export interface DataTableColumn {
  key: string;
  label: string;
  format: NumberFormat;
  sortable: boolean;
  tooltip?: string | null;
}

export interface DataTablePayload {
  type: "data_table";
  id: string;
  title: string;
  subtitle: string;
  columns: DataTableColumn[];
  rows: Array<Record<string, any>>;
  default_sort?: { key: string; direction: "asc" | "desc" } | null;
  /**
   * Makes rows clickable. The row carries its id under `id_key`; the page
   * builds a scope from it and navigates to `lens`.
   */
  row_drilldown?: {
    scope_type: ScopeType;
    lens: LensKey;
    id_key: string;
    label_key: string;
  } | null;
  /** Columns rendered with an in-cell proportion bar, scaled to the column max. */
  bar_columns?: string[] | undefined;
  footnote?: string | undefined;
  state: MetricState;
  error_message?: string | null;
}

export type InsightSeverity = "info" | "good" | "watch" | "bad";

export interface InsightCardPayload {
  type: "insight_card";
  id: string;
  severity: InsightSeverity;
  headline: string;
  body: string;
  evidence: Array<{ label: string; value: string }>;
  source: "rule" | "threshold" | "ai";
  drilldown?: { scope: Scope; lens: LensKey } | null;
  dismissible: boolean;
}

// ─── Section envelope ────────────────────────────────────────────────────────

export type SectionChild =
  | KPITilePayload | ChartCardPayload | DataTablePayload | InsightCardPayload;

export interface KPIRow {
  type: "kpi_row";
  id: string;
  tiles: KPITilePayload[];
}

export interface Section {
  type: "section";
  id: string;
  title: string;
  collapsible: boolean;
  /** Start folded. Caller can still expand it. */
  collapsed?: boolean;
  /** Render children as tabs, labelled by each child's own title. */
  tabbed?: boolean | undefined;
  children: SectionChild[];
}

export type ResponseSection = KPIRow | Section;

// ─── Top-level response ──────────────────────────────────────────────────────

export interface AnalyticsResponse {
  view: {
    scope: Scope;
    lens: LensKey;
    time: TimeRange;
    compare?: TimeRange | null;
    sentence: string;
  };
  sections: ResponseSection[];
  meta: {
    org_id: number;
    org_name: string;
    plan: string;
    role: string | null;
    generated_at: string;
    data_freshness: string | null;
    version: string;
    // Custom — populated by our backend patches
    invoiceless?: boolean;
    /** False when cost/margin were redacted for this viewer. */
    cost_visible?: boolean;
  };
}

// ─── Request body ────────────────────────────────────────────────────────────

export interface AnalyticsQueryBody {
  scope: Scope;
  lens: LensKey;
  time: { type: "relative" | "absolute"; value: string | { start: string; end: string } };
  compare?: { type: "relative" | "absolute"; value: string | { start: string; end: string } } | null | undefined;
}

// ─── Permissions endpoint response ───────────────────────────────────────────

export interface PermissionsResponse {
  org_id: number;
  org_name: string;
  plan: string;
  role: string | null;
  capabilities: {
    can_firm: boolean;
    can_pick_any_client: boolean;
    can_pick_any_staff: boolean;
    available_lenses: LensKey[];
  };
}
