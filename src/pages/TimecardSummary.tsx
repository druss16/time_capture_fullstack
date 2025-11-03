// src/pages/TimecardSummary.tsx
import { useEffect, useMemo, useState } from "react";
import { Calendar, User, Clock, Download, RefreshCw, Save, ChevronRight, TrendingUp } from "lucide-react";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type TaskRow = { task_name: string; total_hours: number; categories: Record<string, number>; block_ids?: number[]; };
type ClientRow = { client_name: string; total_hours: number; categories: Record<string, number>; block_ids?: number[]; tasks?: TaskRow[]; };
type SummaryResp = { date: string; user: string; total_hours: number; clients: ClientRow[]; };

const fmtHours = (n: number) => (Math.round((n || 0) * 100) / 100).toFixed(2);
const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const displayClient = (name?: string) => {
  const n = (name || "").trim();
  if (!n || n.toLowerCase() === "unknown") return "Unassigned";
  return n;
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
        const r = await fetch(`${API_BASE}/whoami/`, { credentials: "include" });
        if (r.ok) {
          const j = (await r.json()) as { username?: string };
          const name = (j?.username || "").trim();
          setWhoami(name);
          setUser((u) => (u.trim() ? u : name));
        }
      } catch {/* ignore */}
    })();
  }, []);

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      const url = new URL(`${API_BASE}/timecards/summary/day/`);
      url.searchParams.set("date", date);
      if (user.trim()) url.searchParams.set("user", user.trim());

      const r = await fetch(url.toString(), { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as SummaryResp;

      const clients = (Array.isArray(j.clients) ? j.clients : []).map((c) => ({
        ...c,
        client_name: displayClient(c.client_name),
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

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [date, user]);

  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : (data?.user?.trim() ? data.user : "All Users");
  }, [user, data?.user]);

  const toggleClient = (clientName: string) => {
    setExpandedClients(prev => {
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
      {/* Modern Header */}
      <div className="border-b border-border bg-card/50 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-[1400px] mx-auto px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
                <Clock className="w-5 h-5 text-primary-foreground" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-foreground">Timecard</h1>
                <p className="text-xs text-muted-foreground">Time allocation dashboard</p>
              </div>
            </div>
            
            {whoami && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-accent/50 text-sm">
                <User className="w-4 h-4 text-accent-foreground" />
                <span className="font-medium text-accent-foreground">{whoami}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-[1400px] mx-auto px-8 py-8">
        {/* Controls Bar */}
        <div className="mb-8 flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border bg-card hover:shadow-md transition-all">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <input 
              type="date" 
              className="bg-transparent border-none outline-none text-sm font-medium text-foreground"
              value={date} 
              onChange={(e) => setDate(e.target.value)} 
            />
          </div>

          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border bg-card hover:shadow-md transition-all">
            <User className="w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              className="bg-transparent border-none outline-none text-sm font-medium text-foreground w-40"
              placeholder="All users"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              list="user-hints"
            />
            <datalist id="user-hints">{whoami ? <option value={whoami} /> : null}</datalist>
          </div>

          <div className="flex-1" />

          <button 
            onClick={load} 
            disabled={busy}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border bg-card hover:bg-accent transition-all disabled:opacity-50 text-sm font-medium"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>

          <button 
            onClick={() => generate("draft")} 
            disabled={busy}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border bg-card hover:bg-accent transition-all disabled:opacity-50 text-sm font-medium"
          >
            <Download className="w-4 h-4" />
            Draft
          </button>

          <button 
            onClick={() => generate("pending")} 
            disabled={busy}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition-all disabled:opacity-50 text-sm font-semibold shadow-lg shadow-primary/25"
          >
            <Save className="w-4 h-4" />
            Submit
          </button>
        </div>

        {err && (
          <div className="mb-6 p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm">
            {err}
          </div>
        )}

        {/* Stats Overview */}
        {data && (
          <div className="mb-6 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-gradient-to-br from-primary to-primary/80 text-primary-foreground shadow-lg shadow-primary/20">
              <div className="flex items-center justify-between mb-2">
                <div className="w-9 h-9 rounded-lg bg-white/20 backdrop-blur flex items-center justify-center">
                  <Clock className="w-5 h-5" />
                </div>
                <TrendingUp className="w-4 h-4 opacity-70" />
              </div>
              <div className="text-3xl font-bold mb-0.5">{fmtHours(data.total_hours)}<span className="text-lg">h</span></div>
              <div className="text-xs opacity-90">Total Hours Today</div>
            </div>

            <div className="p-4 rounded-xl bg-card border border-border hover:shadow-md transition-all">
              <div className="flex items-center justify-between mb-2">
                <div className="w-9 h-9 rounded-lg bg-accent flex items-center justify-center">
                  <User className="w-5 h-5 text-accent-foreground" />
                </div>
              </div>
              <div className="text-2xl font-bold text-foreground mb-0.5 truncate">{headerUser}</div>
              <div className="text-xs text-muted-foreground">Timecard For</div>
            </div>

            <div className="p-4 rounded-xl bg-card border border-border hover:shadow-md transition-all">
              <div className="flex items-center justify-between mb-2">
                <div className="w-9 h-9 rounded-lg bg-success-light flex items-center justify-center">
                  <Calendar className="w-5 h-5 text-success" />
                </div>
              </div>
              <div className="text-3xl font-bold text-foreground mb-0.5">{data.clients.length}</div>
              <div className="text-xs text-muted-foreground">Active Clients</div>
            </div>
          </div>
        )}

        {/* Client Cards */}
        {data && data.clients.length > 0 ? (
          <div className="space-y-4">
            {data.clients.map((client) => {
              const isExpanded = expandedClients.has(client.client_name);
              const hasDetails = (client.tasks?.length || 0) > 0 || Object.keys(client.categories || {}).length > 0;
              
              return (
                <div 
                  key={`${client.client_name}-${fmtHours(client.total_hours)}`}
                  className="rounded-2xl border border-border bg-card hover:shadow-lg transition-all overflow-hidden"
                >
                  <div 
                    className="p-6 cursor-pointer"
                    onClick={() => hasDetails && toggleClient(client.client_name)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4 flex-1">
                        {hasDetails && (
                          <ChevronRight 
                            className={`w-5 h-5 text-muted-foreground transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                          />
                        )}
                        <div className="flex-1">
                          <h3 className="text-xl font-bold text-foreground mb-1">
                            {displayClient(client.client_name)}
                          </h3>
                          {client.tasks && client.tasks.length > 0 && (
                            <p className="text-sm text-muted-foreground">
                              {client.tasks.length} task{client.tasks.length !== 1 ? 's' : ''}
                            </p>
                          )}
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-4">
                        {/* Progress bar */}
                        <div className="hidden md:block w-32">
                          <div className="h-2 bg-muted rounded-full overflow-hidden">
                            <div 
                              className="h-full bg-primary rounded-full transition-all"
                              style={{ width: `${Math.min(100, (client.total_hours / (data.total_hours || 1)) * 100)}%` }}
                            />
                          </div>
                        </div>
                        
                        <div className="text-right">
                          <div className="text-3xl font-bold text-foreground">{fmtHours(client.total_hours)}</div>
                          <div className="text-xs text-muted-foreground">hours</div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {isExpanded && (
                    <div className="border-t border-border bg-muted/30">
                      {/* Categories */}
                      {Object.entries(client.categories || {}).filter(([k]) => !(k === "Uncategorized" && (client.tasks?.length || 0) > 0)).length > 0 && (
                        <div className="p-6 border-b border-border">
                          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Categories</h4>
                          <div className="flex flex-wrap gap-2">
                            {Object.entries(client.categories || {})
                              .filter(([k]) => !(k === "Uncategorized" && (client.tasks?.length || 0) > 0))
                              .map(([cat, hrs]) => (
                                <div 
                                  key={cat}
                                  className="px-4 py-2 rounded-lg bg-primary-light border border-primary/20 flex items-center gap-2"
                                >
                                  <span className="text-sm font-medium text-foreground">{cat}</span>
                                  <span className="text-sm font-bold text-primary">{fmtHours(hrs)}h</span>
                                </div>
                              ))}
                          </div>
                        </div>
                      )}

                      {/* Tasks */}
                      {client.tasks && client.tasks.length > 0 && (
                        <div className="p-6">
                          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Task Breakdown</h4>
                          <div className="space-y-2">
                            {client.tasks.map((task) => (
                              <div 
                                key={`${client.client_name}-${task.task_name}`}
                                className="flex items-center justify-between p-3 rounded-lg bg-card hover:bg-accent/50 transition-all"
                              >
                                <span className="text-sm font-medium text-foreground">{task.task_name}</span>
                                <span className="text-sm font-bold text-primary">{fmtHours(Number(task.total_hours || 0))}h</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : data && data.clients.length === 0 ? (
          <div className="text-center py-20 rounded-2xl border-2 border-dashed border-border bg-muted/20">
            <Clock className="w-16 h-16 text-muted-foreground mx-auto mb-4 opacity-50" />
            <h3 className="text-xl font-semibold text-foreground mb-2">No time tracked</h3>
            <p className="text-muted-foreground">Select a different date or user to view entries</p>
          </div>
        ) : busy ? (
          <div className="text-center py-20">
            <RefreshCw className="w-12 h-12 text-primary mx-auto mb-4 animate-spin" />
            <p className="text-muted-foreground">Loading timecard data...</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
