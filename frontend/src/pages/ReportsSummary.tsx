/**
 * ReportsSummary.tsx — high-level time reporting for customer firms (redesigned).
 *
 * Sits BELOW the C-level DashboardV2. Goal of this pass: a manager should get a
 * clear, synced picture of (1) which CLIENTS are getting billed and for how long,
 * (2) each employee's daily time card, and (3) where everyone spent their time —
 * readable at a glance, no jargon.
 *
 * WHAT CHANGED (readability + drill-down pass):
 *  - Client billing is the HEADLINE: a "Where the billable hours went" panel at
 *    the top, biggest client first. Tap a client to see who worked it.
 *  - Group-by toggle (default Employee) now renders two real views:
 *      • Employee → per-person CARDS with a billable/non-billable/review bar,
 *        three plain stat boxes, a review flag, and an expandable per-client
 *        breakdown (chevron).
 *      • Client   → a searchable, paginated table; click a row for detail.
 *  - Client drill-down modal: totals + who worked it + each person's minutes.
 *  - Review queue REMOVED from this page (Daily Review owns that workflow).
 *  - KPI strip, AI strip, daily-shape chart, CSV export, custom range, the
 *    why-pills, auth chain, and orgIdOverride/impersonation wiring are UNCHANGED.
 *
 * Drill-down data: the API's flat `group_by` rows don't include cross-breakdown
 * (employee→clients, client→employees). This component reads an OPTIONAL
 * `row.breakdown` array if the backend sends it, and gracefully hides the
 * drill-down affordances when it's absent — so nothing breaks before that field
 * ships. See BreakdownItem below for the shape it expects.
 *
 * Role-gating stays server-side. scope==="self" hides team-only affordances.
 * Auth: same localStorage token chain as the rest of the app.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Loader2, Download, Clock, AlertTriangle,
  ChevronDown, Search, X, Maximize2, Minimize2, SlidersHorizontal, Check,
} from "lucide-react";
import { API_BASE } from "@/lib/api";
import {
  TIMEFRAMES, resolveTimeframe, timeframePhrase, type TimeframeKey,
} from "@/lib/timeframes";
import UncategorizedPanel, { UncatPanelParams } from "./UncategorizedPanel";
import ReportsMatrix from "./ReportsMatrix";

// ── Auth token chain (matches ExecutiveDashboard convention) ──────────────
function getAuthToken(): string | null {
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token")
  );
}

// Format decimal hours as "1h 18m" / "27m" / "2h". Display-only.
function fmtHours(hours: number | undefined): string {
  const totalMin = Math.round((hours || 0) * 60);
  if (totalMin < 60) return `${totalMin}m`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// Display label for a client name. The backend uses "Unassigned" for blocks
// with no client (client_id is null); we show that as "No Client".
function displayClient(name: string | null | undefined): string {
  const n = (name || "").trim();
  return n === "Unassigned" ? "No Client" : (n || "No Client");
}

function initials(label: string): string {
  return label
    .split(/[\s]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");
}


type Period = "day" | "week" | "month" | "quarter" | "year";
type GroupBy = "employee" | "client";

// Optional cross-breakdown the backend MAY attach to each row.
//  - On an employee row: the clients that person worked (name = client).
//  - On a client row:    the people who worked it   (name = employee, id = userId).
interface BreakdownItem {
  id: number | null;
  name: string;
  total_hours: number;
  billable_hours: number;
  non_billable_hours: number;
  uncategorized_hours?: number;
}

// Stage C — GET /api/reports/activity/ shape.
interface ActivityItem {
  app: string;
  title: string;
  minutes: number;
  hours: number;
  block_count: number;
  billable: boolean;
  needs_review: boolean;
  first_seen: string | null;
  last_seen: string | null;
}
interface ActivityResponse {
  user_id: number | null;
  user_label: string;
  client_id: number | null;
  client_label: string;
  range: { start: string; end: string };
  totals: {
    billable_hours: number;
    non_billable_hours: number;
    needs_review_hours: number;
    total_hours: number;
  };
  activities: ActivityItem[];
}

interface SummaryRow {
  id: number | null;
  label: string;
  total_hours: number;
  billable_hours: number;
  non_billable_hours: number;
  uncategorized_hours?: number;   // server name kept; displayed as "Needs review"
  utilization_pct: number;
  top_client: string | null;
  block_count: number;
  breakdown?: BreakdownItem[];    // OPTIONAL — drill-down lights up when present
}

interface SummaryResponse {
  org_id: number;
  org_name: string;
  period: Period;
  group_by: GroupBy;
  range: { start: string; end: string };
  scope: "all" | "self";
  totals: {
    total_hours: number;
    billable_hours: number;
    non_billable_hours: number;
    uncategorized_hours?: number;
    utilization_pct: number;
    utilization_standard_pct?: number;
    utilization_captured_pct?: number;
    available_hours?: number;
    headcount?: number;
    working_days?: number;
    active_clients: number;
  };
  rows: SummaryRow[];
  timeseries: { bucket: string; total_hours: number; billable_hours: number }[];
}

const CLIENT_PAGE_SIZE = 8;

// Toggleable page sections. Each user can hide the ones they don't care about;
// the choice persists in localStorage (per browser). "employees" only renders
// for managers anyway — hiding it when it isn't shown is harmless.
const REPORT_WIDGETS: { key: string; label: string }[] = [
  { key: "clients", label: "Where the billable hours went" },
  { key: "employees", label: "Employees" },
  { key: "matrix", label: "Client grid" },
];
const HIDDEN_WIDGETS_LS_KEY = "reports_hidden_widgets";

export default function ReportsSummary({
  orgIdOverride,
}: {
  orgIdOverride?: number | null;
}) {
  const [period, setPeriod] = useState<Period>("month");
  const [timeframe, setTimeframe] = useState<TimeframeKey>("this_month"); // QuickBooks-style preset
  const [customMode, setCustomMode] = useState(false);
  // Draft values bound to the date inputs — typing here does NOT fetch.
  const [customStart, setCustomStart] = useState<string>("");
  const [customEnd, setCustomEnd] = useState<string>("");
  // Applied values — only these drive the fetch, set when the user clicks Apply.
  const [appliedStart, setAppliedStart] = useState<string>("");
  const [appliedEnd, setAppliedEnd] = useState<string>("");
  // Both groupings are shown stacked (no toggle), so we hold both datasets.
  // `data` = employee-grouped response, `clientData` = client-grouped response.
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [clientData, setClientData] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelParams, setPanelParams] = useState<UncatPanelParams | null>(null);

  // Redesign state
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [clientSearch, setClientSearch] = useState("");
  const [clientPage, setClientPage] = useState(0);
  const [clientExpandAll, setClientExpandAll] = useState(false); // show every client, no pager

  // Per-user widget visibility (persisted to localStorage) + the Customize menu.
  const [hiddenWidgets, setHiddenWidgets] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(HIDDEN_WIDGETS_LS_KEY);
      return new Set<string>(raw ? JSON.parse(raw) : []);
    } catch {
      return new Set<string>();
    }
  });
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [detail, setDetail] = useState<SummaryRow | null>(null); // client drill-down
  // When a client is opened from inside an employee's breakdown, this carries
  // the employee context so the modal can lead with "this person on this client".
  // null → opened from the top bars (firm-wide view).
  const [detailScope, setDetailScope] = useState<{
    employeeId: number | null;
    employeeLabel: string;
    scoped: BreakdownItem;
  } | null>(null);
  // Stage C: activity list for the scoped person+client, fetched on open.
  const [scopeActivity, setScopeActivity] = useState<ActivityResponse | null>(null);
  const [scopeActivityLoading, setScopeActivityLoading] = useState(false);

  const buildParams = useCallback((group: GroupBy) => {
    const p = new URLSearchParams({ group_by: group });
    // A resolved range (preset "Last …"/YTD or an applied custom range) wins;
    // otherwise fall back to the named period ("This week/month/…").
    if (appliedStart && appliedEnd) {
      p.set("start", appliedStart);
      p.set("end", appliedEnd);
    } else {
      p.set("period", period);
    }
    const impOrg = localStorage.getItem("impersonating_org_id");
    const effOrg = orgIdOverride || (impOrg ? Number(impOrg) : null);
    if (effOrg) p.set("org_id", String(effOrg));
    return p.toString();
  }, [period, orgIdOverride, customMode, appliedStart, appliedEnd]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getAuthToken();
      const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
      const [empRes, cliRes] = await Promise.all([
        fetch(`${API_BASE}/reports/summary/?${buildParams("employee")}`, { headers, credentials: "include" }),
        fetch(`${API_BASE}/reports/summary/?${buildParams("client")}`, { headers, credentials: "include" }),
      ]);
      if (!empRes.ok) {
        const body = await empRes.json().catch(() => ({}));
        throw new Error(body.error || `Request failed (${empRes.status})`);
      }
      setData(await empRes.json());
      // Client grouping is best-effort — if it fails, the employee section and
      // headline still render; the client table just shows its empty state.
      if (cliRes.ok) {
        setClientData(await cliRes.json());
      } else {
        setClientData(null);
      }
    } catch (e: any) {
      setError(e.message || "Failed to load report");
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Open the client drill-down from anywhere (headline bar, client table row,
  // or an employee row's breakdown). We already hold the client-grouped data,
  // so resolve the row with its people breakdown directly — no extra fetch.
  const openClientDetail = useCallback(
    (client: { id: number | null; label: string; breakdown?: BreakdownItem[] }) => {
      setDetailScope(null); // firm-wide view
      setScopeActivity(null);
      // Fast path: caller passed a row that already carries its breakdown.
      if (client.breakdown && client.breakdown.length > 0) {
        setDetail(client as SummaryRow);
        return;
      }
      // Resolve against the loaded client dataset for the "who worked it" list.
      const match = clientData?.rows.find(
        (r) =>
          (client.id != null && r.id === client.id) || r.label === client.label
      );
      if (match) {
        setDetail(match);
      } else {
        // Fallback: show header with what we know.
        setDetail({
          id: client.id,
          label: client.label,
          total_hours: 0,
          billable_hours: 0,
          non_billable_hours: 0,
          utilization_pct: 0,
          top_client: null,
          block_count: 0,
        });
      }
    },
    [clientData]
  );

  // Open a client scoped to a specific employee (clicked inside their
  // breakdown). Leads with "this person on this client" using the per-person
  // numbers we already have, and still resolves the firm-wide client row so the
  // modal can show "who else worked it" underneath for context.
  const openScopedClientDetail = useCallback(
    (args: {
      clientId: number | null;
      clientName: string;
      employeeId: number | null;
      employeeLabel: string;
      scoped: BreakdownItem;
    }) => {
      setDetailScope({
        employeeId: args.employeeId,
        employeeLabel: args.employeeLabel,
        scoped: args.scoped,
      });
      const match = clientData?.rows.find(
        (r) =>
          (args.clientId != null && r.id === args.clientId) ||
          r.label === args.clientName
      );
      setDetail(
        match || {
          id: args.clientId,
          label: args.clientName,
          total_hours: 0,
          billable_hours: 0,
          non_billable_hours: 0,
          utilization_pct: 0,
          top_client: null,
          block_count: 0,
        }
      );

      // Stage C — fetch the actual work for this person on this client.
      setScopeActivity(null);
      if (args.employeeId != null) {
        setScopeActivityLoading(true);
        (async () => {
          try {
            const token = getAuthToken();
            const p = new URLSearchParams({
              user_id: String(args.employeeId),
              client_id: String(args.clientId ?? 0),
            });
            if (appliedStart && appliedEnd) {
              p.set("start", appliedStart);
              p.set("end", appliedEnd);
            } else {
              p.set("period", period);
            }
            const impOrg = localStorage.getItem("impersonating_org_id");
            const effOrg = orgIdOverride || (impOrg ? Number(impOrg) : null);
            if (effOrg) p.set("org_id", String(effOrg));

            const res = await fetch(`${API_BASE}/reports/activity/?${p.toString()}`, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
              credentials: "include",
            });
            if (res.ok) {
              setScopeActivity(await res.json());
            }
          } catch {
            // Leave activity null — modal falls back to the totals-only view.
          } finally {
            setScopeActivityLoading(false);
          }
        })();
      }
    },
    [clientData, period, customMode, appliedStart, appliedEnd, orgIdOverride]
  );

  // Reset view-local state when the query changes.
  useEffect(() => {
    setExpanded(new Set());
    setClientPage(0);
    setDetail(null);
  }, [period, customMode, appliedStart, appliedEnd, orgIdOverride]);

  // Active-window phrase for copy. A custom range only counts as "applied" when
  // both endpoints are filled (matches the fetch guard).
  const customApplied = customMode && !!appliedStart && !!appliedEnd;
  const windowPhrase = timeframePhrase(timeframe);

  // Apply a QuickBooks-style preset. "This …" presets use the named period;
  // "Last …"/YTD resolve to an explicit range; "Custom range…" reveals the date
  // inputs and waits for Apply.
  const applyTimeframe = (key: TimeframeKey) => {
    setTimeframe(key);
    if (key === "custom") {
      setCustomMode(true);
      return;
    }
    setCustomMode(false);
    const sel = resolveTimeframe(key);
    if (sel.period) {
      setPeriod(sel.period);
      setAppliedStart("");
      setAppliedEnd("");
    } else if (sel.start && sel.end) {
      setAppliedStart(sel.start);
      setAppliedEnd(sel.end);
    }
  };

  const showWidget = (k: string) => !hiddenWidgets.has(k);
  const toggleWidget = (k: string) =>
    setHiddenWidgets((prev) => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      try {
        localStorage.setItem(HIDDEN_WIDGETS_LS_KEY, JSON.stringify([...next]));
      } catch {
        /* private mode / quota — visibility just won't persist */
      }
      return next;
    });

  const handleExport = useCallback(() => {
    const token = getAuthToken();
    const url = `${API_BASE}/reports/summary/export/?${buildParams("employee")}`;
    fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: "include",
    })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement("a");
        const href = URL.createObjectURL(blob);
        a.href = href;
        a.download = appliedStart && appliedEnd
          ? `time_summary_${appliedStart}_to_${appliedEnd}.csv`
          : `time_summary_${timeframe}.csv`;
        a.click();
        URL.revokeObjectURL(href);
      })
      .catch(() => setError("Export failed"));
  }, [buildParams, timeframe, appliedStart, appliedEnd]);

  // ── Derived: employee + client rows straight from the API rows ──────────
  const employeeRows = useMemo(
    () =>
      data && data.group_by === "employee"
        ? [...data.rows].sort((a, b) => b.total_hours - a.total_hours)
        : [],
    [data]
  );

  const clientRowsSorted = useMemo(
    () =>
      clientData && clientData.group_by === "client"
        ? [...clientData.rows].sort((a, b) => b.billable_hours - a.billable_hours)
        : [],
    [clientData]
  );

  // Filtered + paginated client list for the Client view.
  const filteredClients = useMemo(() => {
    const q = clientSearch.trim().toLowerCase();
    return q
      ? clientRowsSorted.filter((r) => r.label.toLowerCase().includes(q))
      : clientRowsSorted;
  }, [clientRowsSorted, clientSearch]);

  const clientPageCount = Math.max(1, Math.ceil(filteredClients.length / CLIENT_PAGE_SIZE));
  const clientPageSafe = Math.min(clientPage, clientPageCount - 1);
  const clientSlice = clientExpandAll
    ? filteredClients
    : filteredClients.slice(
        clientPageSafe * CLIENT_PAGE_SIZE,
        clientPageSafe * CLIENT_PAGE_SIZE + CLIENT_PAGE_SIZE
      );
  // Scale bars against the busiest client in the full filtered set, so widths
  // stay comparable across pages instead of re-normalizing each page.
  const maxClientBill = Math.max(1, ...filteredClients.map((c) => c.billable_hours));

  const toggleExpand = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      {/* Header + period toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Time Summary</h1>
          {data && (
            <p className="text-xs text-slate-500 mt-0.5">
              {data.org_name} · {data.range.start} → {data.range.end} ·{" "}
              {data.scope === "self" ? "Your time" : "Team"}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* QuickBooks-style timeframe presets */}
          <div className="relative inline-flex items-center">
            <select
              value={timeframe}
              onChange={(e) => applyTimeframe(e.target.value as TimeframeKey)}
              className="appearance-none pl-3 pr-8 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 cursor-pointer"
              aria-label="Timeframe"
            >
              <optgroup label="Current">
                {TIMEFRAMES.filter((t) => t.group === "current").map((t) => (
                  <option key={t.key} value={t.key}>{t.label}</option>
                ))}
              </optgroup>
              <optgroup label="Previous">
                {TIMEFRAMES.filter((t) => t.group === "previous").map((t) => (
                  <option key={t.key} value={t.key}>{t.label}</option>
                ))}
              </optgroup>
              <optgroup label="Custom">
                {TIMEFRAMES.filter((t) => t.group === "custom").map((t) => (
                  <option key={t.key} value={t.key}>{t.label}</option>
                ))}
              </optgroup>
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
          </div>

          {customMode && (
            <div className="inline-flex items-center gap-1.5">
              <input
                type="date"
                value={customStart}
                max={customEnd || undefined}
                onChange={(e) => setCustomStart(e.target.value)}
                className="px-2 py-1.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-700"
              />
              <span className="text-xs text-slate-400">to</span>
              <input
                type="date"
                value={customEnd}
                min={customStart || undefined}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="px-2 py-1.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-700"
              />
              <button
                onClick={() => {
                  if (customStart && customEnd && customStart <= customEnd) {
                    setAppliedStart(customStart);
                    setAppliedEnd(customEnd);
                  }
                }}
                disabled={
                  !customStart || !customEnd || customStart > customEnd ||
                  (customStart === appliedStart && customEnd === appliedEnd)
                }
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-700 text-white hover:bg-emerald-800 disabled:opacity-40 disabled:cursor-default"
              >
                Apply
              </button>
            </div>
          )}
          <button
            onClick={handleExport}
            disabled={!data}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            Export CSV
          </button>

          {/* Customize — per-user show/hide of the page's sections */}
          <div className="relative">
            <button
              onClick={() => setCustomizeOpen((v) => !v)}
              className={
                "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors " +
                (customizeOpen
                  ? "border-slate-300 bg-slate-50 text-slate-800"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")
              }
              title="Show or hide sections"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Customize
            </button>
            {customizeOpen && (
              <>
                <button
                  className="fixed inset-0 z-30 cursor-default"
                  aria-label="Close customize menu"
                  onClick={() => setCustomizeOpen(false)}
                />
                <div className="absolute right-0 mt-1.5 z-40 w-64 rounded-xl border border-slate-200 bg-white shadow-lg p-2">
                  <p className="px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-slate-400">
                    Show sections
                  </p>
                  {REPORT_WIDGETS.map((w) => (
                    <button
                      key={w.key}
                      onClick={() => toggleWidget(w.key)}
                      className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg text-xs text-slate-700 hover:bg-slate-50"
                    >
                      <span className="truncate">{w.label}</span>
                      <span
                        className={
                          "flex h-4 w-4 shrink-0 items-center justify-center rounded border " +
                          (showWidget(w.key)
                            ? "bg-emerald-600 border-emerald-600 text-white"
                            : "border-slate-300 text-transparent")
                        }
                      >
                        <Check className="h-3 w-3" />
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {customMode && !customApplied && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-500">
          Pick a start and end date, then choose <span className="font-semibold text-slate-700">Apply</span> to load that range.
        </div>
      )}

      {/* States */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Loading…</span>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/40 p-4 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <div className="text-xs text-rose-700">{error}</div>
        </div>
      )}

      {/* ══ CLIENTS SECTION (bar graph) ══════════════════════════════════ */}
      {showWidget("clients") && !loading && !error && (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <h2 className="text-base font-bold text-slate-900">Where the billable hours went {windowPhrase}</h2>
            <div className="flex items-center gap-2">
              {filteredClients.length > CLIENT_PAGE_SIZE && (
                <button
                  onClick={() => setClientExpandAll((v) => !v)}
                  className={
                    "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors " +
                    (clientExpandAll
                      ? "border-emerald-700 bg-emerald-50 text-emerald-800"
                      : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")
                  }
                  title={clientExpandAll ? "Showing all clients" : "Show every client at once"}
                >
                  {clientExpandAll ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                  {clientExpandAll ? "Expanded" : "Expand all"}
                </button>
              )}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <input
                  value={clientSearch}
                  onChange={(e) => { setClientSearch(e.target.value); setClientPage(0); }}
                  placeholder="Search clients…"
                  className="w-56 pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
                />
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
            <p className="text-[11px] font-medium text-slate-400 mb-4">Click a client for detail</p>

            {clientSlice.length === 0 ? (
              <div className="py-10 text-center text-sm text-slate-400">
                {clientSearch ? `No clients match “${clientSearch}”.` : "No client time in this period yet."}
              </div>
            ) : (
              <div className="space-y-3">
                {clientSlice.map((c) => {
                  const people = Array.isArray(c.breakdown) ? c.breakdown.length : undefined;
                  return (
                    <button
                      key={`${c.id}-${c.label}`}
                      onClick={() => openClientDetail(c)}
                      className="w-full grid grid-cols-[minmax(0,1fr)_84px] sm:grid-cols-[220px_minmax(0,1fr)_84px] items-center gap-3 rounded-lg px-1.5 py-1 text-left hover:bg-slate-50 cursor-pointer"
                    >
                      <span className="truncate text-sm font-semibold text-slate-800">{displayClient(c.label)}</span>
                      <span className="hidden sm:block h-[26px] rounded-full bg-slate-100 overflow-hidden">
                        <span
                          className="flex h-full items-center rounded-full bg-gradient-to-r from-emerald-600 to-emerald-500 pl-2.5 text-[11px] font-bold text-white"
                          style={{ width: `${Math.max((c.billable_hours / maxClientBill) * 100, 6)}%` }}
                        >
                          {people != null ? `${people} ${people > 1 ? "people" : "person"}` : ""}
                        </span>
                      </span>
                      <span className="text-right text-sm font-bold tabular-nums text-slate-800">
                        {fmtHours(c.billable_hours)}
                        <span className="block text-[11px] font-semibold text-slate-400">billable</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* pager — hidden when expanded */}
            <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between gap-2 text-xs text-slate-500">
              <span>
                Showing {clientSlice.length} of {filteredClients.length} client{filteredClients.length === 1 ? "" : "s"}
              </span>
              {!clientExpandAll && clientPageCount > 1 && (
                <div className="flex items-center gap-1.5">
                  <button
                    disabled={clientPageSafe === 0}
                    onClick={() => setClientPage(clientPageSafe - 1)}
                    className="px-2.5 py-1 rounded-md border border-slate-200 bg-white font-semibold text-slate-700 disabled:opacity-40"
                  >
                    ← Prev
                  </button>
                  <span className="px-1.5">{clientPageSafe + 1} / {clientPageCount}</span>
                  <button
                    disabled={clientPageSafe >= clientPageCount - 1}
                    onClick={() => setClientPage(clientPageSafe + 1)}
                    className="px-2.5 py-1 rounded-md border border-slate-200 bg-white font-semibold text-slate-700 disabled:opacity-40"
                  >
                    Next →
                  </button>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* ══ EMPLOYEES SECTION ════════════════════════════════════════════ */}
      {/* Team view — only for viewers the server scopes as "all" (owners/admins/
          managers). Staff scoped to "self" never see the comparative team table;
          it's performance/comp-adjacent data and a naked cross-employee ranking. */}
      {showWidget("employees") && data && !loading && !error && (
        <section className="space-y-3 pt-2">
          <h2 className="text-base font-bold text-slate-900">Employees</h2>
          {employeeRows.length === 0 ? (
            <EmptyState label="No committed time in this period yet." />
          ) : (
            <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
              {/* column header — hidden on narrow screens where columns stack */}
              <div className="hidden md:grid grid-cols-[38px_minmax(150px,1.5fr)_1.4fr_repeat(4,minmax(64px,.8fr))_20px] items-center gap-3 px-4 py-2.5 bg-slate-50 border-b border-slate-200 text-[10.5px] font-bold uppercase tracking-wide text-slate-500">
                <span />
                <span>Employee</span>
                <span>Mix</span>
                <span className="text-right">Billable</span>
                <span className="text-right">Non-bill</span>
                <span className="text-right">Review</span>
                <span className="text-right">Util %</span>
                <span />
              </div>
              <div className="divide-y divide-slate-100">
                {employeeRows.map((r) => (
                  <EmployeeRow
                    key={`${r.id}-${r.label}`}
                    row={r}
                    maxTotal={Math.max(1, ...employeeRows.map((e) => e.total_hours || 0))}
                    expanded={expanded.has(`${r.id}-${r.label}`)}
                    onToggle={() => toggleExpand(`${r.id}-${r.label}`)}
                    onOpenClient={({ clientId, clientName, employeeId, employeeLabel, scoped }) =>
                      openScopedClientDetail({ clientId, clientName, employeeId, employeeLabel, scoped })
                    }
                    onOpenReview={() =>
                      setPanelParams({
                        period, group_by: "employee", orgId: orgIdOverride,
                        userId: r.id, userLabel: r.label,
                      })
                    }
                  />
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Client drill-down modal */}
      {detail && (
        <ClientDetailModal
          row={detail}
          windowPhrase={windowPhrase}
          scope={detailScope}
          activity={scopeActivity}
          activityLoading={scopeActivityLoading}
          onClose={() => { setDetail(null); setDetailScope(null); setScopeActivity(null); }}
        />
      )}

      <UncategorizedPanel
        open={!!panelParams}
        onClose={() => setPanelParams(null)}
        params={panelParams || { period, group_by: "employee" }}
      />

      {/* Client grid (matrix pivot) — its own section below the summary bars.
          Self-contained: loads its own preset/data and honors the same
          orgIdOverride/impersonation wiring the summary above uses. */}
      {showWidget("matrix") && (
        <div className="pt-4 border-t border-slate-200">
          <ReportsMatrix orgIdOverride={orgIdOverride ?? null} />
        </div>
      )}
    </div>
  );
}

// ── Employee dense row (option B) ──────────────────────────────────────────
// One row per person: avatar + name + "most time on", a thin mix bar, then
// Billable / Non-bill / Review / Util % columns, and an expand chevron.
// Clicking the row toggles an inline per-client breakdown below it. On narrow
// screens the columns collapse into a wrapped stat strip so nothing is lost.
function EmployeeRow({
  row, expanded, onToggle, onOpenReview, onOpenClient, maxTotal,
}: {
  row: SummaryRow;
  expanded: boolean;
  onToggle: () => void;
  onOpenReview: () => void;
  maxTotal: number;   // busiest person's total hours — scales the mix bar length
  // Called when a client inside this person's breakdown is clicked. Passes the
  // employee context so the modal can scope to "this person on this client".
  onOpenClient: (args: {
    clientId: number | null;
    clientName: string;
    employeeId: number | null;
    employeeLabel: string;
    scoped: BreakdownItem;
  }) => void;
}) {
  const [bdPage, setBdPage] = useState(0);
  const [bdExpandAll, setBdExpandAll] = useState(false); // show every client, no pager
  const BD_PAGE_SIZE = 6;
  const total = row.total_hours || 0.0001;
  const billPct = (row.billable_hours / total) * 100;
  const nonPct = (row.non_billable_hours / total) * 100;
  const revPct = ((row.uncategorized_hours || 0) / total) * 100;
  // Bar LENGTH encodes total hours (vs the busiest person), so a light week and
  // a heavy week look different at a glance. Segments still show the bill/
  // non-bill/review mix within that length. Floor at 8% so tiny bars stay visible.
  const lengthPct = Math.max(8, (total / (maxTotal || 1)) * 100);
  const review = row.uncategorized_hours || 0;
  const util = row.utilization_pct ?? 0;
  const hasBreakdown = Array.isArray(row.breakdown) && row.breakdown.length > 0;
  // Hide the "No Client" (unassigned) bucket from the per-employee breakdown —
  // it's not client work. The employee's header totals still include it; this
  // only cleans the client list. (Renamed from "Unassigned" → "No Client".)
  const sortedBreakdown = hasBreakdown
    ? [...row.breakdown!]
        .filter((b) => b.name !== "Unassigned" && b.name !== "No Client")
        .sort((a, b) => b.total_hours - a.total_hours)
    : [];
  const maxItem = sortedBreakdown.length
    ? Math.max(1, ...sortedBreakdown.map((b) => b.total_hours))
    : 1;
  const bdPageCount = Math.max(1, Math.ceil(sortedBreakdown.length / BD_PAGE_SIZE));
  const bdPageSafe = Math.min(bdPage, bdPageCount - 1);
  const bdSlice = bdExpandAll
    ? sortedBreakdown
    : sortedBreakdown.slice(
        bdPageSafe * BD_PAGE_SIZE,
        bdPageSafe * BD_PAGE_SIZE + BD_PAGE_SIZE
      );

  return (
    <div className={expanded ? "bg-slate-50/40" : ""}>
      {/* ── the row itself ── */}
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 hover:bg-slate-50/60 transition-colors"
      >
        {/* desktop: aligned columns */}
        <div className="hidden md:grid grid-cols-[38px_minmax(150px,1.5fr)_1.4fr_repeat(4,minmax(64px,.8fr))_20px] items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-700 text-xs font-bold text-white">
            {initials(row.label)}
          </span>
          <div className="min-w-0">
            <div className="text-sm font-bold text-slate-900 truncate">{row.label}</div>
            <div className="text-[11px] text-slate-400 truncate">
              Most time on {row.top_client || "Internal / Admin"}
            </div>
          </div>
          <div>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div className="flex h-full overflow-hidden rounded-full" style={{ width: `${lengthPct}%` }}>
                <span className="h-full bg-emerald-600" style={{ width: `${billPct}%` }} />
                <span className="h-full bg-slate-400" style={{ width: `${nonPct}%` }} />
                <span className="h-full bg-amber-500" style={{ width: `${revPct}%` }} />
              </div>
            </div>
            <div className="mt-1 text-[10px] tabular-nums text-slate-400">{fmtHours(total)} total</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-bold tabular-nums text-emerald-700">{fmtHours(row.billable_hours)}</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-bold tabular-nums text-slate-500">{fmtHours(row.non_billable_hours)}</div>
          </div>
          <div className="text-right">
            {review > 0 ? (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); onOpenReview(); }}
                onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onOpenReview(); } }}
                className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-sm font-bold tabular-nums text-amber-600 hover:bg-amber-100 cursor-pointer"
                title="Open the blocks waiting on review"
              >
                <Clock className="h-3 w-3" />
                {fmtHours(review)}
              </span>
            ) : (
              <span className="text-sm text-slate-300">—</span>
            )}
          </div>
          <div className="text-right">
            <div className="text-sm font-bold tabular-nums text-slate-700">{util}%</div>
          </div>
          <ChevronDown
            className={"h-4 w-4 text-slate-400 transition-transform justify-self-end " + (expanded ? "rotate-180" : "")}
          />
        </div>

        {/* mobile: name row + wrapped stat strip */}
        <div className="md:hidden">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5 min-w-0">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-xs font-bold text-white">
                {initials(row.label)}
              </span>
              <div className="min-w-0">
                <div className="text-sm font-bold text-slate-900 truncate">{row.label}</div>
                <div className="text-[11px] text-slate-400 truncate">
                  Most time on {row.top_client || "Internal / Admin"}
                </div>
              </div>
            </div>
            <ChevronDown
              className={"h-4 w-4 shrink-0 text-slate-400 transition-transform " + (expanded ? "rotate-180" : "")}
            />
          </div>
          <div className="mt-2 flex h-2.5 overflow-hidden rounded-full">
            <span className="h-full bg-emerald-600" style={{ width: `${billPct}%` }} />
            <span className="h-full bg-slate-400" style={{ width: `${nonPct}%` }} />
            <span className="h-full bg-amber-500" style={{ width: `${revPct}%` }} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <span className="tabular-nums"><b className="text-emerald-700 font-bold">{fmtHours(row.billable_hours)}</b> <span className="text-slate-400">bill</span></span>
            <span className="tabular-nums"><b className="text-slate-600 font-bold">{fmtHours(row.non_billable_hours)}</b> <span className="text-slate-400">non-bill</span></span>
            {review > 0 && (
              <span className="tabular-nums text-amber-600"><b className="font-bold">{fmtHours(review)}</b> review</span>
            )}
            <span className="tabular-nums"><b className="text-slate-700 font-bold">{util}%</b> <span className="text-slate-400">util</span></span>
            <span className="tabular-nums"><b className="text-slate-700 font-bold">{fmtHours(total)}</b> <span className="text-slate-400">total</span></span>
          </div>
        </div>
      </button>

      {/* ── inline expand: per-client breakdown ── */}
      {expanded && (
        <div className="px-4 pb-4 pt-1">
          <div className="rounded-lg bg-white border border-slate-200 p-3.5">
            <div className="flex items-center justify-between gap-2 mb-2.5">
              <h4 className="text-[11px] font-bold uppercase tracking-wide text-slate-400">
                Clients worked this period
              </h4>
              {sortedBreakdown.length > BD_PAGE_SIZE && (
                <button
                  onClick={(e) => { e.stopPropagation(); setBdExpandAll((v) => !v); }}
                  className={
                    "inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold rounded-md border transition-colors " +
                    (bdExpandAll
                      ? "border-emerald-700 bg-emerald-50 text-emerald-800"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50")
                  }
                  title={bdExpandAll ? "Showing all clients" : "Show every client at once"}
                >
                  {bdExpandAll ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
                  {bdExpandAll ? "Expanded" : "Expand all"}
                </button>
              )}
            </div>
            {sortedBreakdown.length > 0 ? (
              <>
                <div className="space-y-2.5">
                  {bdSlice.map((b, i) => {
                    const isClient = b.name !== "Unassigned" && b.name !== "No Client" && b.name !== "Internal / Admin";
                    return (
                      <button
                        key={`${b.id}-${b.name}-${i}`}
                        onClick={() =>
                          isClient &&
                          onOpenClient({
                            clientId: b.id,
                            clientName: b.name,
                            employeeId: row.id,
                            employeeLabel: row.label,
                            scoped: b,
                          })
                        }
                        disabled={!isClient}
                        className={
                          "w-full text-left rounded-md -mx-1 px-1 py-0.5 " +
                          (isClient ? "hover:bg-slate-50 cursor-pointer" : "cursor-default")
                        }
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="truncate text-sm font-medium text-slate-700">{b.name}</span>
                          <span className="shrink-0 text-sm font-bold tabular-nums text-slate-800">
                            {fmtHours(b.total_hours)}
                            {b.billable_hours > 0 && (
                              <span className="ml-1.5 rounded bg-emerald-50 px-1.5 py-0.5 align-middle text-[10px] font-bold text-emerald-700">
                                {fmtHours(b.billable_hours)} bill
                              </span>
                            )}
                            {(b.uncategorized_hours || 0) > 0 && (
                              <span className="ml-1.5 rounded bg-amber-50 px-1.5 py-0.5 align-middle text-[10px] font-bold text-amber-600">
                                {fmtHours(b.uncategorized_hours)} review
                              </span>
                            )}
                          </span>
                        </div>
                        <div className="mt-1 h-1.5 rounded bg-slate-100 overflow-hidden">
                          <span
                            className="block h-full bg-emerald-500"
                            style={{ width: `${(b.total_hours / maxItem) * 100}%` }}
                          />
                        </div>
                      </button>
                    );
                  })}
                </div>
                {sortedBreakdown.length > BD_PAGE_SIZE && (
                  <div className="mt-3 pt-2.5 border-t border-slate-100 flex items-center justify-between gap-2 text-xs text-slate-500">
                    <span>
                      Showing {bdSlice.length} of {sortedBreakdown.length} clients
                    </span>
                    {!bdExpandAll && (
                      <div className="flex items-center gap-1.5">
                        <button
                          disabled={bdPageSafe === 0}
                          onClick={(e) => { e.stopPropagation(); setBdPage(bdPageSafe - 1); }}
                          className="px-2 py-0.5 rounded-md border border-slate-200 bg-white font-semibold text-slate-700 disabled:opacity-40"
                        >
                          ← Prev
                        </button>
                        <span className="px-1">{bdPageSafe + 1} / {bdPageCount}</span>
                        <button
                          disabled={bdPageSafe >= bdPageCount - 1}
                          onClick={(e) => { e.stopPropagation(); setBdPage(bdPageSafe + 1); }}
                          className="px-2 py-0.5 rounded-md border border-slate-200 bg-white font-semibold text-slate-700 disabled:opacity-40"
                        >
                          Next →
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p className="text-xs text-slate-400">
                Per-client detail isn't available for this row yet. The top client is{" "}
                <span className="font-medium text-slate-600">{row.top_client || "Internal / Admin"}</span>.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Client drill-down modal ─────────────────────────────────────────────────
function ClientDetailModal({
  row, windowPhrase, scope, activity, activityLoading, onClose,
}: {
  row: SummaryRow;
  windowPhrase: string;
  scope: { employeeId: number | null; employeeLabel: string; scoped: BreakdownItem } | null;
  activity: ActivityResponse | null;
  activityLoading: boolean;
  onClose: () => void;
}) {
  const people = Array.isArray(row.breakdown) ? row.breakdown : [];
  const s = scope?.scoped;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-slate-900/40 px-4 py-16"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
          <div>
            {scope ? (
              <>
                <div className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">{scope.employeeLabel}</div>
                <h3 className="text-xl font-bold text-slate-900">{displayClient(row.label)}</h3>
                <p className="mt-1 text-xs text-slate-500">
                  {scope.employeeLabel}&rsquo;s time on this client {windowPhrase}
                </p>
              </>
            ) : (
              <>
                <h3 className="text-xl font-bold text-slate-900">{displayClient(row.label)}</h3>
                <p className="mt-1 text-xs text-slate-500">
                  {people.length > 0
                    ? `${people.length} ${people.length > 1 ? "people" : "person"} worked this client ${windowPhrase} · ${fmtHours(row.total_hours)} total`
                    : `${fmtHours(row.total_hours)} total ${windowPhrase}`}
                </p>
              </>
            )}
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-500 hover:bg-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-5">
          {/* Stat trio — scoped to the person if opened from their row, else the
              whole client. */}
          <div className="grid grid-cols-3 gap-2.5 mb-5">
            <StatBox label="Billable" value={fmtHours(s ? s.billable_hours : row.billable_hours)} tone="emerald" big />
            <StatBox label="Non-billable" value={fmtHours(s ? s.non_billable_hours : row.non_billable_hours)} big />
            <StatBox
              label="Needs review"
              value={((s ? s.uncategorized_hours : row.uncategorized_hours) || 0) > 0
                ? fmtHours(s ? s.uncategorized_hours : row.uncategorized_hours)
                : "—"}
              tone={((s ? s.uncategorized_hours : row.uncategorized_hours) || 0) > 0 ? "amber" : undefined}
              big
            />
          </div>

          {scope && (
            <div className="mb-5">
              <h4 className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-2">
                What {scope.employeeLabel} worked on
              </h4>
              {activityLoading ? (
                <div className="flex items-center gap-2 py-3 text-slate-400">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-xs">Loading activity…</span>
                </div>
              ) : activity && activity.activities.length > 0 ? (
                <div className="space-y-1.5">
                  {activity.activities.map((a, i) => (
                    <div
                      key={`${a.title}-${i}`}
                      className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-slate-800 truncate">{a.title}</div>
                        <div className="text-[11px] text-slate-400">
                          {a.block_count} {a.block_count === 1 ? "session" : "sessions"}
                        </div>
                      </div>
                      <div className="shrink-0 flex items-center gap-2">
                        {a.billable && (
                          <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700">billable</span>
                        )}
                        {a.needs_review && (
                          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold text-amber-600">review</span>
                        )}
                        <span className="text-sm font-bold tabular-nums text-slate-800">{fmtHours(a.hours)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-400 py-2">
                  No detailed activity recorded for {scope.employeeLabel} on this client in this period.
                </p>
              )}
            </div>
          )}

          <h4 className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1">Who worked it</h4>
          {people.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {people
                .slice()
                .sort((a, b) => b.total_hours - a.total_hours)
                .map((p, i) => {
                  const isScoped = scope != null && p.name === scope.employeeLabel;
                  return (
                  <div
                    key={`${p.id}-${p.name}-${i}`}
                    className={"flex items-center gap-3 py-2.5 px-2 -mx-2 rounded-lg " + (isScoped ? "bg-emerald-50" : "")}
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-xs font-bold text-white">
                      {initials(p.name)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-slate-800 truncate">
                        {p.name}
                        {isScoped && <span className="ml-1.5 text-[10px] font-bold text-emerald-700">• selected</span>}
                      </div>
                      {(p.uncategorized_hours || 0) > 0 && (
                        <div className="text-xs font-medium text-amber-600 mt-0.5">
                          {fmtHours(p.uncategorized_hours)} needs review
                        </div>
                      )}
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-sm font-bold tabular-nums text-slate-800">{fmtHours(p.total_hours)}</div>
                      <div className="text-[11px] font-semibold text-slate-400">
                        {p.billable_hours > 0 ? `${fmtHours(p.billable_hours)} billable` : "non-billable"}
                      </div>
                    </div>
                  </div>
                  );
                })}
            </div>
          ) : (
            <p className="text-xs text-slate-400 py-2">
              Per-person detail for this client isn't available yet.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Small presentational helpers ──────────────────────────────────────────
function StatBox({
  label, value, tone, big,
}: {
  label: string;
  value: string;
  tone?: "emerald" | "amber";
  big?: boolean;
}) {
  const toneMap: Record<string, string> = {
    emerald: "text-emerald-700",
    amber: "text-amber-600",
  };
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2.5">
      <div className={(big ? "text-lg " : "text-base ") + "font-bold tabular-nums " + (tone ? toneMap[tone] : "text-slate-900")}>
        {value}
      </div>
      <div className="mt-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-10 text-center text-sm text-slate-400">
      {label}
    </div>
  );
}