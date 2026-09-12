/**
 * ChartCard — wraps recharts with our brand styling and handles all chart types
 * the backend produces (line, area, bar, horizontal_bar, stacked_bar, pie,
 * wip_aging, sparkline, proportion_bar, dot_matrix).
 */
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/design-system";
import { formatValue } from "@/lib/analytics_v2/format";
import type { ChartCardPayload } from "@/lib/analytics_v2/types";

// Brand palette — teal-led to match the Lightning primary (Daily Review / Reports)
const SERIES_COLORS = ["#0d9488", "#0d1b2a", "#c9a84c", "#fb7185", "#f97316", "#94a3b8"];

// WIP aging band colors — green to red as age increases
const WIP_AGING_COLORS = ["#10b981", "#c9a84c", "#f97316", "#dc2626"];

interface Props {
  card: ChartCardPayload;
}

export default function ChartCard({ card }: Props) {
  return (
    <div className="rounded-[15px] border border-border/70 bg-white p-5 shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)]">
      <header className="mb-4">
        <h3 className="text-sm font-semibold text-slate-900">{card.title}</h3>
        {card.subtitle && (
          <p className="text-xs text-slate-500 mt-0.5">{card.subtitle}</p>
        )}
        {card.hero && (
          <div className="mt-4 flex items-baseline gap-3 flex-wrap">
            <span className="text-5xl font-semibold tracking-tight tabular-nums text-slate-900">
              {card.hero}
            </span>
            {card.hero_label && (
              <span className="text-sm text-slate-500">{card.hero_label}</span>
            )}
          </div>
        )}
      </header>

      {card.state === "empty" ? (
        <EmptyChart />
      ) : card.state === "error" ? (
        <ErrorChart message={card.error_message} />
      ) : (
        <div className="h-64">
          <ChartByType card={card} />
        </div>
      )}
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="h-64 flex flex-col items-center justify-center text-slate-400">
      <Inbox className="h-8 w-8 mb-2" />
      <p className="text-sm">No data for this period</p>
    </div>
  );
}

function ErrorChart({ message }: { message?: string | null }) {
  return (
    <div className="h-64 flex flex-col items-center justify-center text-rose-600">
      <p className="text-sm font-medium">Couldn't load chart</p>
      {message && <p className="text-xs text-rose-500 mt-1">{message}</p>}
    </div>
  );
}

function ChartByType({ card }: { card: ChartCardPayload }) {
  switch (card.chart_type) {
    case "area":          return <AreaChartView card={card} />;
    case "line":          return <LineChartView card={card} />;
    case "bar":           return <BarChartView card={card} />;
    case "horizontal_bar":return <HorizontalBarView card={card} />;
    case "stacked_bar":   return <StackedBarView card={card} />;
    case "pie":           return <PieChartView card={card} />;
    case "wip_aging":     return <WipAgingChart card={card} />;
    case "proportion_bar":return <ProportionBarView card={card} />;
    case "dot_matrix":    return <DotMatrixView card={card} />;
    default:              return <BarChartView card={card} />;
  }
}

// ─── X-axis key inference ────────────────────────────────────────────────────
// Backend data rows have varying x-axis keys (month_label, client_name, band, etc.)
// Pick the first non-series key as the x-axis.
function xKey(card: ChartCardPayload): string {
  const seriesKeys = new Set(card.series.map(s => s.key));
  const first = card.data[0];
  if (!first) return "name";
  for (const k of Object.keys(first)) {
    if (!seriesKeys.has(k)) return k;
  }
  return Object.keys(first)[0] ?? "name";
}

