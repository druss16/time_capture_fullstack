/**
 * TypeScript interfaces matching the backend /api/analytics/query/ response.
 * Mirrors tracker/analytics_v2/types.py — keep these in sync.
 */

// ─── Scope + time ─────────────────────────────────────────────────────────────

export type ScopeType =
  | "firm" | "client" | "staff" | "service" | "engagement" | "composite";

export type LensKey =
  | "pulse" | "profitability" | "utilization" | "wip" | "realization" | "trends"
  | "engagements";

export interface Scope {
  type: ScopeType;
  ids: number[];
  filters?: Record<string, number[]>;
  label?: string;
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
  | "pie" | "wip_aging" | "sparkline";

export interface ChartCardPayload {
  type: "chart_card";
  id: string;
  title: string;
  subtitle: string;
  chart_type: ChartType;
  data: Array<Record<string, any>>;
  series: Array<{ key: string; label: string; color?: string }>;
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
  };
}

// ─── Request body ────────────────────────────────────────────────────────────

export interface AnalyticsQueryBody {
  scope: Scope;
  lens: LensKey;
  time: { type: "relative" | "absolute"; value: string | { start: string; end: string } };
  compare?: { type: "relative" | "absolute"; value: string | { start: string; end: string } } | null;
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
