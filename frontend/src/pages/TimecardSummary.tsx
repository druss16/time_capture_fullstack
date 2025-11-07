// src/pages/TimecardSummary.tsx
import { useEffect, useMemo, useState, useCallback } from "react";
import { Clock, User } from "lucide-react";
import { Header } from "@/components/common/Header";
import {
  FilterBar,
  StatsOverview,
  ClientCard,
  EmptyState,
  LoadingState,
  ErrorBanner,
} from "@/components/timecard";
import { DESIGN_SYSTEM } from "@/lib/design-system";
import { todayIso } from "@/lib/utils/date";
import { displayClientName } from "@/lib/utils/formatting";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";
import { primeCsrf, getCookie } from "@/lib/csrf";

// ---------- Types ----------
type TaskRow = {
  task_name: string;
  total_hours: number;
  categories: Record<string, number>;
  block_ids?: number[];
};

type ClientRow = {
  client_name: string;
  total_hours: number;
  categories: Record<string, number>;
  block_ids?: number[];
  tasks?: TaskRow[];
};

type SummaryResp = {
  date: string;
  user: string;
  total_hours: number;
  clients: ClientRow[];
};

type BlockMeta = { id: number; start: string; end: string; minutes?: number };

// ---------- API helpers ----------
async function fetchBlocksForDay(date: string, user: string) {
  const url = new URL(API_ENDPOINTS.blocksToday);
  url.searchParams.set("date", date);
  if (user?.trim()) url.searchParams.set("user", user.trim());

  try {
    return (await safeFetchJson<BlockMeta[]>(url.toString(), { credentials: "include" })) ?? [];
  } catch {
    return [] as BlockMeta[];
  }
}

async function postJson(url: string, data: any) {
  const csrftoken = getCookie("csrftoken");
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrftoken,
      "X-Requested-With": "XMLHttpRequest",
    },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  return res.json().catch(() => ({}));
}

