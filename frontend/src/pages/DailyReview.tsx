/**
 * DailyReview.tsx — modernized toolbar & layout
 */

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  RefreshCw,
  BarChart3,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { todayIso } from "@/lib/utils/date";
import { primeCsrf } from "@/lib/csrf";
import { useWhoAmI } from "@/lib/useWhoAmI";
import ManualCategorization from "@/components/ManualCategorization";
import { safeFetchJson } from "@/lib/api";
import ManualTimeEntry from "@/components/ManualTimeEntry";
import { cn } from "@/lib/design-system";
import { useSearchParams, Link } from "react-router-dom";
import CompactSummary from "@/components/CompactSummary";
import NoTimeYet from "@/components/NoTimeYet";
import DayReviewedButton from "@/components/DayReviewedButton";
import { MatterPicker } from "@/components/MatterPicker";
import { deriveLanes, mergeOptimisticConfirms, type MismatchBlock, type SplitCandidate, type OptimisticConfirm } from "@/lib/dailyReviewLanes";
import { useAICompletion } from "@/hooks/useAICompletion";


const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api")
  ? RAW_BASE
  : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// How long the user must pause before a post-action reconcile actually fires.
// Long enough that a run of confirms costs ONE today-time query instead of one
// per click; short enough that the totals settle before you look up at them.
const REFRESH_QUIET_MS = 1200;
// How long after a row action the periodic poll keeps out of the way, so a tick
// can't land in the middle of a run of confirms.
const QUIET_AFTER_ACTION_MS = 20 * 1000;
// Ceiling on how stale the header totals may get. Someone confirming steadily
// never pauses long enough to trip the quiet-period debounce, so without this
// the numbers up top would sit frozen for the whole run. Past this, reconcile
// mid-run anyway — it's silent, and the rows are already optimistic.
const MAX_STALE_MS = 15 * 1000;

const formatHours = (hours: number): string => {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
};

// ─── Range (Day / Week / Month) ───────────────────────────────────────────────
// The Lightning view can aggregate a single day, the Mon–Sun week, or the
// calendar month around an "anchor" date. All date math is done in local time
// (never toISOString(), which would shift the day in +UTC zones).
type ViewRange = "day" | "week" | "month" | "quarter";

const isoLocal = (d: Date): string => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};

// Monday-start week to match the rest of the app (WeeklyTimesheet.getMonday).
const mondayOf = (d: Date): Date => {
  const x = new Date(d);
  const day = x.getDay(); // 0=Sun … 6=Sat
  x.setDate(x.getDate() - day + (day === 0 ? -6 : 1));
  return x;
};

// Inclusive [start, end] ISO bounds for the range around `anchorIso`.
const rangeBounds = (anchorIso: string, range: ViewRange): { start: string; end: string } => {
  const d = new Date(anchorIso + "T00:00:00");
  if (range === "week") {
    const start = mondayOf(d);
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    return { start: isoLocal(start), end: isoLocal(end) };
  }
  if (range === "month") {
    const start = new Date(d.getFullYear(), d.getMonth(), 1);
    const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    return { start: isoLocal(start), end: isoLocal(end) };
  }
  if (range === "quarter") {
    const qStartMonth = Math.floor(d.getMonth() / 3) * 3; // 0,3,6,9
    const start = new Date(d.getFullYear(), qStartMonth, 1);
    const end = new Date(d.getFullYear(), qStartMonth + 3, 0);
    return { start: isoLocal(start), end: isoLocal(end) };
  }
  return { start: anchorIso, end: anchorIso };
};

// Human label for the current range (e.g. "Fri, Aug 14", "Aug 10 – 16, 2026",
// "August 2026").
const rangeLabel = (anchorIso: string, range: ViewRange): string => {
  const { start, end } = rangeBounds(anchorIso, range);
  const s = new Date(start + "T00:00:00");
  const e = new Date(end + "T00:00:00");
  if (range === "day") {
    return s.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  }
  if (range === "month") {
    return s.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  }
  if (range === "quarter") {
    return `Q${Math.floor(s.getMonth() / 3) + 1} ${s.getFullYear()}`;
  }
  const sameMonth = s.getMonth() === e.getMonth();
  const left = s.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const right = sameMonth
    ? e.toLocaleDateString(undefined, { day: "numeric", year: "numeric" })
    : e.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  return `${left} – ${right}`;
};

