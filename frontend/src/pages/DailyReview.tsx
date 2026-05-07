/**
 * DailyReview.tsx — modernized toolbar & layout
 */

import { useEffect, useState, useCallback } from "react";
import {
  RefreshCw,
  Edit3,
  BarChart3,
  Check,
  X,
  AlertTriangle,
  Plus,
  Clock,
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
import CategorySummary from "@/components/CategorySummary";

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
  type?: 'mobile_review' | 'ai_disagreement';
  ai_proposed_client_id?: number | null;
  ai_proposed_client_name?: string | null;
  ai_confidence?: number;
  ai_reasoning?: string;
};
type TodayTimeResponse = {
  clients: ClientTime[];
  billable_hours: number;
  non_billable_hours: number;
  global_hours: number;
  date: string;
  flagged_blocks: FlaggedBlock[];
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
  const [flaggedBlocks, setFlaggedBlocks] = useState<FlaggedBlock[]>([]);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const [availableClients, setAvailableClients] = useState<ClientOption[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const [billableHours, setBillableHours] = useState(0);
  const [nonBillableHours, setNonBillableHours] = useState(0);
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
      setFlaggedBlocks(json.flagged_blocks || []);
    } catch (err: any) {
      setErr(err?.message || "Failed to load");
      setTimeSummary([]);
    } finally {
      setBusy(false);
    }
  }, [date]);

  const handleDismissReview = async (blockId: number) => {
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/dismiss-review/`, { method: "POST" });
      setFlaggedBlocks((prev) => prev.filter((f) => f.block_id !== blockId));
      showToast("Entry confirmed", "success");
    } catch {
      showToast("Failed to dismiss", "error");
    }
  };

  const handleResolveDisagreement = async (blockId: number, action: 'accept' | 'dismiss') => {
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/resolve-disagreement/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      setFlaggedBlocks((prev) => prev.filter((f) => f.block_id !== blockId));
      showToast(
        action === 'accept' ? "Switched to AI's suggestion" : "Kept original client",
        "success"
      );
      loadTimeSummary();
    } catch (err: any) {
      showToast(err?.message || "Failed to resolve", "error");
    }
  };

  const loadUncategorizedCount = useCallback(async () => {
    try {
      const data = await safeFetchJson<{ blocks: any[]; categories?: string[] }>(
        `${API_BASE}/categorization/data/?date=${date}`
      );
      setUncategorizedCount(data.blocks?.length || 0);
      if (data.categories?.length) setAvailableCategories(data.categories);
    } catch {}
  }, [date]);

  const runAIClassification = useCallback(async () => {
    try {
      const response = await safeFetchJson<any[]>(`${API_BASE}/blocks/suggestions/`);
      if (Array.isArray(response)) {
        setAiSuggestions(response);  // ← ADD THIS
        const autoSaved = response.filter((r) => r.ai_suggestion?.auto_saved).length;
        if (autoSaved > 0) { loadTimeSummary(); loadUncategorizedCount(); }
      }
    } catch {}
  }, [loadTimeSummary, loadUncategorizedCount]);

  useEffect(() => {
    const t = setTimeout(() => {
      loadTimeSummary();
      loadUncategorizedCount();
      loadClients();
      runAIClassification(); // ← ADD THIS
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
    runAIClassification(); // ← ADD THIS
  }, [loadTimeSummary, loadUncategorizedCount, runAIClassification]);

  const handleCategorizationComplete = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  const totalHours = billableHours + nonBillableHours;

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
              <button
                onClick={() => setActiveTab("categorize")}
                className={cn(
                  "flex items-center gap-1.5 px-3 text-sm font-semibold transition-all border-b-2 -mb-px",
                  activeTab === "categorize"
                    ? "border-primary text-primary"
                    : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
                )}
              >
                <Edit3 className="w-3.5 h-3.5" />
                Categorize
                {uncategorizedCount > 0 && (
                  <span className="bg-amber-400 text-white text-[10px] font-bold rounded-full px-1.5 py-px leading-none">
                    {uncategorizedCount}
                  </span>
                )}
              </button>
            </div>

            {/* Divider */}
            <div className="w-px h-5 bg-border/60" />

            {/* Compact add button */}
            <ManualTimeEntry defaultDate={date} onSuccess={handleRefresh} />
          </div>

          {/* RIGHT — flags, date, refresh, stats */}
          <div className="flex items-center gap-2.5">

            {/* Flagged badge — subtle, not alarming */}
            {flaggedBlocks.length > 0 && (
              <div className="flex items-center gap-1 px-2.5 py-1 bg-amber-50 border border-amber-200 rounded-lg">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                <span className="text-amber-700 font-semibold text-xs">
                  {flaggedBlocks.length} flagged
                </span>
              </div>
            )}

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

            {/* Refresh — ghost icon, no background until hover */}
            <button
              onClick={handleRefresh}
              disabled={busy}
              title="Refresh"
              className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted rounded-lg disabled:opacity-40 transition-all"
            >
              <RefreshCw className={cn("w-4 h-4", busy && "animate-spin")} />
            </button>

            {/* Stats — clean vertical stacks separated by a thin rule */}
            <div className="flex items-center gap-4 pl-3 border-l border-border/60">
              <StatCell
                value={formatHours(billableHours)}
                label="Billable"
                valueClass="text-primary"
              />
              <StatCell
                value={formatHours(nonBillableHours)}
                label="Non-bill"
                valueClass="text-slate-400"
              />
              <StatCell
                value={formatHours(totalHours)}
                label="Total"
                valueClass="text-slate-700"
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

        {activeTab === "summary" ? (
          <>
            {uncategorizedCount > 0 && (
              <div className="mb-4 px-4 py-2.5 bg-amber-50 border border-amber-200 rounded-lg flex items-center justify-between">
                <div className="flex items-center gap-2 text-amber-700 text-sm font-semibold">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  {uncategorizedCount} block{uncategorizedCount !== 1 ? "s" : ""} need categorization
                </div>
                <button
                  onClick={() => setActiveTab("categorize")}
                  className="px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs font-bold rounded-md transition-colors"
                >
                  Categorize now
                </button>
              </div>
            )}

            <CategorySummary
              timeSummary={timeSummary}
              availableClients={availableClients}
              availableCategories={availableCategories}
              flaggedBlocks={flaggedBlocks}
              busy={busy}
              onDismissReview={handleDismissReview}
              onResolveDisagreement={handleResolveDisagreement}
              onRefresh={handleRefresh}
              showToast={showToast}
              aiSuggestions={aiSuggestions}

            />
          </>
        ) : (
          <ManualCategorization onComplete={handleCategorizationComplete} />
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