// ─── Custom tooltip ──────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg bg-slate-900 text-white text-xs px-3 py-2 shadow-lg">
      {label && <div className="font-medium mb-1">{label}</div>}
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-300">{p.name}:</span>
          <span className="font-medium">
            {typeof p.value === "number"
              ? (p.value > 1000 ? `$${Math.round(p.value).toLocaleString()}` : p.value.toFixed(1))
              : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── Chart implementations ───────────────────────────────────────────────────

function AreaChartView({ card }: { card: ChartCardPayload }) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey={x} stroke="#94a3b8" fontSize={11} tickLine={false} />
        <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
        <Tooltip content={<ChartTooltip />} />
        {card.series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
            fill={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
            fillOpacity={0.18}
            strokeWidth={2}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

function LineChartView({ card }: { card: ChartCardPayload }) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey={x} stroke="#94a3b8" fontSize={11} tickLine={false} />
        <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
        <Tooltip content={<ChartTooltip />} />
        {card.series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function BarChartView({ card }: { card: ChartCardPayload }) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey={x} stroke="#94a3b8" fontSize={11} tickLine={false} />
        <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "#f1f5f9" }} />
        {card.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
            radius={[4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function HorizontalBarView({ card }: { card: ChartCardPayload }) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={card.data} layout="vertical" margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
        <XAxis type="number" stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey={x} stroke="#94a3b8" fontSize={11}
               tickLine={false} width={120} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "#f1f5f9" }} />
        {card.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
            radius={[0, 4, 4, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── proportion_bar ─────────────────────────────────────────────────────────
// One horizontal bar whose segments are shares of a whole, with the legend
// carrying the figures. A stacked column answers "how did this month compare";
// this answers "what is this made of", which is a different question and the
// one the Trust lens keeps asking. Rows: {label, value, color?}.
function ProportionBarView({ card }: { card: ChartCardPayload }) {
  const rows = card.data ?? [];
  const total = rows.reduce((sum, r) => sum + (Number(r.value) || 0), 0);
  if (!total) return <EmptyChart />;
  const unit = card.series?.[0]?.label ?? "";
  const pct = (v: unknown) => (Number(v) || 0) / total * 100;
  const colorAt = (r: Record<string, unknown>, i: number) =>
    (r.color as string) ?? SERIES_COLORS[i % SERIES_COLORS.length];

  // Rows may declare a `group`. Five segments read as five peers and the
  // question the chart answers — which is a two-way split — disappears into the
  // subtitle. Grouped, the eye gets two totals and the five reasons become
  // detail underneath them.
  const groups: Array<{ name: string; rows: typeof rows; total: number }> = [];
  rows.forEach(r => {
    const name = (r.group as string) ?? "";
    let g = groups.find(x => x.name === name);
    if (!g) { g = { name, rows: [], total: 0 }; groups.push(g); }
    g.rows.push(r);
    g.total += Number(r.value) || 0;
  });
  const grouped = groups.length > 1 && groups.every(g => g.name);

  return (
    <div className="h-full flex flex-col justify-center gap-6 py-2">
      <div className={cn("flex h-11", grouped ? "gap-2" : "gap-[2px]")} role="img"
           aria-label={rows.map(r => `${r.label}: ${r.value} ${unit}`).join(", ")}>
        {(grouped ? groups : [{ name: "", rows, total }]).map(g => (
          <div key={g.name} className="flex gap-[2px]"
               style={{ width: `${g.total / total * 100}%` }}>
            {g.rows.map(r => {
              const i = rows.indexOf(r);
              if (pct(r.value) <= 0) return null;
              return (
                <div
                  key={String(r.label)}
                  className="rounded-sm min-w-[3px]"
                  style={{ width: `${(Number(r.value) || 0) / g.total * 100}%`,
                           backgroundColor: colorAt(r, i) }}
                  title={`${r.label} — ${formatValue(Number(r.value), "decimal_1dp")} ${unit} (${pct(r.value).toFixed(1)}%)`}
                />
              );
            })}
          </div>
        ))}
      </div>

      {grouped ? (
        <div className="grid gap-x-10 gap-y-5 grid-cols-1 sm:grid-cols-2">
          {groups.map(g => (
            <div key={g.name} className="min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold tabular-nums text-slate-900">
                  {Math.round(g.total / total * 100)}%
                </span>
                <span className="text-sm text-slate-500 tabular-nums">
                  {formatValue(g.total, "decimal_1dp")} {unit}
                </span>
              </div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mt-0.5">
                {g.name}
              </div>
              {/* A lone row would just restate the group total in smaller type. */}
              <ul className={cn("mt-2.5 space-y-1.5", g.rows.length < 2 && "hidden")}>
                {g.rows.map(r => (
                  <li key={String(r.label)} className="flex gap-2 items-baseline text-xs">
                    <span className="h-2 w-2 rounded-sm shrink-0 translate-y-[1px]"
                          style={{ backgroundColor: colorAt(r, rows.indexOf(r)) }} />
                    <span className="tabular-nums text-slate-700 font-medium">
                      {formatValue(Number(r.value), "decimal_1dp")}
                    </span>
                    <span className="text-slate-500 leading-snug">{r.label}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid gap-x-6 gap-y-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((r, i) => (
            <div key={String(r.label)} className="flex gap-2.5 items-start min-w-0">
              <span className="mt-[5px] h-2.5 w-2.5 rounded-sm shrink-0"
                    style={{ backgroundColor: colorAt(r, i) }} />
              <div className="min-w-0">
                <div className="text-sm font-semibold text-slate-900 tabular-nums">
                  {formatValue(Number(r.value), "decimal_1dp")}
                  {unit && <span className="font-normal text-slate-500"> {unit}</span>}
                  <span className="font-normal text-slate-400"> · {pct(r.value).toFixed(1)}%</span>
                </div>
                <div className="text-xs text-slate-500 leading-snug">{r.label}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── dot_matrix ─────────────────────────────────────────────────────────────
// One square per audited item. A percentage invites the reader to take the
// number on faith; a hundred and fifty squares show the sample size, and show
// the ones with no verdict yet, which is the part a bar chart quietly hides.
// Rows: {label, value, color?, outline?}.
function DotMatrixView({ card }: { card: ChartCardPayload }) {
  const rows = card.data ?? [];
  const total = rows.reduce((sum, r) => sum + (Number(r.value) || 0), 0);
  if (!total) return <EmptyChart />;

  const cols = total > 120 ? 15 : total > 60 ? 12 : 10;
  const pitch = 14, size = 9;
  const gridRows = Math.ceil(total / cols);

  const cells: Array<{ fill: string; outline: boolean; label: string }> = [];
  rows.forEach((r, i) => {
    const fill = (r.color as string) ?? SERIES_COLORS[i % SERIES_COLORS.length];
    for (let n = 0; n < (Number(r.value) || 0); n++) {
      cells.push({ fill, outline: Boolean(r.outline), label: String(r.label) });
    }
  });

  return (
    <div className="h-full flex flex-col justify-center gap-4">
      <svg
        viewBox={`0 0 ${cols * pitch - (pitch - size)} ${gridRows * pitch - (pitch - size)}`}
        className="w-full h-auto max-h-44"
        preserveAspectRatio="xMinYMid meet"
        role="img"
        aria-label={rows.map(r => `${r.value} ${r.label}`).join(", ")}
      >
        {cells.map((c, i) => (
          <rect
            key={i}
            x={(i % cols) * pitch}
            y={Math.floor(i / cols) * pitch}
            width={size} height={size} rx={2}
            fill={c.outline ? "none" : c.fill}
            stroke={c.outline ? c.fill : "none"}
            strokeWidth={c.outline ? 1.5 : 0}
          />
        ))}
      </svg>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-600">
        {rows.map((r, i) => {
          const fill = (r.color as string) ?? SERIES_COLORS[i % SERIES_COLORS.length];
          return (
            <span key={String(r.label)} className="inline-flex items-center gap-2">
              <i className="h-2.5 w-2.5 rounded-sm inline-block"
                 style={r.outline
                   ? { border: `1.5px solid ${fill}` }
                   : { backgroundColor: fill }} />
              <span className="tabular-nums font-medium text-slate-900">{r.value}</span>
              {r.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function StackedBarView({ card }: { card: ChartCardPayload }) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey={x} stroke="#94a3b8" fontSize={11} tickLine={false} />
        <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "#f1f5f9" }} />
        {card.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stackId="stack"
            fill={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function PieChartView({ card }: { card: ChartCardPayload }) {
  const valueKey = card.series[0]?.key ?? "value";
  const nameKey = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={card.data}
          dataKey={valueKey}
          nameKey={nameKey}
          cx="50%"
          cy="50%"
          outerRadius={80}
          innerRadius={40}
          paddingAngle={2}
        >
          {card.data.map((_, i) => (
            <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip content={<ChartTooltip />} />
      </PieChart>
    </ResponsiveContainer>
  );
}

/**
 * WIP aging — special chart type. The 90+ band gets visual emphasis.
 * Data shape: [{ band: "0-30 days", value: 12000 }, ...]
 */
function WipAgingChart({ card }: { card: ChartCardPayload }) {
  const total = card.data.reduce((sum, row) => sum + (Number(row.value) || 0), 0);

  return (
    <div className="h-full flex flex-col justify-between">
      {/* Horizontal stacked bar */}
      <div className="flex h-12 rounded-lg overflow-hidden border border-slate-200">
        {card.data.map((row, i) => {
          const pct = total > 0 ? (Number(row.value) / total) * 100 : 0;
          if (pct < 0.5) return null;
          return (
            <div
              key={i}
              className={cn(
                "flex items-center justify-center text-white text-xs font-medium transition-all",
                i === 3 && "ring-2 ring-rose-600 ring-inset", // emphasize 90+
              )}
              style={{
                width: `${pct}%`,
                backgroundColor: WIP_AGING_COLORS[i],
              }}
              title={`${row.band}: ${formatValue(Number(row.value), "currency_0dp")}`}
            >
              {pct > 10 && formatValue(Number(row.value), "currency_0dp")}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="grid grid-cols-4 gap-2 text-xs">
        {card.data.map((row, i) => (
          <div key={i} className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full" style={{ backgroundColor: WIP_AGING_COLORS[i] }} />
              <span className="text-slate-600">{row.band}</span>
            </div>
            <div className={cn(
              "font-medium",
              i === 3 && Number(row.value) > 0 && "text-rose-700",
            )}>
              {formatValue(Number(row.value), "currency_0dp")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
