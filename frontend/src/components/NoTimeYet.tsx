// src/components/NoTimeYet.tsx
/**
 * What Daily Review shows when there is nothing to review.
 *
 * "Nothing tracked yet." was technically true and completely unhelpful: it read
 * identically to a brand-new member whose agent was never installed, a member
 * whose agent had died, and a partner looking at a Sunday. Those need three
 * different sentences, so this asks the server which one applies.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { safeFetchJson, API_BASE } from "@/lib/api";
import { ArrowRight, Monitor, Coffee } from "lucide-react";

type Device = { device_id: string; last_seen_at?: string | null };

type Situation = "checking" | "no_device" | "device_quiet" | "nothing_this_period";

export default function NoTimeYet({ isToday }: { isToday: boolean }) {
  const [situation, setSituation] = useState<Situation>("checking");

  useEffect(() => {
    let cancelled = false;
    safeFetchJson<Device[] | { devices: Device[] }>(`${API_BASE}/devices/`)
      .then((d) => {
        if (cancelled) return;
        const devices = Array.isArray(d) ? d : d?.devices || [];
        if (devices.length === 0) return setSituation("no_device");
        if (!isToday) return setSituation("nothing_this_period");

        // Paired but silent for a long stretch on a day we'd expect activity:
        // usually the agent is not running, which is worth saying out loud.
        const freshest = devices
          .map((x) => (x.last_seen_at ? new Date(x.last_seen_at).getTime() : 0))
          .reduce((a, b) => Math.max(a, b), 0);
        const quiet = !freshest || Date.now() - freshest > 6 * 60 * 60 * 1000;
        setSituation(quiet ? "device_quiet" : "nothing_this_period");
      })
      .catch(() => {
        if (!cancelled) setSituation("nothing_this_period");
      });
    return () => {
      cancelled = true;
    };
  }, [isToday]);

  if (situation === "checking") {
    return (
      <h1 className="mt-2.5 text-[22px] font-bold tracking-[-0.01em] text-slate-900">
        Nothing tracked yet.
      </h1>
    );
  }

  if (situation === "no_device") {
    return (
      <div className="mt-2.5">
        <h1 className="text-[22px] font-bold tracking-[-0.01em] text-slate-900">
          Let's get your time flowing.
        </h1>
        <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-slate-500">
          Nothing has been captured because the desktop app isn't connected to this account
          yet. It takes about two minutes and then this page fills itself in.
        </p>
        <Link
          to="/welcome"
          className="mt-4 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-primary/20 transition-all hover:bg-primary/90"
        >
          Finish setup <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    );
  }

  if (situation === "device_quiet") {
    return (
      <div className="mt-2.5">
        <h1 className="text-[22px] font-bold tracking-[-0.01em] text-slate-900">
          Nothing tracked yet today.
        </h1>
        <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-slate-500">
          Your computer is paired, but TimeTracker hasn't heard from it in a while. If you've
          been working, the desktop app probably isn't running — open it and this page will
          catch up on its own.
        </p>
        <Link
          to="/devices"
          className="mt-4 inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 transition-all hover:bg-slate-50"
        >
          <Monitor className="h-4 w-4" />
          Check my devices
        </Link>
      </div>
    );
  }

  return (
    <div className="mt-2.5">
      <h1 className="flex items-center gap-2.5 text-[22px] font-bold tracking-[-0.01em] text-slate-900">
        <Coffee className="h-5 w-5 text-slate-400" />
        {isToday ? "Nothing tracked yet today." : "Nothing tracked in this stretch."}
      </h1>
      <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-slate-500">
        {isToday
          ? "Your time will appear here as you work — usually within a few minutes of starting."
          : "Try a different date or a wider range."}
      </p>
    </div>
  );
}
