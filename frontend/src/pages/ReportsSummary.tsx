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
  Loader2, Download, Clock, TrendingUp, Users, Briefcase, AlertTriangle,
  AlertCircle, HelpCircle, ChevronDown, Search, X, CheckCircle2, ArrowRight,
} from "lucide-react";
import { API_BASE } from "@/lib/api";
import DailyShapeChart from "./DailyShapeChart";
import UncategorizedPanel, { UncatPanelParams } from "./UncategorizedPanel";
import AIPerformanceStrip from "./AIPerformanceStrip";

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

const PERIODS: { key: Period; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
  { key: "quarter", label: "Quarter" },
  { key: "year", label: "Year" },
];

const CLIENT_PAGE_SIZE = 8;

export default function ReportsSummary({
  orgIdOverride,
}: {
  orgIdOverride?: number | null;
}) {
  const [period, setPeriod] = useState<Period>("day");
  const [customMode, setCustomMode] = useState(false);
  const [customStart, setCustomStart] = useState<string>("");
  const [customEnd, setCustomEnd] = useState<string>("");
  const [groupBy, setGroupBy] = useState<GroupBy>("employee");
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelParams, setPanelParams] = useState<UncatPanelParams | null>(null);

  // Redesign state
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [clientSearch, setClientSearch] = useState("");
  const [clientPage, setClientPage] = useState(0);
  const [detail, setDetail] = useState<SummaryRow | null>(null); // client drill-down

  const buildParams = useCallback(() => {
    const p = new URLSearchParams({ group_by: groupBy });
    if (customMode && customStart && customEnd) {
      p.set("start", customStart);
      p.set("end", customEnd);
    } else {
      p.set("period", period);
    }
    const impOrg = localStorage.getItem("impersonating_org_id");
    const effOrg = orgIdOverride || (impOrg ? Number(impOrg) : null);
    if (effOrg) p.set("org_id", String(effOrg));
    return p.toString();
  }, [period, groupBy, orgIdOverride, customMode, customStart, customEnd]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getAuthToken();
      const res = await fetch(`${API_BASE}/reports/summary/?${buildParams()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `Request failed (${res.status})`);
      }
      setData(await res.json());
    } catch (e: any) {
      setError(e.message || "Failed to load report");
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Reset view-local state when the query changes.
  useEffect(() => {
    setExpanded(new Set());
    setClientPage(0);
    setDetail(null);
  }, [period, groupBy, customMode, customStart, customEnd, orgIdOverride]);

  const handleExport = useCallback(() => {
    const token = getAuthToken();
    const url = `${API_BASE}/reports/summary/export/?${buildParams()}`;
    fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: "include",
    })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement("a");
        const href = URL.createObjectURL(blob);
        a.href = href;
        a.download = `time_summary_${period}.csv`;
        a.click();
        URL.revokeObjectURL(href);
      })
      .catch(() => setError("Export failed"));
  }, [buildParams, period]);

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
      data && data.group_by === "client"
        ? [...data.rows].sort((a, b) => b.billable_hours - a.billable_hours)
        : [],
    [data]
  );

  // Headline "where the billable hours went" — top billable clients.
  // Uses client rows when grouped by client; otherwise derives a light rollup
  // from each employee's top_client + billable hours (best-effort until the
  // client query is loaded).
  const headlineClients = useMemo(() => {
    if (!data) return [];
    if (data.group_by === "client") {
      return clientRowsSorted.filter((r) => r.billable_hours > 0).slice(0, 6);
    }
    const map = new Map<string, { label: string; billable_hours: number; people: number }>();
    for (const r of data.rows) {
      const key = r.top_client;
      if (!key || key === "—") continue;
      const cur = map.get(key) || { label: key, billable_hours: 0, people: 0 };
      cur.billable_hours += r.billable_hours;
      cur.people += 1;
      map.set(key, cur);
    }
    return Array.from(map.values())
      .filter((c) => c.billable_hours > 0)
      .sort((a, b) => b.billable_hours - a.billable_hours)
      .slice(0, 6)
      .map((c) => ({
        id: null,
        label: c.label,
        total_hours: c.billable_hours,
        billable_hours: c.billable_hours,
        non_billable_hours: 0,
        utilization_pct: 0,
        top_client: null,
        block_count: 0,
        _people: c.people,
      })) as (SummaryRow & { _people?: number })[];
  }, [data, clientRowsSorted]);

  // Filtered + paginated client list for the Client view.
  const filteredClients = useMemo(() => {
    const q = clientSearch.trim().toLowerCase();
    return q
      ? clientRowsSorted.filter((r) => r.label.toLowerCase().includes(q))
      : clientRowsSorted;
  }, [clientRowsSorted, clientSearch]);

  const clientPageCount = Math.max(1, Math.ceil(filteredClients.length / CLIENT_PAGE_SIZE));
  const clientPageSafe = Math.min(clientPage, clientPageCount - 1);
  const clientSlice = filteredClients.slice(
    clientPageSafe * CLIENT_PAGE_SIZE,
    clientPageSafe * CLIENT_PAGE_SIZE + CLIENT_PAGE_SIZE
  );

  const toggleExpand = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  // Utilization headline (unchanged logic).
  const utilStandard = data?.totals.utilization_standard_pct;
  const utilCaptured = data?.totals.utilization_captured_pct ?? data?.totals.utilization_pct;
  const utilHeadline = utilStandard != null ? utilStandard : utilCaptured ?? 0;
  const utilIsStandard = utilStandard != null;

  const maxHeadlineBill = Math.max(1, ...headlineClients.map((c) => c.billable_hours));

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
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                onClick={() => { setCustomMode(false); setPeriod(p.key); }}
                className={
                  "px-3 py-1.5 text-xs font-medium rounded-md transition-colors " +
                  (!customMode && period === p.key
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-50")
                }
              >
                {p.label}
              </button>
            ))}
            <button
              onClick={() => setCustomMode(true)}
              className={
                "px-3 py-1.5 text-xs font-medium rounded-md transition-colors " +
                (customMode ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50")
              }
            >
              Custom
            </button>
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
        </div>
      </div>

      {data && <AIPerformanceStrip period={period} orgIdOverride={orgIdOverride} />}

      {data && data.scope === "all" && (
        <div className="flex justify-end -mt-2">
          <a
            href="/reports/blind-spots"
            className="inline-flex items-center gap-1 text-xs font-medium text-violet-600 hover:text-violet-700 hover:underline"
          >
            View AI blind spots →
          </a>
        </div>
      )}

      {/* KPI strip (unchanged) */}
      {data && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <KPICard
            icon={<TrendingUp className="h-4 w-4" />}
            label="Utilization"
            value={`${utilHeadline}%`}
            accent="emerald"
            sub={
              utilIsStandard
                ? `${fmtHours(data.totals.billable_hours)} of ${fmtHours(data.totals.available_hours)} available`
                : "Billable ÷ total captured"
            }
            help={
              utilIsStandard
                ? {
                    title: "Of the hours you pay for, how many were billable.",
                    body: `Denominator is a standard 8-hour day per person across ${data.totals.working_days ?? "—"} working day(s) — so leaving the agent running late can't distort it.`,
                    calc: "billable ÷ (headcount × working days × 8h)",
                    extra: utilCaptured != null ? `Of captured time alone: ${utilCaptured}%` : undefined,
                  }
                : {
                    title: "Of the time we tracked, how much was billable.",
                    body: "This denominator moves with how long the agent ran. A standard-hours view is on the way.",
                    calc: "billable ÷ total captured",
                  }
            }
          />
          <KPICard
            icon={<Briefcase className="h-4 w-4" />}
            label="Billable Hours"
            value={fmtHours(data.totals.billable_hours)}
            accent="blue"
            sub="Invoice-ready this period"
            help={{
              title: "Time marked billable and tied to a client.",
              body: "This is what you can put on an invoice — captured automatically, no timesheet entry.",
              calc: "sum(minutes) where billable & client ≠ none",
            }}
          />
          <KPICard
            icon={<Clock className="h-4 w-4" />}
            label="Total Captured"
            value={fmtHours(data.totals.total_hours)}
            accent="slate"
            sub="The full ledger"
            help={{
              title: "Every real minute the agent recorded this period.",
              body: "The honest ledger. Idle time and overnight sleep/wake artifacts are excluded so the number stays trustworthy.",
              calc: "all non-idle, non-anomalous block minutes",
            }}
          />
          <KPICard
            icon={<AlertCircle className="h-4 w-4" />}
            label="Needs review"
            value={fmtHours(data.totals.uncategorized_hours)}
            accent="amber"
            sub="A short to-do list"
            help={{
              title: "Blocks the AI wasn't confident about.",
              body: "Not errors — a queue for an employee to confirm. The red clock in Daily Review points to the same blocks.",
              calc: "low-confidence blocks not yet confirmed",
            }}
          />
          <KPICard
            icon={<Users className="h-4 w-4" />}
            label="Active Clients"
            value={`${data.totals.active_clients}`}
            accent="violet"
            sub={`${fmtHours(data.totals.non_billable_hours)} non-billable`}
          />
        </div>
      )}

      {/* ── HEADLINE: where the billable hours went (client billing first) ── */}
      {data && data.scope === "all" && headlineClients.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
          <h2 className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-4">
            Where the billable hours went
            {data.group_by === "client" && (
              <span className="normal-case font-medium text-slate-400"> — click a client for detail</span>
            )}
          </h2>
          <div className="space-y-3">
            {headlineClients.map((c) => {
              const people = (c as any)._people as number | undefined;
              const clickable = data.group_by === "client";
              return (
                <button
                  key={c.label}
                  disabled={!clickable}
                  onClick={() => clickable && setDetail(c)}
                  className={
                    "w-full grid grid-cols-[minmax(0,1fr)_84px] sm:grid-cols-[220px_minmax(0,1fr)_84px] items-center gap-3 rounded-lg px-1.5 py-1 text-left " +
                    (clickable ? "hover:bg-slate-50 cursor-pointer" : "cursor-default")
                  }
                >
                  <span className="truncate text-sm font-semibold text-slate-800">{c.label}</span>
                  <span className="hidden sm:block h-[26px] rounded-lg bg-slate-100 overflow-hidden">
                    <span
                      className="flex h-full items-center rounded-lg bg-gradient-to-r from-emerald-600 to-emerald-500 pl-2.5 text-[11px] font-bold text-white"
                      style={{ width: `${Math.max((c.billable_hours / maxHeadlineBill) * 100, 6)}%` }}
                    >
                      {clickable
                        ? `${c.block_count > 0 ? c.block_count + " blocks" : ""}`
                        : people != null
                        ? `${people} ${people > 1 ? "people" : "person"}`
                        : ""}
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

          {/* team mix strip */}
          <div className="mt-5 pt-4 border-t border-slate-100">
            <MixStrip
              billable={data.totals.billable_hours}
              nonBillable={data.totals.non_billable_hours}
              review={data.totals.uncategorized_hours || 0}
            />
          </div>
        </div>
      )}

      {data && <DailyShapeChart data={data.timeseries as any} />}

      {/* Group-by toggle + (client) search */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Group by:</span>
          {(["employee", "client"] as GroupBy[]).map((g) => (
            <button
              key={g}
              onClick={() => setGroupBy(g)}
              className={
                "px-2.5 py-1 rounded-md font-medium capitalize transition-colors " +
                (groupBy === g
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-500 hover:text-slate-700")
              }
            >
              {g}
            </button>
          ))}
        </div>

        {groupBy === "client" && data && !loading && (
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
            <input
              value={clientSearch}
              onChange={(e) => { setClientSearch(e.target.value); setClientPage(0); }}
              placeholder="Search clients…"
              className="w-56 pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
            />
          </div>
        )}
      </div>

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

      {/* ── EMPLOYEE VIEW: cards ─────────────────────────────────────────── */}
      {data && !loading && groupBy === "employee" && (
        employeeRows.length === 0 ? (
          <EmptyState label="No committed time in this period yet." />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {employeeRows.map((r) => (
              <EmployeeCard
                key={`${r.id}-${r.label}`}
                row={r}
                expanded={expanded.has(`${r.id}-${r.label}`)}
                onToggle={() => toggleExpand(`${r.id}-${r.label}`)}
                onOpenReview={() =>
                  setPanelParams({
                    period, group_by: "employee", orgId: orgIdOverride,
                    userId: r.id, userLabel: r.label,
                  })
                }
              />
            ))}
          </div>
        )
      )}

      {/* ── CLIENT VIEW: searchable, paginated table ─────────────────────── */}
      {data && !loading && groupBy === "client" && (
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500">Client</th>
                <th className="px-4 py-3 text-right text-[11px] font-bold uppercase tracking-wide text-slate-500">Billable</th>
                <th className="px-4 py-3 text-right text-[11px] font-bold uppercase tracking-wide text-slate-500">Non-bill</th>
                <th className="px-4 py-3 text-right text-[11px] font-bold uppercase tracking-wide text-slate-500">Needs review</th>
                <th className="px-4 py-3 text-right text-[11px] font-bold uppercase tracking-wide text-slate-500">Total</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {clientSlice.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-slate-400">
                    {clientSearch ? `No clients match “${clientSearch}”.` : "No client time in this period yet."}
                  </td>
                </tr>
              )}
              {clientSlice.map((r) => (
                <tr
                  key={`${r.id}-${r.label}`}
                  onClick={() => setDetail(r)}
                  className="hover:bg-slate-50/60 cursor-pointer"
                >
                  <td className="px-4 py-3 font-semibold text-slate-800">{r.label}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-emerald-700 font-medium">{fmtHours(r.billable_hours)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-400">{fmtHours(r.non_billable_hours)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {(r.uncategorized_hours || 0) > 0 ? (
                      <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-amber-600 font-medium">
                        <Clock className="h-3 w-3" />
                        {fmtHours(r.uncategorized_hours)}
                      </span>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums font-semibold text-slate-700">{fmtHours(r.total_hours)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
                      View <ArrowRight className="h-3 w-3" />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* pager */}
          <div className="flex items-center justify-between gap-2 px-4 py-3 bg-slate-50 border-t border-slate-200 text-xs text-slate-500">
            <span>
              Showing {clientSlice.length} of {filteredClients.length} client{filteredClients.length === 1 ? "" : "s"}
            </span>
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
          </div>
        </div>
      )}

      {/* Client drill-down modal */}
      {detail && (
        <ClientDetailModal
          row={detail}
          onClose={() => setDetail(null)}
        />
      )}

      <UncategorizedPanel
        open={!!panelParams}
        onClose={() => setPanelParams(null)}
        params={panelParams || { period, group_by: groupBy }}
      />
    </div>
  );
}

// ── Employee card ─────────────────────────────────────────────────────────
function EmployeeCard({
  row, expanded, onToggle, onOpenReview,
}: {
  row: SummaryRow;
  expanded: boolean;
  onToggle: () => void;
  onOpenReview: () => void;
}) {
  const total = row.total_hours || 0.0001;
  const billPct = (row.billable_hours / total) * 100;
  const nonPct = (row.non_billable_hours / total) * 100;
  const revPct = ((row.uncategorized_hours || 0) / total) * 100;
  const review = row.uncategorized_hours || 0;
  const hasBreakdown = Array.isArray(row.breakdown) && row.breakdown.length > 0;
  const maxItem = hasBreakdown
    ? Math.max(1, ...row.breakdown!.map((b) => b.total_hours))
    : 1;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      {/* header */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-3 text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-700 text-sm font-bold text-white">
            {initials(row.label)}
          </span>
          <div className="min-w-0">
            <div className="text-base font-bold leading-tight text-slate-900 truncate">{row.label}</div>
            <div className="text-xs text-slate-500 mt-0.5 truncate">
              Most time on {row.top_client || "Internal / Admin"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2.5 shrink-0">
          <div className="text-right">
            <div className="text-lg font-bold tabular-nums text-slate-900">{fmtHours(row.total_hours)}</div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Total</div>
          </div>
          <ChevronDown
            className={"h-4 w-4 text-slate-400 transition-transform " + (expanded ? "rotate-180" : "")}
          />
        </div>
      </button>

      {/* mix bar */}
      <div className="mt-3 mb-3 flex h-3.5 overflow-hidden rounded-md">
        <span className="h-full bg-emerald-600" style={{ width: `${billPct}%` }} />
        <span className="h-full bg-slate-400" style={{ width: `${nonPct}%` }} />
        <span className="h-full bg-amber-500" style={{ width: `${revPct}%` }} />
      </div>

      {/* stat boxes */}
      <div className="grid grid-cols-3 gap-2">
        <StatBox label="Billable" value={fmtHours(row.billable_hours)} tone="emerald" />
        <StatBox label="Non-bill" value={fmtHours(row.non_billable_hours)} />
        <StatBox label="Review" value={review > 0 ? fmtHours(review) : "—"} tone={review > 0 ? "amber" : undefined} />
      </div>

      {/* review flag */}
      {review > 0 ? (
        <button
          onClick={onOpenReview}
          className="mt-3 w-full flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-[13px] font-semibold text-amber-600 hover:bg-amber-100"
        >
          <Clock className="h-3.5 w-3.5" />
          {fmtHours(review)} still needs a quick look
        </button>
      ) : (
        <div className="mt-3 w-full flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-[13px] font-semibold text-emerald-700">
          <CheckCircle2 className="h-3.5 w-3.5" />
          All time reviewed — nothing pending
        </div>
      )}

      {/* expandable per-client breakdown */}
      {expanded && (
        <div className="mt-3.5 pt-3.5 border-t border-slate-100">
          <h4 className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-2.5">
            Clients worked this period
          </h4>
          {hasBreakdown ? (
            <div className="space-y-2.5">
              {row.breakdown!
                .slice()
                .sort((a, b) => b.total_hours - a.total_hours)
                .map((b, i) => (
                  <div key={`${b.id}-${b.name}-${i}`}>
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
                  </div>
                ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400">
              Per-client detail isn't available for this row yet. The top client is{" "}
              <span className="font-medium text-slate-600">{row.top_client || "Internal / Admin"}</span>.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Client drill-down modal ─────────────────────────────────────────────────
function ClientDetailModal({ row, onClose }: { row: SummaryRow; onClose: () => void }) {
  const people = Array.isArray(row.breakdown) ? row.breakdown : [];
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
            <h3 className="text-xl font-bold text-slate-900">{row.label}</h3>
            <p className="mt-1 text-xs text-slate-500">
              {people.length > 0
                ? `${people.length} ${people.length > 1 ? "people" : "person"} worked this client · ${fmtHours(row.total_hours)} total`
                : `${fmtHours(row.total_hours)} total this period`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-500 hover:bg-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-5">
          <div className="grid grid-cols-3 gap-2.5 mb-5">
            <StatBox label="Billable" value={fmtHours(row.billable_hours)} tone="emerald" big />
            <StatBox label="Non-billable" value={fmtHours(row.non_billable_hours)} big />
            <StatBox
              label="Needs review"
              value={(row.uncategorized_hours || 0) > 0 ? fmtHours(row.uncategorized_hours) : "—"}
              tone={(row.uncategorized_hours || 0) > 0 ? "amber" : undefined}
              big
            />
          </div>

          <h4 className="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1">Who worked it</h4>
          {people.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {people
                .slice()
                .sort((a, b) => b.total_hours - a.total_hours)
                .map((p, i) => (
                  <div key={`${p.id}-${p.name}-${i}`} className="flex items-center gap-3 py-2.5">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-xs font-bold text-white">
                      {initials(p.name)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-slate-800 truncate">{p.name}</div>
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
                ))}
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
function MixStrip({ billable, nonBillable, review }: { billable: number; nonBillable: number; review: number }) {
  const grand = billable + nonBillable + review || 1;
  const pct = (v: number) => Math.round((v / grand) * 100);
  return (
    <div>
      <div className="flex h-11 overflow-hidden rounded-xl text-[13px] font-bold text-white">
        <span className="flex items-center justify-center bg-emerald-600" style={{ width: `${pct(billable)}%` }}>
          {pct(billable) >= 8 ? `${pct(billable)}%` : ""}
        </span>
        <span className="flex items-center justify-center bg-slate-400" style={{ width: `${pct(nonBillable)}%` }}>
          {pct(nonBillable) >= 8 ? `${pct(nonBillable)}%` : ""}
        </span>
        <span className="flex items-center justify-center bg-amber-500" style={{ width: `${pct(review)}%` }}>
          {pct(review) >= 8 ? `${pct(review)}%` : ""}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-slate-500">
        <span><span className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-emerald-600 align-middle" />Billable <b className="text-slate-800">{fmtHours(billable)}</b></span>
        <span><span className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-slate-400 align-middle" />Non-billable <b className="text-slate-800">{fmtHours(nonBillable)}</b></span>
        <span><span className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-amber-500 align-middle" />Needs review <b className="text-slate-800">{fmtHours(review)}</b></span>
      </div>
    </div>
  );
}

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

interface Help {
  title: string;
  body: string;
  calc?: string;
  extra?: string;
}

function WhyPill({ help }: { help: Help }) {
  return (
    <span className="relative inline-flex group/why align-middle">
      <HelpCircle className="h-3.5 w-3.5 text-slate-300 hover:text-violet-500 cursor-help" />
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 w-60 -translate-x-1/2 translate-y-1
                   rounded-lg bg-slate-900 px-3 py-2.5 text-left text-[11.5px] leading-relaxed text-slate-100
                   opacity-0 shadow-xl transition-all duration-150
                   group-hover/why:translate-y-0 group-hover/why:opacity-100"
      >
        <span className="font-semibold text-white">{help.title}</span>
        <span className="mt-1 block text-slate-300">{help.body}</span>
        {help.calc && (
          <span className="mt-1.5 block border-t border-white/15 pt-1.5 font-mono text-[10.5px] text-slate-400">
            {help.calc}
          </span>
        )}
        {help.extra && <span className="mt-1 block text-[10.5px] text-slate-400">{help.extra}</span>}
      </span>
    </span>
  );
}

function KPICard({
  icon, label, value, sub, accent, help,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent: "emerald" | "blue" | "slate" | "violet" | "amber";
  help?: Help;
}) {
  const accentMap: Record<string, string> = {
    emerald: "text-emerald-600 bg-emerald-50",
    blue: "text-blue-600 bg-blue-50",
    slate: "text-slate-600 bg-slate-100",
    violet: "text-violet-600 bg-violet-50",
    amber: "text-amber-600 bg-amber-50",
  };
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <span className={`inline-flex h-7 w-7 items-center justify-center rounded-lg ${accentMap[accent]}`}>
          {icon}
        </span>
        <span className="text-xs font-medium text-slate-500 inline-flex items-center gap-1">
          {label}
          {help && <WhyPill help={help} />}
        </span>
      </div>
      <div className="mt-2 text-2xl font-semibold text-slate-900 tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-slate-400">{sub}</div>}
    </div>
  );
}