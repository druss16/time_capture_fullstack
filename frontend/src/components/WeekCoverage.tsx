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
import { Link } from "react-router-dom";
import { safeFetchJson, API_BASE } from "@/lib/api";
import { AlertTriangle, Check, Minus, HelpCircle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/design-system";

type DayState = "ok" | "gap" | "quiet" | "unknown" | "future";

type Day = {
  date: string;
  weekday: string;
  captured_hours: number;
  active_hours: number;
  gap_hours: number;
  state: DayState;
  checkable: boolean;
};

export type Submission = {
  mode: 'push' | 'review' | 'off';
  /** Also happens on a schedule. Independent of everything else. */
  auto: boolean;
  /** What receives the time — a NAME, so the button can say "Send to Clio"
   *  instead of something generic. Null when nothing does. */
  destination: string | null;
  /** Whether SUBMITTING is what sends it. False on the approve trigger, where
   *  approving is — so the button must not promise a send. */
  sends_on_submit: boolean;
  has_approver: boolean;
  reason: string;
};

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
  ok: "bg-card",
  gap: "bg-amber-50",
  quiet: "bg-muted/30",
  unknown: "bg-muted/20",
  future: "bg-muted/10",
};

const ICON: Record<DayState, React.ElementType | null> = {
  ok: Check,
  gap: AlertTriangle,
  quiet: Minus,
  unknown: HelpCircle,
  // A day that has not happened yet needs no verdict — an icon there reads as
  // a judgement about time nobody has spent.
  future: null,
};

const ICON_TONE: Record<DayState, string> = {
  ok: "text-primary",
  gap: "text-amber-600",
  quiet: "text-muted-foreground/40",
  unknown: "text-muted-foreground/40",
  future: "",
};

const HINT: Record<DayState, string> = {
  ok: "captured",
  gap: "agent saw more activity than became time",
  quiet: "nothing captured — usually a day off",
  unknown: "too old to check",
  future: "hasn't happened yet",
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
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/60">
            Is this week whole?
          </div>
          <div className="mt-0.5 text-[13.5px] text-foreground">
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

      {/* Each day links to that day in Daily Review, which is where anything
          it reports can actually be acted on. Days with nothing to look at —
          future, or too old to check — are inert rather than dead links. */}
      <div className="grid grid-cols-7 gap-px border-t border-border/60 bg-border/60">
        {data.days.map((d) => {
          const Icon = ICON[d.state];
          const actionable = d.state !== "future" && d.state !== "unknown";
          const label = `${d.captured_hours > 0 ? `${d.captured_hours.toFixed(1)}h ` : ""}${HINT[d.state]}`;

          const body = (
            <>
              <div className="text-[9.5px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                {d.weekday}
              </div>
              <div className="mt-0.5 flex items-center justify-center gap-1">
                <span className="font-mono text-[13px] font-bold tabular-nums text-foreground">
                  {d.captured_hours > 0 ? d.captured_hours.toFixed(1) : "—"}
                </span>
                {Icon && <Icon className={cn("h-3 w-3 shrink-0", ICON_TONE[d.state])} />}
              </div>
              {d.state === "gap" && (
                <div className="font-mono text-[9.5px] font-semibold tabular-nums text-amber-700">
                  −{d.gap_hours.toFixed(1)}h
                </div>
              )}
            </>
          );

          if (!actionable) {
            return (
              <div key={d.date} className={cn("px-1.5 py-1.5 text-center", TONE[d.state])} title={label}>
                {body}
              </div>
            );
          }
          return (
            <Link
              key={d.date}
              to={`/daily?date=${d.date}`}
              title={`${label} — open in Daily Review`}
              className={cn(
                "px-1.5 py-1.5 text-center transition-colors hover:bg-muted/60",
                TONE[d.state]
              )}
            >
              {body}
            </Link>
          );
        })}
      </div>

      {!clean && data.checkable && (
        <p className="border-t border-border/60 px-4 py-2 text-[12px] leading-relaxed text-muted-foreground">
          On the flagged days the agent saw more activity than turned into time. That usually
          means it was stopped mid-day, the machine slept, or work happened somewhere it can't
          see. Worth adding by hand if you remember what it was.
        </p>
      )}
    </div>
  );
}
