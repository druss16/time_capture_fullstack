/**
 * UncategorizedPanel.tsx — slide-over drill-through for the amber "Uncategorized"
 * number. Opens when the user clicks the KPI tile or a row's uncategorized cell.
 *
 * Fetches /api/reports/uncategorized/ and shows the needs-review time grouped by
 * normalized app+title "theme", sorted by hours. Surfaces a headline ("4h is
 * Outlook — Inbox") so the common pattern is obvious at a glance.
 *
 * Self-contained: own fetch, own auth token chain, slide-over via fixed overlay.
 * Drop in next to ReportsSummary.tsx; no external state library needed.
 *
 * Props:
 *   open        — whether the panel is visible
 *   onClose     — close handler
 *   params      — { period, group_by, orgId? , userId?, userLabel? }
 *                 userId narrows to one employee (row click); userLabel is shown
 *                 in the header.
 */
import { useCallback, useEffect, useState } from "react";
import { X, Loader2, AlertCircle, ArrowRight } from "lucide-react";
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

interface ThemeGroup {
  label: string;
  hours: number;
  minutes: number;
  block_count: number;
  sample_block_ids: number[];
  pct_of_uncategorized: number;
}

interface UncatResponse {
  total_uncategorized_hours: number;
  group_count: number;
  headline: { label: string; hours: number; pct: number } | null;
  groups: ThemeGroup[];
  range: { start: string; end: string };
}

export interface UncatPanelParams {
  period: string;
  group_by: string;
  orgId?: number | null;
  userId?: number | null;
  userLabel?: string | null;
}

export default function UncategorizedPanel({
  open, onClose, params,
}: {
  open: boolean;
  onClose: () => void;
  params: UncatPanelParams;
}) {
  const [data, setData] = useState<UncatResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = new URLSearchParams({
        period: params.period,
        group_by: params.group_by,
      });
      if (params.orgId) p.set("org_id", String(params.orgId));
      if (params.userId) p.set("user_id", String(params.userId));

      const token = getAuthToken();
      const res = await fetch(`${API_BASE}/reports/uncategorized/?${p.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `Request failed (${res.status})`);
      }
      setData(await res.json());
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    if (open) fetchData();
  }, [open, fetchData]);

  // Esc to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-white shadow-2xl h-full overflow-y-auto animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-slate-100 px-5 py-4 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-amber-50 text-amber-600">
                <AlertCircle className="h-4 w-4" />
              </span>
              <h2 className="text-sm font-semibold text-slate-900">Uncategorized time</h2>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {params.userLabel ? `${params.userLabel} · ` : ""}
              Needs review — grouped by activity
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              <span className="text-sm">Loading…</span>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50/40 p-3 text-xs text-rose-700">
              {error}
            </div>
          )}

          {data && !loading && (
            <>
              {/* Headline wow stat */}
              {data.total_uncategorized_hours > 0 ? (
                <div className="rounded-xl bg-amber-50 border border-amber-100 p-4 mb-4">
                  <div className="text-2xl font-semibold text-amber-900 tabular-nums">
                    {fmtH(data.total_uncategorized_hours)}
                  </div>
                  <div className="text-xs text-amber-700 mt-0.5">
                    across {data.group_count} {data.group_count === 1 ? "activity" : "activities"} awaiting review
                  </div>
                  {data.headline && (
                    <div className="text-xs text-amber-800 mt-2 pt-2 border-t border-amber-100">
                      Biggest chunk: <span className="font-semibold">{data.headline.label}</span>{" "}
                      ({fmtH(data.headline.hours)}, {data.headline.pct}%)
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-xl bg-emerald-50 border border-emerald-100 p-6 text-center">
                  <div className="text-sm font-semibold text-emerald-800">All caught up</div>
                  <div className="text-xs text-emerald-600 mt-1">No uncategorized time in this period.</div>
                </div>
              )}

              {/* Theme groups */}
              <div className="space-y-2">
                {data.groups.map((g, i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-slate-200 p-3 hover:border-slate-300 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-slate-800 truncate">{g.label}</div>
                        <div className="text-xs text-slate-400 mt-0.5">
                          {g.block_count} {g.block_count === 1 ? "block" : "blocks"} · {g.pct_of_uncategorized}% of pile
                        </div>
                      </div>
                      <div className="text-sm font-semibold text-amber-600 tabular-nums shrink-0">
                        {fmtH(g.hours)}
                      </div>
                    </div>
                    {/* Mini proportion bar */}
                    <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                      <div
                        className="h-full bg-amber-400 rounded-full"
                        style={{ width: `${Math.min(100, g.pct_of_uncategorized)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>

              {/* CTA into the Categorize tab */}
              {data.total_uncategorized_hours > 0 && (
                <a
                  href="/daily"
                  className="mt-4 flex items-center justify-center gap-1.5 w-full px-3 py-2.5 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 transition-colors"
                >
                  Go categorize these
                  <ArrowRight className="h-3.5 w-3.5" />
                </a>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}