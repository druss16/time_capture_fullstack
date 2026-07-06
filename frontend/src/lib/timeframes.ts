/**
 * timeframes.ts — QuickBooks-style preset date ranges for the Reports page.
 *
 * The reporting endpoints accept EITHER a named `period` (day/week/month/…,
 * resolved server-side relative to today) OR an explicit `start`/`end` range.
 * "This month/quarter/year" map cleanly to the named period; the "Last …" and
 * "Year to date" presets have no period equivalent, so we compute an explicit
 * range on the client and send start/end instead. One resolver returns whichever
 * shape a preset needs, so both ReportsSummary and ReportsMatrix stay in sync.
 *
 * All math is in LOCAL time and weeks start Monday, matching the backend's
 * bucketing (_row_key_and_label uses Monday-anchored weeks).
 */
export type Period = "day" | "week" | "month" | "quarter" | "year";

export type TimeframeKey =
  | "today"
  | "this_week"
  | "this_month"
  | "this_quarter"
  | "this_year"
  | "last_week"
  | "last_month"
  | "last_quarter"
  | "last_year"
  | "ytd"
  | "custom";

export interface TimeframeOption {
  key: TimeframeKey;
  label: string;
  group: "current" | "previous" | "custom";
}

// Order + grouping the dropdown renders (optgroups by `group`).
export const TIMEFRAMES: TimeframeOption[] = [
  { key: "today", label: "Today", group: "current" },
  { key: "this_week", label: "This week", group: "current" },
  { key: "this_month", label: "This month", group: "current" },
  { key: "this_quarter", label: "This quarter", group: "current" },
  { key: "this_year", label: "This year", group: "current" },
  { key: "last_week", label: "Last week", group: "previous" },
  { key: "last_month", label: "Last month", group: "previous" },
  { key: "last_quarter", label: "Last quarter", group: "previous" },
  { key: "last_year", label: "Last year", group: "previous" },
  { key: "ytd", label: "Year to date", group: "previous" },
  { key: "custom", label: "Custom range…", group: "custom" },
];

// A preset resolves to a named period OR an explicit range — never both.
export interface TimeframeSelection {
  period?: Period;
  start?: string; // YYYY-MM-DD
  end?: string; // YYYY-MM-DD
}

// Local-time ISO date (YYYY-MM-DD) — avoids the UTC shift toISOString() causes.
function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// Monday of the week containing `d` (getDay(): 0=Sun … 6=Sat).
function mondayOf(d: Date): Date {
  const out = new Date(d);
  const dow = (out.getDay() + 6) % 7; // 0=Mon … 6=Sun
  out.setDate(out.getDate() - dow);
  return out;
}

/**
 * Resolve a preset to the params the endpoints expect. "custom" returns {} —
 * the caller owns the manual start/end inputs for that case.
 */
export function resolveTimeframe(key: TimeframeKey, now: Date = new Date()): TimeframeSelection {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const q = Math.floor(today.getMonth() / 3); // 0..3

  switch (key) {
    case "today":
      return { period: "day" };
    case "this_week":
      return { period: "week" };
    case "this_month":
      return { period: "month" };
    case "this_quarter":
      return { period: "quarter" };
    case "this_year":
      return { period: "year" };

    case "last_week": {
      const thisMon = mondayOf(today);
      const start = new Date(thisMon);
      start.setDate(start.getDate() - 7);
      const end = new Date(thisMon);
      end.setDate(end.getDate() - 1);
      return { start: iso(start), end: iso(end) };
    }
    case "last_month": {
      const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      const end = new Date(today.getFullYear(), today.getMonth(), 0); // day 0 = last of prev month
      return { start: iso(start), end: iso(end) };
    }
    case "last_quarter": {
      // First month of this quarter, then step back one quarter.
      const start = new Date(today.getFullYear(), q * 3 - 3, 1);
      const end = new Date(today.getFullYear(), q * 3, 0); // last day of prev quarter
      return { start: iso(start), end: iso(end) };
    }
    case "last_year": {
      const start = new Date(today.getFullYear() - 1, 0, 1);
      const end = new Date(today.getFullYear() - 1, 11, 31);
      return { start: iso(start), end: iso(end) };
    }
    case "ytd": {
      const start = new Date(today.getFullYear(), 0, 1);
      return { start: iso(start), end: iso(today) };
    }

    case "custom":
    default:
      return {};
  }
}

// Human phrase used in headings ("… went this month", "… in this range").
export function timeframePhrase(key: TimeframeKey): string {
  switch (key) {
    case "today": return "today";
    case "this_week": return "this week";
    case "this_month": return "this month";
    case "this_quarter": return "this quarter";
    case "this_year": return "this year";
    case "last_week": return "last week";
    case "last_month": return "last month";
    case "last_quarter": return "last quarter";
    case "last_year": return "last year";
    case "ytd": return "year to date";
    case "custom": return "in this range";
    default: return "this period";
  }
}
