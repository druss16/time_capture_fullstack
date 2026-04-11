/**
 * TaxReturnsTab.tsx
 * Add to ExecutiveDashboard as the 6th tab ("TAX RETURNS")
 *
 * Usage inside ExecutiveDashboard:
 *   import TaxReturnsTab from "./TaxReturnsTab";
 *   ...
 *   {tab === "tax-returns" && <TaxReturnsTab apiBase={apiBase} period={period} />}
 *
 * Also add to tab list:
 *   {(["overview","clients","billing","staff","tax-returns","analysis"] as const).map(...)}
 *
 * Backend: GET /api/analytics/tax-returns/?period=12m
 */

import { useState, useEffect, useCallback, CSSProperties } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, PieChart, Pie, Legend,
} from "recharts";

// ─── Design tokens (matches ExecutiveDashboard) ──────────────────────────────
const C = {
  navy:    "#0d1b2a",
  navyMid: "#122035",
  navyLt:  "#1a2e45",
  gold:    "#c9a84c",
  goldLt:  "#e2c97e",
  teal:    "#2dd4bf",
  rose:    "#fb7185",
  amber:   "#f59e0b",
  violet:  "#a78bfa",
  slate:   "#94a3b8",
  white:   "#f1f5f9",
  border:  "rgba(201,168,76,0.15)",
} as const;

const RETURN_TYPE_COLORS: Record<string, string> = {
  "1040":   C.teal,
  "1065":   C.gold,
  "1120S":  C.violet,
  "1120":   C.amber,
  "990":    C.rose,
  "1041":   "#38bdf8",
  "706":    "#fb923c",
  "709":    "#4ade80",
};

function _getToken() {
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token") ||
    ""
  );
}

// ─── Types ────────────────────────────────────────────────────────────────────
interface StaffBreakdown { name: string; hours: number; }
interface TaxpayerRow {
  taxpayer_name: string;
  taxpayer_id_hash: string;
  return_type: string;
  total_hours: number;
  total_minutes: number;
  staff_count: number;
  staff: StaffBreakdown[];
  days_worked: number;
  last_worked: string | null;
  worked_today: boolean;
  worked_this_week: boolean;
}
interface ReturnTypeRow {
  return_type: string;
  count: number;
  total_hours: number;
  avg_hours: number;
}
interface StaffRow {
  name: string;
  total_hours: number;
  returns_worked: number;
}
interface TaxSummary {
  total_returns: number;
  total_tax_hours: number;
  avg_hours_per_return: number;
  returns_worked_today: number;
  returns_worked_this_week: number;
  hours_today: number;
  hours_this_week: number;
  unmatched_internal_tax_hours: number;
}
interface TaxDashboardResponse {
  meta: { org_name: string; period: string; start_date: string; end_date: string; };
  summary: TaxSummary;
  taxpayers: TaxpayerRow[];
  return_types: ReturnTypeRow[];
  staff: StaffRow[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fmt = (h: number) => {
  const hrs = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  if (hrs === 0) return `${mins}m`;
  if (mins === 0) return `${hrs}h`;
  return `${hrs}h ${mins}m`;
};

function KPITile({ label, value, sub, color = C.gold }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div style={{
      background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12,
      padding: "20px 24px", display: "flex", flexDirection: "column", gap: 6,
    }}>
      <span style={{ fontSize: 11, letterSpacing: 1.5, color: C.slate, textTransform: "uppercase" as const }}>{label}</span>
      <span style={{ fontSize: 30, fontFamily: "'Cormorant Garamond', serif", color, fontWeight: 600, lineHeight: 1 }}>{value}</span>
      {sub && <span style={{ fontSize: 12, color: C.slate }}>{sub}</span>}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ margin: "32px 0 16px", paddingBottom: 8, borderBottom: `1px solid ${C.border}` }}>
      <h3 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 20, fontWeight: 600, color: C.goldLt, margin: 0 }}>
        {children}
      </h3>
    </div>
  );
}

const th: CSSProperties = {
  textAlign: "left", padding: "8px 12px", color: C.slate,
  fontSize: 11, letterSpacing: 1, textTransform: "uppercase",
  borderBottom: `1px solid ${C.border}`,
};
const td: CSSProperties = {
  padding: "10px 12px", borderBottom: `1px solid rgba(201,168,76,0.07)`, color: C.white,
};

