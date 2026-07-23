/**
 * URL state serialization for analytics v2.
 *
 * URL is the source of truth — sidebar reads from it, all state changes write to it.
 * Bookmarks and shared links Just Work.
 *
 * Shape:
 *   /analytics?lens=profitability&scope=client:42&time=this_quarter&compare=last_quarter
 *   /analytics?lens=pulse                       (defaults: firm scope, this_quarter)
 */
import type { AnalyticsQueryBody, LensKey, Scope, ScopeType } from "./types";

const VALID_LENSES = new Set<LensKey>([
  "pulse", "profitability", "utilization", "wip", "realization", "trends",
]);

const VALID_SCOPE_TYPES = new Set<ScopeType>([
  "firm", "client", "staff", "service", "engagement", "composite",
]);

/**
 * Parse URL search params into a query body.
 * Falls back to sane defaults when params are missing or malformed.
 */
export function parseUrlState(search: string): AnalyticsQueryBody {
  const params = new URLSearchParams(search);

  // Lens
  const rawLens = params.get("lens");
  const lens: LensKey = (rawLens && VALID_LENSES.has(rawLens as LensKey))
    ? (rawLens as LensKey)
    : "pulse";

  // Scope — "firm" or "client:42" or "staff:56,57"
  const rawScope = params.get("scope") || "firm";
  const scope = parseScopeParam(rawScope);

  // Time — relative string
  const rawTime = params.get("time") || "this_quarter";
  const time: AnalyticsQueryBody["time"] = { type: "relative", value: rawTime };

  // Compare — relative string or omitted
  const rawCompare = params.get("compare");
  const compare = rawCompare
    ? { type: "relative" as const, value: rawCompare }
    : null;

  return { scope, lens, time, compare };
}

function parseScopeParam(raw: string): Scope {
  if (raw === "firm") {
    return { type: "firm", ids: [] };
  }

  // "client:42" or "staff:56,57"
  const [typeRaw, idsRaw] = raw.split(":");
  if (!VALID_SCOPE_TYPES.has(typeRaw as ScopeType)) {
    return { type: "firm", ids: [] };
  }

  const ids = (idsRaw || "")
    .split(",")
    .map(s => parseInt(s, 10))
    .filter(n => !isNaN(n));

  return { type: typeRaw as ScopeType, ids };
}

/**
 * Serialize a query body back to URL params (without the leading "?").
 */
export function serializeUrlState(body: AnalyticsQueryBody): string {
  const params = new URLSearchParams();

  // Lens (always include unless pulse)
  if (body.lens !== "pulse") {
    params.set("lens", body.lens);
  }

  // Scope
  if (body.scope.type === "firm") {
    // Default — omit
  } else {
    const idsStr = body.scope.ids.join(",");
    params.set("scope", `${body.scope.type}:${idsStr}`);
  }

  // Time
  if (body.time.type === "relative" && body.time.value !== "this_quarter") {
    params.set("time", body.time.value as string);
  }

  // Compare
  if (body.compare && body.compare.type === "relative") {
    params.set("compare", body.compare.value as string);
  }

  const s = params.toString();
  return s;
}

/**
 * Build a sentence-style time label without hitting the backend
 * (used optimistically while a new query is loading).
 */
export function timeLabelFor(relativeExpr: string): string {
  const map: Record<string, string> = {
    today: "Today",
    yesterday: "Yesterday",
    this_week: "This week",
    last_week: "Last week",
    this_month: "This month",
    last_month: "Last month",
    this_quarter: "This quarter",
    last_quarter: "Last quarter",
    ytd: "Year to date",
    last_30_days: "Last 30 days",
    last_90_days: "Last 90 days",
    trailing_12_months: "Trailing 12 months",
    busy_season: "Busy season",
    extension_season: "Extension season",
  };
  return map[relativeExpr] ?? relativeExpr;
}

export const TIME_OPTIONS: Array<{ value: string; label: string; group: string }> = [
  { value: "today",              label: "Today",              group: "Days" },
  { value: "yesterday",          label: "Yesterday",          group: "Days" },
  { value: "this_week",          label: "This week",          group: "Weeks" },
  { value: "last_week",          label: "Last week",          group: "Weeks" },
  { value: "this_month",         label: "This month",         group: "Months" },
  { value: "last_month",         label: "Last month",         group: "Months" },
  { value: "this_quarter",       label: "This quarter",       group: "Quarters" },
  { value: "last_quarter",       label: "Last quarter",       group: "Quarters" },
  { value: "ytd",                label: "Year to date",       group: "Years" },
  { value: "trailing_12_months", label: "Trailing 12 months", group: "Years" },
  { value: "last_30_days",       label: "Last 30 days",       group: "Rolling" },
  { value: "last_90_days",       label: "Last 90 days",       group: "Rolling" },
  { value: "busy_season",        label: "Busy season",        group: "CPA-native" },
  { value: "extension_season",   label: "Extension season",   group: "CPA-native" },
];

export const COMPARE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "prior_period",  label: "Prior period (auto)" },
  { value: "last_quarter",  label: "Last quarter" },
  { value: "last_month",    label: "Last month" },
  { value: "last_week",     label: "Last week" },
  { value: "ytd",           label: "Year to date" },
];

export const LENS_OPTIONS: Array<{ value: LensKey; label: string; description: string }> = [
  { value: "pulse",         label: "Pulse",          description: "Curated daily overview" },
  { value: "profitability", label: "Profitability",  description: "Revenue, margin, labor cost" },
  { value: "realization",   label: "Realization",    description: "Billing efficiency" },
  { value: "utilization",   label: "Utilization",    description: "Billable share of tracked time" },
  { value: "wip",           label: "WIP",            description: "Uninvoiced work, aged" },
  { value: "trends",        label: "Trends",         description: "Monthly trend (Executive)" },
];
