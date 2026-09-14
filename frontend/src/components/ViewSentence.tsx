/**
 * ViewSentence — top bar showing the current query as a sentence,
 * with refresh button, freshness indicator, and "back to classic" link.
 */
import { Link } from "react-router-dom";
import { RefreshCw, Clock, Settings, Printer } from "lucide-react";
import { cn } from "@/lib/design-system";

interface Props {
  /** Who the page is about — the firm, or the client/person drilled into. */
  subject: string;
  /** The window, e.g. "Q3 2026". Rendered as a chip, not part of the title. */
  period?: string | undefined;
  /** "Prior period", when a comparison is on. */
  compare?: string | undefined;
  sentence: string;
  generatedAt?: string | null | undefined;
  dataFreshness?: string | null | undefined;
  isFetching: boolean;
  onRefresh: () => void;
}

export default function ViewSentence({
  subject, period, compare, sentence, generatedAt, dataFreshness,
  isFetching, onRefresh,
}: Props) {
  return (
    // Deliberately not sticky: the control bar above it is what stays pinned.
    // Two sticky headers at top-0 just overlap each other, and the page title
    // is not what a viewer needs in front of them while scrolling a table.
    //
    // No background and no rule of its own. It used to be a white band between
    // a grey control bar and a grey page — three surfaces and two hairlines
    // stacked in 120px, which is what made the top of the page look seamed.
    // It now sits on the page ground, so the header reads as one surface.
    <header
      className="print:static print:border-b print:border-black/20"
      style={{ fontFamily: '"Inter", sans-serif' }}
    >
      <div className="px-6 py-3.5 flex items-center justify-between gap-4">
        {/* Sentence */}
        <div className="flex-1 min-w-0">
          {/* No "ANALYTICS" eyebrow: the nav tab already says Analytics, and
              a label repeating where you are costs a line and tells you
              nothing.

              The period is a CHIP, not part of the heading. As one bold black
              string — "TL Wall Accounting · Q3 2026" — this read like the
              title of a Word document rather than product chrome; splitting
              the subject from the window it is scoped to makes it a header.

              leading-[1.2], not leading-none: line-height 1 clips descenders,
              which is why the g in "Accounting" was losing its tail. */}
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <h1 className="truncate pb-0.5 text-[22px] font-bold leading-[1.2] tracking-[-0.02em] text-slate-900">
              {subject || sentence || "Dashboard"}
            </h1>
            {period && (
              <span className="inline-flex items-center rounded-md bg-slate-900/[0.055] px-2 py-0.5 text-[12px] font-semibold tabular-nums text-slate-600">
                {period}
              </span>
            )}
            {compare && (
              <span className="inline-flex items-center rounded-md px-1.5 py-0.5 text-[12px] font-medium text-slate-400">
                vs {compare}
              </span>
            )}
          </div>
          <p className="hidden print:block text-[11px] text-slate-600 mt-1 tabular-nums">
            Printed {new Date().toLocaleString(undefined, {
              year: "numeric", month: "short", day: "numeric",
              hour: "numeric", minute: "2-digit",
            })}
            {generatedAt ? ` · data generated ${new Date(generatedAt).toLocaleString(undefined, {
              month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
            })}` : ""}
          </p>
          {dataFreshness && (
            <p className="text-[12px] text-slate-500 mt-0.5 flex items-center gap-1 tabular-nums">
              <Clock className="h-3 w-3" />
              <span>Data through {formatRelative(dataFreshness)}</span>
            </p>
          )}
        </div>

        {/* Actions — pill controls matching the Timesheet / Reports hero.
            Hidden on paper: a printed page has nothing to click. */}
        <div className="flex items-center gap-2 shrink-0 print:hidden">
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border/60 bg-white/70 text-slate-600 hover:bg-white hover:text-slate-800 transition-colors"
            title="Print, or save as PDF, exactly what's on screen"
          >
            <Printer className="h-3.5 w-3.5" />
            <span>Print</span>
          </button>

          <button
            onClick={onRefresh}
            disabled={isFetching}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border/60 bg-white/70 text-slate-600 hover:bg-white hover:text-slate-800 transition-colors",
              isFetching && "opacity-50 cursor-not-allowed",
            )}
            title="Refresh"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            <span>{isFetching ? "Refreshing" : "Refresh"}</span>
          </button>

          <Link
            to="/settings?tab=economics"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border/60 bg-white/70 text-slate-600 hover:bg-white hover:text-slate-800 transition-colors"
            title="Economics & capacity settings"
          >
            <Settings className="h-3.5 w-3.5" />
            <span>Settings</span>
          </Link>
        </div>
      </div>
    </header>
  );
}

function formatRelative(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMin = Math.round((now.getTime() - d.getTime()) / 60_000);
    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin} min ago`;
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
