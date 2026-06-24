/**
 * AIPerformanceStrip.tsx — the "is the tool earning its keep" banner.
 *
 * Sits ABOVE the operational KPI tiles on the Reports page. Answers the
 * question utilization can't: how much work the AI is doing, and how much
 * time the firm captured that they'd otherwise have had to track by hand.
 *
 * Three metrics, all computed server-side from real classification data:
 *   - Auto-categorization rate: % of classified time the AI handled itself.
 *   - Confirmed as proposed: % of AI guesses a human kept unchanged (the
 *     inverse of override rate — "90.7% confirmed" sells where "9.3%
 *     overridden" reads as a defect). Override count still shown in the sub.
 *     Honest framing — unreviewed blocks count as neither right nor wrong.
 *   - Hours auto-captured: agent-recorded time that exists without manual entry.
 *
 * NEW: an override-rate trend line under the strip, fed by ?trend=N on the same
 * endpoint. Real data only — periods with no AI decisions are skipped so the
 * line never fabricates a slope. Renders only for Week/Month/Quarter/Year and
 * only when ≥2 periods actually have data.
 *
 * Self-contained: own fetch + auth chain, mirrors UncategorizedPanel's style.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Sparkles, ShieldCheck, Clock3, Info, TrendingUp } from "lucide-react";
import { API_BASE } from "@/lib/api";

function getAuthToken(): string | null {
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token")
  );
}

function fmtH(h: number): string {
  const m = Math.round((h || 0) * 60);
  if (m < 60) return `${m}m`;
  const hh = Math.floor(m / 60);
  const mm = m % 60;
  return mm === 0 ? `${hh}h` : `${hh}h ${mm}m`;
}

interface TrendPoint {
  bucket: string;
  ai_override_rate: number | null;
  ai_confirmation_rate: number | null;
  ai_decisions: number;
  hours_auto_captured: number;
  cumulative_hours: number;
}

interface AIPerf {
  auto_categorization_rate: number;
  ai_override_rate: number;
  ai_confirmation_rate: number;
  ai_confidence_rate: number | null;
  hours_auto_captured: number;
  counts: {
    automated_blocks: number;
    manual_blocks: number;
    correction_blocks: number;
    ai_blocks: number;
    classified_total: number;
  };
  trend: TrendPoint[] | null;
}

// How many periods of history to request per period type. Day is excluded —
// no meaningful day-over-day trend for this metric at TL Wall's volume.
const TREND_N: Record<string, number> = {
  day: 0, week: 8, month: 6, quarter: 4, year: 3,
};

export default function AIPerformanceStrip({
  period, orgIdOverride,
}: {
  period: string;
  orgIdOverride?: number | null;
}) {
  const [data, setData] = useState<AIPerf | null>(null);
  const [error, setError] = useState(false);

  const fetchData = useCallback(async () => {
    setError(false);
    try {
      const p = new URLSearchParams({ period });
      const n = TREND_N[period] || 0;
      if (n >= 2) p.set("trend", String(n));
      const impersonatedOrg = localStorage.getItem("impersonating_org_id");
      const effectiveOrg = orgIdOverride || (impersonatedOrg ? Number(impersonatedOrg) : null);
      if (effectiveOrg) p.set("org_id", String(effectiveOrg));
      const token = getAuthToken();
      const res = await fetch(`${API_BASE}/reports/ai-performance/?${p.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!res.ok) throw new Error();
      setData(await res.json());
    } catch {
      setError(true);
    }
  }, [period, orgIdOverride]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Points that actually have captured time — the success line is cumulative
  // hours, which only grows, so we keep every point with real capture.
  const trendPoints = useMemo(
    () => (data?.trend || []).filter((pt) => (pt.hours_auto_captured || 0) > 0),
    [data]
  );

  // Quietly render nothing if it fails — this is a value-add banner, not
  // core data; a failed fetch shouldn't break the page.
  if (error || !data) return null;

  // Don't show the strip if there's nothing classified yet (avoids a
  // misleading "0%" on a brand-new/empty org).
  if (data.counts.classified_total === 0 && data.hours_auto_captured === 0) {
    return null;
  }

  const aiDecisions = data.counts.ai_blocks + data.counts.correction_blocks;
  const showTrend = trendPoints.length >= 2;

  return (
    <div className="rounded-xl border border-violet-100 bg-gradient-to-r from-violet-50/60 to-blue-50/40 p-4">
      <div className="flex items-center gap-1.5 mb-3">
        <Sparkles className="h-3.5 w-3.5 text-violet-500" />
        <span className="text-xs font-semibold text-violet-700 uppercase tracking-wide">
          AI at work
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <AIStat
          icon={<Sparkles className="h-4 w-4" />}
          value={`${data.auto_categorization_rate}%`}
          label="Auto-categorized"
          sub={`${data.counts.automated_blocks.toLocaleString()} of ${data.counts.classified_total.toLocaleString()} classified by AI`}
          accent="violet"
          tip="Of the blocks that were classified this period, the share the AI (and learned rules) handled on its own — versus a person categorizing from scratch. Excludes admin/bulk operations. Higher means less manual work."
        />
        <AIStat
          icon={<ShieldCheck className="h-4 w-4" />}
          value={aiDecisions > 0 ? `${data.ai_confirmation_rate}%` : "—"}
          label="Confirmed as proposed"
          sub={
            aiDecisions === 0
              ? "No AI calls reviewed yet"
              : `${data.counts.correction_blocks} of ${aiDecisions.toLocaleString()} AI calls changed`
          }
          accent="emerald"
          tip="Of the AI's categorizations a person reviewed, the share kept exactly as proposed. Higher is better — it's the inverse of override rate. Blocks nobody has reviewed yet aren't counted as right or wrong, so this measures confirmation, not proven accuracy."
        />
        <AIStat
          icon={<Clock3 className="h-4 w-4" />}
          value={fmtH(data.hours_auto_captured)}
          label="Captured automatically"
          sub="Tracked without manual entry"
          accent="blue"
          tip="Total time the agent recorded automatically this period (material blocks, overnight artifacts excluded) — time that exists without anyone manually starting a timer or writing it down."
        />
      </div>

      {/* cumulative captured-hours trend — the clean "work nobody typed" line.
          Only when there's real history to show. */}
      {showTrend && <CapturedTrend points={trendPoints} period={period} />}
    </div>
  );
}

