// src/components/WeekCoverage.tsx
/**
 * An exception notice for the week's record — silent unless something is off.
 *
 * My Week is the weekly roll-up of the daily reviews, and its job is to be the
 * record that goes to the practice-management tool. This is NOT that job, and
 * an earlier version made the mistake of taking over the page with a seven-day
 * diagnostic strip, which put a forensic question where the record should be.
 *
 * It stays because of what it catches. A day where the agent watched eleven
 * hours and produced four is a record that will land in Clio nearly seven
 * hours short, and once it is there that is what the tool of record says. So
 * it speaks in one line when that happens and shows nothing at all when it
 * does not.
 *
 * What it can see is narrow, deliberately: time the agent WATCHED but that did
 * not survive compaction. A day the agent never ran has no events to compare
 * against and reads as quiet, indistinguishable from a day off — so this can
 * never be read as "the week is complete", only as "nothing looks wrong".
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { safeFetchJson, API_BASE } from "@/lib/api";
import { cn } from "@/lib/design-system";
import { AlertTriangle, Clock } from "lucide-react";

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

export type LateWork = {
  hours: number;
  blocks: number;
  timesheet_status: string;
  handled_automatically: boolean;
};

type Payload = {
  submission?: Submission;
  late_work?: LateWork | null;
  week_start: string;
  captured_hours: number;
  gap_hours: number;
  days_flagged: number;
  checkable: boolean;
  days: Day[];
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

  // Nothing to say while loading, on failure, or when the week looks fine: a
  // notice that renders even when it has no notice to give is just furniture.
  if (loading || err || !data || !data.checkable) return null;

  const flagged = data.days.filter((d) => d.state === "gap");
  const late = data.late_work;
  if (flagged.length === 0 && !late) return null;

  return (
    <div className="space-y-2">
    {late && (
      <div
        className={cn(
          "flex flex-wrap items-start gap-x-2 gap-y-1 rounded-xl border px-3.5 py-2.5",
          late.handled_automatically
            ? "border-border/60 bg-muted/40"
            : "border-amber-200 bg-amber-50"
        )}
      >
        <Clock
          className={cn(
            "mt-0.5 h-3.5 w-3.5 shrink-0",
            late.handled_automatically ? "text-muted-foreground" : "text-amber-600"
          )}
        />
        <p
          className={cn(
            "min-w-0 flex-1 text-[13px] leading-relaxed",
            late.handled_automatically ? "text-muted-foreground" : "text-amber-900"
          )}
        >
          <span className="font-semibold">{late.hours.toFixed(1)}h</span> was captured after
          this week was {late.timesheet_status === "submitted" ? "submitted" : "approved"}.{" "}
          {late.handled_automatically
            ? "It will be sent tonight along with everything else — nothing to do."
            : "It is not on the submitted week and will not be sent. Ask your manager to reopen the week if it should go."}
        </p>
      </div>
    )}
    {flagged.length > 0 && (
    <div className="flex flex-wrap items-start gap-x-2 gap-y-1 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
      <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-amber-900">
        <span className="font-semibold">
          {data.gap_hours.toFixed(1)}h may be missing from this week's record.
        </span>{" "}
        {flagged.map((d, i) => (
          <span key={d.date}>
            {i > 0 && ", "}
            <Link
              to={`/daily?date=${d.date}`}
              className="font-medium underline decoration-amber-400 underline-offset-2 hover:text-amber-950"
            >
              {d.weekday}
            </Link>{" "}
            <span className="text-amber-800/80">
              ({d.active_hours.toFixed(1)}h of activity, {d.captured_hours.toFixed(1)}h recorded)
            </span>
          </span>
        ))}
        . Worth a look before this goes out.
      </p>
      </div>
    )}
    </div>
  );
}
