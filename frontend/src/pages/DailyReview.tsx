/**
 * DailyReview.tsx — Clean time summary view
 * - Shows organized time by client → category
 * - Simple, focused interface
 */

import { useEffect, useMemo, useState, useCallback } from "react";
import { Clock, User, RefreshCw } from "lucide-react";
import { Header } from "@/components/common/Header";
import { DESIGN_SYSTEM } from "@/lib/design-system";
import { FilterBar, ErrorBanner } from "@/components/timecard";
import { todayIso } from "@/lib/utils/date";
import { primeCsrf } from "@/lib/csrf";
import { useWhoAmI } from "@/lib/useWhoAmI";

// ---------- ENV ----------
const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// ---------- types ----------
type Category = {
  name: string;
  hours: number;
  block_count: number;
  sample_activities: string[];
};

type ClientTime = {
  client_id: number | null;
  client: string;
  total_hours: number;
  categories: Category[];
};

// =====================================================================================
// Component
// =====================================================================================
export default function DailyReview() {
  const me = useWhoAmI();
  const whoami = (me?.username || "").trim();

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());

  // Time summary state
  const [timeSummary, setTimeSummary] = useState<ClientTime[]>([]);

  useEffect(() => {
    if (!user && whoami) setUser(whoami);
  }, [whoami, user]);

  useEffect(() => {
    (async () => { try { await primeCsrf(API_BASE); } catch {} })();
  }, []);

  // Load time summary
  const loadTimeSummary = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/today-time/`, {
        credentials: 'include'
      });
      if (res.ok) {
        const json = await res.json();
        setTimeSummary(json);
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err: any) {
      console.error('Failed to load time summary:', err);
      setErr(err?.message || 'Failed to load time summary');
    } finally {
      setBusy(false);
    }
  }, []);

  // Auto-load on mount and when date/user changes
  useEffect(() => {
    const t = setTimeout(() => loadTimeSummary(), 200);
    return () => clearTimeout(t);
  }, [loadTimeSummary]);

  // Add after other useEffects
  useEffect(() => {
    // Auto-refresh every 5 minutes
    const interval = setInterval(() => {
      loadTimeSummary();
    }, 5 * 60 * 1000);

    return () => clearInterval(interval);
  }, [loadTimeSummary]);


  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : whoami?.trim() ? whoami : "All Users";
  }, [user, whoami]);

  const summaryTotalHours = timeSummary.reduce((sum, client) => sum + client.total_hours, 0);

  return (
    <div className="min-h-screen bg-background">
      <Header
        title="Daily Review"
        subtitle="Clean, organized summary of your day"
        icon={<Clock className="w-6 h-6 text-primary-foreground" />}
        rightContent={
          headerUser && (
            <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-primary/20 to-accent/20 border border-primary/30 text-sm hover:border-primary/50 transition-all shadow-sm">
              <User className="w-4 h-4 text-primary" />
              <span className="font-semibold text-primary">{headerUser}</span>
            </div>
          )
        }
      />

      <div className={DESIGN_SYSTEM.spacing.container + " " + DESIGN_SYSTEM.spacing.section}>
        {/* Controls */}
        <FilterBar
          date={date}
          user={user}
          whoami={whoami}
          onDateChange={setDate}
          onUserChange={setUser}
          onRefresh={loadTimeSummary}
          onDraft={undefined as any}
          onSubmit={undefined as any}
          isLoading={busy}
        />

        {err && <ErrorBanner message={err} />}

        {/* Time Summary Section */}
        {timeSummary.length > 0 && (
          <div className="bg-card border border-border rounded-lg p-6 shadow-sm">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-2xl font-semibold flex items-center gap-2">
                <Clock className="w-6 h-6 text-primary" />
                Today's Summary
              </h3>
              <div className="px-6 py-3 bg-gradient-to-r from-primary/20 to-accent/20 rounded-lg border border-primary/30">
                <span className="text-sm text-muted-foreground">Total: </span>
                <span className="text-3xl font-bold text-primary">{summaryTotalHours.toFixed(2)}h</span>
              </div>
            </div>
            
            <div className="space-y-6">
              {timeSummary.map((client) => (
                <div 
                  key={client.client_id || client.client} 
                  className="border border-border rounded-lg overflow-hidden shadow-sm hover:shadow-md transition-shadow"
                >
                  {/* Client Header */}
                  <div className="bg-gradient-to-r from-primary/10 to-accent/10 px-6 py-4 flex items-center justify-between">
                    <h4 className="font-semibold text-xl text-foreground">{client.client}</h4>
                    <span className="text-2xl font-bold text-primary">{client.total_hours.toFixed(2)}h</span>
                  </div>
                  
                  {/* Categories */}
                  <div className="divide-y divide-border bg-white">
                    {client.categories.map((cat) => (
                      <div key={cat.name} className="px-6 py-4 hover:bg-accent/30 transition-colors">
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-medium text-foreground text-lg">{cat.name}</span>
                          <div className="flex items-center gap-4">
                            <span className="text-sm text-muted-foreground">
                              {cat.block_count} {cat.block_count === 1 ? 'block' : 'blocks'}
                            </span>
                            <span className="font-bold text-success text-xl">{cat.hours.toFixed(2)}h</span>
                          </div>
                        </div>
                        
                        {cat.sample_activities && cat.sample_activities.length > 0 && (
                          <ul className="mt-3 ml-2 space-y-1.5">
                            {cat.sample_activities.map((activity, idx) => (
                              <li key={idx} className="text-sm text-muted-foreground flex gap-2 items-start">
                                <span className="text-muted-foreground/50 mt-0.5">→</span>
                                <span className="flex-1">{activity}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {timeSummary.length === 0 && !busy && (
          <div className="text-center py-16 bg-card border border-border rounded-lg shadow-sm">
            <div className="w-16 h-16 bg-primary-light rounded-full flex items-center justify-center mx-auto mb-4">
              <Clock className="w-8 h-8 text-primary" />
            </div>
            <p className="text-xl font-semibold text-foreground mb-2">No time tracked yet today</p>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              Your activity will appear here automatically as you work throughout the day.
            </p>
          </div>
        )}

        {busy && (
          <div className="text-center py-16">
            <RefreshCw className="w-8 h-8 text-primary animate-spin mx-auto mb-4" />
            <p className="text-muted-foreground">Loading your day...</p>
          </div>
        )}
      </div>
    </div>
  );
}