type Category = {
  name: string;
  hours: number;
  block_count: number;
  sample_activities: string[];
  needs_review?: boolean;
};
type ClientTime = {
  client_id: number | null;
  client: string;
  total_hours: number;
  categories: Category[];
};
type ClientOption = { id: number; name: string };
type FlaggedBlock = {
  block_id: number;
  client_name: string;
  review_reason: string;
  minutes: number;
  start: string;
  type?: 'mobile_review' | 'ai_disagreement' | 'mail_disagreement' | 'calendar_disagreement' | 'second_pass';
  ai_proposed_client_id?: number | null;
  ai_proposed_client_name?: string | null;
  ai_confidence?: number;
  ai_reasoning?: string;
  mail_proposed_client_id?: number | null;
  mail_proposed_client_name?: string | null;
  mail_confidence?: number;
  mail_reasoning?: string;
  // v1.3.42: Stage 6 calendar disagreement fields
  calendar_proposed_client_id?: number | null;
  calendar_proposed_client_name?: string | null;
  calendar_confidence?: number;
  calendar_reasoning?: string;
  calendar_disagreement_source?: 'classifier' | 'manual';
  window_title?: string;
  proposed_client_id?: number | null;
  proposed_client_name?: string | null;
  proposed_confidence?: number;
  proposed_category?: string | null;
  proposed_reasoning?: string;
};
type ProposedInline = {
  block_id: number;
  window_title: string;
  minutes: number;
  proposed_client_id: number | null;
  proposed_client_name: string | null;
  proposed_confidence: number;
  proposed_category: string;
  proposed_reasoning?: string;
};
type TodayTimeResponse = {
  clients: ClientTime[];
  billable_hours: number;
  non_billable_hours: number;
  needs_review_hours: number;
  global_hours: number;
  date: string;
  flagged_blocks: FlaggedBlock[];
  proposed_inline?: ProposedInline[];
  mismatch_flags?: Record<string, string>;
  mismatch_blocks?: MismatchBlock[];
  split_candidates?: SplitCandidate[];
};


// ─── Toast ───────────────────────────────────────────────────────────────────

const Toast = ({
  message,
  type,
}: {
  message: string;
  type: "success" | "error";
}) => (
  <div
    className={cn(
      "fixed top-[72px] right-4 z-50 px-4 py-2.5 rounded-lg shadow-lg",
      "flex items-center gap-2 text-white text-sm font-medium",
      "animate-in slide-in-from-top-1 duration-200",
      type === "success" ? "bg-emerald-500" : "bg-red-500"
    )}
  >
    {type === "success" ? <Check className="w-3.5 h-3.5" /> : <X className="w-3.5 h-3.5" />}
    {message}
  </div>
);

// ─── Stat Cell ────────────────────────────────────────────────────────────────

const StatCell = ({
  value,
  label,
  valueClass = "text-slate-800",
}: {
  value: string;
  label: string;
  valueClass?: string;
}) => (
  <div className="flex flex-col items-end">
    <span className={cn("text-lg font-bold leading-none tabular-nums", valueClass)}>
      {value}
    </span>
    <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">
      {label}
    </span>
  </div>
);

// ─── Main Component ───────────────────────────────────────────────────────────

