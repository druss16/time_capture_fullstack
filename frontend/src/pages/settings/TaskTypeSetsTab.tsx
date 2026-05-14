// src/pages/settings/TaskTypeSetsTab.tsx
// Manage bundled TaskTypeSets — left sidebar of sets, right editor with members.

import { useEffect, useState } from 'react';
import {
  Layers, Plus, Trash2, RefreshCw, Star, Check, X,
  Lock, AlertCircle,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import type { RoleType } from './types';

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

// ── Main ──────────────────────────────────────────────────────────────────────

export default function TaskTypeSetsTab({ currentUserRole, onSuccess, onError }: Props) {
  const [sets,          setSets]          = useState<TaskTypeSet[]>([]);
  const [allTypes,      setAllTypes]      = useState<TaskType[]>([]);
  const [selectedId,    setSelectedId]    = useState<number | null>(null);
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
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Layers className="w-5 h-5 text-primary" />
          Task Type Sets
          <span className="text-sm font-semibold text-slate-400">({sets.length})</span>
        </h2>
        {canManage && (
          <button
            onClick={createSet}
            className="flex items-center gap-1.5 px-3 py-2 bg-primary text-white rounded-lg font-semibold text-sm hover:opacity-90 transition-all"
          >
            <Plus className="w-3.5 h-3.5" /> New Set
          </button>
        )}
      </div>

      <p className="text-sm text-slate-500 mb-4">
        Bundle task types into named lists (e.g. "Standard", "Audit-Only"). One set is your firm default; others can be assigned per client.
      </p>

      {/* Split layout */}
      <div className="border border-border/60 rounded-xl overflow-hidden flex" style={{ height: 'calc(100vh - 280px)', minHeight: '500px' }}>

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
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border border-border/60 rounded-lg text-slate-600 hover:bg-slate-50 transition-all"
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
              <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
                Task Types in this set
              </p>

              {allTypes.length === 0 ? (
                <div className="text-center py-10 border border-dashed border-slate-200 rounded-xl">
                  <p className="text-sm text-slate-400">No task types exist yet</p>
                  <p className="text-xs text-slate-400 mt-1">Create task types first in the Task Types tab</p>
                </div>
              ) : (
                <div className="border border-border/60 rounded-xl divide-y divide-border/30">
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
    </div>
  );
}