/**
 * ReportsSummary.tsx — simple high-level time reporting for customer firms.
 *
 * Sits BELOW the C-level DashboardV2. Deliberately flat: four KPI tiles,
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
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Loader2, Download, Clock, TrendingUp, Users, Briefcase, AlertTriangle, AlertCircle,
} from "lucide-react";
import { safeFetchJson, API_BASE } from "@/lib/api";
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

// Format decimal hours as "1h 18m" / "27m" / "2h". Display-only — the raw
// numeric value is still used for sorting, so this doesn't affect ordering.
function fmtHours(hours: number | undefined): string {
  const totalMin = Math.round((hours || 0) * 60);
  if (totalMin < 60) return `${totalMin}m`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

type Period = "day" | "week" | "month" | "quarter";
type GroupBy = "employee" | "client";

interface SummaryRow {
  id: number | null;
  label: string;
  total_hours: number;
  billable_hours: number;
  non_billable_hours: number;
  uncategorized_hours?: number;
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
    utilization_pct: number;
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
  const [groupBy, setGroupBy] = useState<GroupBy>("employee");
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("total_hours");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [panelParams, setPanelParams] = useState<UncatPanelParams | null>(null);

  const buildParams = useCallback(() => {
    const p = new URLSearchParams({ period, group_by: groupBy });
    if (orgIdOverride) p.set("org_id", String(orgIdOverride));
    return p.toString();
  }, [period, groupBy, orgIdOverride]);

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
                onClick={() => setPeriod(p.key)}
                className={
                  "px-3 py-1.5 text-xs font-medium rounded-md transition-colors " +
                  (period === p.key
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-50")
                }
              >
                {p.label}
              </button>
            ))}
          </div>
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
            <ahref="/reports/blind-spots"
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
            value={`${data.totals.utilization_pct}%`}
            accent="emerald"
            sub="Billable ÷ total captured"
          />
          <KPICard
            icon={<Briefcase className="h-4 w-4" />}
            label="Billable Hours"
            value={fmtHours(data.totals.billable_hours)}
            accent="blue"
            sub="Surfaced this period"
          />
          <KPICard
            icon={<Clock className="h-4 w-4" />}
            label="Total Captured"
            value={fmtHours(data.totals.total_hours)}
            accent="slate"
            sub="Confirmed only"
          />
          <KPICard
            icon={<AlertCircle className="h-4 w-4" />}
            label="Uncategorized"
            value={fmtHours(data.totals.uncategorized_hours)}
            accent="amber"
            sub="Needs review"
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
                  Uncategorized
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
                        className="text-amber-600 font-medium hover:underline"
                      >
                        {fmtHours(r.uncategorized_hours)}
                      </button>
                    ) : (
                      <span className="text-slate-300">{fmtHours(r.uncategorized_hours)}</span>
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
      <UncategorizedPanel
        open={!!panelParams}
        onClose={() => setPanelParams(null)}
        params={panelParams || { period, group_by: groupBy }}
      />
    </div>
  );
}

// ── Small presentational helpers ──────────────────────────────────────────
function KPICard({
  icon, label, value, sub, accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent: "emerald" | "blue" | "slate" | "violet" | "amber";
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
        <span className="text-xs font-medium text-slate-500">{label}</span>
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