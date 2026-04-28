/**
 * ExecutiveDashboard.tsx — wired to /api/analytics/executive/
 *
 * Auth: reads token from localStorage key "auth_token"
 * Fallback chain: auth_token → tt_auth_token → authToken → token
 *
 * Plan gating:
 *  - ANALYSIS tab: Executive plan only (hidden/locked for Professional)
 *  - All other tabs: Professional + Executive
 */

import { useState, useEffect, useCallback, ReactNode, CSSProperties } from "react";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, TooltipProps,
} from "recharts";

import AIAnalysisTab from "./AIAnalysisTab";
import TaxReturnsTab from "./TaxReturnsTab";

// ─── Design tokens ─────────────────────────────────────────────────────────
const C = {
  navy:    "#0d1b2a",
  navyMid: "#122035",
  navyLt:  "#1a2e45",
  gold:    "#c9a84c",
  goldLt:  "#e2c97e",
  teal:    "#2dd4bf",
  rose:    "#fb7185",
  slate:   "#94a3b8",
  white:   "#f1f5f9",
  border:  "rgba(201,168,76,0.15)",
} as const;

// ─── Plan gate helper ───────────────────────────────────────────────────────
const isExecutivePlan = (plan: string | undefined): boolean =>
  plan === "executive" || plan?.startsWith("trial") === true;

type StatusKey = "excellent" | "good" | "warning" | "critical" | "no_data";
const STATUS_COLOR: Record<StatusKey, string> = {
  excellent: C.teal, good: "#22c55e", warning: C.gold, critical: C.rose, no_data: C.slate,
};
const WIP_COLORS = [C.teal, C.gold, "#f97316", C.rose];

// ─── Tooltip copy ───────────────────────────────────────────────────────────
const INFO: Record<string, string> = {
  "Realization Rate": "Billed hours ÷ worked hours × 100. Measures how much of your team's time is actually getting invoiced. ≥100% = excellent, 85–99% = good, <85% = leakage.",
  "Billable Utilization": "Billable hours ÷ total tracked hours × 100. Shows what % of time is spent on client work vs. internal/admin. Target: 75–85% for most CPA firms.",
  "WIP Pipeline": "Total dollar value of approved time blocks that haven't been invoiced yet. High WIP means cash is sitting on the table — time to bill.",
  "Effective Rate": "Total billing amount ÷ total billable hours. Your actual blended rate. Compare to your standard rate to see if discounts or write-downs are eroding revenue.",
  "Timesheet Compliance": "% of timesheets submitted within 2 days of week-end. Late submissions delay approvals, invoicing, and cash flow.",
  "Invoice Cycle Time": "Average days from timesheet approval to invoice creation. Shorter = faster cash collection. Target: under 7 days.",
  "Revenue Trend": "Monthly invoiced revenue. Reflects actual billed amounts — only as accurate as your imported invoices.",
  "WIP Aging": "Approved, uninvoiced work bucketed by age. 61–90+ day buckets are at risk of write-off — prioritize invoicing these first.",
  "Timesheet Compliance Chart": "Month-by-month compliance trend. Dips often correlate with busy season, staff changes, or onboarding.",
  "Realization Rate by Client": "Two views of the same gap. HOURS realization (chart): billed hours ÷ worked hours — catches scope creep and unbilled time. DOLLAR realization (table column): invoice $ ÷ standard-rate value of worked hours — also catches rate discounting. Industry benchmark: 95–110% on either measure.",
  "Dollar Realization": "Industry-standard realization rate per AICPA: invoice dollars ÷ standard-rate value of worked hours. Below 90% means a combination of unbilled hours AND discounted rates. Above 100% means premium fixed-fee billing.",
  "Client Profitability": "Revenue (from billing_amount on time blocks) minus labor cost (hours × employee cost rate). All clients appear here even without imported invoices.",
  "Staff Utilization": "Hours per staff member: billable vs. non-billable. Low billable % may indicate admin overload or available capacity.",
  "Staff Detail": "Per-person breakdown of billable hours, total hours, and utilization rate. Useful for capacity planning and performance reviews.",
  "Invoice Revenue vs. Labor Cost": "Actual invoiced revenue vs. labor cost to deliver it. Uses real Invoice amounts — not estimated billing. Requires imported invoices to populate.",
  "Invoice Profitability by Client": "True margin per client: invoiced amount minus worked labor cost. Realization shows invoiced hours ÷ worked hours — gaps indicate unbilled time or scope creep.",
  "Hours by Service Line": "Hours distributed across service types (Tax, Bookkeeping, Advisory, etc.) per client. Requires task types to be tracked on time blocks.",
};

