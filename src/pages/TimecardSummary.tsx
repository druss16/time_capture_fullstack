import { useEffect, useMemo, useState } from "react";
import { Clock, User } from "lucide-react";
import { Header } from "@/components/common/Header";
import { FilterBar } from "@/components/timecard/FilterBar";
import { StatsOverview } from "@/components/timecard/StatsOverview";
import { ClientCard } from "@/components/timecard/ClientCard";
import { EmptyState, LoadingState, ErrorBanner } from "@/components/timecard/EmptyState";
import { DESIGN_SYSTEM } from "@/lib/design-system";
import { todayIso } from "@/lib/utils/date";
import { displayClientName } from "@/lib/utils/formatting";
import { API_ENDPOINTS } from "@/lib/api";

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

export default function TimecardSummary() {
  const [data, setData] = useState<SummaryResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());
  const [err, setErr] = useState<string | null>(null);
  const [whoami, setWhoami] = useState<string>("");
  const [expandedClients, setExpandedClients] = useState<Set<string>>(new Set());

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(API_ENDPOINTS.whoami, { credentials: "include" });
        if (r.ok) {
          const j = (await r.json()) as { username?: string };
          const name = (j?.username || "").trim();
          setWhoami(name);
          setUser((u) => (u.trim() ? u : name));
        }
      } catch {
      }
    })();
  }, []);

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      const url = new URL(API_ENDPOINTS.timecardsSummaryDay);
      url.searchParams.set("date", date);
      if (user.trim()) url.searchParams.set("user", user.trim());

      const r = await fetch(url.toString(), { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as SummaryResp;

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
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to load.");
      setData({ date, user, total_hours: 0, clients: [] });
    } finally {
      setBusy(false);
    }
  };

  const generate = async (status: "draft" | "pending" = "pending") => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`${API_BASE}/timecards/generate/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ date, user, status }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json();
      await load();
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to generate.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load();
  }, [date, user]);

  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : data?.user?.trim() ? data.user : "All Users";
  }, [user, data?.user]);

  const toggleClient = (clientName: string) => {
    setExpandedClients((prev) => {
      const next = new Set(prev);
      if (next.has(clientName)) {
        next.delete(clientName);
      } else {
        next.add(clientName);
      }
      return next;
    });
  };

  return (
    <div className="min-h-screen bg-background">
      <Header
        title="Timecard"
        subtitle="Time allocation dashboard"
        icon={<Clock className="w-5 h-5 text-primary-foreground" />}
        rightContent={
          whoami && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-accent/50 text-sm">
              <User className="w-4 h-4 text-accent-foreground" />
              <span className="font-medium text-accent-foreground">{whoami}</span>
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

        {err && <ErrorBanner message={err} />}

        {data && <StatsOverview totalHours={data.total_hours} currentUser={headerUser} clientCount={data.clients.length} />}

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
