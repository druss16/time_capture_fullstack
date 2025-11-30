/**
 * DailyReview.tsx — Clean time summary view with categorization
 * - Shows organized time by client → category
 * - CLICK TO EDIT: Click pencil icon to change client AND/OR category
 * - Excludes uncategorized, idle time, and unassigned client from billable totals
 * - Includes manual categorization tab for uncategorized blocks
 */

import { useEffect, useMemo, useState, useCallback } from "react";
import { Clock, User, RefreshCw, Edit3, BarChart3, ChevronDown, ChevronRight, Pencil, Check, X } from "lucide-react";
import { Header } from "@/components/common/Header";
import { DESIGN_SYSTEM } from "@/lib/design-system";
import { FilterBar, ErrorBanner } from "@/components/timecard";
import { todayIso } from "@/lib/utils/date";
import { primeCsrf } from "@/lib/csrf";
import { useWhoAmI } from "@/lib/useWhoAmI";
import ManualCategorization from "@/components/ManualCategorization";
import { safeFetchJson } from "@/lib/api";
import ManualTimeEntry from "@/components/ManualTimeEntry";

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

type ClientOption = {
  id: number;
  name: string;
};

// Parsed activity with block ID
type ParsedActivity = {
  blockId: number | null;
  title: string;
  raw: string;
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

  // Track which clients are collapsed (default all expanded)
  const [collapsedClients, setCollapsedClients] = useState<Set<string>>(new Set());

  // Edit state
  const [editingBlock, setEditingBlock] = useState<{
    blockId: number; 
    currentCategory: string;
    currentClientId: number | null;
  } | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);

  // Toast notification state
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  // Available categories - start with defaults
  const [availableCategories, setAvailableCategories] = useState<string[]>([
    'Tax Preparation',
    'Audit/Assurance',
    'Bookkeeping',
    'Advisory/Consulting',
    'Research/AI Assistance',
    'Email/Communication',
    'Admin/Internal',
    'Software Development',
    'Meeting/Call',
    'Training',
  ]);

  // Available clients
  const [availableClients, setAvailableClients] = useState<ClientOption[]>([]);

  useEffect(() => {
    if (!user && whoami) setUser(whoami);
  }, [whoami, user]);

  useEffect(() => {
    (async () => { try { await primeCsrf(API_BASE); } catch {} })();
  }, []);

  // Show toast notification
  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Parse activity string to extract block ID
  const parseActivity = (activity: string): ParsedActivity => {
    const match = activity.match(/\[id:(\d+)\]\s*/);
    if (match) {
      return {
        blockId: parseInt(match[1]),
        title: activity.replace(/\[id:\d+\]\s*/, '').trim(),
        raw: activity
      };
    }
    return { blockId: null, title: activity, raw: activity };
  };

  // Default categories for CPA firms
  const DEFAULT_CATEGORIES = [
    'Tax Preparation',
    'Audit/Assurance',
    'Bookkeeping',
    'Advisory/Consulting',
    'Research/AI Assistance',
    'Email/Communication',
    'Admin/Internal',
    'Software Development',
    'Meeting/Call',
    'Training',
  ];

  // Load available categories (task types)
  const loadCategories = useCallback(async () => {
    try {
      const data = await safeFetchJson<{ id: number; name: string }[]>(`${API_BASE}/options/task-types/`);
      if (data && Array.isArray(data) && data.length > 0) {
        setAvailableCategories(data.map(t => t.name));
      } else {
        setAvailableCategories(DEFAULT_CATEGORIES);
      }
    } catch (err) {
      console.error('Failed to load categories:', err);
      setAvailableCategories(DEFAULT_CATEGORIES);
    }
  }, []);

  // Load available clients - try multiple endpoints with fallback
  const loadClients = useCallback(async () => {
    // Try options/clients/ endpoint first (from urls.py)
    try {
      const data = await safeFetchJson<ClientOption[]>(`${API_BASE}/options/clients/`);
      if (data && Array.isArray(data) && data.length > 0) {
        setAvailableClients(data);
        console.log('Loaded clients from /options/clients/', data);
        return;
      }
    } catch (err) {
      console.warn('Failed to load from /options/clients/', err);
    }
    
    // Try clients/list endpoint (no trailing slash - from urls.py)
    try {
      const data = await safeFetchJson<ClientOption[]>(`${API_BASE}/clients/list`);
      if (data && Array.isArray(data) && data.length > 0) {
        setAvailableClients(data);
        console.log('Loaded clients from /clients/list', data);
        return;
      }
    } catch (err) {
      console.warn('Failed to load from /clients/list', err);
    }
    
    // Try with trailing slash just in case
    try {
      const data = await safeFetchJson<ClientOption[]>(`${API_BASE}/clients/list/`);
      if (data && Array.isArray(data) && data.length > 0) {
        setAvailableClients(data);
        console.log('Loaded clients from /clients/list/', data);
        return;
      }
    } catch (err) {
      console.warn('Failed to load from /clients/list/', err);
    }
  }, []);
  
  // Fallback: Extract clients from time summary when it loads
  useEffect(() => {
    if (availableClients.length === 0 && timeSummary.length > 0) {
      const clientsFromSummary = timeSummary
        .filter(c => c.client_id && c.client.toLowerCase() !== 'unassigned')
        .map(c => ({ id: c.client_id!, name: c.client }));
      
      if (clientsFromSummary.length > 0) {
        setAvailableClients(clientsFromSummary);
      }
    }
  }, [timeSummary, availableClients.length]);

  // Load time summary
  const loadTimeSummary = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const json = await safeFetchJson<ClientTime[]>(`${API_BASE}/today-time/?date=${date}`);
      setTimeSummary(Array.isArray(json) ? json : []);
    } catch (err: any) {
      console.error('Failed to load time summary:', err);
      setErr(err?.message || 'Failed to load time summary');
      setTimeSummary([]);
    } finally {
      setBusy(false);
    }
  }, [date]);

  // Load uncategorized count
  const loadUncategorizedCount = useCallback(async () => {
    try {
      const data = await safeFetchJson<{blocks: any[]}>(`${API_BASE}/categorization/data/?date=${date}`);
      setUncategorizedCount(data.blocks?.length || 0);
    } catch (err) {
      console.error('Failed to fetch uncategorized count:', err);
    }
  }, [date]);

  // Auto-load on mount
  useEffect(() => {
    const t = setTimeout(() => {
      loadTimeSummary();
      loadUncategorizedCount();
      loadCategories();
      loadClients();
    }, 200);
    return () => clearTimeout(t);
  }, [loadTimeSummary, loadUncategorizedCount, loadCategories, loadClients]);

  // Auto-refresh every 2 minutes
  useEffect(() => {
    const interval = setInterval(() => {
      loadTimeSummary();
      loadUncategorizedCount();
    }, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [loadTimeSummary, loadUncategorizedCount]);

  // Refresh handler
  const handleRefresh = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  // When categorization is complete
  const handleCategorizationComplete = useCallback(() => {
    loadTimeSummary();
    loadUncategorizedCount();
  }, [loadTimeSummary, loadUncategorizedCount]);

  // Handle edit click - now includes client ID
  const handleEditClick = (blockId: number, currentCategory: string, currentClientId: number | null) => {
    setEditingBlock({ blockId, currentCategory, currentClientId });
    setSelectedCategory(currentCategory);
    setSelectedClientId(currentClientId);
  };

  // Handle save - both category and client
  const handleSaveCategory = async () => {
    if (!editingBlock) {
      setEditingBlock(null);
      return;
    }

    // Check if anything changed
    const categoryChanged = selectedCategory !== editingBlock.currentCategory;
    const clientChanged = selectedClientId !== editingBlock.currentClientId;
    
    if (!categoryChanged && !clientChanged) {
      setEditingBlock(null);
      return;
    }

    setIsUpdating(true);
    try {
      const payload: Record<string, any> = {};
      
      // Always include category
      payload.category = selectedCategory;
      
      // Include client_id if changed
      if (clientChanged && selectedClientId) {
        payload.client_id = selectedClientId;
      }
      
      await safeFetchJson(`${API_BASE}/blocks/${editingBlock.blockId}/recategorize/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      
      // Build success message
      const changes: string[] = [];
      if (clientChanged && selectedClientId) {
        const newClient = availableClients.find(c => c.id === selectedClientId);
        changes.push(`Client: ${newClient?.name || 'Updated'}`);
      }
      if (categoryChanged) {
        changes.push(`Category: ${selectedCategory}`);
      }
      
      showToast(changes.join(' • ') || 'Updated successfully', 'success');
      setEditingBlock(null);
      setSelectedClientId(null);
      setSelectedCategory("");
      await loadTimeSummary();
    } catch (err: any) {
      console.error('Failed to recategorize:', err);
      showToast(err?.message || 'Failed to update', 'error');
    } finally {
      setIsUpdating(false);
    }
  };

  // Cancel edit
  const handleCancelEdit = () => {
    setEditingBlock(null);
    setSelectedCategory("");
    setSelectedClientId(null);
  };

  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : whoami?.trim() ? whoami : "All Users";
  }, [user, whoami]);

  // Filter logic
  const isIdleCategory = (catName: string) => catName.toLowerCase().includes('idle');
  const isUncategorizedCategory = (catName: string) => catName.toLowerCase().includes('uncategorized');
  const isUnassignedClient = (clientName: string) => clientName.toLowerCase() === 'unassigned';
  const isNonBillableCategory = (catName: string) => isIdleCategory(catName) || isUncategorizedCategory(catName);

  // Calculate total hours
  const summaryTotalHours = timeSummary.reduce((sum, client) => {
    if (isUnassignedClient(client.client)) return sum;
    const clientBillableHours = client.categories
      .filter(cat => !isNonBillableCategory(cat.name))
      .reduce((catSum, cat) => catSum + cat.hours, 0);
    return sum + clientBillableHours;
  }, 0);

  const getClientBillableHours = (client: ClientTime) => {
    return client.categories
      .filter(cat => !isNonBillableCategory(cat.name))
      .reduce((sum, cat) => sum + cat.hours, 0);
  };

  const toggleClientCollapse = (clientKey: string) => {
    setCollapsedClients(prev => {
      const newSet = new Set(prev);
      if (newSet.has(clientKey)) newSet.delete(clientKey);
      else newSet.add(clientKey);
      return newSet;
    });
  };

  return (
    <div className="min-h-screen bg-background">
      <Header
        title="Daily Review"
        subtitle="Clean, organized summary of your day"
        icon={<Clock className="w-6 h-6 text-primary-foreground" />}
        rightContent={
          headerUser && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gradient-to-r from-primary/20 to-accent/20 border border-primary/30 text-sm hover:border-primary/50 transition-all">
              <User className="w-3.5 h-3.5 text-primary" />
              <span className="font-semibold text-primary">{headerUser}</span>
            </div>
          )
        }
      />

      {/* Toast Notification */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 animate-in slide-in-from-right ${
          toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
        }`}>
          {toast.type === 'success' ? <Check className="w-4 h-4" /> : <X className="w-4 h-4" />}
          <span className="text-sm font-medium">{toast.message}</span>
        </div>
      )}

      <div className={DESIGN_SYSTEM.spacing.container + " py-4"}>
        {/* Tab Navigation */}
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setActiveTab('summary')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-all ${
              activeTab === 'summary'
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'bg-card border border-border hover:bg-accent text-foreground'
            }`}
          >
            <BarChart3 className="w-4 h-4" />
            Time Summary
          </button>
          <button
            onClick={() => setActiveTab('categorize')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-all relative ${
              activeTab === 'categorize'
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'bg-card border border-border hover:bg-accent text-foreground'
            }`}
          >
            <Edit3 className="w-4 h-4" />
            Categorize Blocks
            {uncategorizedCount > 0 && (
              <span className="absolute -top-1 -right-1 bg-yellow-500 text-white text-xs font-bold rounded-full min-w-[20px] h-5 px-1 flex items-center justify-center">
                {uncategorizedCount}
              </span>
            )}
          </button>
        </div>

        {/* Alert Banner for Uncategorized Blocks */}
        {activeTab === 'summary' && uncategorizedCount > 0 && (
          <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-3 mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xl">⚠️</span>
              <div>
                <p className="font-semibold text-yellow-900 text-sm">
                  {uncategorizedCount} block{uncategorizedCount !== 1 ? 's' : ''} need{uncategorizedCount === 1 ? 's' : ''} categorization
                </p>
                <p className="text-xs text-yellow-700">Categorize to see accurate billable hours</p>
              </div>
            </div>
            <button
              onClick={() => setActiveTab('categorize')}
              className="px-4 py-1.5 bg-yellow-600 text-white rounded text-sm hover:bg-yellow-700 font-medium transition-colors"
            >
              Categorize →
            </button>
          </div>
        )}

        {activeTab === 'summary' ? (
          <>
            <FilterBar
              date={date}
              user={user}
              whoami={whoami}
              onDateChange={setDate}
              onUserChange={setUser}
              onRefresh={handleRefresh}
              onDraft={undefined as any}
              onSubmit={undefined as any}
              isLoading={busy || isUpdating}
            />

            {err && <ErrorBanner message={err} />}

            {/* Time Summary Section */}
            {timeSummary.length > 0 && (
              <div className="bg-card border border-border rounded-lg p-4 shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold flex items-center gap-2">
                    <Clock className="w-5 h-5 text-primary" />
                    Today's Summary
                  </h3>
                  <div className="flex items-center gap-3">
                    {/* Manual Time Entry Button */}
                    <ManualTimeEntry 
                      defaultDate={date} 
                      onSuccess={handleRefresh} 
                    />
                    
                    {timeSummary.length > 1 && (
                      <button
                        onClick={() => {
                          if (collapsedClients.size === 0) {
                            setCollapsedClients(new Set(timeSummary.map(c => `${c.client_id || 'null'}-${c.client}`)));
                          } else {
                            setCollapsedClients(new Set());
                          }
                        }}
                        className="text-xs px-3 py-1.5 border border-border rounded hover:bg-accent transition-colors font-medium"
                      >
                        {collapsedClients.size === 0 ? 'Collapse All' : 'Expand All'}
                      </button>
                    )}
                    <div className="px-4 py-2 bg-gradient-to-r from-primary/20 to-accent/20 rounded-lg border border-primary/30">
                      <span className="text-xs text-muted-foreground">Billable: </span>
                      <span className="text-2xl font-bold text-primary">{summaryTotalHours.toFixed(2)}h</span>
                    </div>
                  </div>
                </div>
                
                <div className="space-y-3">
                  {timeSummary.map((client) => {
                    const billableHours = getClientBillableHours(client);
                    const isUnassigned = isUnassignedClient(client.client);
                    const clientKey = `${client.client_id || 'null'}-${client.client}`;
                    const isCollapsed = collapsedClients.has(clientKey);
                    
                    return (
                      <div 
                        key={client.client_id || client.client} 
                        className={`border border-border rounded-lg overflow-hidden shadow-sm hover:shadow transition-shadow ${isUnassigned ? 'opacity-60' : ''}`}
                      >
                        {/* Client Header */}
                        <button
                          onClick={() => toggleClientCollapse(clientKey)}
                          className="w-full bg-gradient-to-r from-primary/10 to-accent/10 px-4 py-2.5 flex items-center justify-between hover:from-primary/15 hover:to-accent/15 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            {isCollapsed ? (
                              <ChevronRight className="w-4 h-4 text-primary" />
                            ) : (
                              <ChevronDown className="w-4 h-4 text-primary" />
                            )}
                            <h4 className={`font-semibold text-base ${isUnassigned ? 'text-muted-foreground' : 'text-foreground'}`}>
                              {client.client}
                            </h4>
                            {isUnassigned && (
                              <span className="text-xs px-1.5 py-0.5 bg-muted rounded text-muted-foreground">non-billable</span>
                            )}
                            <span className="text-xs text-muted-foreground ml-2">
                              {client.categories.length} {client.categories.length === 1 ? 'category' : 'categories'}
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className={`text-xl font-bold ${isUnassigned ? 'text-muted-foreground' : 'text-primary'}`}>
                              {isUnassigned ? client.total_hours.toFixed(2) : billableHours.toFixed(2)}h
                            </span>
                            {!isUnassigned && billableHours !== client.total_hours && (
                              <span className="text-xs text-muted-foreground">({client.total_hours.toFixed(2)}h total)</span>
                            )}
                          </div>
                        </button>
                        
                        {/* Categories */}
                        {!isCollapsed && (
                          <div className="divide-y divide-border bg-white">
                            {client.categories.map((cat) => {
                              const isNonBillable = isNonBillableCategory(cat.name);
                              
                              return (
                                <div 
                                  key={cat.name} 
                                  className={`px-4 py-2.5 hover:bg-accent/30 transition-colors ${isNonBillable ? 'opacity-60' : ''}`}
                                >
                                  <div className="flex items-center justify-between mb-1.5">
                                    <div className="flex items-center gap-2">
                                      <span className={`font-medium text-sm ${isNonBillable ? 'text-muted-foreground' : 'text-foreground'}`}>
                                        {cat.name}
                                      </span>
                                      {isNonBillable && (
                                        <span className="text-xs px-1.5 py-0.5 bg-muted rounded text-muted-foreground">needs review</span>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-3">
                                      <span className="text-xs text-muted-foreground">
                                        {cat.block_count} {cat.block_count === 1 ? 'block' : 'blocks'}
                                      </span>
                                      <span className={`font-bold text-base ${isNonBillable ? 'text-muted-foreground' : 'text-success'}`}>
                                        {cat.hours.toFixed(2)}h
                                      </span>
                                    </div>
                                  </div>
                                  
                                  {/* Activities with edit buttons */}
                                  {cat.sample_activities && cat.sample_activities.length > 0 && (
                                    <ul className="mt-2 ml-1 space-y-1.5">
                                      {cat.sample_activities.map((activity, idx) => {
                                        const parsed = parseActivity(activity);
                                        const isEditing = editingBlock?.blockId === parsed.blockId;
                                        
                                        return (
                                          <li key={idx} className="text-xs text-muted-foreground flex items-center gap-1.5 group">
                                            <span className="text-muted-foreground/50">→</span>
                                            
                                            {isEditing ? (
                                              // Edit mode - Client + Category dropdowns
                                              <div className="flex items-center gap-2 flex-1 flex-wrap py-1">
                                                {/* Client Dropdown */}
                                                <select
                                                  value={selectedClientId || ''}
                                                  onChange={(e) => setSelectedClientId(e.target.value ? parseInt(e.target.value) : null)}
                                                  className="text-xs border border-blue-400 rounded px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-500 min-w-[120px]"
                                                >
                                                  <option value="">— Client —</option>
                                                  {availableClients.map(c => (
                                                    <option key={c.id} value={c.id}>{c.name}</option>
                                                  ))}
                                                </select>
                                                
                                                {/* Category Dropdown */}
                                                <select
                                                  value={selectedCategory}
                                                  onChange={(e) => setSelectedCategory(e.target.value)}
                                                  className="text-xs border border-primary rounded px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-primary min-w-[140px]"
                                                >
                                                  {availableCategories.map(catName => (
                                                    <option key={catName} value={catName}>{catName}</option>
                                                  ))}
                                                </select>
                                                
                                                {/* Save button */}
                                                <button
                                                  onClick={handleSaveCategory}
                                                  disabled={isUpdating}
                                                  className="p-1.5 bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50 transition-colors"
                                                  title="Save changes"
                                                >
                                                  <Check className="w-3.5 h-3.5" />
                                                </button>
                                                
                                                {/* Cancel button */}
                                                <button
                                                  onClick={handleCancelEdit}
                                                  className="p-1.5 bg-gray-400 text-white rounded hover:bg-gray-500 transition-colors"
                                                  title="Cancel"
                                                >
                                                  <X className="w-3.5 h-3.5" />
                                                </button>
                                              </div>
                                            ) : (
                                              // Display mode
                                              <>
                                                <span className="flex-1">{parsed.title}</span>
                                                {parsed.blockId && (
                                                  <button
                                                    onClick={() => handleEditClick(parsed.blockId!, cat.name, client.client_id)}
                                                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-primary/10 rounded transition-opacity"
                                                    title="Edit client/category"
                                                  >
                                                    <Pencil className="w-3 h-3 text-primary" />
                                                  </button>
                                                )}
                                              </>
                                            )}
                                          </li>
                                        );
                                      })}
                                    </ul>
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
              </div>
            )}

            {timeSummary.length === 0 && !busy && (
              <div className="text-center py-12 bg-card border border-border rounded-lg shadow-sm">
                <div className="w-12 h-12 bg-primary-light rounded-full flex items-center justify-center mx-auto mb-3">
                  <Clock className="w-6 h-6 text-primary" />
                </div>
                <p className="text-base font-semibold text-foreground mb-1">No time tracked yet today</p>
                <p className="text-sm text-muted-foreground max-w-md mx-auto">
                  Your activity will appear here automatically as you work throughout the day.
                </p>
              </div>
            )}

            {busy && (
              <div className="text-center py-12">
                <RefreshCw className="w-6 h-6 text-primary animate-spin mx-auto mb-3" />
                <p className="text-sm text-muted-foreground">Loading your day...</p>
              </div>
            )}
          </>
        ) : (
          <ManualCategorization onComplete={handleCategorizationComplete} />
        )}
      </div>
    </div>
  );
}