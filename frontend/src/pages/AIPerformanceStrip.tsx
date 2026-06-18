/**
 * AIPerformanceStrip.tsx — the "is the tool earning its keep" banner.
 *
 * Sits ABOVE the operational KPI tiles on the Reports page. Answers the
 * question utilization can't: how much work the AI is doing, and how much
 * time the firm captured that they'd otherwise have had to track by hand.
 *
 * Three metrics, all computed server-side from real classification data:
 *   - Auto-categorization rate: % of classified time the AI handled itself.
 *   - AI override rate: % of AI guesses a human corrected (low = trusted).
 *     Honest framing — "overridden", not "proven correct".
 *   - Hours auto-captured: agent-recorded time that exists without manual entry.
 *
 * Self-contained: own fetch + auth chain, mirrors UncategorizedPanel's style.
 */
import { useCallback, useEffect, useState } from "react";
import { Sparkles, ShieldCheck, Clock3, Info } from "lucide-react";
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

interface AIPerf {
  auto_categorization_rate: number;
  ai_override_rate: number;
  hours_auto_captured: number;
  counts: {
    automated_blocks: number;
    manual_blocks: number;
    correction_blocks: number;
    ai_blocks: number;
    classified_total: number;
  };
}

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

  // Quietly render nothing if it fails — this is a value-add banner, not
  // core data; a failed fetch shouldn't break the page.
  if (error || !data) return null;

  // Don't show the strip if there's nothing classified yet (avoids a
  // misleading "0%" on a brand-new/empty org).
  if (data.counts.classified_total === 0 && data.hours_auto_captured === 0) {
    return null;
  }

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
          value={`${data.ai_override_rate}%`}
          label="Override rate"
          sub={
            data.counts.correction_blocks === 0
              ? "No AI categorizations corrected"
              : `${data.counts.correction_blocks} of ${data.counts.ai_blocks.toLocaleString()} AI calls changed`
          }
          accent="emerald"
          tip="Of the AI's categorizations this period, the share a person later changed. Lower is better. Note: blocks nobody has reviewed yet aren't counted as right or wrong — this measures overrides, not proven accuracy."
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