// Time that cannot be billed until someone says which matter it belongs to.
//
// Lives in Daily Review rather than the timesheet on purpose. A matter chosen
// today is remembered; the same choice on Friday is reconstructed, and a
// reconstruction bills a client. Each pick also teaches the folder, so the week
// gets quieter on its own.
//
// Only lists blocks whose client HAS matters to choose between — a client with
// none is not a task, and including them would make this a queue people skip.
const MatterLane = ({ date, onChanged }: { date: string; onChanged: () => void }) => {
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState(true);
  // Capped for the same reason as the timesheet banner: a lane is a queue you
  // work down, not a wall you scroll past.
  const [shown, setShown] = useState(8);

  const load = useCallback(() => {
    safeFetchJson(`${API_BASE}/blocks/needs-matter/?date=${date}`)
      .then((d: any) => { setRows(d?.blocks ?? []); setTotal(d?.total_minutes ?? 0); })
      .catch(() => { setRows([]); setTotal(0); });
  }, [date]);

  useEffect(() => { load(); }, [load]);

  if (rows.length === 0) return null;

  const fmt = (m: number) => (m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`);

  return (
    <div className="mb-3 overflow-hidden rounded-[15px] border border-amber-200 bg-card">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-amber-50/60"
      >
        <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-amber-500" />
        <span className="font-sans text-[15px] font-bold tracking-[-0.01em] text-amber-800">Needs a matter</span>
        <span className="truncate font-mono text-[11.5px] text-muted-foreground">
          {fmt(total)} · {rows.length} {rows.length === 1 ? "activity" : "activities"}
        </span>
        <span className="flex-1" />
        <span className="shrink-0 rounded-lg border border-border bg-card px-3 py-1.5 font-sans text-[12px] font-medium text-muted-foreground">
          {open ? "Hide" : "Show"}
        </span>
      </button>

      {open && (
        <div className="border-t border-amber-200/70 px-3 pb-2 pt-2">
          {rows.slice(0, shown).map((r) => (
            <div key={r.id} className="flex items-center gap-2 py-1">
              <span className="w-[110px] shrink-0 truncate font-sans text-[12px] font-semibold text-foreground">
                {r.client_name || "No client"}
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground" title={r.label}>
                {r.label}
              </span>
              <span className="w-[46px] shrink-0 text-right font-mono text-[12px] tabular-nums text-muted-foreground/70">
                {fmt(r.minutes)}
              </span>
              <MatterPicker
                blockIds={[r.id]}
                onAssigned={() => {
                  // The row leaves immediately. Reloading the lane here meant a
                  // visible flicker and, worse, the list re-ordering under
                  // someone working down it. The lane refetches on the next date
                  // change or natural refresh.
                  setRows((prev) => prev.filter((x) => x.id !== r.id));
                  setTotal((prev) => Math.max(0, prev - (r.minutes || 0)));
                  onChanged();
                }}
              />
            </div>
          ))}
          {rows.length > shown && (
            <button
              onClick={() => setShown((n) => n + 8)}
              className="mt-1 self-start rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-amber-800 underline-offset-2 hover:underline"
            >
              Show {Math.min(8, rows.length - shown)} more of {rows.length}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default function DailyReview() {
  const me = useWhoAmI();
  const whoami = (me?.username || "").trim();

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());
  const [timeSummary, setTimeSummary] = useState<ClientTime[]>([]);
  const [uncategorizedCount, setUncategorizedCount] = useState(0);
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const [availableClients, setAvailableClients] = useState<ClientOption[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const [billableHours, setBillableHours] = useState(0);
  const [nonBillableHours, setNonBillableHours] = useState(0);
  const [needsReviewHours, setNeedsReviewHours] = useState(0);
  const [showManualEntry, setShowManualEntry] = useState(false);
  const [manualEntry, setManualEntry] = useState<{
    client_id: number | null;
    description: string;
    hours: number;
    date: string;
  }>({
    client_id: null,
    description: "",
    hours: 0,
    date: todayIso(),
  });
  const [aiSuggestions, setAiSuggestions] = useState<any[]>([]);
  const [aiInProgress, setAiInProgress] = useState(false);
  const [proposedInline, setProposedInline] = useState<ProposedInline[]>([]);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [mismatchBlocks, setMismatchBlocks] = useState<MismatchBlock[]>([]);
  const [splitCandidates, setSplitCandidates] = useState<SplitCandidate[]>([]);
  // Optimistically-hidden block ids: as soon as a Needs You row is acted on we
  // drop it from the lanes so the user can keep confirming, WITHOUT waiting for
  // the (slow) today-time reload. Reconciled below once fresh data lands.
  const [hiddenIds, setHiddenIds] = useState<Set<number>>(new Set());
  // Just-confirmed blocks, shown under their client in the Certain lane INSTANTLY
  // (before the reload). Keyed by block id; reconciled away once the real payload
  // carries the committed block.
  const [optimisticConfirms, setOptimisticConfirms] = useState<Map<number, OptimisticConfirm>>(new Map());
  // Lightning view range: single day, Mon–Sun week, or calendar month. `date`
  // is the anchor; the range is derived around it. Persisted per browser.
  const [range, setRange] = useState<ViewRange>(() => {
    try { return (localStorage.getItem("dr_range") as ViewRange) || "day"; }
    catch { return "day"; }
  });
  const chooseRange = (r: ViewRange) => {
    setRange(r);
    try { localStorage.setItem("dr_range", r); } catch { /* noop */ }
  };
  // Mismatch flags the user dismissed as false positives ("Keep here"), per browser.
  const [ignoredMismatch, setIgnoredMismatch] = useState<Set<string>>(() => {
    try { return new Set<string>(JSON.parse(localStorage.getItem("dr_ignored_mismatches") || "[]")); }
    catch { return new Set<string>(); }
  });
  const ignoreMismatch = useCallback((ids: number[]) => {
    setIgnoredMismatch((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(String(id)));
      try { localStorage.setItem("dr_ignored_mismatches", JSON.stringify([...next])); } catch { /* noop */ }
      return next;
    });
  }, []);



  useEffect(() => {
    if (!user && whoami) setUser(whoami);
  }, [whoami, user]);

  useEffect(() => {
    (async () => {
      try { await primeCsrf(API_BASE); } catch {}
    })();
  }, []);

  const showToast = (message: string, type: "success" | "error") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const loadClients = useCallback(async () => {
    for (const url of [
      `${API_BASE}/options/clients/`,
      `${API_BASE}/clients/list`,
      `${API_BASE}/clients/list/`,
    ]) {
      try {
        const data = await safeFetchJson<ClientOption[]>(url);
        if (data?.length) { setAvailableClients(data); return; }
      } catch {}
    }
  }, []);

  useEffect(() => {
    if (availableClients.length === 0 && timeSummary.length > 0) {
      const clients = timeSummary
        .filter((c) => c.client_id && c.client.toLowerCase() !== "unassigned")
        .map((c) => ({ id: c.client_id!, name: c.client }));
      if (clients.length) setAvailableClients(clients);
    }
  }, [timeSummary, availableClients.length]);

  // Reload plumbing. today-time is an expensive query (it re-derives why /
  // mismatch / split for the whole day), so the rules are:
  //   - only ONE may be in flight; starting a new one ABORTS the old one, whose
  //     answer is already stale and whose open connection would otherwise sit in
  //     the browser's per-host pool ahead of the user's next confirm PATCH.
  //   - a response that has been superseded is dropped, never applied.
  const reloadSeq = useRef(0);
  const reloadAbort = useRef<AbortController | null>(null);
  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // When the user last acted on a row. The periodic poll stays out of the way
  // for a beat after each action. Deliberately a TIMESTAMP and not an
  // "is-reconciling" flag: a flag that somehow never cleared (a block the server
  // keeps returning as pending) would silently kill auto-refresh for the whole
  // session, whereas a stale timestamp just lets the next tick through.
  const lastActionAt = useRef(0);
  // When today-time data last actually landed — bounds how stale the totals get.
  const lastLoadAt = useRef(0);
  // True while a row-anchored editor (Change client, Split) is open. Reloading
  // then re-renders the row the popover is pinned to and the half-made choice is
  // gone, so reconciles WAIT — they don't get cancelled, just held, and the one
  // held request runs the moment the picker closes.
  const interactionOpen = useRef(false);
  const reloadHeld = useRef(false);
  // A payload that arrived while a picker was open. Holding the REQUEST isn't
  // enough on its own: one already in flight when the picker opens still lands
  // mid-selection, and rows disappearing above the open popover shift the row
  // it's pinned to out from under it. So the data waits here and is applied on
  // close — the reload isn't wasted, just not shown yet.
  const heldPayload = useRef<TodayTimeResponse | null>(null);

  const applyTodayTime = useCallback((json: TodayTimeResponse) => {
    setTimeSummary(json.clients || []);
    setBillableHours(json.billable_hours || 0);
    setNonBillableHours(json.non_billable_hours || 0);
    setNeedsReviewHours(json.needs_review_hours || 0);
    setProposedInline(json.proposed_inline || []);
    setMismatchBlocks(json.mismatch_blocks || []);
    setSplitCandidates(json.split_candidates || []);
  }, []);
  // `background: true` runs the reload SILENTLY — it does NOT flip `busy`, so the
  // Needs You action buttons stay live and the user can keep confirming while
  // totals reconcile behind the scenes. Foreground loads (initial, date change,
  // manual Refresh) still show the spinner and surface errors.
  const loadTimeSummary = useCallback(async (opts?: { background?: boolean }) => {
    const background = opts?.background ?? false;
    if (!background) { setBusy(true); setErr(null); }
    reloadAbort.current?.abort();
    const ctl = new AbortController();
    reloadAbort.current = ctl;
    const seq = ++reloadSeq.current;
    lastLoadAt.current = Date.now();
    heldPayload.current = null;  // superseded — and never paint one from another date
    try {
      const { start, end } = rangeBounds(date, range);
      const qs = range === "day" ? `date=${date}` : `start=${start}&end=${end}`;
      const json = await safeFetchJson<TodayTimeResponse>(
        `${API_BASE}/today-time/?${qs}`, { signal: ctl.signal }
      );
      if (seq !== reloadSeq.current) return;   // a newer reload already owns the page
      // A silent reconcile never redraws under an open picker — it waits. A
      // foreground load is the user asking for fresh data, so it always applies.
      if (background && interactionOpen.current) { heldPayload.current = json; return; }
      applyTodayTime(json);
    } catch (err: any) {
      if (ctl.signal.aborted || seq !== reloadSeq.current) return;  // superseded, not a failure
      // A failed background reconcile must not blank the page the user is working
      // in — leave the current data and stay quiet.
      if (!background) { setErr(err?.message || "Failed to load"); setTimeSummary([]); }
    } finally {
      // Only the reload that still owns the page clears the spinner — an aborted
      // one must not un-dim a page the newer foreground load is still filling.
      if (!background && seq === reloadSeq.current) setBusy(false);
    }
  }, [date, range, applyTodayTime]);

  const loadUncategorizedCount = useCallback(async () => {
    try {
      const data = await safeFetchJson<{ blocks: any[]; categories?: string[] }>(
        `${API_BASE}/categorization/data/?date=${date}`
      );
      // Count only blocks the user actually sees in Categorize — the tab hides
      // short blocks (< 2 min) by default, so the badge should match that, not
      // the full list. Mirrors SHORT_BLOCK_THRESHOLD_MINUTES in ManualCategorization.
      const SHORT_BLOCK_THRESHOLD_MINUTES = 2;
      const visibleCount = (data.blocks || []).filter(
        (b: any) => (b.duration_minutes ?? 0) >= SHORT_BLOCK_THRESHOLD_MINUTES
      ).length;
      setUncategorizedCount(visibleCount);
      if (data.categories?.length) setAvailableCategories(data.categories);
    } catch {}
  }, [date]);

  // ✨ DEFINE runAIClassification FIRST (before handleAIComplete uses it)
  const runAIClassification = useCallback(async () => {
    try {
      const response = await safeFetchJson<any[]>(`${API_BASE}/blocks/suggestions/`);
      if (Array.isArray(response)) {
        setAiSuggestions(response);
        
        // ✨ NEW: Check if AI was queued
        const hasQueuedAI = response.some(r => r.ai_suggestion?.needs_review);
        if (hasQueuedAI) {
          setAiInProgress(true);
          console.log('⏳ AI queued to background...');
        }
        
        const autoSaved = response.filter((r) => r.ai_suggestion?.auto_saved).length;
        if (autoSaved > 0) {
          // BACKGROUND. /blocks/suggestions/ runs the full classifier incl. a live
          // OpenAI batch, so this lands 5-15s after page load — by which time the
          // user is already confirming rows. A foreground reload here flipped
          // `busy` and killed every button mid-click for no reason the user could
          // see; the lanes don't need the spinner to absorb an auto-file.
          loadTimeSummary({ background: true });
          loadUncategorizedCount();
        }
      }
    } catch {}
  }, [loadTimeSummary, loadUncategorizedCount]);

  // ✨ NOW define handleAIComplete (which depends on runAIClassification)
  const handleAIComplete = useCallback(() => {
    console.log('🎉 AI classification complete! Refetching...');
    setAiInProgress(false);
    loadTimeSummary();  // Just reload summary, don't call runAIClassification to avoid circular dep
  }, [loadTimeSummary]);

  // ✨ NOW call the hook (after both callbacks are defined)
  const orgId = me?.org_id;
  // useAICompletion(orgId, handleAIComplete);

  useEffect(() => {
    const t = setTimeout(() => {
      loadTimeSummary();
      loadUncategorizedCount();
      loadClients();
      runAIClassification();
    }, 200);
    return () => clearTimeout(t);
  }, [loadTimeSummary, loadUncategorizedCount, loadClients, runAIClassification]);

  useEffect(() => {
    const dateParam = searchParams.get("date");
    if (dateParam) setDate(dateParam);
  }, [searchParams]);

  useEffect(() => {
    const shouldAdd = searchParams.get("add") === "true";
    const preSelectedClientId = searchParams.get("client_id");
    if (shouldAdd) {
      if (preSelectedClientId)
        setManualEntry((prev) => ({ ...prev, client_id: parseInt(preSelectedClientId) }));
      setShowManualEntry(true);
      searchParams.delete("add");
      searchParams.delete("client_id");
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleRefresh = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
    runAIClassification();
  }, [loadTimeSummary, loadUncategorizedCount, runAIClassification]);

  // Optimistic row control for Needs You actions. All of these are INSTANT and
  // fire before the save, so the user never waits.
  //   confirmRows — the block leaves Needs You AND appears under its client in
  //     the Certain lane immediately. Caller passes only {blockId, clientId,
  //     category}; the parent enriches client name / minutes / title from the
  //     data it already holds (proposedInline / mismatch / split + client list).
  //   hideRows — just remove from Needs You (e.g. Split, whose pieces only show
  //     after the reload).
  //   revertRows — undo either on save failure (restore the Needs You row, drop
  //     the optimistic Certain row).
  const confirmRows = useCallback((items: { blockId: number; clientId: number | null; category: string }[]) => {
    if (!items.length) return;
    lastActionAt.current = Date.now();
    const ids = items.map((it) => it.blockId);
    setHiddenIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.add(id)); return next; });
    setOptimisticConfirms((prev) => {
      const next = new Map(prev);
      for (const it of items) {
        // Only PENDING blocks are safe to place optimistically — they aren't in a
        // client card yet. A mismatch/committed block already sits under its old
        // client, so we just hide its Needs You row and let the reload move it
        // (placing it here too would double-count for a few seconds).
        const p = proposedInline.find((x) => x.block_id === it.blockId);
        if (!p) continue;
        const clientName = it.clientId == null
          ? "" : (availableClients.find((c) => c.id === it.clientId)?.name || "");
        next.set(it.blockId, {
          blockId: it.blockId, clientId: it.clientId, clientName,
          category: it.category, minutes: p.minutes || 0, title: p.window_title || "(entry)",
        });
      }
      return next;
    });
  }, [proposedInline, availableClients]);

  const hideRows = useCallback((ids: number[]) => {
    if (!ids.length) return;
    lastActionAt.current = Date.now();
    setHiddenIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.add(id)); return next; });
  }, []);

  const revertRows = useCallback((ids: number[]) => {
    if (!ids.length) return;
    setHiddenIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.delete(id)); return next; });
    setOptimisticConfirms((prev) => {
      if (!prev.size) return prev;
      const next = new Map(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }, []);
  // SILENT background reconcile after a per-block action — no busy spinner (so
  // buttons stay live), no AI re-classification (its result the lanes never use;
  // the full pass stays on initial load + the manual Refresh button).
  //
  // COALESCED. Every Needs You action used to fire its own reload, so triaging
  // twenty rows queued twenty full today-time queries; they saturated the
  // browser's per-host connection pool, the confirm PATCHes behind them crawled,
  // and the page spent minutes "catching up". The rows already move instantly
  // (optimistic), so the reconcile only has to happen once the user pauses:
  // restart the timer on each action and reload after REFRESH_QUIET_MS of quiet.
  // The one place a silent reconcile actually happens. Held — not skipped —
  // while a picker is open, so nothing is lost: the reload runs on close.
  const reconcile = useCallback(() => {
    if (interactionOpen.current) { reloadHeld.current = true; return; }
    reloadHeld.current = false;
    loadTimeSummary({ background: true });
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  const scheduleRowRefresh = useCallback(() => {
    if (reloadTimer.current) clearTimeout(reloadTimer.current);
    // Steady clicking never leaves a REFRESH_QUIET_MS gap, so the debounce alone
    // would let the totals freeze for the whole run. Past MAX_STALE_MS, go now.
    if (Date.now() - lastLoadAt.current >= MAX_STALE_MS) { reconcile(); return; }
    reloadTimer.current = setTimeout(() => {
      reloadTimer.current = null;
      reconcile();
    }, REFRESH_QUIET_MS);
  }, [reconcile]);

  // Called by the lanes as a Change-client / Split editor opens and closes. On
  // close, paint whatever the reconcile learned while it was open — the held
  // payload first (already fetched), else run the reconcile that was held back.
  const handleInteractionChange = useCallback((active: boolean) => {
    interactionOpen.current = active;
    if (active) return;
    if (heldPayload.current) {
      applyTodayTime(heldPayload.current);
      heldPayload.current = null;
      reloadHeld.current = false;
      return;
    }
    if (reloadHeld.current) scheduleRowRefresh();
  }, [applyTodayTime, scheduleRowRefresh]);

  // Periodic catch-up for time the agent captured while the page sat open. The
  // auto-refresh STAYS — it just stops fighting the user for the page:
  //   - BACKGROUND (a foreground poll flipped `busy`, which disables every Needs
  //     You button — the page going dead mid-run of confirms was this poll
  //     landing, not the confirms themselves being slow),
  //   - HELD while a picker is open, and skipped while rows are still
  //     reconciling or a post-action reload is already queued — in every case
  //     the next tick (or the picker closing) picks the new time up,
  //   - free of runAIClassification, the heaviest call on the page and one the
  //     lanes never read (it stays on initial load + the manual Refresh button).
  useEffect(() => {
    const interval = setInterval(() => {
      if (document.hidden) return;
      if (reloadTimer.current) return;                                   // a reconcile is already queued
      if (Date.now() - lastActionAt.current < QUIET_AFTER_ACTION_MS) return;  // user is mid-run
      reconcile();
    }, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [reconcile]);

  // Coming back to the tab shouldn't mean waiting out the rest of a 2-minute
  // tick to see current numbers — reconcile on return if the data has aged.
  useEffect(() => {
    const onVisible = () => {
      if (document.hidden) return;
      if (Date.now() - lastLoadAt.current < MAX_STALE_MS) return;
      reconcile();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [reconcile]);

  // Drop any pending reconcile / in-flight reload when the page goes away.
  useEffect(() => () => {
    if (reloadTimer.current) clearTimeout(reloadTimer.current);
    reloadAbort.current?.abort();
  }, []);

  const handleConfirmAll = async () => {
    setConfirmingAll(true);
    try {
      const res = await safeFetchJson<{
        ok: boolean;
        confirmed_with_client: number;
        confirmed_no_client: number;
        skipped: number;
        total: number;
      }>(`${API_BASE}/blocks/confirm-all/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          range === "day"
            ? { date }
            : rangeBounds(date, range) // { start, end } for week / month
        ),
      });
      const wc = res.confirmed_with_client;
      const nc = res.confirmed_no_client;
      const total = res.total;
      if (total === 0) {
        showToast("Nothing to confirm", "success");
      } else {
        showToast(
          `Confirmed ${total} ${total === 1 ? "block" : "blocks"} \u2014 ` +
          `${wc} billable, ${nc} non-billable`,
          "success"
        );
      }
      loadTimeSummary();
    } catch (err: any) {
      showToast(err?.message || "Failed to confirm all", "error");
    } finally {
      setConfirmingAll(false);
    }
  };

  const handleCategorizationComplete = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  // Total = all time captured that day, including not-yet-confirmed review time,
  // so it matches the backend global_hours and the Reports total.
  const totalHours = billableHours + nonBillableHours + needsReviewHours;

  // Reconcile the optimistic sets whenever fresh today-time data lands: keep an
  // entry only while its block is STILL unresolved server-side (pending/mismatch/
  // split). Once a block commits it drops out of that live set — so we stop
  // hiding it AND drop its optimistic Certain row, because the real payload now
  // carries it (today-time returns clients + proposed together, atomically).
  // Race-safe across rapid confirms: an in-flight reload predating a later
  // confirm still lists that later block as unresolved, so it stays optimistic.
  useEffect(() => {
    const live = new Set<number>([
      ...proposedInline.map((p) => p.block_id),
      ...mismatchBlocks.map((m) => m.block_id),
      ...splitCandidates.map((s) => s.block_id),
    ]);
    setHiddenIds((prev) => {
      if (!prev.size) return prev;
      const next = new Set<number>();
      prev.forEach((id) => { if (live.has(id)) next.add(id); });
      return next.size === prev.size ? prev : next;
    });
    setOptimisticConfirms((prev) => {
      if (!prev.size) return prev;
      const next = new Map<number, OptimisticConfirm>();
      prev.forEach((v, id) => { if (live.has(id)) next.set(id, v); });
      return next.size === prev.size ? prev : next;
    });
  }, [proposedInline, mismatchBlocks, splitCandidates]);

  // ── Confidence lanes (single source for the header numbers + the body) ──────
  const lanes = useMemo(
    () => {
      const visiblePending = hiddenIds.size
        ? proposedInline.filter((p) => !hiddenIds.has(p.block_id)) : proposedInline;
      const visibleMismatch = hiddenIds.size
        ? mismatchBlocks.filter((m) => !hiddenIds.has(m.block_id)) : mismatchBlocks;
      const visibleSplit = hiddenIds.size
        ? splitCandidates.filter((s) => !hiddenIds.has(s.block_id)) : splitCandidates;
      const base = deriveLanes(timeSummary, visiblePending, visibleMismatch, ignoredMismatch, visibleSplit);
      return optimisticConfirms.size
        ? mergeOptimisticConfirms(base, Array.from(optimisticConfirms.values())) : base;
    },
    [timeSummary, proposedInline, mismatchBlocks, ignoredMismatch, splitCandidates, hiddenIds, optimisticConfirms],
  );
  const needsYouCount = lanes.needsYou.count;
  const autoFiled = lanes.certain.minutes > 0;

  // ── Progress hero numbers: how much of the day is sorted vs still needs you ──
  const totalMin = Math.round(totalHours * 60);
  const needsMin = lanes.needsYou.minutes;
  const sortedMin = Math.max(0, totalMin - needsMin);
  // 100% is reserved for a truly-clear day (nothing in "Needs you"). While
  // anything remains, never round up to 100 — cap at 99 so 1m left still reads
  // 99%, not a misleading "100% sorted".
  const sortedPct =
    lanes.needsYou.count === 0
      ? 100
      : totalMin > 0
        ? Math.min(99, Math.round((sortedMin / totalMin) * 100))
        : 0;

  // Step the anchor by one range unit: ±1 day, ±1 week, or ±1 month.
  const stepRange = (dir: -1 | 1) => {
    const d = new Date(date + "T00:00:00");
    if (range === "week") {
      d.setDate(d.getDate() + dir * 7);
    } else if (range === "month") {
      d.setMonth(d.getMonth() + dir);
    } else if (range === "quarter") {
      d.setMonth(d.getMonth() + dir * 3);
    } else {
      d.setDate(d.getDate() + dir);
    }
    setDate(isoLocal(d));
  };

  // Disable "next" once the current range already reaches today (never let the
  // user page into a fully-future range). end === date for the day view, so this
  // matches the old `date >= today` behavior.
  // Opening a single day IS the review — the act people already perform. The
  // server ignores it for a future day or one with no time, and the staleness
  // rule means later work un-reviews the day anyway, so this can only ever
  // mean "seen, as of now".
  useEffect(() => {
    if (range !== "day" || busy || totalMin <= 0) return;
    let cancelled = false;
    const t = setTimeout(() => {
      if (cancelled) return;
      safeFetchJson(`${API_BASE}/daily/${date}/seen/`, { method: "POST" }).catch(() => {});
    }, 2500);   // a beat, so paging quickly through days marks none of them
    return () => { cancelled = true; clearTimeout(t); };
  }, [date, range, busy, totalMin]);

  const atLatestRange = rangeBounds(date, range).end >= todayIso();

  return (
    <div className="min-h-full bg-background">
      {toast && <Toast message={toast.message} type={toast.type} />}

      {/* ═══ TOOLBAR ═══════════════════════════════════════════════════════ */}
      <div className="sticky top-0 z-10 bg-card/95 backdrop-blur-sm border-b border-border/60">
        <div className="px-5 h-14 flex items-center justify-between gap-4">

          {/* LEFT — underline tabs + add button */}
          <div className="flex items-center gap-4 h-full">

            {/* Page identity. Daily Review and the timesheet both show your time
                by client, so each has to say which question it answers or they
                read as two copies of one page. This one is about attribution:
                is this time on the right client? The timesheet is about
                commitment: is this week right, and can it go to my manager? */}
            <div className="flex flex-col justify-center h-14 pr-1">
              <span className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-400 leading-none">
                Daily Review
              </span>
              <span className="mt-1 text-[13.5px] font-semibold text-slate-700 leading-none">
                Sort your captured time
              </span>
            </div>

            {/* Divider */}
            <div className="w-px h-5 bg-border/60" />

            {/* Compact add button */}
            <ManualTimeEntry defaultDate={date} onSuccess={handleRefresh} />
          </div>

          {/* RIGHT — flags, date, refresh, stats */}
          <div className="flex items-center gap-2.5">

            {/* Date nav: ‹ date › */}
            <div className="flex items-center gap-0.5 bg-muted/70 border border-border/50 rounded-lg overflow-hidden">
              <button
                onClick={() => stepRange(-1)}
                title={range === "quarter" ? "Previous quarter" : range === "month" ? "Previous month" : range === "week" ? "Previous week" : "Previous day"}
                className="px-1.5 py-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted transition-all"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className={cn(
                  "px-1.5 py-1.5 text-sm font-medium text-slate-700 bg-transparent",
                  "focus:outline-none focus:ring-0 border-0",
                  "transition-colors"
                )}
              />
              <button
                onClick={() => stepRange(1)}
                title={range === "quarter" ? "Next quarter" : range === "month" ? "Next month" : range === "week" ? "Next week" : "Next day"}
                disabled={atLatestRange}
                className="px-1.5 py-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            {/* Confirm all — accept every pending block at once */}
            <button
              onClick={handleConfirmAll}
              disabled={confirmingAll || busy}
              title="Confirm all pending suggestions"
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                "bg-gradient-to-r from-primary to-accent text-white shadow-sm shadow-primary/25 hover:opacity-90",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {confirmingAll
                ? <RefreshCw className="w-4 h-4 animate-spin" />
                : <Check className="w-4 h-4" />}
              {confirmingAll ? "Confirming\u2026" : "Confirm all"}
            </button>

            {/* The affirmative signal. Only meaningful on a single day — a
                range has no one day to vouch for. */}
            {range === "day" && (
              <DayReviewedButton date={date} hasTime={totalMin > 0} />
            )}

            {/* Refresh — ghost icon, no background until hover */}
            <button
              onClick={handleRefresh}
              disabled={busy}
              title="Refresh"
              className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted rounded-lg disabled:opacity-40 transition-all"
            >
              <RefreshCw className={cn("w-4 h-4", busy && "animate-spin")} />
            </button>

            {/* Stats — Billable, Needs Review, Total. */}
            <div className="flex items-center gap-4 pl-3 border-l border-border/60">
              <StatCell
                value={formatHours(billableHours)}
                label="Billable"
                valueClass="text-primary"
              />
              <StatCell
                value={formatHours(needsReviewHours)}
                label="Needs review"
                valueClass={needsReviewHours === 0 ? "text-teal-500" : "text-amber-500"}
              />
              <StatCell
                value={formatHours(totalHours)}
                label="Total"
                valueClass="text-slate-800"
              />
            </div>

          </div>
        </div>
      </div>

      {/* ═══ CONTENT ════════════════════════════════════════════════════════ */}
      <div className="p-5">

        {err && (
          <div className="mb-4 px-4 py-2.5 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm font-medium">
            {err}
          </div>
        )}

{/*        {aiInProgress && (
          <div className="mb-4 px-4 py-2.5 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-2">
            <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
            <span className="text-blue-700 text-sm font-semibold">
              🤖 AI classification in progress... Results will appear automatically
            </span>
          </div>
        )}
*/}
        {/* ── How far back to look for work that still needs a decision.
               Labelled as a backlog scope, not a reporting period: firms that
               submit monthly, and anyone catching up after time off, need to
               reach past today, but this is never "my month's timesheet". ── */}
        <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-[12.5px] font-medium text-slate-500">Reviewing</span>
          <div className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5 text-sm font-medium">
            {([
              ["day", "Today"],
              ["week", "This week"],
              ["month", "This month"],
              ["quarter", "This quarter"],
            ] as const).map(([r, label]) => (
              <button
                key={r}
                onClick={() => chooseRange(r)}
                className={cn("rounded-md px-3.5 py-1.5 transition-colors",
                  range === r ? "bg-card text-foreground shadow-sm" : "text-slate-500 hover:text-slate-800")}
              >
                {label}
              </button>
            ))}
          </div>
          {range !== "day" && (
            <span className="text-[12px] text-slate-400">
              Catching up — anything still unsorted in this stretch
            </span>
          )}
        </div>

        {/* Faint teal-tinted "canvas" — cool + trustworthy; the white lane cards float on it. */}
        <div className="rounded-2xl bg-[#eef4f3] p-5 sm:p-6">
          {/* ── Progress hero: how much of the range is sorted vs still needs you ── */}
          <div className="mb-7 w-full max-w-2xl" style={{ fontFamily: '"Inter", sans-serif' }}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              {rangeLabel(date, range)}
            </div>
            {totalMin <= 0 ? (
              <NoTimeYet isToday={range === "day" && date === todayIso()} />
            ) : (
              <div className="mt-3">
                <div className="flex items-baseline justify-between gap-3">
                  <div className="text-[20px] font-bold tracking-[-0.01em] text-slate-900">
                    {needsYouCount > 0 ? (
                      <><span className="text-amber-600">{needsYouCount} {needsYouCount === 1 ? "thing" : "things"}</span> need{needsYouCount === 1 ? "s" : ""} you{range === "week" ? " this week" : range === "month" ? " this month" : range === "quarter" ? " this quarter" : ""}</>
                    ) : "You’re all caught up"}
                  </div>
                  <div className="shrink-0 text-[12.5px] tabular-nums text-slate-500">{sortedPct}% sorted</div>
                </div>
                <div className="mt-2.5 flex h-3 overflow-hidden rounded-full bg-slate-200 shadow-[inset_0_1px_2px_rgba(16,27,46,0.09)]">
                  <div className="bg-gradient-to-r from-primary to-accent transition-all" style={{ width: `${sortedPct}%` }} />
                  <div className="bg-amber-500 transition-all" style={{ width: `${100 - sortedPct}%` }} />
                </div>
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-slate-500">
                  <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[3px] bg-primary" /><span className="tabular-nums">{formatHours(sortedMin / 60)}</span> sorted</span>
                  {needsMin > 0 && (
                    <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[3px] bg-amber-500" /><span className="tabular-nums">{formatHours(needsMin / 60)}</span> needs you</span>
                  )}
                </div>
                {/* Finishing triage used to be a dead end — the page said "all
                    caught up" and stopped, with no mention of the thing that
                    sorted time is actually for. Name the next step and hand
                    them to it. */}
                {needsYouCount === 0 && (
                  <Link
                    to="/timesheet"
                    className="mt-4 inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-[13px] font-semibold text-white shadow-lg shadow-primary/20 transition-all hover:bg-primary/90"
                  >
                    Review &amp; submit your week
                    <ChevronRight className="h-4 w-4" />
                  </Link>
                )}
              </div>
            )}
          </div>
          <MatterLane date={date} onChanged={scheduleRowRefresh} />
          <CompactSummary
            lanes={lanes}
            availableClients={availableClients}
            availableCategories={availableCategories}
            busy={busy}
            autoFiled={autoFiled}
            onConfirmRows={confirmRows}
            onHideRows={hideRows}
            onRevertRows={revertRows}
            onRefresh={scheduleRowRefresh}
            showToast={showToast}
            onIgnoreMismatch={ignoreMismatch}
            onInteractionChange={handleInteractionChange}
          />
        </div>
      </div>

      {showManualEntry && (
        <ManualTimeEntry
          isOpen={showManualEntry}
          onClose={() => {
            setShowManualEntry(false);
            setManualEntry({ client_id: null, description: "", hours: 0, date: todayIso() });
          }}
          onSuccess={() => {
            setShowManualEntry(false);
            setManualEntry({ client_id: null, description: "", hours: 0, date: todayIso() });
            loadTimeSummary();
            showToast("Time entry added", "success");
          }}
          defaultDate={date}
          preSelectedClientId={manualEntry.client_id}
        />
      )}
    </div>
  );
}