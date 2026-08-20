// src/pages/settings/TaskTypeSetsTab.tsx
// Manage bundled TaskTypeSets — left sidebar of sets, right editor with members.

import { useEffect, useState } from 'react';
import {
  Layers, Plus, Trash2, RefreshCw, Star, Check, X, Tag, DollarSign,
  Lock, AlertCircle,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import type { RoleType } from './types';
import { useTerminology } from '@/lib/terminology';
import {
  SettingsPage, SettingsSection, inputClass, labelClass, primaryBtnClass, secondaryBtnClass,
} from './ui';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;
const TM = `${API_BASE}/task-management`;

// ── Types ─────────────────────────────────────────────────────────────────────

interface TaskType {
  id: number;
  name: string;
  code: string;
  color: string;
  is_billable: boolean;
}

interface SetMember {
  task_type_id: number;
  code: string;
  name: string;
  color: string;
  is_billable: boolean;
  sort_order: number;
}

interface TaskTypeSet {
  id: number;
  name: string;
  description: string;
  is_default: boolean;
  source: 'manual' | 'cch_axcess_sync' | 'seed';
  member_count: number;
  members?: SetMember[];
}

interface Props {
  currentUserRole: RoleType;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

// Shared palette (matches TaskTypesTab)
const COLOR_PRESETS = [
  '#1F3D34', '#2563eb', '#7c3aed', '#db2777', '#dc2626',
  '#ea580c', '#ca8a04', '#16a34a', '#0891b2', '#475569',
];

const BLANK_TT_FORM = {
  name: '', code: '', is_billable: true, color: '#1F3D34',
};

// ── Main ──────────────────────────────────────────────────────────────────────

export default function TaskTypeSetsTab({ currentUserRole, onSuccess, onError }: Props) {
  const terms = useTerminology();
  const [sets,          setSets]          = useState<TaskTypeSet[]>([]);
  const [allTypes,      setAllTypes]      = useState<TaskType[]>([]);
  const [selectedId,    setSelectedId]    = useState<number | null>(null);
  const [showTTForm,    setShowTTForm]    = useState(false);
  const [ttForm,        setTtForm]        = useState(BLANK_TT_FORM);
  const [ttSaving,      setTtSaving]      = useState(false);
  const [detail,        setDetail]        = useState<TaskTypeSet | null>(null);
  const [loadingList,   setLoadingList]   = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);

const canManage = ['owner', 'admin'].includes(currentUserRole) || !currentUserRole;

  // ── Load ──
  const fetchSets = async () => {
    setLoadingList(true);
    try {
      const [setsData, typesData] = await Promise.all([
        safeFetchJson<TaskTypeSet[]>(`${TM}/task-type-sets/`),
        safeFetchJson<TaskType[]>(`${TM}/task-types/`),
      ]);
      setSets(setsData || []);
      setAllTypes(typesData || []);
      if ((setsData || []).length > 0 && selectedId === null) {
        setSelectedId(setsData![0].id);
      }
    } catch (err: any) {
      onError(err?.message || 'Failed to load task type sets');
    } finally {
      setLoadingList(false);
    }
  };

  const fetchDetail = async (id: number) => {
    setLoadingDetail(true);
    try {
      const data = await safeFetchJson<TaskTypeSet>(`${TM}/task-type-sets/${id}/`);
      setDetail(data);
    } catch (err: any) {
      onError(err?.message || 'Failed to load set details');
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => { fetchSets(); }, []);
  useEffect(() => { if (selectedId !== null) fetchDetail(selectedId); }, [selectedId]);

  // ── Mutations ──
  const createSet = async () => {
    const name = window.prompt('Name for the new set?');
    if (!name?.trim()) return;
    try {
      const created = await safeFetchJson<TaskTypeSet>(`${TM}/task-type-sets/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), description: '' }),
      });
      onSuccess('Set created');
      await fetchSets();
      setSelectedId(created.id);
    } catch (err: any) {
      onError(err?.message || 'Failed to create set');
    }
  };

  const setAsDefault = async () => {
    if (!detail) return;
    try {
      await safeFetchJson(`${TM}/task-type-sets/${detail.id}/set-default/`, { method: 'POST' });
      onSuccess(`"${detail.name}" is now the firm default`);
      await fetchSets();
      await fetchDetail(detail.id);
    } catch (err: any) {
      onError(err?.message || 'Failed to set default');
    }
  };

  const toggleMember = async (taskTypeId: number, isMember: boolean) => {
    if (!detail) return;
    try {
      await safeFetchJson(`${TM}/task-type-sets/${detail.id}/members/`, {
        method: isMember ? 'DELETE' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_type_id: taskTypeId }),
      });
      await fetchDetail(detail.id);
      await fetchSets();
    } catch (err: any) {
      onError(err?.message || 'Failed to update members');
    }
  };

  const createTaskTypeAndAdd = async () => {
    if (!ttForm.name.trim() || !detail) return;
    setTtSaving(true);
    try {
      // 1. Create the org-wide task type
      const created = await safeFetchJson<TaskType>(`${TM}/task-types/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: ttForm.name.trim(),
          code: ttForm.code.trim(),
          is_billable: ttForm.is_billable,
          color: ttForm.color,
        }),
      });
      // 2. Add it to the currently-selected set
      await safeFetchJson(`${TM}/task-type-sets/${detail.id}/members/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_type_id: created.id }),
      });
      onSuccess(`"${created.name}" created and added to ${detail.name}`);
      setTtForm(BLANK_TT_FORM);
      setShowTTForm(false);
      // 3. Refresh both lists
      await fetchDetail(detail.id);
      await fetchSets();
    } catch (err: any) {
      onError(err?.message || 'Failed to create task type');
    } finally {
      setTtSaving(false);
    }
  };

  const deleteSet = async () => {
    if (!detail) return;
    if (!confirm(`Delete set "${detail.name}"?`)) return;
    try {
      await safeFetchJson(`${TM}/task-type-sets/${detail.id}/`, { method: 'DELETE' });
      onSuccess('Set deleted');
      setSelectedId(null);
      setDetail(null);
      await fetchSets();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete set');
    }
  };

  const isReadOnly = detail?.source === 'cch_axcess_sync' || !canManage;
  const memberIds = new Set((detail?.members || []).map(m => m.task_type_id));

  // ── Render ──
  if (loadingList) {
    return (
      <div className="flex items-center justify-center py-16">
        <RefreshCw className="w-5 h-5 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <SettingsPage
      title={`${terms.task_type} Sets`}
      subtitle='Bundle task types into named lists (e.g. "Standard", "Audit-Only"). One set is your firm default; others can be assigned per client.'
      actions={canManage ? (
        <button
          onClick={createSet}
          className={primaryBtnClass}
        >
          <Plus className="w-3.5 h-3.5" /> New Set
        </button>
      ) : undefined}
    >
      {/* Split layout */}
      <div className="rounded-2xl border border-slate-200/70 overflow-hidden flex" style={{ height: 'calc(100vh - 280px)', minHeight: '500px' }}>

        {/* ── Sidebar ── */}
        <aside className="w-72 border-r border-border/60 bg-slate-50/40 overflow-y-auto">
          {sets.length === 0 ? (
            <div className="p-6 text-center">
              <Layers className="w-8 h-8 text-slate-200 mx-auto mb-2" />
              <p className="text-sm font-semibold text-slate-500">No sets yet</p>
              {canManage && (
                <button onClick={createSet} className="mt-3 text-xs text-primary hover:underline font-semibold">
                  Create the first one →
                </button>
              )}
            </div>
          ) : (
            <div className="p-2">
              {sets.map(s => {
                const active = s.id === selectedId;
                return (
                  <button
                    key={s.id}
                    onClick={() => setSelectedId(s.id)}
                    className={cn(
                      'w-full text-left px-3 py-2.5 rounded-lg mb-1 transition-all relative group',
                      active
                        ? 'bg-white border border-border/60 shadow-sm'
                        : 'border border-transparent hover:bg-white/60'
                    )}
                  >
                    {active && (
                      <span className="absolute left-0 top-2 bottom-2 w-0.5 bg-primary rounded-r" />
                    )}
                    <div className="flex items-center justify-between gap-2 pl-1">
                      <span className={cn(
                        'text-sm font-semibold truncate',
                        active ? 'text-slate-900' : 'text-slate-700'
                      )}>
                        {s.name}
                      </span>
                      {s.is_default && (
                        <span className="text-[9px] font-bold uppercase tracking-wider bg-primary text-white px-1.5 py-0.5 rounded shrink-0">
                          Default
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1 pl-1">
                      <span className="text-xs text-slate-400">{s.member_count} types</span>
                      {s.source === 'cch_axcess_sync' && (
                        <span className="text-[10px] text-amber-600 font-semibold flex items-center gap-1">
                          <Lock className="w-2.5 h-2.5" /> Synced
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        {/* ── Editor ── */}
        <main className="flex-1 overflow-y-auto">
          {!detail || loadingDetail ? (
            <div className="flex items-center justify-center h-full">
              {loadingDetail ? (
                <RefreshCw className="w-5 h-5 text-primary animate-spin" />
              ) : (
                <p className="text-slate-400 text-sm">Select a set on the left or create a new one</p>
              )}
            </div>
          ) : (
            <div className="p-6">
              {/* Editor header */}
              <div className="flex items-start justify-between mb-5 pb-5 border-b border-border/40">
                <div>
                  <h3 className="text-lg font-bold text-slate-900">{detail.name}</h3>
                  <p className="text-sm text-slate-500 mt-0.5">
                    {detail.description || 'No description'}
                  </p>
                  {detail.source === 'cch_axcess_sync' && (
                    <div className="mt-2 inline-flex items-center gap-1.5 px-2 py-1 bg-amber-50 border border-amber-200 rounded-md">
                      <AlertCircle className="w-3 h-3 text-amber-600" />
                      <span className="text-xs font-semibold text-amber-700">
                        Synced from CCH Axcess — read-only
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {!detail.is_default && !isReadOnly && (
                    <button
                      onClick={setAsDefault}
                      className={secondaryBtnClass}
                    >
                      <Star className="w-3.5 h-3.5" /> Set as Default
                    </button>
                  )}
                  {!isReadOnly && (
                    <button
                      onClick={deleteSet}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border border-red-200 text-red-500 rounded-lg hover:bg-red-50 transition-all"
                    >
                      <Trash2 className="w-3.5 h-3.5" /> Delete
                    </button>
                  )}
                </div>
              </div>

              {/* Members */}
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">
                  {terms.task_types} in this set
                </p>
                {!isReadOnly && (
                  <button
                    onClick={() => setShowTTForm(v => !v)}
                    className={secondaryBtnClass}
                  >
                    {showTTForm ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
                    {showTTForm ? 'Cancel' : `New ${terms.task_type}`}
                  </button>
                )}
              </div>

              {/* Quick-create form */}
              {showTTForm && !isReadOnly && (
                <SettingsSection tint className="mb-4" title={`New ${terms.task_type} — added to ${detail.name}`}>
                  <div className="grid grid-cols-12 gap-3 mb-3">
                    <div className="col-span-7">
                      <label className={labelClass}>Name *</label>
                      <input
                        type="text"
                        value={ttForm.name}
                        onChange={e => setTtForm({ ...ttForm, name: e.target.value })}
                        placeholder="Tax Preparation"
                        className={inputClass}
                      />
                    </div>
                    <div className="col-span-3">
                      <label className={labelClass}>Code</label>
                      <input
                        type="text"
                        value={ttForm.code}
                        onChange={e => setTtForm({ ...ttForm, code: e.target.value.toUpperCase().slice(0, 20) })}
                        placeholder="TAX"
                        maxLength={20}
                        className={`${inputClass} font-mono uppercase`}
                      />
                    </div>
                    <div className="col-span-2 flex items-end">
                      <label className="flex items-center gap-2 text-sm font-semibold text-slate-700 cursor-pointer pb-2">
                        <input
                          type="checkbox"
                          checked={ttForm.is_billable}
                          onChange={e => setTtForm({ ...ttForm, is_billable: e.target.checked })}
                          className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary/20"
                        />
                        Billable
                      </label>
                    </div>
                  </div>
                  <div className="mb-3">
                    <label className={labelClass}>Color</label>
                    <div className="flex items-center gap-2">
                      {COLOR_PRESETS.map(c => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => setTtForm({ ...ttForm, color: c })}
                          className={cn(
                            'w-7 h-7 rounded-lg transition-all',
                            ttForm.color === c ? 'ring-2 ring-offset-2 ring-primary' : 'hover:scale-110'
                          )}
                          style={{ backgroundColor: c }}
                          aria-label={`Color ${c}`}
                        />
                      ))}
                      <input
                        type="text"
                        value={ttForm.color}
                        onChange={e => setTtForm({ ...ttForm, color: e.target.value })}
                        className="ml-2 w-24 border border-border/60 rounded-lg px-2 py-1.5 text-xs font-mono bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
                      />
                    </div>
                  </div>
                  <div className="flex gap-2 pt-3 border-t border-border/50">
                    <button
                      onClick={createTaskTypeAndAdd}
                      disabled={ttSaving || !ttForm.name.trim()}
                      className={primaryBtnClass}
                    >
                      {ttSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                      Create & Add
                    </button>
                    <button
                      onClick={() => { setShowTTForm(false); setTtForm(BLANK_TT_FORM); }}
                      className={secondaryBtnClass}
                    >
                      Cancel
                    </button>
                  </div>
                </SettingsSection>
              )}

              {allTypes.length === 0 ? (
                <div className="text-center py-10 border border-dashed border-slate-200 rounded-xl">
                  <p className="text-sm text-slate-400">No task types exist yet</p>
                  <p className="text-xs text-slate-400 mt-1">Create {terms.task_types.toLowerCase()} first in the {terms.task_types} tab</p>
                </div>
              ) : (
                <div className="rounded-2xl border border-slate-200/70 overflow-hidden divide-y divide-border/30">
                  {allTypes.map(tt => {
                    const isMember = memberIds.has(tt.id);
                    return (
                      <label
                        key={tt.id}
                        className={cn(
                          'flex items-center gap-3 px-4 py-2.5 transition-colors',
                          !isReadOnly && 'cursor-pointer hover:bg-slate-50/60',
                          isReadOnly && 'opacity-80'
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={isMember}
                          disabled={isReadOnly}
                          onChange={() => toggleMember(tt.id, isMember)}
                          className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary/20 disabled:opacity-50"
                        />
                        <span
                          className="w-3 h-3 rounded shrink-0"
                          style={{ backgroundColor: tt.color || '#94a3b8' }}
                        />
                        <span className="font-mono text-xs font-semibold text-slate-600 w-16">
                          {tt.code}
                        </span>
                        <span className="flex-1 text-sm text-slate-800">{tt.name}</span>
                        {tt.is_billable && (
                          <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">
                            Billable
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
              )}

              <p className="text-xs text-slate-400 mt-4">
                {memberIds.size} of {allTypes.length} task types in this set
              </p>
            </div>
          )}
        </main>
      </div>
    </SettingsPage>
  );
}