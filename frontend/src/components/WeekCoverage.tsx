// src/components/WeekCoverage.tsx
/**
 * Is this week whole?
 *
 * Daily Review answers whether time is on the right client. It cannot answer
 * whether time is *missing*, because time that was never captured does not
 * appear anywhere — not on a wrong client, not in a queue. Under a model where
 * a partner sets fees from these hours, that is the expensive failure: billing
 * from 47 hours when the real number was 62 loses the difference for good.
 *
 * So this compares what the agent watched against what became reviewable time,
 * per day, and says where the difference is big enough to look at. It reports
 * "can't tell" for days older than raw-event retention rather than implying a
 * clean bill it has no evidence for.
 */
import { useCallback, useEffect, useState } from "react";
import { safeFetchJson, API_BASE } from "@/lib/api";
import { AlertTriangle, Check, Minus, HelpCircle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/design-system";

type DayState = "ok" | "gap" | "quiet" | "unknown";

type Day = {
  date: string;
  weekday: string;
  captured_hours: number;
  active_hours: number;
  gap_hours: number;
  state: DayState;
  checkable: boolean;
};

export type Submission = { mode: 'push' | 'review' | 'auto' | 'off'; reason: string };

type Payload = {
  submission?: Submission;
  week_start: string;
  captured_hours: number;
  gap_hours: number;
  days_flagged: number;
  checkable: boolean;
  days: Day[];
};

const TONE: Record<DayState, string> = {
  ok: "border-border/60 bg-card",
  gap: "border-amber-300 bg-amber-50",
  quiet: "border-border/40 bg-muted/30",
  unknown: "border-border/40 bg-muted/20",
};

const ICON: Record<DayState, React.ElementType> = {
  ok: Check,
  gap: AlertTriangle,
  quiet: Minus,
  unknown: HelpCircle,
};

const ICON_TONE: Record<DayState, string> = {
  ok: "text-primary",
  gap: "text-amber-600",
  quiet: "text-muted-foreground/50",
  unknown: "text-muted-foreground/50",
};

export default function WeekCoverage({
  weekStart,
  onSubmission,
}: {
  weekStart?: string;
  /** Lifted so the timesheet below can gate its submit control off the same
   *  response instead of repeating this query. */
  onSubmission?: (s: Submission | null) => void;
}) {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const qs = weekStart ? `?start=${weekStart}` : "";
      const d = await safeFetchJson<Payload>(`${API_BASE}/billing/week-coverage/${qs}`);
      setData(d);
      onSubmission?.(d.submission ?? null);
    } catch (e: any) {
      setErr(e?.message || "Couldn't check this week");
    } finally {
      setLoading(false);
    }
  }, [weekStart, onSubmission]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return (
      <div className="rounded-2xl border border-border/60 bg-card p-4 text-sm text-muted-foreground">
        Checking your week…
      </div>
    );
  }
  if (err || !data) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/60 bg-card p-4">
        <span className="text-sm text-muted-foreground">{err || "No data"}</span>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12.5px] font-medium hover:bg-muted/50"
        >
          <RefreshCw className="h-3 w-3" /> Retry
        </button>
      </div>
    );
  }

  const clean = data.days_flagged === 0;

  return (
    <div className="overflow-hidden rounded-2xl border border-border/60 bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">
            Is this week whole?
          </div>
          <div className="mt-0.5 text-[14px] text-foreground">
            {!data.checkable ? (
              <span className="text-muted-foreground">
                This week is too old to check — we only keep the raw detail for about a month.
              </span>
            ) : clean ? (
              <>
                <span className="font-semibold">{data.captured_hours.toFixed(1)}h</span> captured ·
                nothing looks missing
              </>
            ) : (
              <>
                <span className="font-semibold">{data.captured_hours.toFixed(1)}h</span> captured ·{" "}
                <span className="font-semibold text-amber-700">
                  {data.gap_hours.toFixed(1)}h
                </span>{" "}
                may be missing across {data.days_flagged}{" "}
                {data.days_flagged === 1 ? "day" : "days"}
              </>
            )}
          </div>
        </div>
        <button
          onClick={load}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12.5px] font-medium text-foreground hover:bg-muted/50"
        >
          <RefreshCw className="h-3 w-3" /> Recheck
        </button>
      </div>

      <div className="grid grid-cols-7 gap-px border-t border-border/60 bg-border/60">
        {data.days.map((d) => {
          const Icon = ICON[d.state];
          return (
            <div
              key={d.date}
              className={cn("px-2 py-2.5 text-center", TONE[d.state])}
              title={
                d.state === "gap"
                  ? `Agent saw ${d.active_hours.toFixed(1)}h of activity, ${d.captured_hours.toFixed(1)}h became time`
                  : d.state === "quiet"
                  ? "Nothing captured — usually a day off"
                  : d.state === "unknown"
                  ? "Too old to check"
                  : `${d.captured_hours.toFixed(1)}h captured`
              }
            >
              <div className="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                {d.weekday}
              </div>
              <div className="mt-1 font-mono text-[15px] font-bold tabular-nums text-foreground">
                {d.captured_hours > 0 ? d.captured_hours.toFixed(1) : "—"}
              </div>
              <Icon className={cn("mx-auto mt-1 h-3.5 w-3.5", ICON_TONE[d.state])} />
              {d.state === "gap" && (
                <div className="mt-0.5 font-mono text-[10.5px] font-semibold tabular-nums text-amber-700">
                  −{d.gap_hours.toFixed(1)}h
                </div>
              )}
            </div>
          );
        })}
      </div>

      {!clean && data.checkable && (
        <p className="border-t border-border/60 px-4 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
          On the flagged days the agent saw more activity than turned into time. That usually
          means it was stopped mid-day, the machine slept, or work happened somewhere it can't
          see. Worth adding by hand if you remember what it was.
        </p>
      )}
    </div>
  );
}
