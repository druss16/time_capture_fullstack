/**
 * DailyShapeChart.tsx — adaptive "shape" visual for the Reports page.
 *
 * Adapts to how many buckets the period has:
 *   • ONE bucket (Day view)        → horizontal 100% proportion bar.
 *       A single stacked column tells no story; a proportion bar reads as
 *       "61% of today needs review" at a glance.
 *   • MULTIPLE buckets (Week+)     → vertical stacked trend bars (recharts),
 *       where the shape across buckets is the insight.
 *
 * Three bands throughout: billable (emerald) / non-billable (slate) /
 * needs review (amber). Reads the `timeseries` array from reports_summary:
 *   { bucket, billable_hours, non_billable_hours, uncategorized_hours, total_hours }
 *
 * NOTE: the API field is still `uncategorized_hours` — only the user-facing
 * label is "Needs review". Don't rename the data key.
 */
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";

interface ShapePoint {
  bucket: string;
  billable_hours: number;
  non_billable_hours: number;
  uncategorized_hours: number;
  total_hours: number;
}

const COLORS = {
  billable: "#059669",
  non_billable: "#94a3b8",
  uncategorized: "#d97706",
};

// User-facing band label for the amber band. Kept as a constant so the wording
// lives in one place even though the data key stays `uncategorized_hours`.
const NEEDS_REVIEW_LABEL = "Needs review";

function fmtH(h: number): string {
  const m = Math.round((h || 0) * 60);
  if (m < 60) return `${m}m`;
  const hh = Math.floor(m / 60);
  const mm = m % 60;
  return mm === 0 ? `${hh}h` : `${hh}h ${mm}m`;
}

// "2026-06-17" → "Jun 17"
function labelBucket(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── Legend shared by both modes ───────────────────────────────────────────
function BandLegend() {
  const items = [
    ["Billable", COLORS.billable],
    ["Non-billable", COLORS.non_billable],
    [NEEDS_REVIEW_LABEL, COLORS.uncategorized],
  ] as const;
  return (
    <div className="flex items-center justify-center gap-4 mt-3">
      {items.map(([label, color]) => (
        <span key={label} className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}

// ── Day view: horizontal 100% proportion bar ──────────────────────────────
function ProportionBar({ point }: { point: ShapePoint }) {
  const total =
    point.billable_hours + point.non_billable_hours + point.uncategorized_hours;

  if (total <= 0) {
    return (
      <div className="py-10 text-center text-sm text-slate-400">
        No time captured for this day yet.
      </div>
    );
  }

  const pct = (h: number) => (h / total) * 100;
  const segs = [
    { key: "billable", label: "Billable", hours: point.billable_hours, color: COLORS.billable },
    { key: "non_billable", label: "Non-billable", hours: point.non_billable_hours, color: COLORS.non_billable },
    { key: "uncategorized", label: NEEDS_REVIEW_LABEL, hours: point.uncategorized_hours, color: COLORS.uncategorized },
  ].filter((s) => s.hours > 0);

  // Headline: the single biggest band, framed as a sentence.
  const biggest = [...segs].sort((a, b) => b.hours - a.hours)[0];
  const biggestPct = Math.round(pct(biggest.hours));

  return (
    <div>
      <div className="mb-3 text-sm text-slate-600">
        <span className="font-semibold" style={{ color: biggest.color }}>
          {biggestPct}%
        </span>{" "}
        of today is{" "}
        <span className="font-semibold" style={{ color: biggest.color }}>
          {biggest.label.toLowerCase()}
        </span>{" "}
        <span className="text-slate-400">({fmtH(biggest.hours)} of {fmtH(total)})</span>
      </div>

      {/* The bar */}
      <div className="flex h-10 w-full overflow-hidden rounded-lg">
        {segs.map((s) => (
          <div
            key={s.key}
            className="flex items-center justify-center text-[11px] font-medium text-white/95"
            style={{ width: `${pct(s.hours)}%`, background: s.color, minWidth: pct(s.hours) > 6 ? undefined : 0 }}
            title={`${s.label}: ${fmtH(s.hours)} (${Math.round(pct(s.hours))}%)`}
          >
            {pct(s.hours) > 10 ? `${Math.round(pct(s.hours))}%` : ""}
          </div>
        ))}
      </div>

      {/* Per-band readout under the bar */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        {segs.map((s) => (
          <div key={s.key} className="text-center">
            <div className="text-sm font-semibold tabular-nums" style={{ color: s.color }}>
              {fmtH(s.hours)}
            </div>
            <div className="text-[11px] text-slate-400">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Week+ view: vertical stacked trend bars ────────────────────────────────
function TrendTooltip({ active, payload, label }: any) {
  if (!active || !payload || !payload.length) return null;
  const rows = payload
    .filter((p: any) => (p.value || 0) > 0)
    .map((p: any) => (
      <div key={p.dataKey} className="flex items-center justify-between gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} />
          {p.name}
        </span>
        <span className="tabular-nums font-medium">{fmtH(p.value)}</span>
      </div>
    ));
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg">
      <div className="text-xs font-semibold text-slate-700 mb-1">{labelBucket(label)}</div>
      <div className="space-y-1">{rows}</div>
    </div>
  );
}

function TrendBars({ data }: { data: ShapePoint[] }) {
  const chartData = data.map((d) => ({ ...d, label: labelBucket(d.bucket) }));
  return (
    <div style={{ width: "100%", height: 240 }}>
      <ResponsiveContainer>
        <BarChart data={chartData} margin={{ top: 4, right: 8, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            axisLine={{ stroke: "#e2e8f0" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            axisLine={false}
            tickLine={false}
            width={36}
            tickFormatter={(v) => `${v}h`}
          />
          <Tooltip content={<TrendTooltip />} cursor={{ fill: "#f8fafc" }} />
          <Bar dataKey="billable_hours" name="Billable" stackId="a" fill={COLORS.billable} />
          <Bar dataKey="non_billable_hours" name="Non-billable" stackId="a" fill={COLORS.non_billable} />
          <Bar dataKey="uncategorized_hours" name={NEEDS_REVIEW_LABEL} stackId="a" fill={COLORS.uncategorized} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Main ───────────────────────────────────────────────────────────────────
export default function DailyShapeChart({ data }: { data: ShapePoint[] }) {
  if (!data || data.length === 0) return null;

  const single = data.length === 1;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-800">
          {single ? "Today at a glance" : "Shape of the period"}
        </h2>
        <span className="text-[11px] text-slate-400">Billable · Non-billable · {NEEDS_REVIEW_LABEL}</span>
      </div>

      {single ? <ProportionBar point={data[0]} /> : <TrendBars data={data} />}

      {!single && <BandLegend />}
    </div>
  );
}