// ---------- Component ----------
export default function TimecardSummary() {
  const [data, setData] = useState<SummaryResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());
  const [err, setErr] = useState<string | null>(null);
  const [whoami, setWhoami] = useState<string>("");
  const [expandedClients, setExpandedClients] = useState<Set<string>>(new Set());
  const [blocks, setBlocks] = useState<BlockMeta[] | null>(null);
  const [hasOverlap, setHasOverlap] = useState(false);

  // ---------- Identify current user ----------
  useEffect(() => {
    (async () => {
      try {
        const j = await safeFetchJson<{ username?: string }>(API_ENDPOINTS.whoami, {
          credentials: "include",
        });
        const name = (j?.username || "").trim();
        setWhoami(name);
        setUser((u) => (u.trim() ? u : name));
      } catch {
        // ignore — anon
      }
    })();
  }, []);

  // ---------- Load summary + blocks ----------
  const load = useCallback(async () => {
    if (!date) return;
    setBusy(true);
    setErr(null);
    try {
      const url = new URL(API_ENDPOINTS.timecardsSummaryDay);
      url.searchParams.set("date", date);
      if (user.trim()) url.searchParams.set("user", user.trim());

      const j = await safeFetchJson<SummaryResp>(url.toString(), { credentials: "include" });

      const clients = (Array.isArray(j.clients) ? j.clients : []).map((c) => ({
        ...c,
        client_name: displayClientName(c.client_name),
        tasks: Array.isArray((c as any).tasks) ? (c as any).tasks : [],
      }));

      clients.sort((a, b) => {
        const au = a.client_name === "Unassigned";
        const bu = b.client_name === "Unassigned";
        if (au && !bu) return 1;
        if (!au && bu) return -1;
        return b.total_hours - a.total_hours;
      });

      setData({
        date: j.date || date,
        user: typeof j.user === "string" ? j.user : user,
        total_hours: Number(j.total_hours || 0),
        clients,
      });

      // ---- Compute overlap warning ----
      const blk = await fetchBlocksForDay(date, user);
      setBlocks(blk);

      const rawTotalMins = (blk ?? []).reduce((a, b) => a + (b.minutes || 0), 0);
      const hasSpan = (blk ?? []).length > 0;
      const minStart = hasSpan ? Math.min(...blk.map((b) => +new Date(b.start))) : 0;
      const maxEnd = hasSpan ? Math.max(...blk.map((b) => +new Date(b.end))) : 0;
      const spanHours = hasSpan ? (maxEnd - minStart) / 3600000 : 0;
      const overlapRatio = spanHours ? (rawTotalMins / 60) / spanHours : 1;
      setHasOverlap(overlapRatio > 1.15);
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to load.");
      setData({ date, user, total_hours: 0, clients: [] });
      setBlocks([]);
      setHasOverlap(false);
    } finally {
      setBusy(false);
    }
  }, [date, user]);

  // ---------- Generate timecard ----------
  const generate = async (status: "draft" | "pending" = "pending") => {
    if (!(whoami || user)) {
      setErr("No user detected — cannot generate timecard.");
      return;
    }

    setBusy(true);
    setErr(null);
    try {
      await primeCsrf(); // ensure csrftoken exists
      await postJson(API_ENDPOINTS.timecardsGenerate, {
        date,
        user: user || whoami,
        status,
      });
      await load();
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to generate.");
    } finally {
      setBusy(false);
    }
  };

  // ---------- Auto-load ----------
  useEffect(() => {
    const timer = setTimeout(() => {
      load();
    }, 300);
    return () => clearTimeout(timer);
  }, [load]);

  // ---------- UI Helpers ----------
  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : data?.user?.trim() ? data.user : "All Users";
  }, [user, data?.user]);

  const toggleClient = (clientName: string) => {
    setExpandedClients((prev) => {
      const next = new Set(prev);
      next.has(clientName) ? next.delete(clientName) : next.add(clientName);
      return next;
    });
  };

  // ---------- Render ----------
  return (
    <div className="min-h-screen bg-background">
      <Header
        title="Timecard"
        subtitle="Time allocation dashboard"
        icon={<Clock className="w-6 h-6 text-primary-foreground" />}
        rightContent={
          whoami && (
            <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-primary/20 to-accent/20 border border-primary/30 text-sm hover:border-primary/50 transition-all shadow-sm">
              <User className="w-4 h-4 text-primary" />
              <span className="font-semibold text-primary">{whoami}</span>
            </div>
          )
        }
      />

      <div className={DESIGN_SYSTEM.spacing.container + " " + DESIGN_SYSTEM.spacing.section}>
        <FilterBar
          date={date}
          user={user}
          whoami={whoami}
          onDateChange={setDate}
          onUserChange={setUser}
          onRefresh={load}
          onDraft={() => generate("draft")}
          onSubmit={() => generate("pending")}
          isLoading={busy}
        />

        {hasOverlap && (
          <div className="mb-4 p-3 rounded-md border border-red-200 bg-red-50 text-red-700 text-sm">
            Totals may be inflated due to overlapping segments. Refresh after compaction.
          </div>
        )}

        {err && <ErrorBanner message={err} />}

        {data && (
          <StatsOverview
            totalHours={data.total_hours}
            currentUser={headerUser}
            clientCount={data.clients.length}
          />
        )}

        {data && data.clients.length > 0 ? (
          <div className="space-y-4">
            {data.clients.map((client) => (
              <ClientCard
                key={`${client.client_name}-${client.total_hours}`}
                client={client}
                totalHours={data.total_hours}
                isExpanded={expandedClients.has(client.client_name)}
                onToggle={() => toggleClient(client.client_name)}
              />
            ))}
          </div>
        ) : data && data.clients.length === 0 ? (
          <EmptyState />
        ) : busy ? (
          <LoadingState />
        ) : null}
      </div>
    </div>
  );
}