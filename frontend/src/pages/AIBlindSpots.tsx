/**
 * AIBlindSpots.tsx — "where the AI needs improvement" view.
 *
 * Calls the existing /api/reports/uncategorized/ endpoint (org-wide when no
 * user_id is passed) and ranks the activity themes the classifier keeps
 * failing to categorize. This is the tuning surface: the themes at the top are
 * where adding a rule or training example buys the most accuracy.
 *
 * Two modes via the `scope` toggle:
 *   - Org-wide: all employees combined (default). The firm's blind spots.
 *   - Per-employee: narrow to one person (pass userId).
 *
 * The user_count per theme tells you whether a blind spot is one person's quirk
 * (user_count=1) or a firm-wide pattern (user_count=many) — the latter is the
 * higher-leverage fix.
 *
 * Intended as a MavOps-admin / power-user tool more than a customer feature,
 * but harmless to expose to firm owners.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, AlertCircle, Users, Layers } from "lucide-react";
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

type Period = "day" | "week" | "month" | "quarter";

interface ThemeGroup {
  label: string;
  hours: number;
  minutes: number;
  block_count: number;
  user_count?: number;
  sample_block_ids: number[];
  pct_of_uncategorized: number;
  is_immaterial?: boolean;
}

interface Resp {
  total_uncategorized_hours: number;
  group_count: number;
  groups: ThemeGroup[];
  range: { start: string; end: string };
}

const PERIODS: { key: Period; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
  { key: "quarter", label: "Quarter" },
];

export default function AIBlindSpots({
  orgIdOverride,
}: {
  orgIdOverride?: number | null;
}) {
  const [period, setPeriod] = useState<Period>("week");
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = new URLSearchParams({ period });
      if (orgIdOverride) p.set("org_id", String(orgIdOverride));
      // No user_id → org-wide aggregation (all employees combined).
      const token = getAuthToken();
      const res = await fetch(`${API_BASE}/reports/uncategorized/?${p.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error(b.error || `Request failed (${res.status})`);
      }
      setData(await res.json());
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [period, orgIdOverride]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Real themes only (drop the rolled-up immaterial line — not a blind spot).
  const themes = (data?.groups || []).filter((g) => !g.is_immaterial);
  const maxMin = themes.length ? Math.max(...themes.map((t) => t.minutes)) : 0;

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
            <Layers className="h-5 w-5 text-violet-500" />
            AI Blind Spots
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Activities the classifier isn't categorizing — ranked by impact. Top
            of the list is where a rule or training example buys the most.
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={
                "px-3 py-1.5 text-xs font-medium rounded-md transition-colors " +
                (period === p.key
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:bg-slate-50")
              }
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Loading…</span>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/40 p-4 text-xs text-rose-700">
          {error}
        </div>
      )}

      {data && !loading && (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-2xl font-semibold text-slate-900 tabular-nums">
              {fmtH(data.total_uncategorized_hours)}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              uncategorized across {themes.length} distinct {themes.length === 1 ? "activity" : "activities"} this period
            </div>
          </div>

          {themes.length === 0 ? (
            <div className="rounded-xl border border-emerald-100 bg-emerald-50 p-6 text-center">
              <div className="text-sm font-semibold text-emerald-800">Nothing to tune</div>
              <div className="text-xs text-emerald-600 mt-1">
                No material uncategorized activities this period.
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {themes.map((t, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-slate-200 bg-white p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-slate-800 truncate">
                        {t.label}
                      </div>
                      <div className="flex items-center gap-3 text-xs text-slate-400 mt-0.5">
                        <span>{t.block_count} {t.block_count === 1 ? "block" : "blocks"}</span>
                        {typeof t.user_count === "number" && (
                          <span className="flex items-center gap-1">
                            <Users className="h-3 w-3" />
                            {t.user_count} {t.user_count === 1 ? "employee" : "employees"}
                          </span>
                        )}
                        <span>{t.pct_of_uncategorized}% of pile</span>
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-amber-600 tabular-nums shrink-0">
                      {fmtH(t.hours)}
                    </div>
                  </div>
                  {/* Impact bar, scaled to the biggest theme */}
                  <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className="h-full bg-violet-400 rounded-full"
                      style={{ width: `${maxMin ? (t.minutes / maxMin) * 100 : 0}%` }}
                    />
                  </div>
                  {/* Firm-wide flag: a theme many people hit is higher leverage */}
                  {typeof t.user_count === "number" && t.user_count >= 3 && (
                    <div className="mt-1.5 text-[11px] text-violet-600 flex items-center gap-1">
                      <AlertCircle className="h-3 w-3" />
                      Firm-wide pattern — a rule here helps {t.user_count} people
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}