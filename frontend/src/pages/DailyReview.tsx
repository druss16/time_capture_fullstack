/**
 * DailyReview.tsx - Top toolbar layout
 * Quick daily task interface with prominent controls
 */

import { useEffect, useState, useCallback } from "react";
import { 
  RefreshCw, 
  Edit3, 
  BarChart3, 
  ChevronDown, 
  ChevronRight, 
  Pencil, 
  Check, 
  X, 
  Trash2,
  AlertTriangle,
  FileQuestion
} from "lucide-react";
import { todayIso } from "@/lib/utils/date";
import { primeCsrf } from "@/lib/csrf";
import { useWhoAmI } from "@/lib/useWhoAmI";
import ManualCategorization from "@/components/ManualCategorization";
import { safeFetchJson } from "@/lib/api";
import ManualTimeEntry from "@/components/ManualTimeEntry";
import { cn, getClientColor, SKELETON, DESIGN_SYSTEM } from "@/lib/design-system";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type Category = { name: string; hours: number; block_count: number; sample_activities: string[]; };
type ClientTime = { client_id: number | null; client: string; total_hours: number; categories: Category[]; };
type ClientOption = { id: number; name: string; };
type ParsedActivity = { blockId: number | null; title: string; raw: string; };

// Toast Component
const Toast = ({ message, type }: { message: string; type: 'success' | 'error' }) => (
  <div className={cn(
    'fixed top-20 right-4 z-50 px-4 py-3 rounded-xl shadow-xl',
    'flex items-center gap-2 text-white text-sm font-semibold animate-in slide-in-from-top-2',
    type === 'success' ? 'bg-success shadow-success/30' : 'bg-destructive shadow-destructive/30'
  )}>
    {type === 'success' ? <Check className="w-4 h-4" /> : <X className="w-4 h-4" />}
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
  const [activeTab, setActiveTab] = useState<'summary' | 'categorize'>('summary');
  const [timeSummary, setTimeSummary] = useState<ClientTime[]>([]);
  const [uncategorizedCount, setUncategorizedCount] = useState(0);
  const [collapsedClients, setCollapsedClients] = useState<Set<string>>(new Set());
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());

  const [editingBlock, setEditingBlock] = useState<{ blockId: number; currentCategory: string; currentClientId: number | null; } | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [deletingBlockId, setDeletingBlockId] = useState<number | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [availableClients, setAvailableClients] = useState<ClientOption[]>([]);

  useEffect(() => { if (!user && whoami) setUser(whoami); }, [whoami, user]);
  useEffect(() => { (async () => { try { await primeCsrf(API_BASE); } catch {} })(); }, []);

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const parseActivity = (activity: string): ParsedActivity => {
    const match = activity.match(/\[id:(\d+)\]\s*/);
    if (match) return { blockId: parseInt(match[1]), title: activity.replace(/\[id:\d+\]\s*/, '').trim(), raw: activity };
    return { blockId: null, title: activity, raw: activity };
  };

  const DEFAULT_CATEGORIES = [
    "Tax Preparation", "Tax Planning", "Tax Research", "Tax Compliance", "Idle",
    "Accounting/Bookkeeping", "Financial Statement Prep", "Audit/Assurance", "Payroll Services",
    "Advisory/Financial Planning", "Software Development", "Research/AI Assistance",
    "Email/Communication", "Meetings", "Administration", "Documentation", "Review",
  ];

  const loadCategories = useCallback(async () => {
    try {
      const data = await safeFetchJson<{ id: number; name: string }[]>(`${API_BASE}/options/task-types/`);
      setAvailableCategories(data?.length ? data.map(t => t.name) : DEFAULT_CATEGORIES);
    } catch { setAvailableCategories(DEFAULT_CATEGORIES); }
  }, []);

  const loadClients = useCallback(async () => {
    for (const url of [`${API_BASE}/options/clients/`, `${API_BASE}/clients/list`, `${API_BASE}/clients/list/`]) {
      try {
        const data = await safeFetchJson<ClientOption[]>(url);
        if (data?.length) { setAvailableClients(data); return; }
      } catch {}
    }
  }, []);

  useEffect(() => {
    if (availableClients.length === 0 && timeSummary.length > 0) {
      const clients = timeSummary.filter(c => c.client_id && c.client.toLowerCase() !== 'unassigned').map(c => ({ id: c.client_id!, name: c.client }));
      if (clients.length) setAvailableClients(clients);
    }
  }, [timeSummary, availableClients.length]);

  const loadTimeSummary = useCallback(async () => {
    setBusy(true); setErr(null);
    try {
      const json = await safeFetchJson<ClientTime[]>(`${API_BASE}/today-time/?date=${date}`);
      setTimeSummary(Array.isArray(json) ? json : []);
    } catch (err: any) { setErr(err?.message || 'Failed to load'); setTimeSummary([]); }
    finally { setBusy(false); }
  }, [date]);

  const loadUncategorizedCount = useCallback(async () => {
    try {
      const data = await safeFetchJson<{blocks: any[]}>(`${API_BASE}/categorization/data/?date=${date}`);
      setUncategorizedCount(data.blocks?.length || 0);
    } catch {}
  }, [date]);

  useEffect(() => {
    const t = setTimeout(() => { loadTimeSummary(); loadUncategorizedCount(); loadCategories(); loadClients(); }, 200);
    return () => clearTimeout(t);
  }, [loadTimeSummary, loadUncategorizedCount, loadCategories, loadClients]);

  useEffect(() => {
    const interval = setInterval(() => { loadTimeSummary(); loadUncategorizedCount(); }, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [loadTimeSummary, loadUncategorizedCount]);

  const handleRefresh = useCallback(() => { loadTimeSummary(); loadUncategorizedCount(); }, [loadTimeSummary, loadUncategorizedCount]);
  const handleCategorizationComplete = useCallback(() => { loadTimeSummary(); loadUncategorizedCount(); }, [loadTimeSummary, loadUncategorizedCount]);

  const handleEditClick = (blockId: number, currentCategory: string, currentClientId: number | null) => {
    setEditingBlock({ blockId, currentCategory, currentClientId });
    setSelectedCategory(currentCategory);
    setSelectedClientId(currentClientId);
  };

  const handleSaveCategory = async () => {
    if (!editingBlock) { setEditingBlock(null); return; }
    const categoryChanged = selectedCategory !== editingBlock.currentCategory;
    const clientChanged = selectedClientId !== editingBlock.currentClientId;
    if (!categoryChanged && !clientChanged) { setEditingBlock(null); return; }

    setIsUpdating(true);
    try {
      const payload: Record<string, any> = { category: selectedCategory };
      if (clientChanged && selectedClientId) payload.client_id = selectedClientId;
      await safeFetchJson(`${API_BASE}/blocks/${editingBlock.blockId}/recategorize/`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      showToast('Updated successfully', 'success');
      setEditingBlock(null); setSelectedClientId(null); setSelectedCategory("");
      await loadTimeSummary();
    } catch (err: any) { showToast(err?.message || 'Update failed', 'error'); }
    finally { setIsUpdating(false); }
  };

  const handleCancelEdit = () => { setEditingBlock(null); setSelectedCategory(""); setSelectedClientId(null); };

  const handleDeleteBlock = async (blockId: number, title: string) => {
    if (!confirm(`Delete "${title}"?`)) return;
    setDeletingBlockId(blockId);
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/delete/`, { method: 'DELETE' });
      showToast('Deleted successfully', 'success');
      await loadTimeSummary();
    } catch (err: any) { showToast(err?.message || 'Delete failed', 'error'); }
    finally { setDeletingBlockId(null); }
  };

  const isIdleCategory = (n: string) => n.toLowerCase().includes('idle');
  const isUncategorizedCategory = (n: string) => n.toLowerCase().includes('uncategorized');
  const isUnassignedClient = (n: string) => n.toLowerCase() === 'unassigned';
  const isNonBillable = (n: string) => isIdleCategory(n) || isUncategorizedCategory(n);

  const summaryTotalHours = timeSummary.reduce((sum, client) => {
    if (isUnassignedClient(client.client)) return sum;
    return sum + client.categories.filter(cat => !isNonBillable(cat.name)).reduce((s, cat) => s + cat.hours, 0);
  }, 0);

  const getClientBillableHours = (client: ClientTime) => 
    client.categories.filter(cat => !isNonBillable(cat.name)).reduce((sum, cat) => sum + cat.hours, 0);

  const toggleClient = (key: string) => setCollapsedClients(prev => {
    const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s;
  });

  const toggleCategory = (key: string) => setExpandedCategories(prev => {
    const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s;
  });

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
                  onClick={() => setActiveTab('summary')}
                  className={cn(
                    'px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2',
                    activeTab === 'summary' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <BarChart3 className="w-4 h-4" />
                  Summary
                </button>
                <button
                  onClick={() => setActiveTab('categorize')}
                  className={cn(
                    'px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2',
                    activeTab === 'categorize' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
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

            {/* Right: Date + Refresh + Billable */}
            <div className="flex items-center gap-3">
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className={cn(DESIGN_SYSTEM.components.inputCompact, 'w-auto')}
              />
              <button
                onClick={handleRefresh}
                disabled={busy}
                className="p-2.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg disabled:opacity-50 transition-all"
              >
                <RefreshCw className={cn('w-4 h-4', busy && 'animate-spin')} />
              </button>
              
              {/* Billable Total */}
              <div className="px-4 py-2 bg-primary/10 border-2 border-primary/20 rounded-xl">
                <span className="text-xl font-bold text-primary">{summaryTotalHours.toFixed(2)}h</span>
                <span className="text-primary/60 text-sm ml-1.5">billable</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ===== CONTENT ===== */}
      <div className="p-6">
        {/* Alert */}
        {activeTab === 'summary' && uncategorizedCount > 0 && (
          <div className="mb-4 px-4 py-3 bg-warning/10 border-2 border-warning/30 rounded-xl flex items-center justify-between">
            <div className="flex items-center gap-2 text-warning font-semibold">
              <AlertTriangle className="w-5 h-5" />
              {uncategorizedCount} blocks need categorization
            </div>
            <button
              onClick={() => setActiveTab('categorize')}
              className="px-4 py-2 bg-warning text-warning-foreground font-semibold rounded-lg hover:opacity-90 transition-all"
            >
              Categorize
            </button>
          </div>
        )}

        {err && (
          <div className="mb-4 px-4 py-3 bg-destructive/10 border-2 border-destructive/30 rounded-xl text-destructive font-medium">
            {err}
          </div>
        )}

        {activeTab === 'summary' ? (
          <>
            {/* Collapse toggle */}
            {timeSummary.length > 1 && (
              <div className="mb-3 flex justify-end">
                <button
                  onClick={() => {
                    if (collapsedClients.size === 0) {
                      setCollapsedClients(new Set(timeSummary.map(c => `${c.client_id}-${c.client}`)));
                    } else {
                      setCollapsedClients(new Set());
                    }
                  }}
                  className="text-sm text-muted-foreground hover:text-foreground font-medium px-3 py-1.5 rounded-lg hover:bg-muted transition-all"
                >
                  {collapsedClients.size === 0 ? 'Collapse All' : 'Expand All'}
                </button>
              </div>
            )}

            {/* Client Cards */}
            {busy && timeSummary.length === 0 ? (
              <div className="space-y-3">
                {[1, 2, 3].map(i => (
                  <div key={i} className={cn(SKELETON.card, 'h-32')} />
                ))}
              </div>
            ) : timeSummary.length > 0 ? (
              <div className="space-y-3">
                {timeSummary.map((client, clientIndex) => {
                  const billable = getClientBillableHours(client);
                  const isUnassigned = isUnassignedClient(client.client);
                  const clientKey = `${client.client_id}-${client.client}`;
                  const isCollapsed = collapsedClients.has(clientKey);
                  const colors = isUnassigned 
                    ? { bg: 'bg-muted/50', border: 'border-border', accent: 'bg-muted', text: 'text-muted-foreground', hours: 'text-muted-foreground' }
                    : getClientColor(clientIndex);
                  
                  return (
                    <div 
                      key={clientKey} 
                      className={cn(
                        'rounded-2xl border-2 overflow-hidden shadow-sm transition-all duration-200',
                        'hover:shadow-md hover:-translate-y-0.5',
                        colors.bg, colors.border,
                        isUnassigned && 'opacity-60'
                      )}
                    >
                      {/* Client Header */}
                      <button
                        onClick={() => toggleClient(clientKey)}
                        className={cn('w-full px-4 py-3 flex items-center justify-between', colors.accent)}
                      >
                        <div className="flex items-center gap-3">
                          <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center', isUnassigned ? 'bg-muted' : 'bg-white/60')}>
                            {isCollapsed ? <ChevronRight className={cn('w-4 h-4', colors.text)} /> : <ChevronDown className={cn('w-4 h-4', colors.text)} />}
                          </div>
                          <span className={cn('font-bold tracking-tight', isUnassigned ? 'text-muted-foreground' : 'text-foreground')}>
                            {client.client}
                          </span>
                          <span className="text-sm text-muted-foreground">
                            {client.categories.length} {client.categories.length === 1 ? 'category' : 'categories'}
                          </span>
                        </div>
                        <span className={cn('text-2xl font-bold', colors.hours)}>
                          {(isUnassigned ? client.total_hours : billable).toFixed(2)}h
                        </span>
                      </button>
                      
                      {/* Categories */}
                      {!isCollapsed && (
                        <div className="bg-card">
                          {client.categories.map((cat) => {
                            const catNonBillable = isNonBillable(cat.name);
                            const catKey = `${client.client_id}-${cat.name}`;
                            const isExpanded = expandedCategories.has(catKey);
                            
                            return (
                              <div key={cat.name} className={cn('border-t border-border', catNonBillable && 'opacity-50')}>
                                <div className="px-4 py-3 flex items-center justify-between">
                                  <div className="flex items-center gap-3 ml-10">
                                    <span className={cn('font-semibold', catNonBillable ? 'text-muted-foreground' : 'text-foreground')}>
                                      {cat.name}
                                    </span>
                                    <span className="text-sm text-muted-foreground">({cat.sample_activities.length})</span>
                                  </div>
                                  <span className={cn('font-bold text-lg', catNonBillable ? 'text-muted-foreground' : 'text-success')}>
                                    {cat.hours.toFixed(2)}h
                                  </span>
                                </div>
                                
                                {cat.sample_activities.length > 0 && (
                                  <div className="px-4 pb-3 ml-10">
                                    {cat.sample_activities.length > 3 && (
                                      <button onClick={() => toggleCategory(catKey)} className="text-xs text-primary font-semibold mb-2">
                                        {isExpanded ? '▼ Less' : `▶ All ${cat.sample_activities.length}`}
                                      </button>
                                    )}
                                    <ul className="space-y-1.5">
                                      {(isExpanded ? cat.sample_activities : cat.sample_activities.slice(0, 3)).map((activity, idx) => {
                                        const parsed = parseActivity(activity);
                                        const isEditing = editingBlock?.blockId === parsed.blockId;
                                        
                                        return (
                                          <li key={idx} className="flex items-center gap-2 group">
                                            <span className="text-muted-foreground/50">→</span>
                                            {isEditing ? (
                                              <div className="flex items-center gap-2 flex-wrap">
                                                <select value={selectedClientId || ''} onChange={(e) => setSelectedClientId(e.target.value ? parseInt(e.target.value) : null)} className={DESIGN_SYSTEM.components.inputCompact}>
                                                  <option value="">Client</option>
                                                  {availableClients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                                </select>
                                                <select value={selectedCategory} onChange={(e) => setSelectedCategory(e.target.value)} className={DESIGN_SYSTEM.components.inputCompact}>
                                                  {availableCategories.map(n => <option key={n} value={n}>{n}</option>)}
                                                </select>
                                                <button onClick={handleSaveCategory} disabled={isUpdating} className="p-1.5 bg-success text-success-foreground rounded-lg"><Check className="w-4 h-4" /></button>
                                                <button onClick={handleCancelEdit} className="p-1.5 bg-muted rounded-lg"><X className="w-4 h-4" /></button>
                                              </div>
                                            ) : (
                                              <>
                                                <span className="text-foreground flex-1 truncate">{parsed.title}</span>
                                                {parsed.blockId && (
                                                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                    <button onClick={() => handleEditClick(parsed.blockId!, cat.name, client.client_id)} className="p-1.5 hover:bg-primary/10 rounded-lg"><Pencil className="w-3.5 h-3.5 text-primary" /></button>
                                                    <button onClick={() => handleDeleteBlock(parsed.blockId!, parsed.title)} disabled={deletingBlockId === parsed.blockId} className="p-1.5 hover:bg-destructive/10 rounded-lg"><Trash2 className="w-3.5 h-3.5 text-destructive" /></button>
                                                  </div>
                                                )}
                                              </>
                                            )}
                                          </li>
                                        );
                                      })}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : !busy ? (
              <div className="text-center py-16 bg-card rounded-2xl border-2 border-border">
                <FileQuestion className="w-12 h-12 text-muted-foreground mx-auto mb-3" />
                <h3 className="text-lg font-semibold text-foreground mb-1">No time tracked yet</h3>
                <p className="text-muted-foreground">Activity appears automatically as you work, or add time manually.</p>
              </div>
            ) : null}
          </>
        ) : (
          <ManualCategorization onComplete={handleCategorizationComplete} />
        )}
      </div>
    </div>
  );
}