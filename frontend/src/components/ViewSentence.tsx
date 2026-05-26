/**
 * ViewSentence — top bar showing the current query as a sentence,
 * with refresh button, freshness indicator, and "back to classic" link.
 */
import { Link } from "react-router-dom";
import { RefreshCw, Clock, ArrowLeftRight } from "lucide-react";
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
    <header className="border-b border-slate-200/80 bg-white/95 backdrop-blur-sm sticky top-0 z-20">
      <div className="px-6 py-3 flex items-center justify-between gap-4">
        {/* Sentence */}
        <div className="flex-1 min-w-0">
          <h1 className="font-display font-light text-xl text-slate-900 truncate">
            {sentence || "Dashboard"}
          </h1>
          {dataFreshness && (
            <p className="text-[11px] text-slate-500 mt-0.5 flex items-center gap-1">
              <Clock className="h-3 w-3" />
              <span>Data through {formatRelative(dataFreshness)}</span>
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onRefresh}
            disabled={isFetching}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors",
              isFetching && "opacity-50 cursor-not-allowed",
            )}
            title="Refresh"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            <span>{isFetching ? "Refreshing" : "Refresh"}</span>
          </button>

          <Link
            to="/analytics"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
            title="Switch to the classic dashboard"
          >
            <ArrowLeftRight className="h-3.5 w-3.5" />
            <span>Classic view</span>
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
