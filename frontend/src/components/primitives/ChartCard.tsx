/**
 * ChartCard — wraps recharts with our brand styling and handles all chart types
 * the backend produces (line, area, bar, horizontal_bar, stacked_bar, pie,
 * wip_aging, sparkline, proportion_bar, dot_matrix).
 */
import { useState } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/design-system";
import { formatValue } from "@/lib/analytics_v2/format";
import type {
  ChartCardPayload, ChartToggleView, NumberFormat,
} from "@/lib/analytics_v2/types";
import {
  CHROME, EMPHASIS, SERIES, SERIES_FALLBACK, seriesColor,
} from "@/lib/analytics_v2/theme";

// WIP aging band colors — an ordered ramp, not categorical identity: these
// bands have a natural order (fresher → staler), so a single-hue-to-status
// progression is the right encoding.
const WIP_AGING_COLORS = ["#0f766e", "#0d9488", "#eb6834", "#be123c"];

/**
 * Colour for a series, by IDENTITY not by row number.
 *
 * The old implementation was `SERIES_COLORS[i % SERIES_COLORS.length]` over a
 * hand-picked six. Two problems: the modulo silently reused a hue for a 7th
 * series, and the six were never checked for colour-vision separation. The
 * palette in theme.ts is validated; `seriesColor` folds anything past it into
 * a neutral instead of inventing a hue.
 */
/** Palette slot for a ROW index (proportion bar, dot matrix). Neutral past the end. */
function rowColor(i: number): string {
  return i < SERIES.length ? SERIES[i] : SERIES_FALLBACK;
}

function colorFor(card: ChartCardPayload, key: string, explicit?: string): string {
  if (explicit) return explicit;
  const role = card.series.find(x => x.key === key)?.role;
  if (role === "primary") return EMPHASIS.primary;
  if (role === "muted") return EMPHASIS.muted;
  return seriesColor(key, card.series.map(x => x.key));
}

interface Props {
  card: ChartCardPayload;
}

export default function ChartCard({ card }: Props) {
  const views = card.toggle_views ?? [];
  const [activeKey, setActiveKey] = useState(views[0]?.key ?? "");
  // Falls back to the first view if a previously-selected one has gone — which
  // happens for real: the backend drops the cost views for a viewer who may
  // not see cost.
  const active: ChartToggleView | undefined =
    views.find(v => v.key === activeKey) ?? views[0];

  // With a toggle, the card renders the active view: its series, its chart
  // type, and crucially its FORMAT. Without one it renders what it was sent.
  const shown: ChartCardPayload = active
    ? {
        ...card,
        chart_type: active.chart_type ?? card.chart_type,
        series: active.series.map(key => ({
          key,
          label: active.label,
        })),
      }
    : card;
  const format: NumberFormat | undefined =
    active?.format ?? (card.value_format || undefined);

  return (
    <div className="rounded-2xl border border-[rgba(15,42,60,0.08)] bg-white p-5 shadow-[0_1px_2px_rgba(16,27,46,0.04),0_8px_24px_-12px_rgba(16,27,46,0.10)]">
      <header className="mb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-900">{card.title}</h3>
            {card.subtitle && (
              <p className="text-xs text-slate-500 mt-0.5">{card.subtitle}</p>
            )}
          </div>
          {views.length > 1 && (
            <div
              role="tablist"
              aria-label={card.toggle_label || "Measure"}
              className="flex flex-wrap gap-1 rounded-xl bg-slate-100/80 p-1 print:hidden"
            >
              {views.map(v => (
                <button
                  key={v.key}
                  type="button"
                  role="tab"
                  aria-selected={active?.key === v.key}
                  onClick={() => setActiveKey(v.key)}
                  className={cn(
                    "rounded-lg px-2.5 py-1 text-xs font-medium transition-colors",
                    active?.key === v.key
                      ? "bg-white text-slate-900 shadow-sm"
                      : "text-slate-500 hover:text-slate-800",
                  )}
                >
                  {v.label}
                </button>
              ))}
            </div>
          )}
        </div>
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
        <>
          {/* Identity is never colour alone: 2+ series always get a legend.
              A single series needs none — the title already names it. */}
          {shown.series.length > 1 && (
            <ul className="mb-3 flex flex-wrap gap-x-5 gap-y-1.5">
              {shown.series.map(sr => (
                <li key={sr.key}
                    className="inline-flex items-center gap-2 text-xs text-slate-600">
                  <span
                    aria-hidden
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ background: colorFor(shown, sr.key, sr.color) }}
                  />
                  {sr.label}
                </li>
              ))}
            </ul>
          )}
          <div style={{ height: chartHeight(shown) }}>
            <ChartByType card={shown} format={format} />
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Ranked bars grow with their rows; everything else is a fixed 16rem.
 * A twelve-client ranking squeezed into 16rem gives each bar 13px, which is
 * too thin to compare and too thin to label.
 */
