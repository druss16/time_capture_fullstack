/**
 * ViewSentence — top bar showing the current query as a sentence,
 * with refresh button, freshness indicator, and "back to classic" link.
 */
import { Link } from "react-router-dom";
import { RefreshCw, Clock, Settings } from "lucide-react";
import { cn } from "@/lib/design-system";

interface Props {
  sentence: string;
  generatedAt?: string | null;
  dataFreshness?: string | null;
  isFetching: boolean;
  onRefresh: () => void;
}

export default function ViewSentence({
  sentence, generatedAt, dataFreshness, isFetching, onRefresh,
}: Props) {
  return (
    <header
      className="border-b border-border/70 bg-white/95 backdrop-blur-sm sticky top-0 z-20"
      style={{ fontFamily: '"Inter", sans-serif' }}
    >
      <div className="px-6 py-3.5 flex items-center justify-between gap-4">
        {/* Sentence */}
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Analytics
          </div>
          <h1 className="mt-1 text-[22px] font-bold tracking-[-0.01em] text-slate-900 truncate">
            {sentence || "Dashboard"}
          </h1>
          {dataFreshness && (
            <p className="text-[12px] text-slate-500 mt-0.5 flex items-center gap-1 tabular-nums">
              <Clock className="h-3 w-3" />
              <span>Data through {formatRelative(dataFreshness)}</span>
            </p>
          )}
        </div>

        {/* Actions — pill controls matching the Timesheet / Reports hero */}
        <div className="flex items-center gap-2 shrink-0">
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
