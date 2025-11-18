/**
 * DailyReview.tsx — Clean time summary view with categorization
 * - Shows organized time by client → category
 * - Simple, focused interface
 * - Excludes uncategorized, idle time, and unassigned client from billable totals
 * - Includes manual categorization tab for uncategorized blocks
 */

import { useEffect, useMemo, useState, useCallback } from "react";
import { Clock, User, RefreshCw, Edit3, BarChart3 } from "lucide-react";
import { Header } from "@/components/common/Header";
import { DESIGN_SYSTEM } from "@/lib/design-system";
import { FilterBar, ErrorBanner } from "@/components/timecard";
import { todayIso } from "@/lib/utils/date";
import { primeCsrf } from "@/lib/csrf";
import { useWhoAmI } from "@/lib/useWhoAmI";
import ManualCategorization from "@/components/ManualCategorization";

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

  // Tab state
  const [activeTab, setActiveTab] = useState<'summary' | 'categorize'>('summary');

  // Time summary state
  const [timeSummary, setTimeSummary] = useState<ClientTime[]>([]);
  
  // Uncategorized blocks count
  const [uncategorizedCount, setUncategorizedCount] = useState(0);

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

  // Fetch uncategorized count
  const loadUncategorizedCount = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/categorization/data/?date=${date}`, {
        credentials: 'include'
      });
      if (res.ok) {
        const data = await res.json();
        setUncategorizedCount(data.blocks?.length || 0);
      }
    } catch (err) {
      console.error('Failed to fetch uncategorized count:', err);
    }
  }, [date]);

  // Auto-load on mount and when date/user changes
  useEffect(() => {
    const t = setTimeout(() => {
      loadTimeSummary();
      loadUncategorizedCount();
    }, 200);
    return () => clearTimeout(t);
  }, [loadTimeSummary, loadUncategorizedCount]);

  // Auto-refresh every 5 minutes
  useEffect(() => {
    const interval = setInterval(() => {
      loadTimeSummary();
      loadUncategorizedCount();
    }, 5 * 60 * 1000);

    return () => clearInterval(interval);
  }, [loadTimeSummary, loadUncategorizedCount]);

  // Refresh handler that updates both summary and count
  const handleRefresh = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  // When categorization is complete, refresh and switch to summary
  const handleCategorizationComplete = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
    // Optionally switch back to summary tab
    // setActiveTab('summary');
  }, [loadTimeSummary, loadUncategorizedCount]);

  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : whoami?.trim() ? whoami : "All Users";
  }, [user, whoami]);

  // Filter logic: exclude idle, uncategorized categories and entire "Unassigned" client
  const isIdleCategory = (catName: string) => {
    const lower = catName.toLowerCase();
    return lower.includes('idle');
  };

  const isUncategorizedCategory = (catName: string) => {
    const lower = catName.toLowerCase();
    return lower.includes('uncategorized');
  };

  const isUnassignedClient = (clientName: string) => {
    return clientName.toLowerCase() === 'unassigned';
  };

  const isNonBillableCategory = (catName: string) => {
    return isIdleCategory(catName) || isUncategorizedCategory(catName);
  };

  // Calculate total hours excluding idle, uncategorized, and unassigned client
  const summaryTotalHours = timeSummary.reduce((sum, client) => {
    // Skip entire Unassigned client
    if (isUnassignedClient(client.client)) {
      return sum;
    }
    
    const clientBillableHours = client.categories
      .filter(cat => !isNonBillableCategory(cat.name))
      .reduce((catSum, cat) => catSum + cat.hours, 0);
    return sum + clientBillableHours;
  }, 0);

  // Helper to get client's billable hours (excluding idle and uncategorized)
  const getClientBillableHours = (client: ClientTime) => {
    return client.categories
      .filter(cat => !isNonBillableCategory(cat.name))
      .reduce((sum, cat) => sum + cat.hours, 0);
  };

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
        {/* Tab Navigation */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={() => setActiveTab('summary')}
            className={`flex items-center gap-2 px-6 py-3 rounded-lg font-semibold transition-all ${
              activeTab === 'summary'
                ? 'bg-primary text-primary-foreground shadow-md'
                : 'bg-card border border-border hover:bg-accent text-foreground'
            }`}
          >
            <BarChart3 className="w-5 h-5" />
            Time Summary
          </button>
          <button
            onClick={() => setActiveTab('categorize')}
            className={`flex items-center gap-2 px-6 py-3 rounded-lg font-semibold transition-all relative ${
              activeTab === 'categorize'
                ? 'bg-primary text-primary-foreground shadow-md'
                : 'bg-card border border-border hover:bg-accent text-foreground'
            }`}
          >
            <Edit3 className="w-5 h-5" />
            Categorize Blocks
            {uncategorizedCount > 0 && (
              <span className="absolute -top-2 -right-2 bg-yellow-500 text-white text-xs font-bold rounded-full w-6 h-6 flex items-center justify-center">
                {uncategorizedCount}
              </span>
            )}
          </button>
        </div>

        {/* Alert Banner for Uncategorized Blocks */}
        {activeTab === 'summary' && uncategorizedCount > 0 && (
          <div className="bg-yellow-50 border-2 border-yellow-300 rounded-lg p-4 mb-6 flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-3">
              <span className="text-3xl">⚠️</span>
              <div>
                <p className="font-semibold text-yellow-900 text-lg">
                  {uncategorizedCount} block{uncategorizedCount !== 1 ? 's' : ''} need{uncategorizedCount === 1 ? 's' : ''} categorization
                </p>
                <p className="text-sm text-yellow-700">
                  Categorize your time blocks to see accurate billable hours in the summary
                </p>
              </div>
            </div>
            <button
              onClick={() => setActiveTab('categorize')}
              className="px-6 py-2.5 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 font-semibold transition-colors shadow-sm hover:shadow-md"
            >
              Categorize Now →
            </button>
          </div>
        )}

        {/* Show active tab content */}
        {activeTab === 'summary' ? (
          <>
            {/* Controls */}
            <FilterBar
              date={date}
              user={user}
              whoami={whoami}
              onDateChange={setDate}
              onUserChange={setUser}
              onRefresh={handleRefresh}
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
                    <span className="text-sm text-muted-foreground">Billable: </span>
                    <span className="text-3xl font-bold text-primary">{summaryTotalHours.toFixed(2)}h</span>
                  </div>
                </div>
                
                <div className="space-y-6">
                  {timeSummary.map((client) => {
                    const billableHours = getClientBillableHours(client);
                    const isUnassigned = isUnassignedClient(client.client);
                    
                    return (
                      <div 
                        key={client.client_id || client.client} 
                        className={`border border-border rounded-lg overflow-hidden shadow-sm hover:shadow-md transition-shadow ${isUnassigned ? 'opacity-60' : ''}`}
                      >
                        {/* Client Header */}
                        <div className="bg-gradient-to-r from-primary/10 to-accent/10 px-6 py-4 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <h4 className={`font-semibold text-xl ${isUnassigned ? 'text-muted-foreground' : 'text-foreground'}`}>
                              {client.client}
                            </h4>
                            {isUnassigned && (
                              <span className="text-xs px-2 py-0.5 bg-muted rounded text-muted-foreground">
                                non-billable
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-3">
                            <span className={`text-2xl font-bold ${isUnassigned ? 'text-muted-foreground' : 'text-primary'}`}>
                              {isUnassigned ? client.total_hours.toFixed(2) : billableHours.toFixed(2)}h
                            </span>
                            {!isUnassigned && billableHours !== client.total_hours && (
                              <span className="text-sm text-muted-foreground">
                                ({client.total_hours.toFixed(2)}h total)
                              </span>
                            )}
                          </div>
                        </div>
                        
                        {/* Categories */}
                        <div className="divide-y divide-border bg-white">
                          {client.categories.map((cat) => {
                            const isNonBillable = isNonBillableCategory(cat.name);
                            
                            return (
                              <div 
                                key={cat.name} 
                                className={`px-6 py-4 hover:bg-accent/30 transition-colors ${isNonBillable ? 'opacity-60' : ''}`}
                              >
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    <span className={`font-medium text-lg ${isNonBillable ? 'text-muted-foreground' : 'text-foreground'}`}>
                                      {cat.name}
                                    </span>
                                    {isNonBillable && (
                                      <span className="text-xs px-2 py-0.5 bg-muted rounded text-muted-foreground">
                                        needs review
                                      </span>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-4">
                                    <span className="text-sm text-muted-foreground">
                                      {cat.block_count} {cat.block_count === 1 ? 'block' : 'blocks'}
                                    </span>
                                    <span className={`font-bold text-xl ${isNonBillable ? 'text-muted-foreground' : 'text-success'}`}>
                                      {cat.hours.toFixed(2)}h
                                    </span>
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
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
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
          </>
        ) : (
          /* Categorization Tab */
          <ManualCategorization onComplete={handleCategorizationComplete} />
        )}
      </div>
    </div>
  );
}