function chartHeight(card: ChartCardPayload): number {
  if (card.chart_type !== "horizontal_bar") return 256;
  return Math.min(Math.max(card.data.length * 28 + 40, 180), 620);
}

function EmptyChart() {
  return (
    <div className="h-64 flex flex-col items-center justify-center text-slate-400">
      <Inbox className="h-8 w-8 mb-2" />
      <p className="text-sm">No data for this period</p>
    </div>
  );
}

function ErrorChart({ message }: { message?: string | null | undefined }) {
  return (
    <div className="h-64 flex flex-col items-center justify-center text-rose-600">
      <p className="text-sm font-medium">Couldn't load chart</p>
      {message && <p className="text-xs text-rose-500 mt-1">{message}</p>}
    </div>
  );
}

interface ViewProps {
  card: ChartCardPayload;
  /**
   * How to render values in axes and tooltips. Supplied by the active toggle
   * view. Without it the tooltip has to guess from magnitude, which is how
   * "10.0 hours" and "$10" end up formatted the same way.
   */
  format?: NumberFormat | undefined;
}

function ChartByType({ card, format }: ViewProps) {
  switch (card.chart_type) {
    case "area":          return <AreaChartView card={card} format={format} />;
    case "line":          return <LineChartView card={card} format={format} />;
    case "bar":           return <BarChartView card={card} format={format} />;
    case "horizontal_bar":return <HorizontalBarView card={card} format={format} />;
    case "stacked_bar":   return <StackedBarView card={card} format={format} />;
    case "pie":           return <PieChartView card={card} />;
    case "wip_aging":     return <WipAgingChart card={card} />;
    case "proportion_bar":return <ProportionBarView card={card} />;
    case "dot_matrix":    return <DotMatrixView card={card} />;
    default:              return <BarChartView card={card} format={format} />;
  }
}

// ─── X-axis key inference ────────────────────────────────────────────────────
// Backend data rows have varying x-axis keys (month_label, client_name, band, etc.)
// Pick the first non-series key as the x-axis.
function xKey(card: ChartCardPayload): string {
  // The backend states it outright when it knows; the inference below is the
  // fallback for older payloads that don't.
  if (card.x_key) return card.x_key;
  const seriesKeys = new Set(card.series.map(s => s.key));
  const first = card.data[0];
  if (!first) return "name";
  for (const k of Object.keys(first)) {
    if (!seriesKeys.has(k)) return k;
  }
  return Object.keys(first)[0] ?? "name";
}

