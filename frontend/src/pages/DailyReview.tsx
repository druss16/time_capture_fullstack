/**
 * DailyReview.tsx — modernized toolbar & layout
 */

import { useEffect, useState, useCallback, useMemo } from "react";
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
import { useSearchParams } from "react-router-dom";
import CompactSummary from "@/components/CompactSummary";
import ClassicSummary from "@/components/ClassicSummary";
import { deriveLanes, type MismatchBlock } from "@/lib/dailyReviewLanes";
import { useAICompletion } from "@/hooks/useAICompletion";


const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api")
  ? RAW_BASE
  : `${RAW_BASE.replace(/\/+$/, "")}/api`;

const formatHours = (hours: number): string => {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
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

export default function DailyReview() {
  const me = useWhoAmI();
  const whoami = (me?.username || "").trim();

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());
  const [activeTab, setActiveTab] = useState<"summary" | "categorize">("summary");
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
  // Classic view still consumes these; kept alongside the Lightning-view slices.
  const [flaggedBlocks, setFlaggedBlocks] = useState<FlaggedBlock[]>([]);
  const [mismatchFlags, setMismatchFlags] = useState<Record<string, string>>({});
  // Which view: Classic (old client-card summary) or Lightning (confidence lanes).
  const [view, setView] = useState<"classic" | "lightning">(() => {
    try { return (localStorage.getItem("dr_view") as "classic" | "lightning") || "lightning"; }
    catch { return "lightning"; }
  });
  const chooseView = (v: "classic" | "lightning") => {
    setView(v);
    try { localStorage.setItem("dr_view", v); } catch { /* noop */ }
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

  const loadTimeSummary = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const json = await safeFetchJson<TodayTimeResponse>(
        `${API_BASE}/today-time/?date=${date}`
      );
      setTimeSummary(json.clients || []);
      setBillableHours(json.billable_hours || 0);
      setNonBillableHours(json.non_billable_hours || 0);
      setNeedsReviewHours(json.needs_review_hours || 0);
      setProposedInline(json.proposed_inline || []);
      setMismatchBlocks(json.mismatch_blocks || []);
      setMismatchFlags(json.mismatch_flags || {});
      const allFlagged = (json.flagged_blocks || []).map((b) => ({ ...b, type: b.type || "mobile_review" as const }));
      setFlaggedBlocks(allFlagged);
    } catch (err: any) {
      setErr(err?.message || "Failed to load");
      setTimeSummary([]);
    } finally {
      setBusy(false);
    }
  }, [date]);

  // Classic-view handlers (mobile-review dismiss + AI/mail/calendar disagreement).
  const handleDismissReview = async (blockId: number) => {
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/dismiss-review/`, { method: "POST" });
      setFlaggedBlocks((prev) => prev.filter((f) => f.block_id !== blockId));
      showToast("Entry confirmed", "success");
    } catch { showToast("Failed to dismiss", "error"); }
  };
  const handleResolveDisagreement = async (blockId: number, action: "accept" | "dismiss") => {
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/resolve-disagreement/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      setFlaggedBlocks((prev) => prev.filter((f) => f.block_id !== blockId));
      showToast(action === "accept" ? "Switched to suggested client" : "Kept original client", "success");
      loadTimeSummary();
    } catch (err: any) { showToast(err?.message || "Failed to resolve", "error"); }
  };

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
          loadTimeSummary(); 
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
    const interval = setInterval(() => {
      loadTimeSummary();
      loadUncategorizedCount();
      runAIClassification();
    }, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [loadTimeSummary, loadUncategorizedCount, runAIClassification]);

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
        body: JSON.stringify({ date }),
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

  // ── Confidence lanes (single source for the header numbers + the body) ──────
  const lanes = useMemo(
    () => deriveLanes(timeSummary, proposedInline, mismatchBlocks, ignoredMismatch),
    [timeSummary, proposedInline, mismatchBlocks, ignoredMismatch],
  );
  const needsYouCount = lanes.needsYou.count;
  const autoFiled = lanes.certain.minutes > 0;

  // State-dependent headline (see spec). Leads with a sentence, not a control.
  const capturedLabel = formatHours(totalHours);
  const headline =
    totalHours <= 0
      ? "Nothing tracked yet."
      : needsYouCount === 0
        ? `All ${capturedLabel} is sorted.`
        : autoFiled
          ? `${capturedLabel} sorted. ${needsYouCount} ${needsYouCount === 1 ? "thing needs" : "things need"} you.`
          : `${capturedLabel} captured. ${needsYouCount} ${needsYouCount === 1 ? "item" : "items"} still open.`;

  const stepDate = (days: number) => {
    const d = new Date(date + "T00:00:00");
    d.setDate(d.getDate() + days);
    setDate(d.toISOString().split("T")[0]);
  };

  return (
    <div className="min-h-full bg-background">
      {toast && <Toast message={toast.message} type={toast.type} />}

      {/* ═══ TOOLBAR ═══════════════════════════════════════════════════════ */}
      <div className="sticky top-0 z-10 bg-card/95 backdrop-blur-sm border-b border-border/60">
        <div className="px-5 h-14 flex items-center justify-between gap-4">

          {/* LEFT — underline tabs + add button */}
          <div className="flex items-center gap-4 h-full">

            {/* Underline-style tabs — sits flush with toolbar bottom border */}
            <div className="flex items-stretch h-14 gap-0.5">
              <button
                onClick={() => setActiveTab("summary")}
                className={cn(
                  "flex items-center gap-1.5 px-3 text-sm font-semibold transition-all border-b-2 -mb-px",
                  activeTab === "summary"
                    ? "border-primary text-primary"
                    : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
                )}
              >
                <BarChart3 className="w-3.5 h-3.5" />
                Summary
              </button>
              {/* Categorize tab removed — the Summary page is the single review
                  surface (it already shows the same pending blocks inline). The
                  one-at-a-time SimpleReview flow was a redundant second view. */}
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
                onClick={() => stepDate(-1)}
                title="Previous day"
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
                onClick={() => stepDate(1)}
                title="Next day"
                disabled={date >= todayIso()}
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
                "bg-primary text-white hover:bg-primary/90",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {confirmingAll
                ? <RefreshCw className="w-4 h-4 animate-spin" />
                : <Check className="w-4 h-4" />}
              {confirmingAll ? "Confirming\u2026" : "Confirm all"}
            </button>

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
        {/* ── View toggle: Classic (old client cards) vs Lightning (lanes) ── */}
        <div className="mb-5 flex items-center">
          <div className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5 text-sm font-medium">
            <button onClick={() => chooseView("classic")}
              className={cn("rounded-md px-3.5 py-1.5 transition-colors",
                view === "classic" ? "bg-card text-foreground shadow-sm" : "text-slate-500 hover:text-slate-800")}>
              Classic View
            </button>
            <button onClick={() => chooseView("lightning")}
              className={cn("rounded-md px-3.5 py-1.5 transition-colors",
                view === "lightning" ? "bg-card text-foreground shadow-sm" : "text-slate-500 hover:text-slate-800")}>
              ⚡ Lightning View
            </button>
          </div>
        </div>

        {view === "lightning" ? (
          <>
            {/* ── Headline: the page leads with a sentence, not a control. ── */}
            <div className="mb-7 w-full" style={{ fontFamily: '"Inter", sans-serif' }}>
              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                {new Date(date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
              </div>
              <h1 className="mt-2.5 text-[32px] font-bold leading-[1.12] tracking-[-0.021em] text-slate-900">{headline}</h1>
              {autoFiled && needsYouCount > 0 && (
                <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-slate-500">
                  Everything else matched a client with high confidence and was filed automatically.
                  You can look, but you don’t have to.
                </p>
              )}
            </div>
            <CompactSummary
              lanes={lanes}
              availableClients={availableClients}
              availableCategories={availableCategories}
              busy={busy}
              autoFiled={autoFiled}
              onRefresh={handleRefresh}
              showToast={showToast}
              onIgnoreMismatch={ignoreMismatch}
            />
          </>
        ) : (
          <ClassicSummary
            timeSummary={timeSummary}
            availableClients={availableClients}
            availableCategories={availableCategories}
            flaggedBlocks={flaggedBlocks}
            proposedInline={proposedInline}
            busy={busy}
            onDismissReview={handleDismissReview}
            onResolveDisagreement={handleResolveDisagreement}
            onRefresh={handleRefresh}
            showToast={showToast}
            mismatchFlags={mismatchFlags}
            date={date}
          />
        )}
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