function ReturnTypeBadge({ type }: { type: string }) {
  const color = RETURN_TYPE_COLORS[type] || C.slate;
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      background: `${color}22`, border: `1px solid ${color}55`,
      color, fontSize: 11, fontFamily: "'DM Mono', monospace", letterSpacing: 0.5,
    }}>
      {type}
    </span>
  );
}

function StaffPills({ staff }: { staff: StaffBreakdown[] }) {
  return (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" as const }}>
      {staff.slice(0, 3).map((s) => (
        <span key={s.name} style={{
          fontSize: 10, padding: "2px 6px", borderRadius: 3,
          background: C.navyLt, color: C.slate, whiteSpace: "nowrap" as const,
        }}>
          {s.name.split(" ")[0]} {fmt(s.hours)}
        </span>
      ))}
      {staff.length > 3 && (
        <span style={{ fontSize: 10, color: C.slate }}>+{staff.length - 3}</span>
      )}
    </div>
  );
}

function Skeleton({ height = 200 }: { height?: number }) {
  return (
    <div style={{ height, background: C.navyLt, borderRadius: 8, animation: "pulse 1.5s ease-in-out infinite" }}>
      <style>{`@keyframes pulse { 0%,100%{opacity:.4} 50%{opacity:.8} }`}</style>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
interface TaxReturnsTabProps {
  apiBase?: string;
  period?: string;
}

export default function TaxReturnsTab({
  apiBase = "https://timetracker-api-k375.onrender.com",
  period = "12m",
}: TaxReturnsTabProps) {
  const [data, setData] = useState<TaxDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState<string>("all");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/analytics/tax-returns/?period=${period}`, {
        headers: { Authorization: `Bearer ${_getToken()}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || `HTTP ${res.status}`);
      }
      const json = await res.json() as TaxDashboardResponse;
      setData(json);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [apiBase, period]);

  useEffect(() => { load(); }, [load]);

  if (!loading && error) {
    return (
      <div style={{ textAlign: "center", padding: "60px 32px", color: C.rose }}>
        ⚠ {error}
      </div>
    );
  }

  const summary = data?.summary;
  const taxpayers = data?.taxpayers ?? [];
  const returnTypes = data?.return_types ?? [];
  const staff = data?.staff ?? [];

  // Filter taxpayers
  const filtered = taxpayers.filter((t) => {
    const matchSearch = !search || t.taxpayer_name.toLowerCase().includes(search.toLowerCase());
    const matchType = filterType === "all" || t.return_type === filterType;
    return matchSearch && matchType;
  });

  // Chart data
  const returnTypeChartData = returnTypes.map((r) => ({
    name: r.return_type,
    returns: r.count,
    hours: r.total_hours,
    avg: r.avg_hours,
  }));

  const staffChartData = staff.slice(0, 8).map((s) => ({
    name: s.name.split(" ")[0],
    hours: s.total_hours,
    returns: s.returns_worked,
  }));

  const uniqueTypes = Array.from(new Set(taxpayers.map((t) => t.return_type))).sort();

  return (
    <div style={{ paddingBottom: 48 }}>

      {/* ── KPI tiles ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 8 }}>
        <KPITile label="Total Returns" value={loading ? "—" : String(summary?.total_returns ?? 0)} sub={`${period} period`} />
        <KPITile label="Total Tax Hours" value={loading ? "—" : fmt(summary?.total_tax_hours ?? 0)} sub="across all staff" color={C.teal} />
        <KPITile label="Avg per Return" value={loading ? "—" : fmt(summary?.avg_hours_per_return ?? 0)} sub="all return types" color={C.goldLt} />
        <KPITile label="Worked Today" value={loading ? "—" : String(summary?.returns_worked_today ?? 0)} sub={`${fmt(summary?.hours_today ?? 0)} tracked`} color={C.violet} />
        <KPITile label="This Week" value={loading ? "—" : String(summary?.returns_worked_this_week ?? 0)} sub={`${fmt(summary?.hours_this_week ?? 0)} tracked`} color={C.amber} />
        {(summary?.unmatched_internal_tax_hours ?? 0) > 0 && (
          <KPITile
            label="Unmatched Time"
            value={loading ? "—" : fmt(summary?.unmatched_internal_tax_hours ?? 0)}
            sub="Internal-Tax, no taxpayer"
            color={C.rose}
          />
        )}
      </div>

      {/* ── Charts row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>

        {/* Return type breakdown */}
        <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24 }}>
          <div style={{ fontSize: 13, color: C.slate, textTransform: "uppercase" as const, letterSpacing: 1, marginBottom: 16 }}>
            Hours by Return Type
          </div>
          {loading ? <Skeleton height={220} /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={returnTypeChartData} margin={{ top: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="name" tick={{ fill: C.white, fontSize: 12 }} />
                <YAxis tick={{ fill: C.slate, fontSize: 11 }} tickFormatter={(v: number) => `${v}h`} />
                <Tooltip
                  contentStyle={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 8 }}
                  labelStyle={{ color: C.gold }}
                  formatter={(v: number, name: string) => [name === "hours" ? `${v}h` : `${v} returns`, name === "hours" ? "Total Hours" : "Returns"]}
                />
                <Bar dataKey="hours" name="hours" radius={[4, 4, 0, 0] as [number, number, number, number]}>
                  {returnTypeChartData.map((d, i) => (
                    <Cell key={i} fill={RETURN_TYPE_COLORS[d.name] || C.slate} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Staff hours on tax */}
        <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24 }}>
          <div style={{ fontSize: 13, color: C.slate, textTransform: "uppercase" as const, letterSpacing: 1, marginBottom: 16 }}>
            Staff Tax Hours
          </div>
          {loading ? <Skeleton height={220} /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={staffChartData} margin={{ top: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="name" tick={{ fill: C.white, fontSize: 12 }} />
                <YAxis tick={{ fill: C.slate, fontSize: 11 }} tickFormatter={(v: number) => `${v}h`} />
                <Tooltip
                  contentStyle={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 8 }}
                  labelStyle={{ color: C.gold }}
                  formatter={(v: number, name: string) => [name === "hours" ? `${v}h` : `${v}`, name === "hours" ? "Hours" : "Returns"]}
                />
                <Bar dataKey="hours" name="hours" fill={C.teal} radius={[4, 4, 0, 0] as [number, number, number, number]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Return type summary table ── */}
      <SectionTitle>Return Type Summary</SectionTitle>
      <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24, marginBottom: 16 }}>
        {loading ? <Skeleton /> : (
          <table style={{ width: "100%", borderCollapse: "collapse" as const, fontSize: 13 }}>
            <thead>
              <tr>
                {["Return Type", "Returns Worked", "Total Hours", "Avg Hours / Return"].map((h) => (
                  <th key={h} style={th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {returnTypes.map((r) => (
                <tr key={r.return_type}>
                  <td style={td}><ReturnTypeBadge type={r.return_type} /></td>
                  <td style={td}>{r.count}</td>
                  <td style={td}>{fmt(r.total_hours)}</td>
                  <td style={{ ...td, color: C.goldLt }}>{fmt(r.avg_hours)}</td>
                </tr>
              ))}
              {returnTypes.length === 0 && (
                <tr><td colSpan={4} style={{ ...td, textAlign: "center", color: C.slate, padding: 32 }}>No tax return data for this period.</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Taxpayer table ── */}
      <SectionTitle>Time per Taxpayer</SectionTitle>

      {/* Search + filter */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <input
          type="text"
          placeholder="Search taxpayer…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            flex: 1, padding: "8px 14px", borderRadius: 8,
            background: C.navyMid, border: `1px solid ${C.border}`,
            color: C.white, fontSize: 13, fontFamily: "'DM Mono', monospace",
            outline: "none",
          }}
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          style={{
            padding: "8px 14px", borderRadius: 8,
            background: C.navyMid, border: `1px solid ${C.border}`,
            color: C.white, fontSize: 12, fontFamily: "'DM Mono', monospace",
            cursor: "pointer",
          }}
        >
          <option value="all">All Types</option>
          {uniqueTypes.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <span style={{ fontSize: 12, color: C.slate, whiteSpace: "nowrap" as const }}>
          {filtered.length} of {taxpayers.length} returns
        </span>
        <button
          onClick={load}
          style={{
            padding: "8px 16px", borderRadius: 8, background: "transparent",
            border: `1px solid ${C.border}`, color: C.slate, cursor: "pointer",
            fontSize: 12, fontFamily: "'DM Mono', monospace",
          }}
        >
          ↻ Refresh
        </button>
      </div>

      <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12, overflow: "hidden" }}>
        {loading ? <div style={{ padding: 24 }}><Skeleton height={300} /></div> : (
          <table style={{ width: "100%", borderCollapse: "collapse" as const, fontSize: 13 }}>
            <thead>
              <tr>
                {["Taxpayer", "Type", "Total Hours", "Staff", "Last Worked", "Status"].map((h) => (
                  <th key={h} style={th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <>
                  <tr
                    key={t.taxpayer_id_hash || t.taxpayer_name}
                    onClick={() => setExpandedRow(
                      expandedRow === t.taxpayer_id_hash ? null : t.taxpayer_id_hash
                    )}
                    style={{ cursor: "pointer" }}
                  >
                    <td style={{ ...td, fontWeight: 500 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{
                          fontSize: 10, color: C.slate, transform: expandedRow === t.taxpayer_id_hash ? "rotate(90deg)" : "none",
                          transition: "transform 0.15s", display: "inline-block",
                        }}>▶</span>
                        {t.taxpayer_name}
                      </div>
                    </td>
                    <td style={td}><ReturnTypeBadge type={t.return_type} /></td>
                    <td style={{ ...td, color: C.gold, fontWeight: 600 }}>{fmt(t.total_hours)}</td>
                    <td style={td}><StaffPills staff={t.staff} /></td>
                    <td style={{ ...td, color: C.slate, fontSize: 12 }}>
                      {t.last_worked ? new Date(t.last_worked).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—"}
                    </td>
                    <td style={td}>
                      {t.worked_today ? (
                        <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 4, background: `${C.teal}22`, border: `1px solid ${C.teal}55`, color: C.teal }}>
                          Today
                        </span>
                      ) : t.worked_this_week ? (
                        <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 4, background: `${C.amber}22`, border: `1px solid ${C.amber}55`, color: C.amber }}>
                          This week
                        </span>
                      ) : (
                        <span style={{ fontSize: 11, color: C.slate }}>—</span>
                      )}
                    </td>
                  </tr>

                  {/* Expanded staff detail row */}
                  {expandedRow === t.taxpayer_id_hash && (
                    <tr key={`${t.taxpayer_id_hash}-detail`}>
                      <td colSpan={6} style={{ padding: "0 12px 16px 36px", background: C.navyLt }}>
                        <div style={{ paddingTop: 12 }}>
                          <div style={{ fontSize: 11, color: C.slate, marginBottom: 8, letterSpacing: 1, textTransform: "uppercase" as const }}>
                            Staff Breakdown
                          </div>
                          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" as const }}>
                            {t.staff.map((s) => (
                              <div key={s.name} style={{
                                background: C.navyMid, border: `1px solid ${C.border}`,
                                borderRadius: 8, padding: "8px 16px",
                                display: "flex", flexDirection: "column" as const, gap: 4,
                              }}>
                                <span style={{ fontSize: 12, color: C.white, fontWeight: 500 }}>{s.name}</span>
                                <span style={{ fontSize: 14, color: C.teal, fontFamily: "'Cormorant Garamond', serif", fontWeight: 600 }}>
                                  {fmt(s.hours)}
                                </span>
                              </div>
                            ))}
                          </div>
                          <div style={{ marginTop: 12, fontSize: 11, color: C.slate }}>
                            {t.days_worked} day{t.days_worked !== 1 ? "s" : ""} worked on this return
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}

              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ ...td, textAlign: "center", color: C.slate, padding: 40 }}>
                    {taxpayers.length === 0
                      ? "No taxpayer data found. Make sure the AI classifier is running and tax software blocks are being processed."
                      : "No results match your search."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Unmatched time notice ── */}
      {(summary?.unmatched_internal_tax_hours ?? 0) > 0 && (
        <div style={{
          marginTop: 16, padding: "12px 16px",
          background: `${C.amber}11`, border: `1px solid ${C.amber}44`,
          borderRadius: 8, display: "flex", gap: 10, alignItems: "flex-start",
        }}>
          <span style={{ color: C.amber, fontSize: 16, flexShrink: 0 }}>⚠</span>
          <div>
            <div style={{ fontSize: 13, color: C.amber, fontWeight: 600 }}>
              {fmt(summary!.unmatched_internal_tax_hours)} of unmatched Internal-Tax time
            </div>
            <div style={{ fontSize: 12, color: C.slate, marginTop: 4 }}>
              These blocks are assigned to Internal-Tax but have no taxpayer linked. This happens when the AI classifier
              doesn't recognize the UltraTax return title. Check your AI sensitivity settings or add client records
              to match these returns.
            </div>
          </div>
        </div>
      )}

      <p style={{ textAlign: "center", color: C.slate, fontSize: 11, marginTop: 32 }}>
        Taxpayer data is derived from UltraTax and TaxWise window titles. SSNs are never stored — only a one-way hash is retained for deduplication.
      </p>
    </div>
  );
}