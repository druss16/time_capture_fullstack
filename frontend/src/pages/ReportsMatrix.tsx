/**
 * ReportsMatrix.tsx — the "Wayne grid": a client-as-columns pivot table.
 *
 * Reproduces the client's spreadsheet tabs by swapping the ROW axis while CLIENT
 * stays the fixed column axis:
 *    Employees → person × client   (JUN2026 tab)
 *    Days      → day × client      (work-effort sheet)
 *    Months    → month × client    (Summary tab)
 *
 * "Custom for TL Wall, scalable for everyone" lives in the PRESET:
 *   - GET /api/reports/presets/ returns this org's saved layouts. If a default
 *     preset exists (TL Wall's has expand_all=true, paginate=false), we honor it.
 *   - Every other firm gets the built-in default (paginated) unless they flip
 *     "Expand all" — the toggle is available to everyone, per the product call.
 *
 * SCALABILITY: when expanded (no pagination), rows render through a lightweight
 * windowing pass (only rows near the viewport are in the DOM) so 85 columns ×
 * hundreds of rows stays smooth. No react-window dependency required — a simple
 * scroll-window slice keeps the bundle lean and avoids a new package.
 *
 * Reuses ReportsSummary conventions verbatim: auth token chain, orgIdOverride /
 * impersonation wiring, fmtHours, emerald/slate palette. Drop it into the
 * Reports page as its own <section> (or a tab) — it's fully self-contained.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Download, AlertTriangle, Table2, Maximize2, Minimize2 } from "lucide-react";
import { API_BASE } from "@/lib/api";

// ── Auth token chain (identical to ReportsSummary) ────────────────────────
function getAuthToken(): string | null {
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token")
  );
}

function fmtHours(hours: number | undefined): string {
  const totalMin = Math.round((hours || 0) * 60);
  if (totalMin === 0) return "";
  if (totalMin < 60) return `${totalMin}m`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m === 0 ? `${h}h` : `${h}h${m}m`;
}

type RowAxis = "employee" | "day" | "week" | "month" | "quarter" | "year";
type Metric = "total" | "billable" | "non_billable";
type Period = "day" | "week" | "month" | "quarter" | "year";

interface MatrixColumn { id: number | null; key: string; label: string; total_hours: number; }
interface MatrixRow { key: string | null; label: string; cells: Record<string, number>; total_hours: number; }
interface MatrixResponse {
  org_id: number;
  org_name: string;
  rows_axis: RowAxis;
  cols_axis: "client";
  metric: Metric;
  period: Period;
  range: { start: string; end: string };
  scope: "all" | "self";
  columns: MatrixColumn[];
  rows: MatrixRow[];
  grand_total_hours: number;
}
interface Preset {
  id: number;
  name: string;
  rows_axis: RowAxis;
  metric: Metric;
  expand_all: boolean;
  paginate: boolean;
  show_totals: boolean;
  is_default: boolean;
}

const ROW_AXES: { key: RowAxis; label: string }[] = [
  { key: "employee", label: "Employees" },
  { key: "day", label: "Days" },
  { key: "month", label: "Months" },
];
const METRICS: { key: Metric; label: string }[] = [
  { key: "billable", label: "Billable" },
  { key: "total", label: "Total" },
  { key: "non_billable", label: "Non-billable" },
];
const PERIODS: { key: Period; label: string }[] = [
  { key: "month", label: "Month" },
  { key: "quarter", label: "Quarter" },
  { key: "year", label: "Year" },
];

const ROW_PAGE_SIZE = 25;   // when paginated
const ROW_HEIGHT = 34;      // px, for the virtualization window
const VIEWPORT_ROWS = 24;   // rows kept in DOM around the scroll position

export default function ReportsMatrix({
  orgIdOverride,
}: {
  orgIdOverride?: number | null;
}) {
  const [rowsAxis, setRowsAxis] = useState<RowAxis>("employee");
  const [metric, setMetric] = useState<Metric>("billable");
  const [period, setPeriod] = useState<Period>("month");
  const [expandAll, setExpandAll] = useState(false);   // preset may flip this on
  const [presetLoaded, setPresetLoaded] = useState(false);

  const [data, setData] = useState<MatrixResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const effOrg = useMemo(() => {
    const imp = localStorage.getItem("impersonating_org_id");
    return orgIdOverride || (imp ? Number(imp) : null);
  }, [orgIdOverride]);

  // ── Load the org's default preset ONCE, then apply its layout ───────────
  useEffect(() => {
    (async () => {
      try {
        const token = getAuthToken();
        const p = new URLSearchParams();
        if (effOrg) p.set("org_id", String(effOrg));
        const res = await fetch(`${API_BASE}/reports/presets/?${p.toString()}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: "include",
        });
        if (res.ok) {
          const body: { presets: Preset[] } = await res.json();
          const def = body.presets?.find((x) => x.is_default);
          if (def) {
            setRowsAxis(def.rows_axis);
            setMetric(def.metric);
            setExpandAll(def.expand_all || !def.paginate);
          }
        }
      } catch {
        /* No preset → built-in defaults (paginated employee×client billable). */
      } finally {
        setPresetLoaded(true);
      }
    })();
  }, [effOrg]);

  const buildParams = useCallback(() => {
    const p = new URLSearchParams({ rows: rowsAxis, metric, period });
    if (effOrg) p.set("org_id", String(effOrg));
    return p.toString();
  }, [rowsAxis, metric, period, effOrg]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getAuthToken();
      const res = await fetch(`${API_BASE}/reports/matrix/?${buildParams()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `Request failed (${res.status})`);
      }
      setData(await res.json());
      setPage(0);
    } catch (e: any) {
      setError(e.message || "Failed to load matrix");
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  // Fetch only after the preset has been resolved, so we don't fetch twice
  // (once with defaults, once after the preset flips the axis).
  useEffect(() => {
    if (presetLoaded) fetchData();
  }, [presetLoaded, fetchData]);

  const handleExport = useCallback(() => {
    const token = getAuthToken();
    fetch(`${API_BASE}/reports/matrix/export/?${buildParams()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: "include",
    })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement("a");
        const href = URL.createObjectURL(blob);
        a.href = href;
        a.download = `matrix_${rowsAxis}_x_client_${metric}_${period}.xlsx`;
        a.click();
        URL.revokeObjectURL(href);
      })
      .catch(() => setError("Export failed"));
  }, [buildParams, rowsAxis, metric, period]);

  const columns = data?.columns ?? [];
  const allRows = data?.rows ?? [];

  // Paginated slice (only when NOT expandAll)
  const pageCount = Math.max(1, Math.ceil(allRows.length / ROW_PAGE_SIZE));
  const pageSafe = Math.min(page, pageCount - 1);
  const pagedRows = expandAll
    ? allRows
    : allRows.slice(pageSafe * ROW_PAGE_SIZE, pageSafe * ROW_PAGE_SIZE + ROW_PAGE_SIZE);

  return (
    <section className="space-y-3">
      {/* Header + controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Table2 className="h-4 w-4 text-emerald-700" />
          <h2 className="text-base font-bold text-slate-900">Client grid</h2>
          {data && (
            <span className="text-xs text-slate-400">
              {data.range.start} → {data.range.end}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Row axis */}
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
            {ROW_AXES.map((a) => (
              <button
                key={a.key}
                onClick={() => setRowsAxis(a.key)}
                className={
                  "px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors " +
                  (rowsAxis === a.key ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50")
                }
              >
                {a.label}
              </button>
            ))}
          </div>

          {/* Metric */}
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
            {METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => setMetric(m.key)}
                className={
                  "px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors " +
                  (metric === m.key ? "bg-emerald-700 text-white" : "text-slate-600 hover:bg-slate-50")
                }
              >
                {m.label}
              </button>
            ))}
          </div>

          {/* Period (only meaningful for the employee grid; the day/month grids
              still respect it as the window they span) */}
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                onClick={() => setPeriod(p.key)}
                className={
                  "px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors " +
                  (period === p.key ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50")
                }
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Expand-all toggle — available to every firm */}
          <button
            onClick={() => setExpandAll((v) => !v)}
            className={
              "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors " +
              (expandAll
                ? "border-emerald-700 bg-emerald-50 text-emerald-800"
                : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")
            }
            title={expandAll ? "Currently showing all rows" : "Show all rows and columns at once"}
          >
            {expandAll ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            {expandAll ? "Expanded" : "Expand all"}
          </button>

          <button
            onClick={handleExport}
            disabled={!data}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            Export Excel
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Loading grid…</span>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/40 p-4 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <div className="text-xs text-rose-700">{error}</div>
        </div>
      )}

      {!loading && !error && data && (
        <>
          {columns.length === 0 ? (
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-10 text-center text-sm text-slate-400">
              No client time in this period yet.
            </div>
          ) : (
            <MatrixTable
              rowAxisLabel={ROW_AXES.find((a) => a.key === rowsAxis)?.label.replace(/s$/, "") || "Row"}
              columns={columns}
              rows={pagedRows}
              expandAll={expandAll}
              grandTotal={data.grand_total_hours}
            />
          )}

          {/* Pager — hidden when expanded */}
          {!expandAll && allRows.length > ROW_PAGE_SIZE && (
            <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
              <span>
                Showing {pagedRows.length} of {allRows.length} rows · {columns.length} clients
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  disabled={pageSafe === 0}
                  onClick={() => setPage(pageSafe - 1)}
                  className="px-2.5 py-1 rounded-md border border-slate-200 bg-white font-semibold text-slate-700 disabled:opacity-40"
                >
                  ← Prev
                </button>
                <span className="px-1.5">{pageSafe + 1} / {pageCount}</span>
                <button
                  disabled={pageSafe >= pageCount - 1}
                  onClick={() => setPage(pageSafe + 1)}
                  className="px-2.5 py-1 rounded-md border border-slate-200 bg-white font-semibold text-slate-700 disabled:opacity-40"
                >
                  Next →
                </button>
              </div>
            </div>
          )}
          {expandAll && (
            <div className="text-xs text-slate-400">
              Showing all {allRows.length} rows · {columns.length} clients · scroll to see more
            </div>
          )}
        </>
      )}
    </section>
  );
}

