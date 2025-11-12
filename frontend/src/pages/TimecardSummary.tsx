// src/pages/TimecardSummary.tsx
import { useEffect, useMemo, useState, useCallback, useRef } from "react";
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
import { primeCsrf, postJson } from "@/lib/csrf";

// ---------- UI shapes ----------
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

// ---------- server response shape ----------
type Bucket = {
  client: string;
  project: string | null;
  minutes: number; // union-minutes within the bucket (int)
  hours: number;   // rounded on server (2 dp)
  categories: Record<string, number | string>;
};

type SummaryRespStable = {
  date: string;
  user: string;
  total_hours: number;   // ACTIVE, de-duplicated across all buckets
  buckets: Bucket[];
  meta?: {
    count_blocks?: number;
    stable?: boolean;
    active_minutes?: number;
    idle_minutes?: number; // we'll surface this as Idle/Away
  };
};

export default function TimecardSummary() {
  const [data, setData] = useState<{
    date: string;
    user: string;
    total_hours: number;     // active hours (header)
    clients: ClientRow[];
    idle_hours: number;      // derived from meta.idle_minutes
    active_minutes: number;  // passthrough for debugging/QA if needed
  } | null>(null);

  const [busy, setBusy] = useState(false);
  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());
  const [err, setErr] = useState<string | null>(null);
  const [whoami, setWhoami] = useState<string>("");
  const [expandedClients, setExpandedClients] = useState<Set<string>>(new Set());

  // StrictMode double-run guard
  const loadOnceRef = useRef(0);
  useEffect(() => { loadOnceRef.current = 0; }, [date, user]);

  // ---------- identify current user ----------
  useEffect(() => {
    (async () => {
      try {
        const j = await safeFetchJson<{ username?: string }>(API_ENDPOINTS.whoami, { credentials: "include" });
        const name = (j?.username || "").trim();
        setWhoami(name);
        setUser((u) => (u.trim() ? u : name));
      } catch {
        // ok if anonymous
      }
    })();
  }, []);

  // ---------- load snapshot & adapt to UI ----------
  const load = useCallback(async () => {
    if (loadOnceRef.current) return;
    loadOnceRef.current = 1;

    if (!date) return;
    setBusy(true);
    setErr(null);
    try {
      const url = new URL(API_ENDPOINTS.timecardsSummaryDay);
      url.searchParams.set("date", date);
      if (user.trim()) url.searchParams.set("user", user.trim());

      const j = await safeFetchJson<SummaryRespStable>(url.toString(), { credentials: "include" });
      const buckets = Array.isArray(j?.buckets) ? j.buckets : [];

      // bucket → clients + tasks
      const byClient: Record<string, ClientRow> = {};
      for (const b of buckets) {
        const clientNameRaw = b.client || "Unassigned";
        const clientName = displayClientName(clientNameRaw);
        const project = b.project || "—";
        const hours = Number(b.hours || 0);

        if (!byClient[clientName]) {
          byClient[clientName] = {
            client_name: clientName,
            total_hours: 0,
            categories: {},
            tasks: [],
            block_ids: [],
          };
        }

        const C = byClient[clientName];
        C.total_hours = Number((C.total_hours + hours).toFixed(2));

        // sum categories at client level (coerce to number)
        for (const [k, v] of Object.entries(b.categories || {})) {
          const n = Number(v || 0);
          C.categories[k] = Number(((C.categories[k] || 0) + n).toFixed(2));
        }

        // upsert task row by project
        const idx = C.tasks!.findIndex((t) => t.task_name === project);
        if (idx === -1) {
          const cat: Record<string, number> = {};
          for (const [k, v] of Object.entries(b.categories || {})) cat[k] = Number(v || 0);
          C.tasks!.push({
            task_name: project,
            total_hours: Number(hours || 0),
            categories: cat,
          });
        } else {
          const T = C.tasks![idx];
          T.total_hours = Number((T.total_hours + hours).toFixed(2));
          for (const [k, v] of Object.entries(b.categories || {})) {
            const n = Number(v || 0);
            T.categories[k] = Number(((T.categories[k] || 0) + n).toFixed(2));
          }
        }
      }

      // sort tasks per client (hours desc, then alpha)
      const clients: ClientRow[] = Object.values(byClient).map((c) => ({
        ...c,
        tasks: (c.tasks || []).sort(
          (a, b) => (b.total_hours - a.total_hours) || a.task_name.localeCompare(b.task_name)
        ),
      }));

      // client sort: Unassigned last → hours desc → alpha
      clients.sort((a, b) => {
        const au = a.client_name === "Unassigned";
        const bu = b.client_name === "Unassigned";
        if (au && !bu) return 1;
        if (!au && bu) return -1;
        if (b.total_hours !== a.total_hours) return b.total_hours - a.total_hours;
        return a.client_name.localeCompare(b.client_name);
      });

      const idleMinutes = Number(j?.meta?.idle_minutes || 0);
      const activeMinutes = Number(j?.meta?.active_minutes || Math.round((j?.total_hours || 0) * 60));
      const idleHours = Number((idleMinutes / 60).toFixed(2));

      // Add an explicit Idle bucket (NOT counted in header total_hours)
      if (idleHours >= 0.1) {
        clients.push({
          client_name: "Idle/Away",
          total_hours: idleHours,
          categories: { Idle: idleHours },
          tasks: [
            {
              task_name: "—",
              total_hours: idleHours,
              categories: { Idle: idleHours },
            },
          ],
        });
      }

      setData({
        date: j?.date || date,
        user: typeof j?.user === "string" ? j.user : user,
        total_hours: Number(j?.total_hours || 0), // ACTIVE hours only
        clients,
        idle_hours: idleHours,
        active_minutes: activeMinutes,
      });
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to load.");
      setData({ date, user, total_hours: 0, clients: [], idle_hours: 0, active_minutes: 0 });
    } finally {
      setBusy(false);
    }
  }, [date, user]);

  // ---------- generate timecard then reload ----------
  const generate = async (status: "draft" | "pending" = "pending") => {
    if (!(whoami || user)) {
      setErr("No user detected — cannot generate timecard.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await primeCsrf(); // ensure csrftoken exists
      const res = await postJson(API_ENDPOINTS.timecardsGenerate, {
        date,
        user: user || whoami,
        status,
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(`Generate failed: HTTP ${res.status} ${res.statusText} ${t?.slice(0, 200)}`);
      }
      loadOnceRef.current = 0;
      await load();
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to generate.");
    } finally {
      setBusy(false);
    }
  };

  // ---------- auto-load ----------
  useEffect(() => {
    const t = setTimeout(() => { void load(); }, 250);
    return () => clearTimeout(t);
  }, [load]);

  // ---------- helpers ----------
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

  // Cross-bucket overlap notice — header total is a union across buckets
  const overlapBanner = useMemo(() => {
    if (!data) return null;
    const sumBuckets = Number(
      data.clients.reduce((a, c) => a + (c.total_hours || 0), 0).toFixed(2)
    );
    const overlap = sumBuckets > data.total_hours * 1.1; // wiggle room for rounding
    if (!overlap) return null;
    return (
      <div className="mb-3 p-3 rounded-md border border-amber-200 bg-amber-50 text-amber-800 text-sm">
        Heads-up: client totals can exceed the header total when work overlaps across buckets.
        The header shows de-duplicated time across all buckets; each bucket de-duplicates only within itself.
      </div>
    );
  }, [data]);

  // ---------- tiny component: Idle pill ----------
  const IdlePill = ({ hours }: { hours: number }) => {
    if (!hours || hours < 0.01) return null;
    return (
      <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border text-xs ml-2
                      border-slate-200 bg-slate-50 text-slate-700">
        <span className="inline-block w-2 h-2 rounded-full bg-slate-400" />
        Idle/Away: <span className="font-semibold">{hours.toFixed(2)}h</span>
      </div>
    );
  };

  // ---------- render ----------
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
          onRefresh={() => { loadOnceRef.current = 0; void load(); }}
          onDraft={() => generate("draft")}
          onSubmit={() => generate("pending")}
          isLoading={busy}
        />

        {overlapBanner}

        {err && <ErrorBanner message={err} />}

        {data && (
          <div className="mb-3 flex items-center">
            <StatsOverview
              totalHours={data.total_hours}   // active only
              currentUser={headerUser}
              clientCount={data.clients.length}
            />
            <IdlePill hours={data.idle_hours} />
          </div>
        )}

        {data && data.clients.length > 0 ? (
          <div className="space-y-4">
            {data.clients.map((client) => (
              <ClientCard
                key={client.client_name}
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