// ─── Custom tooltip ──────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label, format }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg bg-slate-900 text-white text-xs px-3 py-2 shadow-lg">
      {label && <div className="font-medium mb-1">{label}</div>}
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-300">{p.name}:</span>
          <span className="font-medium">{tooltipValue(p.value, format)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Format a tooltip value.
 *
 * When the card told us its format, use it. The legacy fallback — "over 1000
 * means dollars" — is kept only for cards that still send no format, because
 * it is a guess: it renders 1,200 billable hours as $1,200.
 */
function tooltipValue(value: unknown, format?: NumberFormat): string {
  if (typeof value !== "number") return String(value ?? "—");
  if (format) return formatValue(value, format);
  return value > 1000
    ? `$${Math.round(value).toLocaleString()}`
    : value.toFixed(1);
}

/** Compact Y-axis ticks, format-aware. */
function axisTick(format?: NumberFormat) {
  return (value: number) => {
    if (typeof value !== "number") return String(value);
    const compact = Math.abs(value) >= 1000
      ? `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k`
      : String(Math.round(value * 10) / 10);
    if (!format) return compact;
    if (format.startsWith("currency")) return `$${compact}`;
    if (format.startsWith("percent")) return `${Math.round(value)}%`;
    if (format.startsWith("hours")) return `${compact}h`;
    return compact;
  };
}

// ─── Chart implementations ───────────────────────────────────────────────────

function AreaChartView({ card, format }: ViewProps) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={CHROME.grid} strokeWidth={1} vertical={false} />
        <XAxis dataKey={x} stroke={CHROME.tick} fontSize={11} tickLine={false} />
        <YAxis stroke={CHROME.tick} fontSize={11} tickLine={false} axisLine={false}
               tickFormatter={axisTick(format)} width={56} />
        <Tooltip content={<ChartTooltip format={format} />} />
        {card.series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={colorFor(card, s.key, s.color)}
            fill={colorFor(card, s.key, s.color)}
            fillOpacity={CHROME.areaFillOpacity}
            strokeWidth={CHROME.strokeWidth}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

function LineChartView({ card, format }: ViewProps) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={CHROME.grid} strokeWidth={1} vertical={false} />
        <XAxis dataKey={x} stroke={CHROME.tick} fontSize={11} tickLine={false} />
        <YAxis stroke={CHROME.tick} fontSize={11} tickLine={false} axisLine={false}
               tickFormatter={axisTick(format)} width={56} />
        <Tooltip content={<ChartTooltip format={format} />} />
        {card.series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={colorFor(card, s.key, s.color)}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function BarChartView({ card, format }: ViewProps) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={CHROME.grid} strokeWidth={1} vertical={false} />
        <XAxis dataKey={x} stroke={CHROME.tick} fontSize={11} tickLine={false} />
        <YAxis stroke={CHROME.tick} fontSize={11} tickLine={false} axisLine={false}
               tickFormatter={axisTick(format)} width={56} />
        <Tooltip content={<ChartTooltip format={format} />} cursor={{ fill: "#f1f5f9" }} />
        {card.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={colorFor(card, s.key, s.color)}
            radius={[CHROME.barRadius, CHROME.barRadius, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function HorizontalBarView({ card, format }: ViewProps) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={card.data} layout="vertical" margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={CHROME.grid} strokeWidth={1} horizontal={false} />
        <XAxis type="number" stroke={CHROME.tick} fontSize={11} tickLine={false}
               axisLine={false} tickFormatter={axisTick(format)} />
        {/* 180px: CPA client names are long ("St. Mary of the Assumption"),
            and a truncated label makes the ranking unreadable. */}
        <YAxis type="category" dataKey={x} stroke="#94a3b8" fontSize={11}
               tickLine={false} width={180} interval={0} />
        <Tooltip content={<ChartTooltip format={format} />} cursor={{ fill: "#f1f5f9" }} />
        {card.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={colorFor(card, s.key, s.color)}
            radius={[0, CHROME.barRadius, CHROME.barRadius, 0]}
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
    (r.color as string) ?? rowColor(i);

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
    const fill = (r.color as string) ?? rowColor(i);
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
          const fill = (r.color as string) ?? rowColor(i);
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

function StackedBarView({ card, format }: ViewProps) {
  const x = xKey(card);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={card.data} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={CHROME.grid} strokeWidth={1} vertical={false} />
        <XAxis dataKey={x} stroke={CHROME.tick} fontSize={11} tickLine={false} />
        <YAxis stroke={CHROME.tick} fontSize={11} tickLine={false} axisLine={false}
               tickFormatter={axisTick(format)} width={56} />
        <Tooltip content={<ChartTooltip format={format} />} cursor={{ fill: "#f1f5f9" }} />
        {card.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stackId="stack"
            fill={colorFor(card, s.key, s.color)}
            // A surface-coloured hairline between segments, so adjacent fills
            // read as separate blocks rather than one gradient.
            stroke={CHROME.surface}
            strokeWidth={CHROME.segmentGap}
            // Only the top segment gets the rounded data-end; the ones below
            // it stay square so the stack reads as one column.
            radius={i === card.series.length - 1
              ? [CHROME.barRadius, CHROME.barRadius, 0, 0]
              : [0, 0, 0, 0]}
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
            <Cell key={i} fill={SERIES[i % SERIES.length]} />
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
