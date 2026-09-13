/**
 * URL state for Analytics.
 *
 * The URL is the source of truth — the control bar reads from it, every change
 * writes to it. Bookmarks, shared links and back/forward all work, which is
 * what makes "send me that view" a link rather than a screenshot.
 *
 * Shape:
 *   /analytics
 *   /analytics?view=clients&time=last_quarter&compare=same_period_last_year
 *   /analytics?view=clients&scope=client:42
 *   /analytics?time=custom:2026-01-01:2026-03-31
 *   /analytics?f.billable=billable&f.service=3,7
 */
import type {
  AnalyticsQueryBody, BillableFilter, LensKey, Scope, ScopeFilters, ScopeType,
} from "./types";

const VALID_SCOPE_TYPES = new Set<ScopeType>([
  "firm", "client", "staff", "service", "engagement", "composite",
]);

/** The landing view. */
export const DEFAULT_VIEW: LensKey = "overview";
export const DEFAULT_TIME = "this_quarter";

// ─── Views (the top nav) ─────────────────────────────────────────────────────

export interface ViewOption {
  value: LensKey;
  label: string;
  description: string;
  /** Secondary views live behind "More" so the primary nav stays readable. */
  secondary?: boolean;
}

/**
 * The executive dashboard leads; the focused lenses stay reachable behind
 * "More". They answer questions the overview deliberately does not — whether
 * the underlying time data can be trusted at all, what is sitting uninvoiced,
 * how engagements are burning their budgets — and deleting them to tidy the
 * nav would remove capability, not clutter.
 */
export const VIEW_OPTIONS: ViewOption[] = [
  { value: "overview",     label: "Overview",       description: "How the firm is doing" },
  { value: "clients",      label: "Clients",        description: "Hours, value and margin by client" },
  { value: "team",         label: "Team",           description: "Capacity and contribution by person" },
  { value: "distribution", label: "Where time goes", description: "Time by client, project and category" },
  { value: "profitability", label: "Profitability", description: "Revenue, margin, labor cost" },
  { value: "trust",        label: "Trust",          description: "Can you believe the time data?",       secondary: true },
  { value: "review",       label: "Review",         description: "The numbers, and where they came from", secondary: true },
  { value: "utilization",  label: "Utilization",    description: "Billable share and capacity",           secondary: true },
  { value: "wip",          label: "WIP",            description: "Uninvoiced work, aged",                 secondary: true },
  { value: "realization",  label: "Realization",    description: "Billing efficiency",                    secondary: true },
  { value: "engagements",  label: "Engagements",    description: "Budget burn vs work done",              secondary: true },
  { value: "trends",       label: "Invoice trends", description: "Monthly invoiced revenue",              secondary: true },
];

/** Kept for the older sidebar import path. */
export const LENS_OPTIONS = VIEW_OPTIONS;

// ─── Time ────────────────────────────────────────────────────────────────────

export const TIME_OPTIONS: Array<{ value: string; label: string; group: string }> = [
  { value: "this_week",          label: "This week",          group: "Common" },
  { value: "last_week",          label: "Last week",          group: "Common" },
  { value: "this_month",         label: "This month",         group: "Common" },
  { value: "last_month",         label: "Last month",         group: "Common" },
  { value: "this_quarter",       label: "This quarter",       group: "Common" },
  { value: "last_quarter",       label: "Last quarter",       group: "Common" },
  { value: "ytd",                label: "Year to date",       group: "Common" },
  { value: "today",              label: "Today",              group: "Shorter" },
  { value: "yesterday",          label: "Yesterday",          group: "Shorter" },
  { value: "last_30_days",       label: "Last 30 days",       group: "Rolling" },
  { value: "last_90_days",       label: "Last 90 days",       group: "Rolling" },
  { value: "trailing_12_months", label: "Trailing 12 months", group: "Rolling" },
  { value: "busy_season",        label: "Busy season",        group: "CPA calendar" },
  { value: "extension_season",   label: "Extension season",   group: "CPA calendar" },
];

export const COMPARE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "",                      label: "No comparison" },
  { value: "prior_period",          label: "Previous period" },
  { value: "same_period_last_year", label: "Same period last year" },
];

const TIME_LABELS: Record<string, string> = Object.fromEntries(
  TIME_OPTIONS.map(o => [o.value, o.label]),
);

/** A sentence-style label without waiting on the backend. */
export function timeLabelFor(time: AnalyticsQueryBody["time"]): string {
  if (time.type === "absolute" && typeof time.value === "object") {
    return `${time.value.start} → ${time.value.end}`;
  }
  const expr = String(time.value);
  return TIME_LABELS[expr] ?? expr;
}