// ── The grid itself ────────────────────────────────────────────────────────
// Sticky first column (row labels) + sticky header row. When expandAll is on
// and there are many rows, we window the row set to keep the DOM light.
function MatrixTable({
  rowAxisLabel, columns, rows, expandAll, grandTotal,
}: {
  rowAxisLabel: string;
  columns: MatrixColumn[];
  rows: MatrixRow[];
  expandAll: boolean;
  grandTotal: number;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);

  // Virtualize only when expanded AND the row count is large enough to matter.
  const virtualize = expandAll && rows.length > 60;

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    if (virtualize) setScrollTop(e.currentTarget.scrollTop);
  }, [virtualize]);

  const startIdx = virtualize ? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 4) : 0;
  const endIdx = virtualize ? Math.min(rows.length, startIdx + VIEWPORT_ROWS + 8) : rows.length;
  const visibleRows = rows.slice(startIdx, endIdx);
  const padTop = virtualize ? startIdx * ROW_HEIGHT : 0;
  const padBottom = virtualize ? (rows.length - endIdx) * ROW_HEIGHT : 0;

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="rounded-xl border border-slate-200 bg-white overflow-auto"
      style={{ maxHeight: expandAll ? "70vh" : undefined }}
    >
      <table className="border-collapse text-xs" style={{ minWidth: "max-content" }}>
        <thead className="sticky top-0 z-20">
          <tr>
            <th className="sticky left-0 z-30 bg-slate-800 text-white text-left font-bold px-3 py-2 min-w-[160px]">
              {rowAxisLabel}
            </th>
            {columns.map((c) => (
              <th
                key={c.key}
                className="bg-slate-800 text-white font-semibold px-2 py-2 text-right whitespace-nowrap max-w-[120px]"
                title={c.label}
              >
                <span className="block truncate max-w-[110px]">{c.label}</span>
              </th>
            ))}
            <th className="sticky right-0 z-30 bg-slate-900 text-white font-bold px-3 py-2 text-right">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {padTop > 0 && (
            <tr style={{ height: padTop }}>
              <td colSpan={columns.length + 2} />
            </tr>
          )}
          {visibleRows.map((r, i) => (
            <tr
              key={`${r.key}-${r.label}`}
              className={((startIdx + i) % 2 === 0 ? "bg-white" : "bg-slate-50/60") + " hover:bg-emerald-50/40"}
              style={{ height: ROW_HEIGHT }}
            >
              <td className="sticky left-0 z-10 bg-inherit font-semibold text-slate-800 px-3 py-1.5 whitespace-nowrap border-r border-slate-100">
                {r.label}
              </td>
              {columns.map((c) => {
                const v = r.cells[String(c.key)] || 0;
                return (
                  <td
                    key={c.key}
                    className={
                      "px-2 py-1.5 text-right tabular-nums whitespace-nowrap " +
                      (v > 0 ? "text-slate-800" : "text-slate-200")
                    }
                  >
                    {v > 0 ? fmtHours(v) : "·"}
                  </td>
                );
              })}
              <td className="sticky right-0 z-10 bg-inherit font-bold text-slate-900 px-3 py-1.5 text-right tabular-nums border-l border-slate-100">
                {fmtHours(r.total_hours)}
              </td>
            </tr>
          ))}
          {padBottom > 0 && (
            <tr style={{ height: padBottom }}>
              <td colSpan={columns.length + 2} />
            </tr>
          )}
        </tbody>
        <tfoot className="sticky bottom-0 z-20">
          <tr>
            <td className="sticky left-0 z-30 bg-slate-100 font-bold text-slate-900 px-3 py-2 border-t border-slate-300">
              Total
            </td>
            {columns.map((c) => (
              <td key={c.key} className="bg-slate-100 font-bold text-slate-700 px-2 py-2 text-right tabular-nums border-t border-slate-300 whitespace-nowrap">
                {fmtHours(c.total_hours)}
              </td>
            ))}
            <td className="sticky right-0 z-30 bg-slate-200 font-extrabold text-slate-900 px-3 py-2 text-right tabular-nums border-t border-slate-300">
              {fmtHours(grandTotal)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}