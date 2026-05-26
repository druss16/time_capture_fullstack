/**
 * ChartCard — wraps recharts with our brand styling and handles all chart types
 * the backend produces (line, area, bar, horizontal_bar, pie, wip_aging, sparkline).
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

// Brand palette — matches v1 ExecutiveDashboard for visual continuity
const SERIES_COLORS = ["#c9a84c", "#2dd4bf", "#0d1b2a", "#fb7185", "#f97316", "#94a3b8"];

// WIP aging band colors — green to red as age increases
const WIP_AGING_COLORS = ["#10b981", "#c9a84c", "#f97316", "#dc2626"];

interface Props {
  card: ChartCardPayload;
}

export default function ChartCard({ card }: Props) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-5">
      <header className="mb-4">
        <h3 className="text-sm font-semibold text-slate-900">{card.title}</h3>
        {card.subtitle && (
          <p className="text-xs text-slate-500 mt-0.5">{card.subtitle}</p>
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
