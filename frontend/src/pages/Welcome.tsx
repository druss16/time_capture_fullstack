// src/pages/Welcome.tsx
/**
 * First-run setup for a new member: /welcome
 *
 * The invite email used to end on "You're done!" while the member still had to
 * install an agent and pair it, so people arrived at an empty Daily Review and
 * assumed the product was broken. This page owns the gap between "I have an
 * account" and "my time is appearing", and it does not claim a step is done
 * until the server says so.
 *
 * Firms rolled out by MSI are auto-paired before the member ever gets here.
 * That is why every step reads live state instead of walking a fixed script —
 * an already-paired member should drop straight to the end.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { safeFetchJson, API_BASE } from "@/lib/api";
import PairDeviceCard from "@/components/PairDeviceCard";
import { useItDeployed } from "@/lib/useItDeployed";
import {
  Check,
  Download,
  Monitor,
  Apple,
  ArrowRight,
  Loader2,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/design-system";

const DOWNLOADS = {
  macos: "https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker.pkg",
  windows:
    "https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker-Windows-Setup.exe",
} as const;

type OS = "macos" | "windows";

function detectOS(): OS {
  const ua = navigator.userAgent;
  if (/Mac|iPhone|iPad|iPod/i.test(ua)) return "macos";
  return "windows";
}

type Device = { device_id: string; hostname?: string; last_seen_at?: string | null };

/** The devices endpoint returns a bare array; tolerate a wrapped shape too. */
function readDevices(payload: any): Device[] {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.devices)) return payload.devices;
  return [];
}

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

type StepState = "done" | "active" | "waiting";

function StepShell({
  n,
  state,
  title,
  blurb,
  children,
}: {
  n: number;
  state: StepState;
  title: string;
  blurb?: string;
  children?: React.ReactNode;
}) {
  const done = state === "done";
  return (
    <div
      className={cn(
        "rounded-2xl border bg-card transition-all",
        state === "active" ? "border-primary/40 shadow-sm" : "border-border/60",
        state === "waiting" && "opacity-55"
      )}
    >
      <div className="flex gap-4 p-5">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-bold",
            done
              ? "bg-primary text-white"
              : state === "active"
              ? "bg-primary/10 text-primary border border-primary/30"
              : "bg-muted text-muted-foreground"
          )}
        >
          {done ? <Check className="h-4 w-4" /> : n}
        </div>
        <div className="min-w-0 flex-1">
          <h3
            className={cn(
              "text-[15px] font-bold tracking-[-0.01em]",
              done ? "text-muted-foreground line-through decoration-1" : "text-foreground"
            )}
          >
            {title}
          </h3>
          {blurb && !done && (
            <p className="mt-1 text-[13.5px] leading-relaxed text-muted-foreground">{blurb}</p>
          )}
          {!done && children && <div className="mt-4">{children}</div>}
        </div>
      </div>
    </div>
  );
}