// ─── CSV helper (pure client-side) ─────────────────────────────────────────
function downloadCSV(filename: string, rows: Record<string, string | number>[]) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const escape  = (v: string) => (v.includes(",") || v.includes('"') ? `"${v.replace(/"/g, '""')}"` : v);
  const lines   = [
    headers.join(","),
    ...rows.map((r) => headers.map((h) => escape(String(r[h] ?? ""))).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ─── InfoTooltip ────────────────────────────────────────────────────────────
function InfoTooltip({ text, align = "right" }: { text: string; align?: "right" | "left" }) {
  const [vis, setVis] = useState(false);
  return (
    <div style={{ position: "relative", display: "inline-flex", flexShrink: 0 }}
      onMouseEnter={() => setVis(true)} onMouseLeave={() => setVis(false)}>
      <div style={{
        width: 16, height: 16, borderRadius: "50%",
        border: `1px solid ${vis ? C.gold : C.slate}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 10, color: vis ? C.gold : C.slate, cursor: "help",
        fontFamily: "'DM Mono', monospace", transition: "all 0.15s", userSelect: "none",
      }}>i</div>
      {vis && (
        <div style={{
          position: "absolute",
          ...(align === "right" ? { right: 0 } : { left: 0 }),
          top: "calc(100% + 8px)", width: 260,
          background: C.navy, border: `1px solid ${C.gold}`,
          borderRadius: 8, padding: "10px 14px",
          fontSize: 12, color: C.slate, lineHeight: 1.6,
          zIndex: 9999, boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
          pointerEvents: "none",
        }}>{text}</div>
      )}
    </div>
  );
}

// ─── Fullscreen expand modal ─────────────────────────────────────────────────
function ExpandModal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.88)", zIndex: 10000, display: "flex", flexDirection: "column", padding: 32 }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 26, color: C.gold, margin: 0 }}>{title}</h2>
        <button onClick={onClose} style={{ background: "transparent", border: `1px solid ${C.border}`, color: C.slate, borderRadius: 6, padding: "6px 16px", cursor: "pointer", fontSize: 13, fontFamily: "'DM Mono', monospace" }}>
          ✕ Close
        </button>
      </div>
      <div style={{ flex: 1, background: C.navyMid, borderRadius: 12, border: `1px solid ${C.border}`, padding: 24, overflow: "auto" }}>
        {children}
      </div>
      <p style={{ textAlign: "center", color: C.slate, fontSize: 11, marginTop: 10 }}>Press Escape or click outside to close</p>
    </div>
  );
}

// ─── Card wrapper with controls: info + expand + csv ─────────────────────────
interface InfoCardProps {
  children: ReactNode;
  infoKey: string;
  title?: string;
  expandContent?: ReactNode;
  csvData?: Record<string, string | number>[];
  csvFilename?: string;
  style?: CSSProperties;
}
function InfoCard({ children, infoKey, title, expandContent, csvData, csvFilename, style }: InfoCardProps) {
  const [expanded, setExpanded] = useState(false);
  const infoText = INFO[infoKey];
  const canExpand = !!expandContent;
  const canCSV    = !!(csvData?.length);

  const btnBase: CSSProperties = {
    background: "transparent", border: `1px solid ${C.border}`, borderRadius: 5,
    padding: "3px 9px", cursor: "pointer", fontSize: 11,
    fontFamily: "'DM Mono', monospace", transition: "all 0.15s", color: C.slate,
  };

  return (
    <>
      <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12, padding: "24px", marginBottom: 16, position: "relative", ...style }}>
        <div style={{ position: "absolute", top: 14, right: 14, display: "flex", gap: 7, alignItems: "center", zIndex: 10 }}>
          {canCSV && (
            <button
              style={{ ...btnBase, letterSpacing: 0.4 }}
              title="Download CSV"
              onClick={() => downloadCSV(csvFilename ?? "export.csv", csvData!)}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = C.teal; (e.currentTarget as HTMLElement).style.borderColor = C.teal; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = C.slate; (e.currentTarget as HTMLElement).style.borderColor = C.border; }}
            >↓ CSV</button>
          )}
          {canExpand && (
            <button
              style={{ ...btnBase, fontSize: 13 }}
              title="Expand chart"
              onClick={() => setExpanded(true)}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = C.gold; (e.currentTarget as HTMLElement).style.borderColor = C.gold; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = C.slate; (e.currentTarget as HTMLElement).style.borderColor = C.border; }}
            >⤢</button>
          )}
          {infoText && <InfoTooltip text={infoText} />}
        </div>
        {children}
      </div>
      {expanded && (
        <ExpandModal title={title ?? infoKey} onClose={() => setExpanded(false)}>
          {expandContent}
        </ExpandModal>
      )}
    </>
  );
}

// ─── KPI card ───────────────────────────────────────────────────────────────
function KPICard({ title, value, unit = "", sub, delta, color = C.gold, loading }: {
  title: string; value: string | number | null | undefined; unit?: string; sub?: string; delta?: number; color?: string; loading: boolean;
}) {
  const infoText = INFO[title];
  return (
    <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 12, padding: "20px 24px", display: "flex", flexDirection: "column", gap: 6, minWidth: 160, position: "relative" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, letterSpacing: 1.5, color: C.slate, textTransform: "uppercase" }}>{title}</span>
        {infoText && <InfoTooltip text={infoText} />}
      </div>
      {loading ? <div style={{ height: 40, background: C.navyLt, borderRadius: 6 }} /> : (
        <>
          <span style={{ fontSize: 32, fontFamily: "'Cormorant Garamond', serif", color, fontWeight: 600, lineHeight: 1 }}>
            {value ?? "—"}<span style={{ fontSize: 16, marginLeft: 4 }}>{unit}</span>
          </span>
          {sub && <span style={{ fontSize: 12, color: C.slate }}>{sub}</span>}
          {delta !== undefined && (
            <span style={{ fontSize: 12, color: delta >= 0 ? C.teal : C.rose }}>
              {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}{unit} vs standard
            </span>
          )}
        </>
      )}
    </div>
  );
}

function SectionTitle({ children, infoKey }: { children: ReactNode; infoKey?: string }) {
  const key = infoKey ?? (typeof children === "string" ? children : undefined);
  const infoText = key ? INFO[key] : undefined;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "32px 0 16px", paddingBottom: 8, borderBottom: `1px solid ${C.border}` }}>
      <h3 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 20, fontWeight: 600, color: C.goldLt, margin: 0 }}>{children}</h3>
      {infoText && <InfoTooltip text={infoText} align="left" />}
    </div>
  );
}

function ErrorBox({ kpiName, error }: { kpiName: string; error?: string }) {
  if (!error) return null;
  return (
    <div style={{ padding: "12px 16px", background: "rgba(251,113,133,0.1)", border: `1px solid ${C.rose}`, borderRadius: 8, color: C.rose, fontSize: 13, marginBottom: 8 }}>
      ⚠ {kpiName}: {error}
    </div>
  );
}

function CustomTooltip({ active, payload, label, prefix = "", suffix = "" }: TooltipProps<number, string> & { prefix?: string; suffix?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 14px", fontSize: 13 }}>
      <p style={{ color: C.slate, marginBottom: 6 }}>{label}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey)} style={{ color: p.color || C.gold, margin: "2px 0" }}>
          {p.name}: {prefix}{typeof p.value === "number" ? p.value.toLocaleString() : p.value}{suffix}
        </p>
      ))}
    </div>
  );
}

// ─── Reusable chart renderers ────────────────────────────────────────────────
function RevenueChart({ data, height = 260 }: { data: { month: string; revenue: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
        <defs>
          <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={C.gold} stopOpacity={0.3} />
            <stop offset="95%" stopColor={C.gold} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
        <XAxis dataKey="month" tick={{ fill: C.slate, fontSize: 11 }} />
        <YAxis tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} tick={{ fill: C.slate, fontSize: 11 }} />
        <Tooltip content={<CustomTooltip prefix="$" />} />
        <Area type="monotone" dataKey="revenue" name="Revenue" stroke={C.gold} strokeWidth={2} fill="url(#revGrad)" dot={{ fill: C.gold, r: 3 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

type RealizDatum = {
  name: string;
  worked: number;
  billed: number;
  gap: number;
  realization: number;
  status: StatusKey;
};

function RealizTooltip(props: TooltipProps<number, string>) {
  const { active, payload } = props as { active?: boolean; payload?: Array<{ payload: RealizDatum }> };
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload as RealizDatum;
  const underbilled = d.gap > 0;
  return (
    <div style={{
      background: C.navy, border: `1px solid ${C.border}`, borderRadius: 8,
      padding: "10px 14px", fontSize: 12, color: C.white, minWidth: 220,
    }}>
      <div style={{ fontWeight: 600, color: C.gold, marginBottom: 6 }}>{d.name}</div>
      <div style={{ display: "flex", justifyContent: "space-between", margin: "2px 0" }}>
        <span style={{ color: C.slate }}>Worked:</span>
        <span>{d.worked.toFixed(1)}h</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", margin: "2px 0" }}>
        <span style={{ color: C.slate }}>Billed:</span>
        <span style={{ color: C.gold }}>{d.billed.toFixed(1)}h</span>
      </div>
      <div style={{ height: 1, background: C.border, margin: "6px 0" }} />
      <div style={{ display: "flex", justifyContent: "space-between", margin: "2px 0" }}>
        <span style={{ color: C.slate }}>Gap:</span>
        <span style={{ color: underbilled ? C.rose : "#22c55e", fontWeight: 600 }}>
          {underbilled ? "−" : "+"}{Math.abs(d.gap).toFixed(1)}h
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", margin: "2px 0" }}>
        <span style={{ color: C.slate }}>Realization:</span>
        <span style={{ color: STATUS_COLOR[d.status] }}>{d.realization.toFixed(1)}%</span>
      </div>
      <div style={{ marginTop: 6, fontSize: 11, color: underbilled ? C.rose : "#22c55e", fontStyle: "italic" }}>
        {underbilled ? "Under-billed — hours not making it to invoice" : "Over-realization — fixed-fee or premium rate"}
      </div>
    </div>
  );
}

function RealizChart({ data, height }: { data: RealizDatum[]; height?: number }) {
  const h = height ?? Math.max(280, data.length * 48 + 80);

  // Summary strip totals
  const totalWorked = data.reduce((s, d) => s + d.worked, 0);
  const totalBilled = data.reduce((s, d) => s + d.billed, 0);
  const totalGap = totalWorked - totalBilled;
  const gapColor = totalGap > 0 ? C.rose : "#22c55e";

  const stat: CSSProperties = {
    flex: 1, padding: "12px 16px", background: C.navy,
    border: `1px solid ${C.border}`, borderRadius: 8, textAlign: "center",
  };
  const statLabel: CSSProperties = {
    fontSize: 11, color: C.slate, textTransform: "uppercase",
    letterSpacing: 1, marginBottom: 4,
  };
  const statValue: CSSProperties = { fontSize: 22, fontWeight: 600 };

  return (
    <div>
      {/* Summary strip */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        <div style={stat}>
          <div style={statLabel}>Total Worked</div>
          <div style={{ ...statValue, color: C.white }}>{totalWorked.toFixed(0)}h</div>
        </div>
        <div style={stat}>
          <div style={statLabel}>Total Billed</div>
          <div style={{ ...statValue, color: C.gold }}>{totalBilled.toFixed(0)}h</div>
        </div>
        <div style={stat}>
          <div style={statLabel}>Gap</div>
          <div style={{ ...statValue, color: gapColor }}>
            {totalGap > 0 ? "−" : "+"}{Math.abs(totalGap).toFixed(0)}h
          </div>
        </div>
      </div>

      {/* Paired bar chart */}
      <ResponsiveContainer width="100%" height={h}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ left: 20, right: 60, top: 10, bottom: 10 }}
          barCategoryGap={"20%"}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={C.border} horizontal={false} />
          <XAxis
            type="number"
            tickFormatter={(v: number) => `${v}h`}
            tick={{ fill: C.slate, fontSize: 11 }}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fill: C.white, fontSize: 12 }}
            width={150}
          />
          <Tooltip content={<RealizTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
          <Legend wrapperStyle={{ fontSize: 12, color: C.slate, paddingTop: 8 }} />
          <Bar
            dataKey="worked"
            name="Worked Hours"
            fill={C.slate}
            radius={[0, 4, 4, 0] as [number, number, number, number]}
          />
          <Bar
            dataKey="billed"
            name="Billed Hours"
            radius={[0, 4, 4, 0] as [number, number, number, number]}
          >
            {data.map((d, i) => (
              <Cell key={i} fill={d.gap > 0 ? C.rose : C.gold} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function StaffChart({ data, height = 280 }: { data: { name: string; billable: number; nonBillable: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 10, right: 20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
        <XAxis dataKey="name" tick={{ fill: C.white, fontSize: 12 }} />
        <YAxis tick={{ fill: C.slate, fontSize: 11 }} />
        <Tooltip content={<CustomTooltip suffix="h" />} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.slate }} />
        <Bar dataKey="billable"    name="Billable"     stackId="a" fill={C.teal}    radius={[0,0,0,0] as [number,number,number,number]} />
        <Bar dataKey="nonBillable" name="Non-Billable" stackId="a" fill={C.navyLt} radius={[4,4,0,0] as [number,number,number,number]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function ComplianceChart({ data, height = 200 }: { data: { month: string; compliance: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
        <XAxis dataKey="month" tick={{ fill: C.slate, fontSize: 10 }} />
        <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fill: C.slate, fontSize: 10 }} />
        <Tooltip content={<CustomTooltip suffix="%" />} />
        <Line type="monotone" dataKey="compliance" name="Compliance" stroke={C.teal} strokeWidth={2} dot={{ fill: C.teal, r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function InvoiceBarChart({ data, height }: { data: { name: string; fullName: string; invoiced: number; cost: number; margin: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(280, data.length * 48 + 40)}>
      <BarChart data={data} layout="vertical" margin={{ left: 10, right: 60, top: 10, bottom: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.border} horizontal={false} />
        <XAxis type="number" tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} tick={{ fill: C.slate, fontSize: 11 }} />
        <YAxis type="category" dataKey="name" tick={{ fill: C.white, fontSize: 12 }} width={130} />
        <Tooltip content={({ active, payload }) => {
          if (!active || !payload?.length) return null;
          const d = payload[0]?.payload;
          return (
            <div style={{ background: C.navyMid, border: `1px solid ${C.border}`, padding: "10px 14px", borderRadius: 8 }}>
              <div style={{ color: C.gold, fontWeight: 600, marginBottom: 6 }}>{d.fullName}</div>
              <div style={{ color: C.teal, fontSize: 13 }}>Invoiced: ${d.invoiced?.toLocaleString()}</div>
              <div style={{ color: C.rose, fontSize: 13 }}>Cost: ${d.cost?.toLocaleString()}</div>
              <div style={{ color: d.margin >= 0 ? C.teal : C.rose, fontSize: 13, fontWeight: 600 }}>Margin: ${d.margin?.toLocaleString()}</div>
            </div>
          );
        }} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.slate }} />
        <Bar dataKey="invoiced" name="Invoiced Revenue" fill={C.teal} radius={[0,4,4,0] as [number,number,number,number]} />
        <Bar dataKey="cost"     name="Labor Cost"       fill={C.rose} radius={[0,4,4,0] as [number,number,number,number]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ─── API types ───────────────────────────────────────────────────────────────
interface DashboardMeta { org_id: number; org_name: string; period: string; start_date: string; end_date: string; generated_at: string; plan: string; role: string; }
interface RealizationClient { client_id: number; client_name: string; billed_hours: number; worked_hours: number; billed_amount: number; realization: number; status: StatusKey; }
interface RealizationKPI { overall: number; total_billed_hours: number; total_worked_hours: number; clients: RealizationClient[]; error?: string; }
interface StaffMember { user_id: number; name: string; billable_hours: number; total_hours: number; utilization: number; }
interface UtilizationKPI { overall: number; total_billable_hours: number; total_tracked_hours: number; staff: StaffMember[]; error?: string; }
interface WipBuckets { "0_30": number; "31_60": number; "61_90": number; "90_plus": number; }
interface WipKPI { total: number; buckets: WipBuckets; top_clients: { client: string; wip: number }[]; error?: string; }
interface EffectiveRateKPI { effective_rate: number; standard_rate: number; variance: number; total_billable_hours: number; total_revenue: number; error?: string; }
interface RevenueTrendMonth { month: string; month_label: string; revenue: number; hours: number; invoice_count: number; }
interface RevenueTrendKPI { trend: RevenueTrendMonth[]; total_revenue: number; avg_monthly_revenue: number; error?: string; }
interface ProfitClient { client_id: number; client_name: string; revenue: number; cost: number; margin: number; margin_pct: number; hours: number; }
interface ProfitTotals { revenue: number; cost: number; margin: number; margin_pct: number; }
interface ProfitabilityKPI { clients: ProfitClient[]; totals: ProfitTotals; error?: string; }
interface ComplianceTrendMonth { month: string; compliance: number; total: number; compliant: number; }
interface ComplianceKPI { overall: number | null; total_timesheets: number; compliant: number; late: number; grace_days: number; trend: ComplianceTrendMonth[]; error?: string; }
interface CycleTimeKPI { avg_days: number | null; median_days: number | null; sample_size: number; error?: string; }
interface InvoiceProfitService { service: string; hours: number; cost: number; }
interface InvoiceProfitClient { client_id: number; client_name: string; invoiced_amount: number; invoiced_hours: number; worked_hours: number; worked_cost: number; margin: number; margin_pct: number; realization: number | null; invoice_count: number; services: InvoiceProfitService[]; }
interface InvoiceProfitTotals { invoiced_amount: number; worked_cost: number; margin: number; margin_pct: number; worked_hours: number; }
interface InvoiceProfitabilityKPI { clients: InvoiceProfitClient[]; totals: InvoiceProfitTotals; has_invoices: boolean; error?: string; }
interface DashboardKPIs { realization_rate: RealizationKPI; billable_utilization: UtilizationKPI; wip_pipeline: WipKPI; effective_rate: EffectiveRateKPI; revenue_trend: RevenueTrendKPI; client_profitability: ProfitabilityKPI; invoice_profitability: InvoiceProfitabilityKPI; timesheet_compliance: ComplianceKPI; invoice_cycle_time: CycleTimeKPI; }
interface DashboardResponse { meta: DashboardMeta; kpis: DashboardKPIs; }

function _getToken() {
  return localStorage.getItem("auth_token") || localStorage.getItem("tt_auth_token") || localStorage.getItem("authToken") || localStorage.getItem("token") || "";
}

async function fetchDashboard(apiBase: string, period: string): Promise<DashboardResponse> {
  const params = new URLSearchParams(window.location.search);
  const orgId = params.get("org_id")                          // URL param (existing)
    ?? localStorage.getItem("impersonating_org_id");          // ← add localStorage fallback
  const url = `${apiBase}/analytics/executive/?period=${period}${orgId ? `&org_id=${orgId}` : ""}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${_getToken()}`, "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { error?: string; message?: string };
    throw new Error(body.error || body.message || `HTTP ${res.status}`);
  }
  return res.json();
}

type PeriodValue = "3m" | "6m" | "12m" | "ytd";
const PERIODS: { label: string; value: PeriodValue }[] = [
  { label: "3 months", value: "3m" }, { label: "6 months", value: "6m" },
  { label: "12 months", value: "12m" }, { label: "YTD", value: "ytd" },
];

function buildStyles() {
  const periodBtn = (active: boolean): CSSProperties => ({
    padding: "6px 14px", borderRadius: 6,
    border: `1px solid ${active ? C.gold : C.border}`,
    background: active ? "rgba(201,168,76,0.15)" : "transparent",
    color: active ? C.gold : C.slate, cursor: "pointer",
    fontSize: 12, letterSpacing: 1, fontFamily: "'DM Mono', monospace", transition: "all 0.15s",
  });
  const tabStyle = (active: boolean): CSSProperties => ({
    padding: "10px 20px", cursor: "pointer", fontSize: 12, letterSpacing: 1,
    color: active ? C.gold : C.slate,
    borderBottom: `2px solid ${active ? C.gold : "transparent"}`,
    background: "transparent", border: "none",
    fontFamily: "'DM Mono', monospace", marginBottom: -1, transition: "all 0.15s",
  });
  return {
    root:       { background: C.navy, minHeight: "100vh", fontFamily: "'DM Mono', monospace", color: C.white, padding: "32px 40px" } as CSSProperties,
    header:     { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 32 } as CSSProperties,
    title:      { fontFamily: "'Cormorant Garamond', serif", fontSize: 36, fontWeight: 700, color: C.gold, lineHeight: 1 } as CSSProperties,
    subtitle:   { fontSize: 12, color: C.slate, marginTop: 6 } as CSSProperties,
    periodBar:  { display: "flex", gap: 8, alignItems: "center" } as CSSProperties,
    periodBtn, tabStyle,
    refreshBtn: { padding: "6px 14px", borderRadius: 6, border: `1px solid ${C.border}`, background: "transparent", color: C.slate, cursor: "pointer", fontSize: 12, fontFamily: "'DM Mono', monospace" } as CSSProperties,
    kpiGrid:    { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginBottom: 8 } as CSSProperties,
    tabs:       { display: "flex", gap: 0, marginBottom: 24, borderBottom: `1px solid ${C.border}` } as CSSProperties,
    twoCol:     { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 } as CSSProperties,
    table:      { width: "100%", borderCollapse: "collapse" as const, fontSize: 13 } as CSSProperties,
    th:         { textAlign: "left" as const, padding: "8px 12px", color: C.slate, fontSize: 11, letterSpacing: 1, textTransform: "uppercase" as const, borderBottom: `1px solid ${C.border}` } as CSSProperties,
    td:         { padding: "10px 12px", borderBottom: `1px solid rgba(201,168,76,0.07)`, color: C.white } as CSSProperties,
  };
}

// ─── Upgrade wall (shown inside ANALYSIS tab for non-executive plans) ────────
function AnalysisUpgradeWall({ plan }: { plan: string | undefined }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", padding: "80px 32px", textAlign: "center", gap: 24,
      background: `radial-gradient(ellipse at center, ${C.navyMid} 0%, ${C.navy} 70%)`,
      border: `1px solid ${C.border}`, borderRadius: 16,
    }}>
      <div style={{ fontSize: 52 }}>🔒</div>
      <h2 style={{
        fontFamily: "'Cormorant Garamond', serif", fontSize: 30,
        color: C.gold, margin: 0,
      }}>
        Executive Plan Required
      </h2>
      <p style={{ color: C.slate, fontSize: 15, maxWidth: 440, lineHeight: 1.7, margin: 0 }}>
        AI Firm Analysis is available on the Executive plan. Get instant, actionable
        insights based on your real firm data — wins, warnings, and exactly what to do next.
      </p>
      <a
        href="/account/billing"
        style={{
          padding: "13px 36px", borderRadius: 8, background: C.gold,
          color: C.navy, textDecoration: "none", fontWeight: 700,
          fontFamily: "'DM Mono', monospace", fontSize: 14, letterSpacing: 1,
          boxShadow: `0 0 32px ${C.gold}44`,
        }}
      >
        Upgrade to Executive
      </a>
      <span style={{ fontSize: 11, color: C.slate }}>
        Current plan: {plan ?? "professional"}
      </span>
    </div>
  );
}

// ─── Main ───────────────────────────────────────────────────────────────────
export default function ExecutiveDashboard({ apiBase = "https://timetracker-api-k375.onrender.com" }: { apiBase?: string }) {
  const [period, setPeriod]   = useState<PeriodValue>("12m");
  const [data, setData]       = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [tab, setTab]         = useState("overview");

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetchDashboard(apiBase, period).then(setData).catch((e: Error) => setError(e.message)).finally(() => setLoading(false));
  }, [apiBase, period]);

  useEffect(() => { load(); }, [load]);

  const kpis       = data?.kpis ?? ({} as Partial<DashboardKPIs>);
  const meta       = data?.meta ?? ({} as Partial<DashboardMeta>);
  const realiz     = (kpis.realization_rate     ?? {}) as Partial<RealizationKPI>;
  const utiliz     = (kpis.billable_utilization ?? {}) as Partial<UtilizationKPI>;
  const wip        = (kpis.wip_pipeline         ?? {}) as Partial<WipKPI>;
  const effRate    = (kpis.effective_rate        ?? {}) as Partial<EffectiveRateKPI>;
  const revTrend   = (kpis.revenue_trend         ?? {}) as Partial<RevenueTrendKPI>;
  const profit     = (kpis.client_profitability  ?? {}) as Partial<ProfitabilityKPI>;
  const invProfit  = (kpis.invoice_profitability ?? {}) as Partial<InvoiceProfitabilityKPI>;
  const compliance = (kpis.timesheet_compliance  ?? {}) as Partial<ComplianceKPI>;
  const cycletime  = (kpis.invoice_cycle_time    ?? {}) as Partial<CycleTimeKPI>;

  const params = new URLSearchParams(window.location.search);
  const isAdminOverride = !!params.get("org_id") 
    || !!localStorage.getItem("impersonating_org_id");
  const canAccessAnalysis = isExecutivePlan(meta.plan) || isAdminOverride;

  // chart data
  const revData    = (revTrend.trend ?? []).map((t) => ({ month: t.month_label || t.month, revenue: t.revenue, invoices: t.invoice_count }));
  const wipData    = !wip.buckets ? [] : [
    { name: "0–30 days", value: wip.buckets["0_30"] || 0 },
    { name: "31–60 days", value: wip.buckets["31_60"] || 0 },
    { name: "61–90 days", value: wip.buckets["61_90"] || 0 },
    { name: "90+ days",   value: wip.buckets["90_plus"] || 0 },
  ];
  // Sort by largest GAP first (worked - billed), so worst leakage is at top of chart
  const realizData = [...(realiz.clients ?? [])]
    .map((c) => ({
      name: c.client_name,
      worked: c.worked_hours,
      billed: c.billed_hours,
      gap: c.worked_hours - c.billed_hours,
      realization: c.realization,                                  // hours-based
      dollar_realization: (c as any).dollar_realization ?? null,   // dollar-based
      worked_value: (c as any).worked_value ?? 0,
      billed_amount: (c as any).billed_amount ?? 0,
      status: c.status,
    }))
    .sort((a, b) => b.gap - a.gap)
    .slice(0, 12);
  const staffData  = (utiliz.staff ?? []).slice(0, 8).map((s) => ({
    name: s.name.split(" ")[0],
    billable:    parseFloat(s.billable_hours.toFixed(1)),
    nonBillable: parseFloat((s.total_hours - s.billable_hours).toFixed(1)),
  }));
  const compData   = (compliance.trend ?? []).map((t) => ({ month: t.month, compliance: t.compliance }));
  const invClients = invProfit.clients ?? [];
  const invBarData = invClients.map((c) => ({
    name: c.client_name.length > 14 ? c.client_name.slice(0, 13) + "…" : c.client_name,
    fullName: c.client_name, invoiced: c.invoiced_amount, cost: c.worked_cost, margin: c.margin,
  }));

  // CSV datasets
  const csvRevenue    = revData.map((r)    => ({ Month: r.month, Revenue: r.revenue, Invoices: r.invoices }));
  const csvRealiz     = realizData.map((r) => ({
    Client: r.name,
    "Worked Hours": r.worked,
    "Billed Hours": r.billed,
    "Gap (hrs)": r.gap,
    "Realization %": r.realization,
    Status: r.status,
  }));
  const csvProfit     = (profit.clients ?? []).map((c) => ({ Client: c.client_name, Revenue: c.revenue, Cost: c.cost, Margin: c.margin, "Margin %": c.margin_pct, Hours: c.hours }));
  const csvStaff      = (utiliz.staff ?? []).map((s) => ({ Name: s.name, "Billable Hrs": s.billable_hours, "Total Hrs": s.total_hours, "Utilization %": s.utilization }));
  const csvCompliance = (compliance.trend ?? []).map((t) => ({ Month: t.month, "Compliance %": t.compliance, Total: t.total, Compliant: t.compliant }));
  const csvInvProfit  = invClients.map((c) => ({
    Client: c.client_name, Invoiced: c.invoiced_amount, "Hours Worked": c.worked_hours,
    "Labor Cost": c.worked_cost, Margin: c.margin, "Margin %": c.margin_pct,
    "Realization %": c.realization ?? "", Invoices: c.invoice_count,
  }));

  const s = buildStyles();
  const realizStatus = (v: number | undefined): StatusKey =>
    !v ? "no_data" : v >= 125 ? "excellent" : v >= 100 ? "good" : v >= 85 ? "warning" : "critical";

  // ── Error screen ────────────────────────────────────────────────────────
  if (!loading && error) {
    const isUpgrade = error.includes("upgrade") || error.includes("403");
    return (
      <div style={{ ...s.root, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "60vh" }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>{isUpgrade ? "🔒" : "⚠"}</div>
        <h2 style={{ color: C.gold, fontFamily: "'Cormorant Garamond', serif", fontSize: 28 }}>{isUpgrade ? "Executive Plan Required" : "Dashboard Unavailable"}</h2>
        <p style={{ color: C.slate, marginTop: 8 }}>{error}</p>
        {isUpgrade && <a href="/account/billing" style={{ marginTop: 20, padding: "10px 24px", background: C.gold, color: C.navy, borderRadius: 8, textDecoration: "none", fontWeight: 600 }}>Upgrade Plan</a>}
      </div>
    );
  }

  // ── Tab: Overview ───────────────────────────────────────────────────────
  const OverviewTab = () => (
    <>
      <div style={s.kpiGrid}>
        <KPICard title="Realization Rate"     loading={loading} value={realiz.overall?.toFixed(1)} unit="%" sub={`${realiz.total_billed_hours ?? "—"}h billed / ${realiz.total_worked_hours ?? "—"}h worked`} color={STATUS_COLOR[realizStatus(realiz.overall)]} />
        <KPICard title="Billable Utilization" loading={loading} value={utiliz.overall?.toFixed(1)} unit="%" sub={`${utiliz.total_billable_hours ?? "—"}h billable`} />
        <KPICard title="WIP Pipeline"         loading={loading} value={wip.total?.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })} sub="Approved, not yet invoiced" color={C.teal} />
        <KPICard title="Effective Rate"       loading={loading} value={effRate.effective_rate != null ? `$${effRate.effective_rate.toFixed(0)}` : null} unit="/hr" delta={effRate.variance} color={(effRate.variance ?? 0) >= 0 ? C.teal : C.rose} />
        <KPICard title="Timesheet Compliance" loading={loading} value={compliance.overall?.toFixed(1)} unit="%" sub={`${compliance.compliant ?? "—"} / ${compliance.total_timesheets ?? "—"} on time`} />
        <KPICard title="Invoice Cycle Time"   loading={loading} value={cycletime.avg_days?.toFixed(1)} unit=" days" sub={`Median ${cycletime.median_days ?? "—"}d · n=${cycletime.sample_size ?? 0}`} color={!cycletime.avg_days ? C.slate : cycletime.avg_days <= 7 ? C.teal : cycletime.avg_days <= 14 ? C.gold : C.rose} />
      </div>

      <ErrorBox kpiName="Realization" error={realiz.error} />
      <ErrorBox kpiName="Revenue Trend" error={revTrend.error} />

      <SectionTitle infoKey="Revenue Trend">Revenue Trend — Rolling {meta.period ?? period}</SectionTitle>
      <InfoCard
        infoKey="Revenue Trend" title="Revenue Trend"
        csvData={csvRevenue} csvFilename={`revenue-trend-${period}.csv`}
        expandContent={<RevenueChart data={revData} height={500} />}
      >
        {loading ? <div style={{ height: 260, background: C.navyLt, borderRadius: 8 }} /> : <RevenueChart data={revData} height={260} />}
        <div style={{ display: "flex", gap: 32, marginTop: 16, paddingTop: 16, borderTop: `1px solid ${C.border}` }}>
          <div>
            <div style={{ fontSize: 11, color: C.slate, textTransform: "uppercase", letterSpacing: 1 }}>Total Revenue</div>
            <div style={{ fontSize: 22, fontFamily: "'Cormorant Garamond', serif", color: C.gold }}>${(revTrend.total_revenue ?? 0).toLocaleString()}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.slate, textTransform: "uppercase", letterSpacing: 1 }}>Avg / Month</div>
            <div style={{ fontSize: 22, fontFamily: "'Cormorant Garamond', serif", color: C.goldLt }}>${(revTrend.avg_monthly_revenue ?? 0).toLocaleString()}</div>
          </div>
        </div>
      </InfoCard>

      <div style={s.twoCol}>
        <InfoCard infoKey="WIP Aging" title="WIP Aging"
          expandContent={
            <ResponsiveContainer width="100%" height={500}>
              <PieChart>
                <Pie data={wipData} cx="50%" cy="50%" innerRadius={120} outerRadius={200} paddingAngle={3} dataKey="value">
                  {wipData.map((_, i) => <Cell key={i} fill={WIP_COLORS[i % WIP_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: number) => `$${v.toLocaleString()}`} />
                <Legend wrapperStyle={{ fontSize: 13, color: C.slate }} />
              </PieChart>
            </ResponsiveContainer>
          }
        >
          <div style={{ fontSize: 13, color: C.slate, textTransform: "uppercase", letterSpacing: 1, marginBottom: 16 }}>WIP Aging</div>
          {loading ? <div style={{ height: 200, background: C.navyLt, borderRadius: 8 }} /> : (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={wipData} cx="50%" cy="50%" innerRadius={55} outerRadius={80} paddingAngle={3} dataKey="value">
                  {wipData.map((_, i) => <Cell key={i} fill={WIP_COLORS[i % WIP_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: number) => `$${v.toLocaleString()}`} />
                <Legend wrapperStyle={{ fontSize: 11, color: C.slate }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </InfoCard>

        <InfoCard infoKey="Timesheet Compliance Chart" title="Timesheet Compliance"
          csvData={csvCompliance} csvFilename={`compliance-${period}.csv`}
          expandContent={<ComplianceChart data={compData} height={500} />}
        >
          <div style={{ fontSize: 13, color: C.slate, textTransform: "uppercase", letterSpacing: 1, marginBottom: 16 }}>Timesheet Compliance</div>
          {loading ? <div style={{ height: 200, background: C.navyLt, borderRadius: 8 }} /> : <ComplianceChart data={compData} height={200} />}
        </InfoCard>
      </div>
    </>
  );

  // ── Tab: Clients ────────────────────────────────────────────────────────
  const ClientsTab = () => (
    <>
      <SectionTitle infoKey="Realization Rate by Client">Realization Rate by Client</SectionTitle>
      <InfoCard infoKey="Realization Rate by Client" title="Realization Rate by Client"
        csvData={csvRealiz} csvFilename={`realization-${period}.csv`}
        expandContent={realizData.length > 0 ? <RealizChart data={realizData} height={Math.max(400, realizData.length * 56 + 40)} /> : undefined}
      >
        {loading ? <div style={{ height: 280, background: C.navyLt, borderRadius: 8 }} /> :
         realizData.length === 0 ? <p style={{ color: C.slate, textAlign: "center", padding: 40 }}>No invoice data for this period. Import invoices via Settings → Invoices.</p> :
         <RealizChart data={realizData} />}
      </InfoCard>
      
      {/* Build a quick lookup of realization by client_id for table cells */}
      {/* (placed inline so it's recomputed only when realizData changes) */}
      <SectionTitle infoKey="Invoice Profitability by Client">Client Profitability (Actual Invoices)</SectionTitle>
      <InfoCard
        infoKey="Invoice Profitability by Client"
        csvData={invClients.map((c) => {
          const realizMatch = (realiz.clients ?? []).find(
            (rc: any) => rc.client_id === c.client_id
          ) as any;
          const hoursRealiz = c.worked_hours > 0 ? (c.invoiced_hours / c.worked_hours) * 100 : null;
          return {
            Client: c.client_name,
            "Invoiced $": c.invoiced_amount,
            "Worked Cost $": c.worked_cost,
            Margin: c.margin,
            "Margin %": c.margin_pct,
            "Worked Hrs": c.worked_hours,
            "Billed Hrs": c.invoiced_hours,
            "Hours Realiz %": hoursRealiz != null ? hoursRealiz.toFixed(1) : "",
            "Dollar Realiz %": realizMatch?.dollar_realization ?? "",
          };
        })}
        csvFilename={`invoice-profitability-${period}.csv`}
      >
        {loading ? <div style={{ height: 200, background: C.navyLt, borderRadius: 8 }} /> :
         !invProfit.has_invoices ? (
            <p style={{ color: C.slate, textAlign: "center", padding: 40 }}>
              No invoices imported yet. Profitability requires invoiced revenue — go to Settings → Invoices to import from QuickBooks, Xero, or CSV.
            </p>
         ) : (
          <table style={s.table}>
              <thead><tr>{["Client","Invoiced","Labor Cost","Margin","Margin %","Worked Hrs","Billed Hrs","Hours Realiz.","Dollar Realiz."].map((h) => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
              <tbody>
              {invClients.map((r) => (
                <tr key={r.client_id}>
                  <td style={s.td}>{r.client_name}</td>
                  <td style={s.td}>${r.invoiced_amount.toLocaleString()}</td>
                  <td style={s.td}>${r.worked_cost.toLocaleString()}</td>
                  <td style={{ ...s.td, color: r.margin >= 0 ? C.teal : C.rose, fontWeight: 600 }}>
                    {r.margin < 0 ? "−" : ""}${Math.abs(r.margin).toLocaleString()}
                  </td>
                  <td style={s.td}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ flex: 1, height: 6, background: C.navyLt, borderRadius: 3 }}>
                        <div style={{
                          width: `${Math.min(100, Math.max(0, r.margin_pct))}%`,
                          height: "100%",
                          background: r.margin_pct >= 40 ? C.teal : r.margin_pct >= 20 ? C.gold : C.rose,
                          borderRadius: 3,
                        }} />
                      </div>
                      <span style={{
                        fontSize: 12,
                        color: r.margin_pct < 0 ? C.rose : C.slate,
                        minWidth: 50,
                        fontWeight: r.margin_pct < 0 ? 600 : 400,
                      }}>
                        {r.margin_pct.toFixed(1)}%
                      </span>
                    </div>
                    </td>
                  <td style={{ ...s.td, color: C.slate }}>{r.worked_hours.toFixed(1)}h</td>
                  <td style={{ ...s.td, color: C.gold }}>{r.invoiced_hours.toFixed(1)}h</td>
                  {(() => {
                    // Hours realization: invoiced hours / worked hours
                    const hoursRealiz = r.worked_hours > 0
                      ? (r.invoiced_hours / r.worked_hours) * 100
                      : null;
                    const hoursColor = hoursRealiz == null ? C.slate
                      : hoursRealiz >= 100 ? C.teal
                      : hoursRealiz >= 85  ? C.gold
                      : C.rose;
                    return (
                      <td style={{ ...s.td, color: hoursColor, fontWeight: 500 }}>
                        {hoursRealiz == null ? "—" : `${hoursRealiz.toFixed(1)}%`}
                      </td>
                    );
                  })()}
                  {(() => {
                    // Dollar realization: invoiced amount / (worked hours × standard rate)
                    // Use realiz.clients to find the dollar_realization field
                    const realizMatch = (realiz.clients ?? []).find(
                      (rc: any) => rc.client_id === r.client_id
                    ) as any;
                    const dollarRealiz = realizMatch?.dollar_realization ?? null;
                    const dollarColor = dollarRealiz == null ? C.slate
                      : dollarRealiz >= 100 ? C.teal
                      : dollarRealiz >= 85  ? C.gold
                      : C.rose;
                    return (
                      <td style={{ ...s.td, color: dollarColor, fontWeight: 500 }}>
                        {dollarRealiz == null ? "—" : `${dollarRealiz.toFixed(1)}%`}
                      </td>
                    );
                  })()}
                </tr>
              ))}
              {invProfit.totals && (
                <tr style={{ borderTop: `2px solid ${C.border}` }}>
                  <td style={{ ...s.td, color: C.gold, fontWeight: 600 }}>TOTAL</td>
                  <td style={{ ...s.td, color: C.gold }}>${invProfit.totals.invoiced_amount?.toLocaleString()}</td>
                  <td style={{ ...s.td, color: C.gold }}>${invProfit.totals.worked_cost?.toLocaleString()}</td>
                  <td style={{
                    ...s.td,
                    color: (invProfit.totals.margin ?? 0) >= 0 ? C.teal : C.rose,
                    fontWeight: 600,
                  }}>
                    ${invProfit.totals.margin?.toLocaleString()}
                  </td>
                  <td style={{ ...s.td, color: C.gold }}>{invProfit.totals.margin_pct?.toFixed(1)}%</td>
                  <td style={{ ...s.td, color: C.slate }}>{invProfit.totals.worked_hours?.toFixed(1)}h</td>
                  <td style={s.td} />
                  <td style={{ ...s.td, color: C.gold, fontWeight: 600 }}>
                    {realiz.overall != null ? `${realiz.overall.toFixed(1)}%` : "—"}
                  </td>
                  <td style={{ ...s.td, color: C.gold, fontWeight: 600 }}>
                    {(realiz as any).overall_dollar != null ? `${(realiz as any).overall_dollar.toFixed(1)}%` : "—"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </InfoCard>
    </>
  );

  // ── Tab: Staff ──────────────────────────────────────────────────────────
  const StaffTab = () => (
    <>
      <SectionTitle infoKey="Staff Utilization">Staff Utilization</SectionTitle>
      <InfoCard infoKey="Staff Utilization" title="Staff Utilization"
        csvData={csvStaff} csvFilename={`staff-utilization-${period}.csv`}
        expandContent={<StaffChart data={staffData} height={500} />}
      >
        {loading ? <div style={{ height: 280, background: C.navyLt, borderRadius: 8 }} /> : <StaffChart data={staffData} height={280} />}
      </InfoCard>

      <SectionTitle infoKey="Staff Detail">Staff Detail</SectionTitle>
      <InfoCard infoKey="Staff Detail" csvData={csvStaff} csvFilename={`staff-detail-${period}.csv`}>
        <table style={s.table}>
          <thead><tr>{["Name","Billable Hrs","Total Hrs","Utilization"].map((h) => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
          <tbody>
            {(utiliz.staff ?? []).map((member) => (
              <tr key={member.user_id}>
                <td style={s.td}>{member.name}</td>
                <td style={s.td}>{member.billable_hours.toFixed(1)}</td>
                <td style={s.td}>{member.total_hours.toFixed(1)}</td>
                <td style={s.td}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ flex: 1, height: 6, background: C.navyLt, borderRadius: 3 }}>
                      <div style={{ width: `${Math.min(100, member.utilization)}%`, height: "100%", background: member.utilization >= 75 ? C.teal : member.utilization >= 60 ? C.gold : C.rose, borderRadius: 3 }} />
                    </div>
                    <span style={{ fontSize: 12, color: C.slate, minWidth: 40 }}>{member.utilization.toFixed(1)}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </InfoCard>
    </>
  );

  // ── Tab: Billing ────────────────────────────────────────────────────────
  const BillingTab = () => {
    const totals      = invProfit.totals;
    const hasInvoices = invProfit.has_invoices ?? invClients.length > 0;
    return (
      <>
        <SectionTitle infoKey="Invoice Revenue vs. Labor Cost">Invoice Revenue vs. Labor Cost</SectionTitle>
        <InfoCard infoKey="Invoice Revenue vs. Labor Cost" title="Invoice Revenue vs. Labor Cost"
          csvData={hasInvoices ? csvInvProfit : undefined} csvFilename={`invoice-revenue-vs-cost-${period}.csv`}
          expandContent={hasInvoices ? <InvoiceBarChart data={invBarData} height={Math.max(400, invClients.length * 64 + 40)} /> : undefined}
        >
          {loading ? <div style={{ height: 280, background: C.navyLt, borderRadius: 8 }} /> :
           !hasInvoices ? <p style={{ color: C.slate, textAlign: "center", padding: 40 }}>No invoices found for this period. Import invoices via Settings → Invoices.</p> : (
            <>
              <InvoiceBarChart data={invBarData} />
              {totals && (
                <div style={{ display: "flex", gap: 32, marginTop: 20, paddingTop: 16, borderTop: `1px solid ${C.border}`, flexWrap: "wrap" }}>
                  {[
                    { label: "Total Invoiced",    value: `$${totals.invoiced_amount.toLocaleString()}`, color: C.teal },
                    { label: "Total Labor Cost",   value: `$${totals.worked_cost.toLocaleString()}`,    color: C.rose },
                    { label: "Total Margin",       value: `$${totals.margin.toLocaleString()}`,         color: totals.margin >= 0 ? C.teal : C.rose },
                    { label: "Margin %",           value: `${totals.margin_pct.toFixed(1)}%`,           color: totals.margin_pct >= 30 ? C.teal : totals.margin_pct >= 0 ? C.gold : C.rose },
                    { label: "Total Hours Worked", value: `${totals.worked_hours.toFixed(1)}h`,         color: C.slate },
                  ].map((item) => (
                    <div key={item.label}>
                      <div style={{ fontSize: 11, color: C.slate, textTransform: "uppercase", letterSpacing: 1 }}>{item.label}</div>
                      <div style={{ fontSize: 20, fontFamily: "'Cormorant Garamond', serif", color: item.color }}>{item.value}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </InfoCard>

        <SectionTitle infoKey="Invoice Profitability by Client">Invoice Profitability by Client</SectionTitle>
        <InfoCard infoKey="Invoice Profitability by Client" csvData={csvInvProfit} csvFilename={`invoice-profitability-${period}.csv`}>
          {loading ? <div style={{ height: 200, background: C.navyLt, borderRadius: 8 }} /> :
           invClients.length === 0 ? <p style={{ color: C.slate, textAlign: "center", padding: 40 }}>No data for this period.</p> : (
            <table style={s.table}>
              <thead><tr>{["Client","Invoiced","Hrs Worked","Labor Cost","Margin","Margin %","Realization","Invoices"].map((h) => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
              <tbody>
                {invClients.map((c) => (
                  <tr key={c.client_id}>
                    <td style={s.td}>{c.client_name}</td>
                    <td style={s.td}>${c.invoiced_amount.toLocaleString()}</td>
                    <td style={{ ...s.td, color: C.slate }}>{c.worked_hours.toFixed(1)}h</td>
                    <td style={s.td}>${c.worked_cost.toLocaleString()}</td>
                    <td style={{ ...s.td, color: c.margin >= 0 ? C.teal : C.rose, fontWeight: 600 }}>${c.margin.toLocaleString()}</td>
                    <td style={s.td}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={{ flex: 1, height: 6, background: C.navyLt, borderRadius: 3, minWidth: 60 }}>
                          <div style={{ width: `${Math.min(100, Math.max(0, c.margin_pct))}%`, height: "100%", background: c.margin_pct >= 40 ? C.teal : c.margin_pct >= 20 ? C.gold : C.rose, borderRadius: 3 }} />
                        </div>
                        <span style={{ fontSize: 12, color: C.slate, minWidth: 38 }}>{c.margin_pct.toFixed(1)}%</span>
                      </div>
                    </td>
                    <td style={{ ...s.td, color: c.realization == null ? C.slate : c.realization >= 100 ? C.teal : c.realization >= 85 ? C.gold : C.rose }}>
                      {c.realization != null ? `${c.realization.toFixed(1)}%` : "—"}
                    </td>
                    <td style={{ ...s.td, color: C.slate, textAlign: "center" }}>{c.invoice_count}</td>
                  </tr>
                ))}
                {totals && (
                  <tr style={{ borderTop: `2px solid ${C.border}` }}>
                    <td style={{ ...s.td, color: C.gold, fontWeight: 600 }}>TOTAL</td>
                    <td style={{ ...s.td, color: C.gold }}>${totals.invoiced_amount.toLocaleString()}</td>
                    <td style={{ ...s.td, color: C.slate }}>{totals.worked_hours.toFixed(1)}h</td>
                    <td style={{ ...s.td, color: C.gold }}>${totals.worked_cost.toLocaleString()}</td>
                    <td style={{ ...s.td, color: totals.margin >= 0 ? C.teal : C.rose, fontWeight: 600 }}>${totals.margin.toLocaleString()}</td>
                    <td style={{ ...s.td, color: C.gold }}>{totals.margin_pct.toFixed(1)}%</td>
                    <td style={s.td} /><td style={s.td} />
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </InfoCard>

        {invClients.some((c) => c.services?.length > 1) && (
          <>
            <SectionTitle infoKey="Hours by Service Line">Hours by Service Line</SectionTitle>
            <InfoCard infoKey="Hours by Service Line">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={invClients.filter((c) => c.worked_hours > 0).map((c) => {
                    const row: Record<string, string | number> = { name: c.client_name };
                    c.services.forEach((sv) => { row[sv.service] = sv.hours; });
                    return row;
                  })}
                  margin={{ top: 10, right: 20 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                  <XAxis dataKey="name" tick={{ fill: C.white, fontSize: 11 }} />
                  <YAxis tick={{ fill: C.slate, fontSize: 11 }} tickFormatter={(v: number) => `${v}h`} />
                  <Tooltip content={<CustomTooltip suffix="h" />} />
                  <Legend wrapperStyle={{ fontSize: 12, color: C.slate }} />
                  {Array.from(new Set(invClients.flatMap((c) => c.services.map((sv) => sv.service)))).map((svc, i) => (
                    <Bar key={svc} dataKey={svc} stackId="a" fill={[C.teal, C.gold, "#a78bfa", "#f97316", C.rose][i % 5]} radius={[0,0,0,0] as [number,number,number,number]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </InfoCard>
          </>
        )}
      </>
    );
  };

  // ── Root render ─────────────────────────────────────────────────────────
  return (
    <div style={s.root}>
      <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet" />
      <div style={s.header}>
        <div>
          <div style={s.title}>Executive Dashboard</div>
          <div style={s.subtitle}>{meta.org_name ?? "—"} · {meta.start_date} → {meta.end_date} · {meta.role ?? ""}</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
          <div style={s.periodBar}>
            {PERIODS.map((p) => <button key={p.value} style={s.periodBtn(period === p.value)} onClick={() => setPeriod(p.value)}>{p.label}</button>)}
            <button style={s.refreshBtn} onClick={load} disabled={loading}>{loading ? "…" : "↻ Refresh"}</button>
          </div>
          {meta.generated_at && <span style={{ fontSize: 11, color: C.slate }}>Generated {new Date(meta.generated_at).toLocaleTimeString()}</span>}
        </div>
      </div>

      {/* ── Page-level plan gate — blocks all tabs for non-executive ── */}
      {!loading && !canAccessAnalysis ? (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", padding: "80px 32px", textAlign: "center", gap: 24,
          background: `radial-gradient(ellipse at center, ${C.navyMid} 0%, ${C.navy} 70%)`,
          border: `1px solid ${C.border}`, borderRadius: 16,
        }}>
          <div style={{ fontSize: 52 }}>🔒</div>
          <h2 style={{
            fontFamily: "'Cormorant Garamond', serif", fontSize: 30,
            color: C.gold, margin: 0,
          }}>
            Executive Plan Required
          </h2>
          <p style={{ color: C.slate, fontSize: 15, maxWidth: 460, lineHeight: 1.7, margin: 0 }}>
            The Executive Dashboard — including KPI analytics, client profitability,
            staff utilization, and AI firm analysis — is available on the Executive plan.
          </p>
          <a
            href="/account/billing"
            style={{
              padding: "13px 36px", borderRadius: 8, background: C.gold,
              color: C.navy, textDecoration: "none", fontWeight: 700,
              fontFamily: "'DM Mono', monospace", fontSize: 14, letterSpacing: 1,
              boxShadow: `0 0 32px ${C.gold}44`,
            }}
          >
            Upgrade to Executive
          </a>
          <span style={{ fontSize: 11, color: C.slate }}>
            Current plan: {meta.plan ?? "professional"}
          </span>
        </div>
      ) : (
        <>
          {/* ── Tab bar ── */}
          <div style={s.tabs}>
            {(["overview", "clients", "billing", "staff", "tax-returns", "analysis"] as const).map((id) => (
              <button key={id} style={s.tabStyle(tab === id)} onClick={() => setTab(id)}>
                {id.toUpperCase()}
              </button>
            ))}
          </div>

          {/* ── Tab content ── */}
          {tab === "overview"  && <OverviewTab />}
          {tab === "clients"   && <ClientsTab />}
          {tab === "billing"   && <BillingTab />}
          {tab === "staff"     && <StaffTab />}
          {tab === "tax-returns" && <TaxReturnsTab apiBase={apiBase} period={period} />}
          {tab === "analysis"  && <AIAnalysisTab data={data} apiBase={apiBase} period={period} />}
        </>
      )}
    </div>
  );
}