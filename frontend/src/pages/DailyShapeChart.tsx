/**
 * DailyShapeChart.tsx — the "shape of the week" hero chart for the Reports page.
 *
 * Stacked bars per bucket (day/week/month/quarter) with three bands:
 *   billable (emerald) / non-billable (slate) / uncategorized (amber)
 *
 * Reads the `timeseries` array the reports_summary endpoint returns. Each item:
 *   { bucket, billable_hours, non_billable_hours, uncategorized_hours, total_hours }
 *
 * Uses recharts (already a project dependency, per DashboardV2). Self-contained
 * so it can be dropped in without touching ReportsSummary's body.
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

function fmtH(h: number): string {
  const m = Math.round((h || 0) * 60);
  if (m < 60) return `${m}m`;
  const hh = Math.floor(m / 60);
  const mm = m % 60;
  return mm === 0 ? `${hh}h` : `${hh}h ${mm}m`;
}

// Friendly bucket label: "2026-06-17" → "Jun 17"
function labelBucket(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function CustomTooltip({ active, payload, label }: any) {
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

export default function DailyShapeChart({ data }: { data: ShapePoint[] }) {
  if (!data || data.length === 0) return null;

  const chartData = data.map((d) => ({
    ...d,
    label: labelBucket(d.bucket),
  }));

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-800">Shape of the period</h2>
        <span className="text-[11px] text-slate-400">Billable · Non-billable · Uncategorized</span>
      </div>
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
            <Tooltip content={<CustomTooltip />} cursor={{ fill: "#f8fafc" }} />
            <Legend
              iconType="square"
              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
            />
            <Bar dataKey="billable_hours" name="Billable" stackId="a" fill="#059669" radius={[0, 0, 0, 0]} />
            <Bar dataKey="non_billable_hours" name="Non-billable" stackId="a" fill="#94a3b8" />
            <Bar dataKey="uncategorized_hours" name="Uncategorized" stackId="a" fill="#d97706" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}