export default function Welcome() {
  const itDeployed = useItDeployed();
  const nav = useNavigate();
  const os = detectOS();

  const [name, setName] = useState<string>("");
  const [orgName, setOrgName] = useState<string>("");
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [hasTime, setHasTime] = useState<boolean | null>(null);
  const [downloadClicked, setDownloadClicked] = useState(false);

  const paired = (devices?.length ?? 0) > 0;
  const timeFlowing = hasTime === true;

  useEffect(() => {
    safeFetchJson<any>(`${API_BASE}/whoami/`)
      .then((d) => {
        setName((d?.first_name || "").trim());
        setOrgName(d?.org_name || "");
      })
      .catch(() => {});
  }, []);

  const pollDevices = useCallback(async () => {
    try {
      const d = await safeFetchJson<any>(`${API_BASE}/devices/`);
      setDevices(readDevices(d));
    } catch {
      setDevices((prev) => prev ?? []);
    }
  }, []);

  const pollTime = useCallback(async () => {
    try {
      const d = await safeFetchJson<any>(`${API_BASE}/today-time/?date=${todayIso()}`);
      setHasTime((d?.global_hours || 0) > 0 || (d?.clients?.length || 0) > 0);
    } catch {
      setHasTime((prev) => prev ?? false);
    }
  }, []);

  useEffect(() => {
    pollDevices();
  }, [pollDevices]);

  // Poll only while there is still something to wait for. Two different
  // cadences on purpose: the device list is cheap, the time summary is not.
  const pairedRef = useRef(paired);
  pairedRef.current = paired;
  useEffect(() => {
    if (timeFlowing) return;
    const t = setInterval(() => {
      if (!pairedRef.current) pollDevices();
      else pollTime();
    }, pairedRef.current ? 10_000 : 5_000);
    return () => clearInterval(t);
  }, [paired, timeFlowing, pollDevices, pollTime]);

  // Once a device shows up, find out whether anything has landed yet.
  useEffect(() => {
    if (paired && hasTime === null) pollTime();
  }, [paired, hasTime, pollTime]);

  const installState: StepState = paired ? "done" : "active";
  const pairState: StepState = paired ? "done" : downloadClicked ? "active" : "waiting";
  const timeState: StepState = timeFlowing ? "done" : paired ? "active" : "waiting";

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-8">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">
          Setting up{orgName ? ` · ${orgName}` : ""}
        </div>
        <h1 className="mt-2 text-[26px] font-bold tracking-[-0.02em] text-foreground">
          {name ? `Welcome, ${name}.` : "Welcome to TimeTracker."}
        </h1>
        <p className="mt-2 text-[14.5px] leading-relaxed text-muted-foreground">
          One thing left: connect this computer so TimeTracker can capture your billable time.
          It runs quietly in the background — you won't have to start or stop anything.
        </p>
      </div>

      <div className="space-y-3">
        <StepShell n={1} state="done" title="Account ready" />

        <StepShell
          n={2}
          state={installState}
          title={itDeployed ? "Your firm installs the desktop app" : "Install the desktop app"}
          blurb={
            itDeployed
              ? "It arrives on its own and connects itself — nothing to download and no code to enter."
              : "This is the piece that watches which client you're working in. Everything else follows from it."
          }
        >
          {itDeployed ? (
            // Handing a member an installer at a firm that pushes an MSI puts
            // an unmanaged, unmatched copy on the machine and breaks the
            // provisioning map their rollout is measured by.
            <p className="text-[13px] text-muted-foreground">
              If it hasn't appeared after a day or two, your IT contact can push it —{" "}
              <a
                href="mailto:info@mavops.ai?subject=TimeTracker%20not%20installed%20on%20my%20computer"
                className="font-medium text-primary underline-offset-2 hover:underline"
              >
                tell us
              </a>{" "}
              and we'll help them.
            </p>
          ) : (
          <>
          <div className="flex flex-wrap items-center gap-3">
            <a
              href={DOWNLOADS[os]}
              onClick={() => setDownloadClicked(true)}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-primary/20 transition-all hover:bg-primary/90"
            >
              {os === "macos" ? <Apple className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
              Download for {os === "macos" ? "Mac" : "Windows"}
            </a>
            <a
              href={DOWNLOADS[os === "macos" ? "windows" : "macos"]}
              onClick={() => setDownloadClicked(true)}
              className="inline-flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              <Download className="h-3.5 w-3.5" />
              I use {os === "macos" ? "Windows" : "a Mac"} instead
            </a>
          </div>
          <p className="mt-3 text-[12.5px] text-muted-foreground/80">
            Open the installer once it downloads, then come back to this page.
          </p>
          </>
          )}
        </StepShell>

        <StepShell
          n={3}
          state={pairState}
          title="Connect this computer"
          blurb="Generate a code here and type it into the desktop app once."
        >
          {itDeployed === true ? (
            // Nothing to do: the MSI carries the org token and the machine
            // pairs itself against the provisioning map.
            <p className="text-[13px] text-muted-foreground">
              Your firm installs TimeTracker centrally, so this connects on its own once
              IT has pushed it — there's no code to enter.
            </p>
          ) : pairState === "active" ? (
            <div className="space-y-3">
              <PairDeviceCard />
              <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Watching for your computer to connect — this page updates on its own.
              </p>
            </div>
          ) : (
            <p className="text-[13px] text-muted-foreground">
              Install the app first and this will open up.
            </p>
          )}
        </StepShell>

        <StepShell
          n={4}
          state={timeState}
          title="Your time starts appearing"
          blurb="Nothing to do here. Work normally for a few minutes and your first entries will show up."
        >
          {timeState === "active" && (
            <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Connected. Waiting for your first captured work…
            </p>
          )}
        </StepShell>
      </div>

      {timeFlowing && (
        <div className="mt-6 rounded-2xl border border-primary/30 bg-primary/5 p-6 text-center">
          <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/15">
            <Sparkles className="h-5 w-5 text-primary" />
          </div>
          <h2 className="text-[17px] font-bold tracking-[-0.01em] text-foreground">
            You're all set.
          </h2>
          <p className="mx-auto mt-1.5 max-w-md text-[13.5px] leading-relaxed text-muted-foreground">
            Your time is being captured and sorted by client. Daily Review is where you check
            anything TimeTracker wasn't sure about — it takes a minute or two a day.
          </p>
          <button
            onClick={() => nav("/daily", { replace: true })}
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-primary/20 transition-all hover:bg-primary/90"
          >
            Go to Daily Review <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="mt-8 flex items-center justify-between border-t border-border/60 pt-5">
        <p className="text-[12.5px] text-muted-foreground">
          Stuck?{" "}
          <a
            href="mailto:info@mavops.ai"
            className="font-medium text-primary underline-offset-2 hover:underline"
          >
            info@mavops.ai
          </a>
        </p>
        <Link
          to="/daily"
          className="text-[12.5px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          Skip for now →
        </Link>
      </div>
    </div>
  );
}
