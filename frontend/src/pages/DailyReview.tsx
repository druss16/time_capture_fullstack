/**
 * DailyReview.tsx
 */

import { useEffect, useState, useCallback } from "react";
import {
  RefreshCw,
  Edit3,
  BarChart3,
  Check,
  X,
  AlertTriangle,
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
};
type TodayTimeResponse = {
  clients: ClientTime[];
  billable_hours: number;
  non_billable_hours: number;
  global_hours: number;
  date: string;
  flagged_blocks: FlaggedBlock[];
};

const Toast = ({
  message,
  type,
}: {
  message: string;
  type: "success" | "error";
}) => (
  <div
    className={cn(
      "fixed top-20 right-4 z-50 px-4 py-3 rounded-xl shadow-xl",
      "flex items-center gap-2 text-white text-sm font-semibold animate-in slide-in-from-top-2",
      type === "success"
        ? "bg-success shadow-success/30"
        : "bg-destructive shadow-destructive/30"
    )}
  >
    {type === "success" ? (
      <Check className="w-4 h-4" />
    ) : (
      <X className="w-4 h-4" />
    )}
    {message}
  </div>
);

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

  useEffect(() => {
    if (!user && whoami) setUser(whoami);
  }, [whoami, user]);

  useEffect(() => {
    (async () => {
      try {
        await primeCsrf(API_BASE);
      } catch {}
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
        if (data?.length) {
          setAvailableClients(data);
          return;
        }
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
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/dismiss-review/`, {
        method: "POST",
      });
      setFlaggedBlocks((prev) => prev.filter((f) => f.block_id !== blockId));
      showToast("Entry confirmed", "success");
    } catch {
      showToast("Failed to dismiss", "error");
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
        const autoSaved = response.filter((r) => r.ai_suggestion?.auto_saved).length;
        if (autoSaved > 0) {
          loadTimeSummary();
          loadUncategorizedCount();
        }
      }
    } catch {}
  }, [loadTimeSummary, loadUncategorizedCount]);

  useEffect(() => {
    const t = setTimeout(() => {
      loadTimeSummary();
      loadUncategorizedCount();
      loadClients();
    }, 200);
    return () => clearTimeout(t);
  }, [loadTimeSummary, loadUncategorizedCount, loadClients]);

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
        setManualEntry((prev) => ({
          ...prev,
          client_id: parseInt(preSelectedClientId),
        }));
      setShowManualEntry(true);
      searchParams.delete("add");
      searchParams.delete("client_id");
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleRefresh = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  const handleCategorizationComplete = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  return (
    <div className="min-h-full bg-background">
      {toast && <Toast message={toast.message} type={toast.type} />}

      {/* ===== TOP TOOLBAR ===== */}
      <div className="sticky top-0 z-10 bg-card border-b-2 border-border shadow-sm">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between flex-wrap gap-3">

            {/* Left: Tabs + Add Time */}
            <div className="flex items-center gap-3">
              <div className="flex items-center bg-muted p-1 rounded-xl">
                <button
                  onClick={() => setActiveTab("summary")}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-bold transition-all flex items-center gap-2",
                    activeTab === "summary"
                      ? "bg-card text-slate-900 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  )}
                >
                  <BarChart3 className="w-4 h-4" />
                  Summary
                </button>
                <button
                  onClick={() => setActiveTab("categorize")}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-bold transition-all flex items-center gap-2",
                    activeTab === "categorize"
                      ? "bg-card text-slate-900 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  )}
                >
                  <Edit3 className="w-4 h-4" />
                  Categorize
                  {uncategorizedCount > 0 && (
                    <span className="bg-warning text-warning-foreground text-xs font-bold rounded-full px-2 py-0.5 min-w-[20px]">
                      {uncategorizedCount}
                    </span>
                  )}
                </button>
              </div>
              <ManualTimeEntry defaultDate={date} onSuccess={handleRefresh} />
            </div>

            {/* Right: Date + Refresh + Stats */}
            <div className="flex items-center gap-3">
              {flaggedBlocks.length > 0 && (
                <div className="flex items-center gap-1.5 px-3 py-2 bg-amber-50 border-2 border-amber-300 rounded-xl">
                  <AlertTriangle className="w-4 h-4 text-amber-500" />
                  <span className="text-amber-800 font-bold text-sm">
                    {flaggedBlocks.length} flagged
                  </span>
                </div>
              )}
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="px-3 py-2 rounded-lg bg-muted border-2 border-border text-sm font-semibold text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
              />
              <button
                onClick={handleRefresh}
                disabled={busy}
                className="p-2.5 text-slate-500 hover:text-slate-900 hover:bg-muted rounded-lg disabled:opacity-50 transition-all"
              >
                <RefreshCw className={cn("w-4 h-4", busy && "animate-spin")} />
              </button>
              <div className="flex items-center bg-muted border-2 border-border rounded-xl overflow-hidden divide-x-2 divide-border">
                <div className="px-4 py-2 flex items-center gap-1.5">
                  <span className="text-xl font-extrabold text-primary">
                    {formatHours(billableHours)}
                  </span>
                  <span className="text-primary/70 font-semibold text-xs uppercase tracking-wide">
                    billable
                  </span>
                </div>
                <div className="px-4 py-2 flex items-center gap-1.5">
                  <span className="text-xl font-extrabold text-slate-400">
                    {formatHours(nonBillableHours)}
                  </span>
                  <span className="text-slate-400 font-semibold text-xs uppercase tracking-wide">
                    non-bill
                  </span>
                </div>
                <div className="px-4 py-2 flex items-center gap-1.5">
                  <span className="text-xl font-extrabold text-slate-700">
                    {formatHours(billableHours + nonBillableHours)}
                  </span>
                  <span className="text-slate-500 font-semibold text-xs uppercase tracking-wide">
                    total
                  </span>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>

      {/* ===== CONTENT ===== */}
      <div className="p-6">
        {err && (
          <div className="mb-4 px-4 py-3 bg-destructive/10 border-2 border-destructive/30 rounded-xl text-red-700 font-semibold">
            {err}
          </div>
        )}

        {activeTab === "summary" ? (
          <>
            {uncategorizedCount > 0 && (
              <div className="mb-4 px-4 py-3 bg-warning/10 border-2 border-warning/30 rounded-xl flex items-center justify-between">
                <div className="flex items-center gap-2 text-amber-700 font-bold">
                  <AlertTriangle className="w-5 h-5" />
                  {uncategorizedCount} blocks need categorization
                </div>
                <button
                  onClick={() => setActiveTab("categorize")}
                  className="px-4 py-2 bg-warning text-warning-foreground font-bold rounded-lg hover:opacity-90 transition-all"
                >
                  Categorize
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
              onRefresh={handleRefresh}
              showToast={showToast}
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