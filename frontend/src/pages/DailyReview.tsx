/**
 * DailyReview.tsx - Top toolbar layout
 * STRONGER FONTS - darker text, bolder weights
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
import { useSearchParams } from 'react-router-dom';
import { useCategories } from '@/hooks/useCategories';


const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;
const [nonBillableHours, setNonBillableHours] = useState(0);


type Category = { name: string; hours: number; block_count: number; sample_activities: string[]; };
type ClientTime = { client_id: number | null; client: string; total_hours: number; categories: Category[]; };
type ClientOption = { id: number; name: string; };
type ParsedActivity = { blockId: number | null; title: string; raw: string; };

// ADD THIS:
type TodayTimeResponse = {
  clients: ClientTime[];
  billable_hours: number;
  non_billable_hours: number;  // ✅ ADD
  global_hours: number;
  date: string;
};

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
  const { categories: dynamicCategories, industryType } = useCategories();
  

  const [editingBlock, setEditingBlock] = useState<{ blockId: number; activityKey: string; currentCategory: string; currentClientId: number | null; } | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [deletingBlockId, setDeletingBlockId] = useState<number | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [availableClients, setAvailableClients] = useState<ClientOption[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const [billableHours, setBillableHours] = useState(0);
  // Add these with your other useState declarations
  const [showManualEntry, setShowManualEntry] = useState(false);
  const [manualEntry, setManualEntry] = useState<{
    client_id: number | null;
    description: string;
    hours: number;
    date: string;
  }>({
    client_id: null,
    description: '',
    hours: 0,
    date: todayIso(),
  });

  const INTERNAL_CATEGORIES = [
  "Idle", "Personal/Non-Billable",
  "Administration", "Team Meetings", "Training/Professional Development",
  "Business Development/Sales", "Hiring/HR", "Company Planning",
  "Internal Projects", "Marketing (Own Firm)", "IT/Tech Support",
  "Finance/Accounting (Own Firm)", "PTO/Time Off", "Email/Communication",
];


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

  // Update loadTimeSummary (around line 111)
  const loadTimeSummary = useCallback(async () => {
    setBusy(true); setErr(null);
    try {
      const json = await safeFetchJson<TodayTimeResponse>(`${API_BASE}/today-time/?date=${date}`);
      setTimeSummary(json.clients || []);
      setBillableHours(json.billable_hours || 0);  // ADD THIS STATE
      setNonBillableHours(json.non_billable_hours || 0);  // ✅ ADD
    } catch (err: any) { setErr(err?.message || 'Failed to load'); setTimeSummary([]); }
    finally { setBusy(false); }
  }, [date]);



  const loadUncategorizedCount = useCallback(async () => {
    try {
      const data = await safeFetchJson<{blocks: any[]}>(`${API_BASE}/categorization/data/?date=${date}`);
      setUncategorizedCount(data.blocks?.length || 0);
    } catch {}
  }, [date]);


  const runAIClassification = useCallback(async () => {
    try {
      const response = await safeFetchJson<any[]>(`${API_BASE}/blocks/suggestions/`);
      if (Array.isArray(response)) {
        const autoSaved = response.filter(r => r.ai_suggestion?.auto_saved).length;
        if (autoSaved > 0) {
          console.log(`[AI] Auto-categorized ${autoSaved} blocks`);
          loadTimeSummary();
          loadUncategorizedCount();
        }
      }
    } catch (err) {
      console.warn('[AI] Classification skipped:', err);
    }
  }, [loadTimeSummary, loadUncategorizedCount]);

  useEffect(() => {
    const t = setTimeout(() => { 
      loadTimeSummary(); 
      loadUncategorizedCount(); 
      loadClients(); 
      // Categories now come from useCategories hook automatically
    }, 200);
    return () => clearTimeout(t);
  }, [loadTimeSummary, loadUncategorizedCount, loadClients]);

  // And update the interval useEffect to also run AI:
  useEffect(() => {
    const interval = setInterval(() => { 
      loadTimeSummary(); 
      loadUncategorizedCount();
      runAIClassification();  // <-- ADD THIS
    }, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [loadTimeSummary, loadUncategorizedCount, runAIClassification]);

  // Check for auto-open params on mount

  // Check for date param on mount (from notification deep link)
  useEffect(() => {
    const dateParam = searchParams.get('date');
    if (dateParam) {
      setDate(dateParam);
    }
  }, [searchParams]);

  // Check for auto-open params on mount
  useEffect(() => {
    const shouldAdd = searchParams.get('add') === 'true';
    const preSelectedClientId = searchParams.get('client_id');
    
    if (shouldAdd) {
      // Pre-fill the client if provided
      if (preSelectedClientId) {
        setManualEntry(prev => ({
          ...prev,
          client_id: parseInt(preSelectedClientId),
        }));
      }
      
      // Open the modal
      setShowManualEntry(true);
      
      // Clear the params so refresh doesn't re-open
      searchParams.delete('add');
      searchParams.delete('client_id');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleRefresh = useCallback(() => { loadTimeSummary(); loadUncategorizedCount(); }, [loadTimeSummary, loadUncategorizedCount]);
  const handleCategorizationComplete = useCallback(() => { loadTimeSummary(); loadUncategorizedCount(); }, [loadTimeSummary, loadUncategorizedCount]);

  const handleEditClick = (blockId: number, activityKey: string, currentCategory: string, currentClientId: number | null) => {
    setEditingBlock({ blockId, activityKey, currentCategory, currentClientId });
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
  const isPersonalCategory = (n: string) => n.toLowerCase().includes('personal');
  const isNonBillable = (n: string) => isIdleCategory(n) || isUncategorizedCategory(n) || isPersonalCategory(n);


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
                    'px-4 py-2 rounded-lg text-sm font-bold transition-all flex items-center gap-2',
                    activeTab === 'summary' ? 'bg-card text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                  )}
                >
                  <BarChart3 className="w-4 h-4" />
                  Summary
                </button>
                <button
                  onClick={() => setActiveTab('categorize')}
                  className={cn(
                    'px-4 py-2 rounded-lg text-sm font-bold transition-all flex items-center gap-2',
                    activeTab === 'categorize' ? 'bg-card text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
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
                className="px-3 py-2 rounded-lg bg-muted border-2 border-border text-sm font-semibold text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
              />
              <button
                onClick={handleRefresh}
                disabled={busy}
                className="p-2.5 text-slate-500 hover:text-slate-900 hover:bg-muted rounded-lg disabled:opacity-50 transition-all"
              >
                <RefreshCw className={cn('w-4 h-4', busy && 'animate-spin')} />
              </button>

            {/* ✅ REPLACE old billable pill with this */}
            <div className="flex items-center bg-muted border-2 border-border rounded-xl overflow-hidden divide-x-2 divide-border">
              <div className="px-4 py-2 flex items-center gap-1.5">
                <span className="text-xl font-extrabold text-primary">{billableHours.toFixed(2)}h</span>
                <span className="text-primary/70 font-semibold text-xs uppercase tracking-wide">billable</span>
              </div>
              <div className="px-4 py-2 flex items-center gap-1.5">
                <span className="text-xl font-extrabold text-slate-400">{nonBillableHours.toFixed(2)}h</span>
                <span className="text-slate-400 font-semibold text-xs uppercase tracking-wide">non-bill</span>
              </div>
              <div className="px-4 py-2 flex items-center gap-1.5">
                <span className="text-xl font-extrabold text-slate-700">
                  {(billableHours + nonBillableHours).toFixed(2)}h
                </span>
                <span className="text-slate-500 font-semibold text-xs uppercase tracking-wide">total</span>
              </div>
            </div>
          </div>

      {/* ===== CONTENT ===== */}
      <div className="p-6">
        {/* Alert */}
        {activeTab === 'summary' && uncategorizedCount > 0 && (
          <div className="mb-4 px-4 py-3 bg-warning/10 border-2 border-warning/30 rounded-xl flex items-center justify-between">
            <div className="flex items-center gap-2 text-amber-700 font-bold">
              <AlertTriangle className="w-5 h-5" />
              {uncategorizedCount} blocks need categorization
            </div>
            <button
              onClick={() => setActiveTab('categorize')}
              className="px-4 py-2 bg-warning text-warning-foreground font-bold rounded-lg hover:opacity-90 transition-all"
            >
              Categorize
            </button>
          </div>
        )}

        {err && (
          <div className="mb-4 px-4 py-3 bg-destructive/10 border-2 border-destructive/30 rounded-xl text-red-700 font-semibold">
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
                  className="text-sm text-slate-600 hover:text-slate-900 font-semibold px-3 py-1.5 rounded-lg hover:bg-muted transition-all"
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
                    ? { bg: 'bg-slate-100', border: 'border-slate-300', accent: 'bg-slate-200', text: 'text-slate-500', hours: 'text-slate-500' }
                    : getClientColor(clientIndex);
                  
                  return (
                    <div 
                      key={clientKey} 
                      className={cn(
                        'rounded-2xl border-2 overflow-hidden shadow-sm transition-all duration-200',
                        'hover:shadow-md hover:-translate-y-0.5',
                        colors.bg, colors.border,
                        isUnassigned && 'opacity-70'
                      )}
                    >
                      {/* Client Header */}
                      <button
                        onClick={() => toggleClient(clientKey)}
                        className={cn('w-full px-4 py-3 flex items-center justify-between', colors.accent)}
                      >
                        <div className="flex items-center gap-3">
                          <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center', isUnassigned ? 'bg-slate-300' : 'bg-white/70')}>
                            {isCollapsed ? <ChevronRight className={cn('w-4 h-4', colors.text)} /> : <ChevronDown className={cn('w-4 h-4', colors.text)} />}
                          </div>
                          <span className={cn('font-extrabold text-lg tracking-tight', isUnassigned ? 'text-slate-500' : 'text-slate-900')}>
                            {client.client}
                          </span>
                          <span className="text-sm text-slate-600 font-semibold">
                            {client.categories.length} {client.categories.length === 1 ? 'category' : 'categories'}
                          </span>
                        </div>
                        <span className={cn('text-2xl font-extrabold', colors.hours)}>
                          {(isUnassigned ? client.total_hours : billable).toFixed(2)}h
                        </span>
                      </button>
                      
                      {/* Categories */}
                      {!isCollapsed && (
                        <div className="bg-white">
                          {client.categories.map((cat) => {
                            const catNonBillable = isNonBillable(cat.name);
                            const catKey = `${client.client_id}-${cat.name}`;
                            const isExpanded = expandedCategories.has(catKey);
                            
                            return (
                              <div key={cat.name} className={cn('border-t border-slate-200', catNonBillable && 'opacity-50')}>
                                <div className="px-4 py-3 flex items-center justify-between">
                                  <div className="flex items-center gap-3 ml-10">
                                    <span className={cn('font-bold text-base', catNonBillable ? 'text-slate-500' : 'text-slate-800')}>
                                      {cat.name}
                                    </span>
                                    <span className="text-sm text-slate-500 font-semibold">({cat.sample_activities.length})</span>
                                  </div>
                                  <span className={cn('font-extrabold text-lg', catNonBillable ? 'text-slate-400' : 'text-emerald-600')}>
                                    {cat.hours.toFixed(2)}h
                                  </span>
                                </div>
                                
                                {cat.sample_activities.length > 0 && (
                                  <div className="px-4 pb-3 ml-10">
                                    {cat.sample_activities.length > 3 && (
                                      <button onClick={() => toggleCategory(catKey)} className="text-sm text-primary font-bold mb-2">
                                        {isExpanded ? '▼ Less' : `▶ All ${cat.sample_activities.length}`}
                                      </button>
                                    )}
                                    <ul className="space-y-2">
                                      {(isExpanded ? cat.sample_activities : cat.sample_activities.slice(0, 3)).map((activity, idx) => {
                                        const parsed = parseActivity(activity);
                                        const activityKey = `${client.client_id}-${cat.name}-${idx}`;
                                        const isEditing = editingBlock?.activityKey === activityKey;
                                        
                                        return (
                                          <li key={idx} className="flex items-center gap-2 group">
                                            <span className="text-slate-400 font-bold">→</span>
                                            {isEditing ? (
                                              <div className="flex items-center gap-2 flex-wrap">
                                                <select value={selectedClientId || ''} onChange={(e) => setSelectedClientId(e.target.value ? parseInt(e.target.value) : null)} className={DESIGN_SYSTEM.components.inputCompact}>
                                                  <option value="">Client</option>
                                                  {availableClients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                                </select>
                                                <select value={selectedCategory} onChange={(e) => setSelectedCategory(e.target.value)} className={DESIGN_SYSTEM.components.inputCompact}>
                                                  {(availableClients.find(c => c.id === selectedClientId)?.name === 'Internal'
                                                    ? INTERNAL_CATEGORIES
                                                    : dynamicCategories
                                                  ).map(n => <option key={n} value={n}>{n}</option>)}
                                                </select>
                                                <button onClick={handleSaveCategory} disabled={isUpdating} className="p-1.5 bg-success text-success-foreground rounded-lg"><Check className="w-4 h-4" /></button>
                                                <button onClick={handleCancelEdit} className="p-1.5 bg-muted rounded-lg"><X className="w-4 h-4" /></button>
                                              </div>
                                            ) : (
                                              <>
                                                <span className="text-slate-700 font-medium flex-1 truncate">{parsed.title}</span>
                                                {parsed.blockId && (
                                                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                    <button onClick={() => handleEditClick(parsed.blockId!, activityKey, cat.name, client.client_id)} className="p-1.5 hover:bg-primary/10 rounded-lg"><Pencil className="w-3.5 h-3.5 text-primary" /></button>
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
                <FileQuestion className="w-12 h-12 text-slate-400 mx-auto mb-3" />
                <h3 className="text-lg font-bold text-slate-800 mb-1">No time tracked yet</h3>
                <p className="text-slate-600 font-medium">Activity appears automatically as you work, or add time manually.</p>
              </div>
            ) : null}
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
              setManualEntry({ client_id: null, description: '', hours: 0, date: todayIso() });
            }}
            onSuccess={() => {
              setShowManualEntry(false);
              setManualEntry({ client_id: null, description: '', hours: 0, date: todayIso() });
              loadTimeSummary();
              showToast('Time entry added', 'success');
            }}
            defaultDate={date}
            preSelectedClientId={manualEntry.client_id}
          />
        )}

        </div>  // <-- Final closing div
  );
}