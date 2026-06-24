/**
 * ReportsSummary.tsx — simple high-level time reporting for customer firms.
 *
 * Sits BELOW the C-level DashboardV2. Deliberately flat: five KPI tiles,
 * a period toggle, one sortable table, and a CSV export button. No drilldowns.
 *
 * Role-gating is enforced server-side (members see only their own numbers),
 * so this component just renders whatever scope the API returns and shows a
 * small "Your time" vs "Team" indicator.
 *
 * MavOps admin reuse: pass an `orgIdOverride` prop (wired from MavOpsAdmin's
 * org selector) and it's appended as ?org_id= — the backend only honors it
 * for staff/superusers.
 *
 * Auth: uses the same localStorage token chain as the rest of the app.
 *
 * WHAT CHANGED (value-framing pass):
 *  - "Uncategorized" → "Needs review" everywhere (it's a queue, not a defect).
 *  - Utilization leads with the STANDARD-HOURS number (billable ÷ available
 *    hours), the figure partners actually quote — with the capture-based number
 *    available in its tooltip. Falls back to capture-based if the backend hasn't
 *    sent the new field yet.
 *  - Every defensible metric carries a small "?" that explains, in plain words,
 *    exactly how it's calculated. Transparency-on-demand is the product thesis
 *    (glass box vs black box), so it lives in the UI, not a help doc.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Loader2, Download, Clock, TrendingUp, Users, Briefcase, AlertTriangle, AlertCircle, HelpCircle,
} from "lucide-react";
import { safeFetchJson, API_BASE } from "@/lib/api";
import DailyShapeChart from "./DailyShapeChart";
import UncategorizedPanel, { UncatPanelParams } from "./UncategorizedPanel";
import AIPerformanceStrip from "./AIPerformanceStrip";
import NeedsReviewQueue from "./NeedsReviewQueue";

// ── Auth token chain (matches ExecutiveDashboard convention) ──────────────
function getAuthToken(): string | null {
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token")
  );
}

// Format decimal hours as "1h 18m" / "27m" / "2h". Display-only — the raw
// numeric value is still used for sorting, so this doesn't affect ordering.
function fmtHours(hours: number | undefined): string {
  const totalMin = Math.round((hours || 0) * 60);
  if (totalMin < 60) return `${totalMin}m`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

type Period = "day" | "week" | "month" | "quarter" | "year";
type GroupBy = "employee" | "client";

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
    utilization_pct: number;                 // legacy / capture-based
    utilization_standard_pct?: number;       // NEW: billable ÷ available hours
    utilization_captured_pct?: number;       // NEW: explicit capture-based
    available_hours?: number;                // NEW: headcount × workdays × 8
    headcount?: number;                      // NEW
    working_days?: number;                   // NEW
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

type SortKey = keyof Pick<
  SummaryRow,
  "label" | "total_hours" | "billable_hours" | "non_billable_hours" | "uncategorized_hours" | "utilization_pct"
>;

export default function ReportsSummary({
  orgIdOverride,
}: {
  orgIdOverride?: number | null;
}) {
  const [period, setPeriod] = useState<Period>("week");
  const [customMode, setCustomMode] = useState(false);
  const [customStart, setCustomStart] = useState<string>("");
  const [customEnd, setCustomEnd] = useState<string>("");
  const [groupBy, setGroupBy] = useState<GroupBy>("employee");
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("total_hours");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [panelParams, setPanelParams] = useState<UncatPanelParams | null>(null);

  const buildParams = useCallback(() => {
    const p = new URLSearchParams({ group_by: groupBy });
    if (customMode && customStart && customEnd) {
      // Backend uses explicit start/end when both are present, ignoring period.
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
      const res = await fetch(
        `${API_BASE}/reports/summary/?${buildParams()}`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: "include",
        }
      );
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

  const handleExport = useCallback(() => {
    const token = getAuthToken();
    const url = `${API_BASE}/reports/summary/export/?${buildParams()}`;
    // Token in querystring isn't used here — export relies on session cookie
    // via credentials. For token-only clients, fetch+blob instead:
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

  const sortedRows = useMemo(() => {
    if (!data) return [];
    const rows = [...data.rows];
    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp: number;
      if (typeof av === "string" && typeof bv === "string") {
        cmp = av.localeCompare(bv);
      } else {
        cmp = ((av as number) || 0) - ((bv as number) || 0);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [data, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  // Lead with standard-hours utilization (billable ÷ available hours) — the
  // number partners quote. Fall back to capture-based if the backend hasn't
  // shipped the new field. Keep both so the tooltip can show the contrast.
  const utilStandard = data?.totals.utilization_standard_pct;
  const utilCaptured =
    data?.totals.utilization_captured_pct ?? data?.totals.utilization_pct;
  const utilHeadline =
    utilStandard != null ? utilStandard : (utilCaptured ?? 0);
  const utilIsStandard = utilStandard != null;

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
            <a href="/reports/blind-spots"
            className="inline-flex items-center gap-1 text-xs font-medium text-violet-600 hover:text-violet-700 hover:underline"
          >
            View AI blind spots →
          </a>
        </div>
      )}

      {/* KPI strip */}
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

      {data && <DailyShapeChart data={data.timeseries as any} />}

      {/* Group-by toggle */}
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

      {/* Table */}
      {data && !loading && (
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <Th onClick={() => toggleSort("label")} active={sortKey === "label"} dir={sortDir}>
                  {groupBy === "employee" ? "Employee" : "Client"}
                </Th>
                <Th onClick={() => toggleSort("total_hours")} active={sortKey === "total_hours"} dir={sortDir} right>
                  Total
                </Th>
                <Th onClick={() => toggleSort("billable_hours")} active={sortKey === "billable_hours"} dir={sortDir} right>
                  Billable
                </Th>
                <Th onClick={() => toggleSort("non_billable_hours")} active={sortKey === "non_billable_hours"} dir={sortDir} right>
                  Non-Bill
                </Th>
                <Th onClick={() => toggleSort("uncategorized_hours")} active={sortKey === "uncategorized_hours"} dir={sortDir} right>
                  Needs review
                </Th>
                <Th onClick={() => toggleSort("utilization_pct")} active={sortKey === "utilization_pct"} dir={sortDir} right>
                  Util %
                </Th>
                {groupBy === "employee" && (
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500">
                    Top Client
                  </th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {sortedRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-sm text-slate-400">
                    No committed time in this period yet.
                  </td>
                </tr>
              )}
              {sortedRows.map((r) => (
                <tr key={`${r.id}-${r.label}`} className="hover:bg-slate-50/60">
                  <td className="px-4 py-2.5 font-medium text-slate-800">{r.label}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-700">{fmtHours(r.total_hours)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-emerald-700">{fmtHours(r.billable_hours)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-400">{fmtHours(r.non_billable_hours)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {(r.uncategorized_hours || 0) > 0 ? (
                      <button
                        onClick={() => setPanelParams({
                          period, group_by: groupBy, orgId: orgIdOverride,
                          userId: groupBy === "employee" ? r.id : null,
                          userLabel: r.label,
                        })}
                        className="inline-flex items-center gap-1 text-amber-600 font-medium hover:underline"
                        title="Open the blocks waiting on review"
                      >
                        <Clock className="h-3 w-3" />
                        {fmtHours(r.uncategorized_hours)}
                      </button>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-700">{r.utilization_pct}%</td>
                  {groupBy === "employee" && (
                    <td className="px-4 py-2.5 text-slate-500 text-xs">{r.top_client || "—"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Distinct bottom section: Needs review ──────────────────────────
          Moved here (below the table) so the page reads top-to-bottom as:
          AI strip → KPIs → shape → team table → the review queue. Team scope
          only; a single member sees their own pile in Daily Review already. */}
      {data && data.scope === "all" && !loading && (
        <section className="pt-6 mt-2 border-t border-slate-200 space-y-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Review queue</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Blocks the AI flagged for a person to confirm — and the patterns
              worth teaching it.
            </p>
          </div>
          <NeedsReviewQueue period={period} orgIdOverride={orgIdOverride} />
        </section>
      )}

      <UncategorizedPanel
        open={!!panelParams}
        onClose={() => setPanelParams(null)}
        params={panelParams || { period, group_by: groupBy }}
      />
    </div>
  );
}

// ── Small presentational helpers ──────────────────────────────────────────

// The signature move: a why-pill that explains a metric in plain words, with
// the actual formula. Transparency-on-demand — the glass-box thesis lives here.
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
        {help.extra && (
          <span className="mt-1 block text-[10.5px] text-slate-400">{help.extra}</span>
        )}
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

function Th({
  children, onClick, active, dir, right,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  dir: "asc" | "desc";
  right?: boolean;
}) {
  return (
    <th
      onClick={onClick}
      className={
        "px-4 py-2.5 text-xs font-medium text-slate-500 cursor-pointer select-none hover:text-slate-700 " +
        (right ? "text-right" : "text-left")
      }
    >
      {children}
      {active && <span className="ml-1 text-slate-400">{dir === "asc" ? "↑" : "↓"}</span>}
    </th>
  );
}