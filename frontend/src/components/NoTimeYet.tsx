// src/components/NoTimeYet.tsx
/**
 * What Daily Review shows when there is nothing to review.
 *
 * Three different things produce an empty day — never set up, set up but the
 * agent is not running, and simply not working that day — and they need three
 * different sentences. An earlier version decided between them from
 * /api/devices/, which is guarded by @login_required and redirects a
 * token-authenticated caller to a login page rather than returning anything.
 * The empty result read as "no device", so a partner with four hundred blocks
 * that week was told the desktop app was not connected and offered a setup
 * wizard, on a day he was simply out of the office.
 *
 * Capture history is the honest signal and cannot be wrong in that direction:
 * somebody who has captured time obviously has a working agent. Setup is only
 * ever suggested to someone who has never captured anything at all.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { safeFetchJson, API_BASE } from "@/lib/api";
import { ArrowRight, Monitor, Coffee, LifeBuoy } from "lucide-react";

type Status = {
  /** Rolled out by the firm's IT department, so nobody should self-pair. */
  it_deployed: boolean;
  has_captured: boolean;
  last_capture_at: string | null;
  captured_recently: boolean;
  last_device_seen_at: string | null;
  device_seen_recently: boolean;
};

type Situation = "checking" | "never_set_up" | "agent_quiet" | "day_off";

function daysAgo(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

export default function NoTimeYet({ isToday }: { isToday: boolean }) {
  const [situation, setSituation] = useState<Situation>("checking");
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    let cancelled = false;
    safeFetchJson<Status>(`${API_BASE}/capture-status/`)
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        if (!s.has_captured) return setSituation("never_set_up");
        // Captured before, but the agent has gone quiet on a day we would
        // expect it. Only ever raised about today — a past empty day is
        // history, not something to act on.
        if (isToday && !s.device_seen_recently) return setSituation("agent_quiet");
        setSituation("day_off");
      })
      .catch(() => {
        // Never guess "not set up" from a failed request. Saying nothing is
        // better than telling a working user their agent is missing.
        if (!cancelled) setSituation("day_off");
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

  if (situation === "never_set_up") {
    // At a firm rolled out by IT, the machine is meant to arrive already
    // paired. Offering a setup wizard here asks somebody to work around their
    // own IT department, and a device they pair by hand is a device that
    // never matches the provisioning map.
    if (status?.it_deployed) {
      return (
        <div className="mt-2.5">
          <h1 className="text-[22px] font-bold tracking-[-0.01em] text-slate-900">
            TimeTracker hasn't reached this computer yet.
          </h1>
          <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-slate-500">
            Your firm installs it centrally, so there's nothing to set up here — it
            arrives on its own. If it hasn't after a day or two, your IT contact can
            push it, and we'll help them.
          </p>
          <a
            href="mailto:info@mavops.ai?subject=TimeTracker%20not%20installed%20on%20my%20computer"
            className="mt-4 inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 transition-all hover:bg-slate-50"
          >
            <LifeBuoy className="h-4 w-4" />
            Tell us it's missing
          </a>
        </div>
      );
    }
    return (
      <div className="mt-2.5">
        <h1 className="text-[22px] font-bold tracking-[-0.01em] text-slate-900">
          Let's get your time flowing.
        </h1>
        <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-slate-500">
          Nothing has been captured on this account yet. Connecting the desktop app takes
          about two minutes, and then this page fills itself in.
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

  if (situation === "agent_quiet") {
    const d = daysAgo(status?.last_device_seen_at ?? null);
    return (
      <div className="mt-2.5">
        <h1 className="text-[22px] font-bold tracking-[-0.01em] text-slate-900">
          Nothing tracked yet today.
        </h1>
        <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-slate-500">
          If you've been working, the desktop app probably isn't running — TimeTracker
          last heard from your computer{" "}
          {d === null ? "a while ago" : d === 0 ? "earlier today" : d === 1 ? "yesterday" : `${d} days ago`}.
          Open it and this page will catch up on its own.
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

  // Nothing captured, and nothing wrong. Most often a day off — say so plainly
  // rather than implying something needs fixing.
  return (
    <div className="mt-2.5">
      <h1 className="flex items-center gap-2.5 text-[22px] font-bold tracking-[-0.01em] text-slate-900">
        <Coffee className="h-5 w-5 text-slate-400" />
        {isToday ? "Nothing tracked yet today." : "No time on this day."}
      </h1>
      <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-slate-500">
        {isToday
          ? "Your time appears here as you work — usually within a few minutes of starting."
          : "Nothing was captured. If that's a day you worked, you can add it by hand."}
      </p>
    </div>
  );
}