function AIStat({
  icon, value, label, sub, accent, tip,
}: {
  icon: React.ReactNode;
  value: string;
  label: string;
  sub: string;
  accent: "violet" | "emerald" | "blue";
  tip?: string;
}) {
  const accentMap: Record<string, string> = {
    violet: "text-violet-600",
    emerald: "text-emerald-600",
    blue: "text-blue-600",
  };
  return (
    <div className="flex items-start gap-2.5">
      <span className={`mt-0.5 ${accentMap[accent]}`}>{icon}</span>
      <div className="min-w-0">
        <div className="text-xl font-semibold text-slate-900 tabular-nums leading-tight">
          {value}
        </div>
        <div className="flex items-center gap-1 text-xs font-medium text-slate-600">
          {label}
          {tip && (
            <span className="group relative inline-flex">
              <Info className="h-3 w-3 text-slate-300 hover:text-slate-500 cursor-help" />
              <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-1 hidden w-60 -translate-x-1/2 rounded-lg bg-slate-900 px-3 py-2 text-[11px] font-normal leading-snug text-white shadow-lg group-hover:block">
                {tip}
              </span>
            </span>
          )}
        </div>
        <div className="text-[11px] text-slate-400 mt-0.5">{sub}</div>
      </div>
    </div>
  );
}

/**
 * CapturedTrend — cumulative hours the agent captured that nobody had to type.
 * The honest success line: it only grows, and it's immune to the review-ramp
 * distortion that makes accuracy %s misleading during onboarding. Area chart
 * climbing left→right, with the running total as the headline. Pure SVG.
 */
function CapturedTrend({ points, period }: { points: TrendPoint[]; period: string }) {
  const W = 720, H = 150, padL = 40, padR = 12, padT = 16, padB = 24;
  const cum = points.map((p) => p.cumulative_hours || 0);
  const n = points.length;
  const maxCum = Math.max(1, ...cum);
  // round the y-axis top up to a "nice" number for the gridline labels
  const niceTop = (() => {
    const raw = maxCum;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = mag / 2 || 1;
    return Math.ceil(raw / step) * step;
  })();

  const x = (i: number) => padL + (i * (W - padL - padR)) / Math.max(1, n - 1);
  const y = (v: number) => padT + (1 - v / niceTop) * (H - padT - padB);

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.cumulative_hours).toFixed(1)}`)
    .join(" ");
  const areaPath =
    `${linePath} L${x(n - 1).toFixed(1)},${(H - padB).toFixed(1)} L${x(0).toFixed(1)},${(H - padB).toFixed(1)} Z`;

  const total = cum[cum.length - 1];
  const totalLabel = total >= 100 ? Math.round(total).toLocaleString() : total.toFixed(1);

  const labelIdxs = n <= 3 ? points.map((_, i) => i) : [0, Math.floor((n - 1) / 2), n - 1];
  const periodWord =
    period === "week" ? "week" : period === "month" ? "month"
      : period === "quarter" ? "quarter" : "year";

  return (
    <div className="mt-4 pt-4 border-t border-violet-100">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-emerald-600" />
          <span className="text-sm font-semibold text-slate-800">
            {totalLabel} hours captured — time nobody had to type
          </span>
        </div>
        <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
          <Info className="h-3 w-3" />
          Running total of auto-captured time, by {periodWord}
        </span>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="none">
        <defs>
          <linearGradient id="capFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#0f7a5a" stopOpacity="0.18" />
            <stop offset="1" stopColor="#0f7a5a" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0, niceTop / 2, niceTop].map((val, i) => (
          <g key={i}>
            <line x1={padL} y1={y(val)} x2={W - padR} y2={y(val)} stroke="#eef2f7" strokeWidth="1" />
            <text x={padL - 6} y={y(val) + 3} textAnchor="end" fontSize="10" fill="#94a3b8">
              {Math.round(val)}h
            </text>
          </g>
        ))}

        <path d={areaPath} fill="url(#capFill)" />
        <path d={linePath} fill="none" stroke="#0f7a5a" strokeWidth="2.5" />

        {points.map((p, i) => (
          <circle
            key={i}
            cx={x(i)} cy={y(p.cumulative_hours)}
            r={i === n - 1 ? 4.5 : 3}
            fill="#0f7a5a"
            stroke={i === n - 1 ? "#fff" : "none"}
            strokeWidth={i === n - 1 ? 2 : 0}
          >
            <title>{p.bucket}: {Math.round(p.cumulative_hours)}h total (+{p.hours_auto_captured}h this {periodWord})</title>
          </circle>
        ))}

        {labelIdxs.map((i) => (
          <text
            key={i}
            x={x(i)} y={H - 6}
            textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}
            fontSize="10" fill="#94a3b8"
          >
            {fmtBucket(points[i].bucket)}
          </text>
        ))}
      </svg>

      <p className="mt-2 text-[11px] text-slate-400 leading-relaxed">
        Every hour here is time the agent recorded on its own — work the team would
        otherwise have had to reconstruct and enter by hand.
      </p>
    </div>
  );
}

function fmtBucket(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}