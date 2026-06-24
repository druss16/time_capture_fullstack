/**
 * NeedsReviewQueue.tsx — the Phase 2 "what's still outstanding" panel.
 *
 * Two things, both fed by the EXISTING /reports/uncategorized/ endpoint
 * (no new backend needed):
 *
 *   1. A themed queue of blocks awaiting confirmation — the new "uncategorized,"
 *      framed as a to-do list, not a defect count. Each row deep-links into
 *      Daily Review filtered to those blocks.
 *
 *   2. A blind-spot callout: the single biggest recurring theme in the pile.
 *      That's the candidate for a routing rule — the loop that drives the
 *      override rate down over time. (The actual "make a rule" action is
 *      staff-gated server-side via /reports/suggest-rule/, so here we surface
 *      it and let managers flag it.)
 *
 * Renders nothing when the pile is empty — an empty queue is a good state, not
 * something to take up space.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, ArrowRight, ChevronLeft, ChevronRight, Lightbulb, Loader2 } from "lucide-react";
import { API_BASE } from "@/lib/api";

// How many themed rows to show per page in the review queue. Keeps a long pile
// (think tax season, hundreds of unreviewed signatures) from sprawling down the
// page — the queue stays a scannable card, you page through the rest.
const QUEUE_PAGE_SIZE = 8;

function getAuthToken(): string | null {
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token")
  );
}

function fmtHours(hours: number | undefined): string {
  const totalMin = Math.round((hours || 0) * 60);
  if (totalMin < 60) return `${totalMin}m`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

type Period = "day" | "week" | "month" | "quarter" | "year";

interface ThemeGroup {
  label: string;
  hours: number;
  minutes: number;
  block_count: number;
  user_count: number;
  sample_block_ids: number[];
  pct_of_uncategorized: number;
  is_immaterial?: boolean;
}

interface UncatResponse {
  total_uncategorized_hours: number;
  immaterial_hours: number;
  immaterial_count: number;
  group_count: number;
  headline: { label: string; hours: number; pct: number } | null;
  groups: ThemeGroup[];
}

export default function NeedsReviewQueue({
  period,
  orgIdOverride,
  onOpenReview,
}: {
  period: Period;
  orgIdOverride?: number | null;
  /** Optional: deep-link into Daily Review for a set of block ids. */
  onOpenReview?: (blockIds: number[], label: string) => void;
}) {
  const [data, setData] = useState<UncatResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);   // 0-indexed page of the themed queue

  const buildParams = useCallback(() => {
    const p = new URLSearchParams({ period, group_by: "employee" });
    const impOrg = localStorage.getItem("impersonating_org_id");
    const effOrg = orgIdOverride || (impOrg ? Number(impOrg) : null);
    if (effOrg) p.set("org_id", String(effOrg));
    return p.toString();
  }, [period, orgIdOverride]);

  useEffect(() => {
    let cancelled = false;
    setPage(0);   // new period/org → back to the first page
    (async () => {
      setLoading(true);
      try {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/reports/uncategorized/?${buildParams()}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: "include",
        });
        if (!res.ok) throw new Error(String(res.status));
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [buildParams]);

  if (loading && !data) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-5 flex items-center gap-2 text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Checking the review queue…</span>
      </div>
    );
  }

  // Empty queue is a good state — show a quiet "all clear" rather than a table.
  if (!data || data.total_uncategorized_hours <= 0) {
    return (
      <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-4 flex items-center gap-2.5">
        <AlertCircle className="h-4 w-4 text-emerald-600" />
        <span className="text-sm text-emerald-800 font-medium">
          Nothing waiting on review — every captured block has been confirmed.
        </span>
      </div>
    );
  }

  const realGroups = data.groups.filter((g) => !g.is_immaterial);
  const totalBlocks = realGroups.reduce((s, g) => s + g.block_count, 0);

  // Pagination over the themed rows. Clamp the page in case data shrank after a
  // refetch (e.g. someone confirmed a chunk and there are now fewer pages).
  const pageCount = Math.max(1, Math.ceil(realGroups.length / QUEUE_PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageStart = safePage * QUEUE_PAGE_SIZE;
  const pageGroups = realGroups.slice(pageStart, pageStart + QUEUE_PAGE_SIZE);
  const showPager = realGroups.length > QUEUE_PAGE_SIZE;

  return (
    <div className="space-y-4">
      {/* the queue */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <h3 className="text-[15px] font-semibold text-slate-900">
            Needs review
            <span className="ml-2 text-amber-600 font-bold">
              {fmtHours(data.total_uncategorized_hours)} across {totalBlocks} block
              {totalBlocks === 1 ? "" : "s"}
            </span>
          </h3>
          <a
            href="/daily-review"
            className="inline-flex items-center gap-1 text-xs font-semibold text-violet-600 hover:text-violet-700"
          >
            Open Daily Review <ArrowRight className="h-3.5 w-3.5" />
          </a>
        </div>

        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-5 py-2.5 text-left text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Most common theme
              </th>
              <th className="px-5 py-2.5 text-right text-[11px] font-medium uppercase tracking-wide text-slate-500">
                People
              </th>
              <th className="px-5 py-2.5 text-right text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Blocks
              </th>
              <th className="px-5 py-2.5 text-right text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Time
              </th>
              <th className="px-5 py-2.5"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageGroups.map((g, i) => (
              <tr key={pageStart + i} className="hover:bg-slate-50/60">
                <td className="px-5 py-3 text-slate-700">{g.label}</td>
                <td className="px-5 py-3 text-right tabular-nums text-slate-500">{g.user_count}</td>
                <td className="px-5 py-3 text-right tabular-nums text-slate-500">{g.block_count}</td>
                <td className="px-5 py-3 text-right tabular-nums font-semibold text-amber-600">
                  {fmtHours(g.hours)}
                </td>
                <td className="px-5 py-3 text-right">
                  {onOpenReview && g.sample_block_ids.length > 0 ? (
                    <button
                      onClick={() => onOpenReview(g.sample_block_ids, g.label)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-violet-600 hover:text-violet-700"
                    >
                      Confirm <ArrowRight className="h-3 w-3" />
                    </button>
                  ) : (
                    <a
                      href="/daily-review"
                      className="inline-flex items-center gap-1 text-xs font-medium text-violet-600 hover:text-violet-700"
                    >
                      Confirm <ArrowRight className="h-3 w-3" />
                    </a>
                  )}
                </td>
              </tr>
            ))}

            {/* rolled-up tiny activities — show only on the last page, since
                it's a footer summary of the whole pile, not a per-page row. */}
            {data.immaterial_count > 0 && safePage === pageCount - 1 && (
              <tr className="bg-slate-50/40">
                <td className="px-5 py-2.5 text-slate-400 text-xs" colSpan={3}>
                  {data.immaterial_count} small activities (under 2m each)
                </td>
                <td className="px-5 py-2.5 text-right tabular-nums text-slate-400 text-xs">
                  {fmtHours(data.immaterial_hours)}
                </td>
                <td></td>
              </tr>
            )}
          </tbody>
        </table>

        {/* pager — only when the queue spills past one page */}
        {showPager && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-100 bg-slate-50/40">
            <span className="text-[11px] text-slate-400 tabular-nums">
              {pageStart + 1}–{Math.min(pageStart + QUEUE_PAGE_SIZE, realGroups.length)} of{" "}
              {realGroups.length} themes
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={safePage === 0}
                className="inline-flex items-center gap-0.5 rounded-md px-2 py-1 text-xs font-medium text-slate-600 hover:bg-white disabled:opacity-40 disabled:hover:bg-transparent"
              >
                <ChevronLeft className="h-3.5 w-3.5" /> Prev
              </button>
              <span className="text-[11px] text-slate-400 tabular-nums px-1">
                {safePage + 1} / {pageCount}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                disabled={safePage >= pageCount - 1}
                className="inline-flex items-center gap-0.5 rounded-md px-2 py-1 text-xs font-medium text-slate-600 hover:bg-white disabled:opacity-40 disabled:hover:bg-transparent"
              >
                Next <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* blind-spot callout — the rule-learning loop */}
      {data.headline && data.headline.pct >= 15 && (
        <div className="flex gap-3.5 items-start rounded-xl border border-slate-200 border-l-[3px] border-l-violet-500 bg-gradient-to-b from-white to-violet-50/30 p-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-50 text-violet-600 shrink-0">
            <Lightbulb className="h-5 w-5" />
          </span>
          <div>
            <h4 className="text-sm font-semibold text-slate-900 mb-0.5">
              A pattern worth teaching the AI
            </h4>
            <p className="text-[12.5px] text-slate-500 leading-relaxed">
              The biggest recurring theme right now is{" "}
              <b className="text-slate-700">{data.headline.label}</b> —{" "}
              {data.headline.pct}% of everything waiting on review. Turning this
              into a routing rule teaches TimeTracker to handle it on its own next
              time, which is how the override rate keeps dropping. Flag it to
              MavOps from the blind-spots view to set one up.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}