export function compareLabelFor(compare: AnalyticsQueryBody["compare"]): string {
  if (!compare) return "No comparison";
  const v = String(compare.value);
  return COMPARE_OPTIONS.find(o => o.value === v)?.label ?? v;
}

export function isCustomTime(time: AnalyticsQueryBody["time"]): boolean {
  return time.type === "absolute";
}

// ─── Parse ───────────────────────────────────────────────────────────────────

const ID_FILTER_DIMS = ["client", "staff", "service", "engagement"] as const;
const BILLABLE_VALUES = new Set<BillableFilter>(["all", "billable", "non_billable"]);

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function parseUrlState(search: string): AnalyticsQueryBody {
  const params = new URLSearchParams(search);

  // View. `lens` is still read so links shared before the rename keep working.
  const rawView = params.get("view") ?? params.get("lens");
  const lens: LensKey = VIEW_OPTIONS.some(o => o.value === rawView)
    ? (rawView as LensKey)
    : DEFAULT_VIEW;

  const scope = parseScopeParam(params.get("scope") || "firm", params);
  const time = parseTimeParam(params.get("time") || DEFAULT_TIME);

  const rawCompare = params.get("compare");
  const compare = rawCompare
    ? { type: "relative" as const, value: rawCompare }
    : null;

  return { scope, lens, time, compare };
}

/** "custom:2026-01-01:2026-03-31", or a relative expression. */
function parseTimeParam(raw: string): AnalyticsQueryBody["time"] {
  if (raw.startsWith("custom:")) {
    const [, start, end] = raw.split(":");
    // A malformed custom range falls back to the default rather than being
    // sent on to the backend as a 400 the viewer can do nothing about.
    if (ISO_DATE.test(start ?? "") && ISO_DATE.test(end ?? "") && start <= end) {
      return { type: "absolute", value: { start, end } };
    }
    return { type: "relative", value: DEFAULT_TIME };
  }
  return { type: "relative", value: raw };
}

function parseScopeParam(raw: string, params: URLSearchParams): Scope {
  const filters = parseFilters(params);

  if (raw === "firm") {
    return { type: "firm", ids: [], filters };
  }
  const [typeRaw, idsRaw] = raw.split(":");
  if (!VALID_SCOPE_TYPES.has(typeRaw as ScopeType)) {
    return { type: "firm", ids: [], filters };
  }
  const ids = (idsRaw || "")
    .split(",")
    .map(s => parseInt(s, 10))
    .filter(n => !isNaN(n));

  // A non-firm scope with no usable ids is not a scope — the backend rejects
  // it with a 400. Fall back rather than surface that as a broken page.
  if (ids.length === 0) return { type: "firm", ids: [], filters };

  return { type: typeRaw as ScopeType, ids, filters };
}

function parseFilters(params: URLSearchParams): ScopeFilters {
  const filters: ScopeFilters = {};
  for (const dim of ID_FILTER_DIMS) {
    const raw = params.get(`f.${dim}`);
    if (!raw) continue;
    const ids = raw.split(",").map(s => parseInt(s, 10)).filter(n => !isNaN(n));
    if (ids.length) filters[dim] = ids;
  }
  const billable = params.get("f.billable") as BillableFilter | null;
  if (billable && BILLABLE_VALUES.has(billable) && billable !== "all") {
    filters.billable = billable;
  }
  return filters;
}

// ─── Serialize ───────────────────────────────────────────────────────────────

/** Back to URL params (no leading "?"). Defaults are omitted to keep links short. */
export function serializeUrlState(body: AnalyticsQueryBody): string {
  const params = new URLSearchParams();

  if (body.lens !== DEFAULT_VIEW) params.set("view", body.lens);

  if (body.scope.type !== "firm" && body.scope.ids.length) {
    params.set("scope", `${body.scope.type}:${body.scope.ids.join(",")}`);
  }

  if (body.time.type === "absolute" && typeof body.time.value === "object") {
    params.set("time", `custom:${body.time.value.start}:${body.time.value.end}`);
  } else if (body.time.value !== DEFAULT_TIME) {
    params.set("time", String(body.time.value));
  }

  if (body.compare) params.set("compare", String(body.compare.value));

  const filters = body.scope.filters ?? {};
  for (const dim of ID_FILTER_DIMS) {
    const ids = filters[dim];
    if (ids?.length) params.set(`f.${dim}`, ids.join(","));
  }
  if (filters.billable && filters.billable !== "all") {
    params.set("f.billable", filters.billable);
  }

  return params.toString();
}

/** How many filters are active — drives the "Filters (2)" badge. */
export function countActiveFilters(filters: ScopeFilters | undefined): number {
  if (!filters) return 0;
  let n = 0;
  for (const dim of ID_FILTER_DIMS) if (filters[dim]?.length) n++;
  if (filters.billable && filters.billable !== "all") n++;
  return n;
}
