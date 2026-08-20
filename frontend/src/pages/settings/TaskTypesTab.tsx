// src/pages/settings/TaskTypesTab.tsx
// Firm-wide TaskType CRUD — matches ClientsTab pattern.

import { useEffect, useMemo, useState } from 'react';
import {
  Tag, Plus, Pencil, Trash2, Search, X, Check, RefreshCw,
  CheckSquare, Square, DollarSign,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import { useTerminology } from '@/lib/terminology';
import type { RoleType } from './types';
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
  is_billable: boolean;
  default_rate: string | null;
  color: string;
  icon: string;
  sort_order: number;
  is_active: boolean;
  created_at: string | null;
}

interface Props {
  currentUserRole: RoleType;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

// ── Default colors palette ────────────────────────────────────────────────────

const COLOR_PRESETS = [
  '#1F3D34', '#2563eb', '#7c3aed', '#db2777', '#dc2626',
  '#ea580c', '#ca8a04', '#16a34a', '#0891b2', '#475569',
];

// ── Main ──────────────────────────────────────────────────────────────────────

export default function TaskTypesTab({ currentUserRole, onSuccess, onError }: Props) {
  const terms = useTerminology();
  const [taskTypes, setTaskTypes] = useState<TaskType[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [showAdd,   setShowAdd]   = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving,    setSaving]    = useState(false);
  const [search,    setSearch]    = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('active');

  const [form, setForm] = useState({
    name: '', code: '', is_billable: true,
    default_rate: '', color: '#1F3D34', sort_order: 0, is_active: true,
  });

  const canManage = ['owner', 'admin'].includes(currentUserRole) || !currentUserRole;

  // ── Load ──
  const fetchTaskTypes = async () => {
    setLoading(true);
    try {
      const data = await safeFetchJson<TaskType[]>(`${TM}/task-types/`);
      setTaskTypes(data || []);
    } catch (err: any) {
      onError(err?.message || 'Failed to load task types');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchTaskTypes(); }, []);

  // ── Filter ──
  const filtered = useMemo(() => {
    let list = taskTypes;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(t =>
        t.name.toLowerCase().includes(q) || t.code.toLowerCase().includes(q)
      );
    }
    if (statusFilter === 'active')   list = list.filter(t => t.is_active);
    if (statusFilter === 'inactive') list = list.filter(t => !t.is_active);
    return list;
  }, [taskTypes, search, statusFilter]);

  // ── Form ──
  const resetForm = () => {
    setForm({ name: '', code: '', is_billable: true, default_rate: '', color: '#1F3D34', sort_order: 0, is_active: true });
    setShowAdd(false);
    setEditingId(null);
  };

  const handleEdit = (tt: TaskType) => {
    if (!canManage) return;
    setForm({
      name: tt.name,
      code: tt.code,
      is_billable: tt.is_billable,
      default_rate: tt.default_rate || '',
      color: tt.color || '#1F3D34',
      sort_order: tt.sort_order,
      is_active: tt.is_active,
    });
    setEditingId(tt.id);
    setShowAdd(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const body = {
        ...form,
        default_rate: form.default_rate.trim() || null,
      };
      if (editingId) {
        await safeFetchJson(`${TM}/task-types/${editingId}/`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        onSuccess('Task type updated');
      } else {
        await safeFetchJson(`${TM}/task-types/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        onSuccess('Task type added');
      }
      resetForm();
      fetchTaskTypes();
    } catch (err: any) {
      onError(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (tt: TaskType) => {
    if (!canManage) return;
    if (!confirm(`Deactivate task type "${tt.name}"?`)) return;
    try {
      await safeFetchJson(`${TM}/task-types/${tt.id}/`, { method: 'DELETE' });
      onSuccess('Task type deactivated');
      fetchTaskTypes();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  // ── Render ──
  return (
    <SettingsPage
      title={terms.task_types}
      subtitle="Firm-wide categories used to classify time blocks. These appear in your team's timesheet picker and feed billing rates."
      actions={canManage ? (
        <button
          onClick={() => { resetForm(); setShowAdd(true); }}
          className={primaryBtnClass}
        >
          <Plus className="w-3.5 h-3.5" /> Add {terms.task_type}
        </button>
      ) : undefined}
    >
      {/* Search + filter */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by name or code..."
            className="w-full pl-8 pr-8 py-2 text-sm bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5">
          {(['all', 'active', 'inactive'] as const).map(f => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={cn(
                'px-3 py-1.5 text-xs font-semibold rounded-md transition-all',
                statusFilter === f ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              )}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400 ml-auto">
          {filtered.length === taskTypes.length
            ? `${taskTypes.length} types`
            : <><span className="font-semibold text-slate-600">{filtered.length}</span> of {taskTypes.length}</>
          }
          {(search || statusFilter !== 'all') && filtered.length < taskTypes.length && (
            <button onClick={() => { setSearch(''); setStatusFilter('all'); }} className="ml-2 text-primary hover:underline font-medium">Clear</button>
          )}
        </span>
      </div>

      {/* Add/edit form */}
      {showAdd && canManage && (
        <SettingsSection tint className="mb-5" title={editingId ? `Edit ${terms.task_type}` : `New ${terms.task_type}`}>
          <div className="grid grid-cols-12 gap-4 mb-4">
            <div className="col-span-5">
              <label className={labelClass}>Name *</label>
              <input
                type="text"
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="Tax Preparation"
                className={inputClass}
              />
            </div>
            <div className="col-span-3">
              <label className={labelClass}>Code</label>
              <input
                type="text"
                value={form.code}
                onChange={e => setForm({ ...form, code: e.target.value.toUpperCase().slice(0, 20) })}
                placeholder="TAX"
                maxLength={20}
                className={`${inputClass} font-mono uppercase`}
              />
            </div>
            <div className="col-span-2">
              <label className={labelClass}>Sort</label>
              <input
                type="number"
                value={form.sort_order}
                onChange={e => setForm({ ...form, sort_order: Number(e.target.value) || 0 })}
                className={inputClass}
              />
            </div>
            <div className="col-span-2 flex items-end">
              <label className="flex items-center gap-2 text-sm font-semibold text-slate-700 cursor-pointer pb-2">
                <input
                  type="checkbox"
                  checked={form.is_billable}
                  onChange={e => setForm({ ...form, is_billable: e.target.checked })}
                  className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary/20"
                />
                Billable
              </label>
            </div>
          </div>

          <div className="grid grid-cols-12 gap-4 mb-4">
            <div className="col-span-3">
              <label className={labelClass}>
                Default Rate <span className="text-[10px] font-normal text-slate-400 normal-case">$/hr, optional</span>
              </label>
              <div className="relative">
                <DollarSign className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                <input
                  type="text"
                  value={form.default_rate}
                  onChange={e => setForm({ ...form, default_rate: e.target.value })}
                  placeholder="150.00"
                  className={`${inputClass} pl-7`}
                />
              </div>
            </div>
            <div className="col-span-9">
              <label className={labelClass}>Color</label>
              <div className="flex items-center gap-2">
                {COLOR_PRESETS.map(c => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setForm({ ...form, color: c })}
                    className={cn(
                      'w-7 h-7 rounded-lg transition-all',
                      form.color === c
                        ? 'ring-2 ring-offset-2 ring-primary'
                        : 'hover:scale-110'
                    )}
                    style={{ backgroundColor: c }}
                    aria-label={`Color ${c}`}
                  />
                ))}
                <input
                  type="text"
                  value={form.color}
                  onChange={e => setForm({ ...form, color: e.target.value })}
                  className="ml-2 w-24 border border-border/60 rounded-lg px-2 py-1.5 text-xs font-mono bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
                />
              </div>
            </div>
          </div>

          <div className="flex gap-2 pt-4 border-t border-border/50">
            <button
              onClick={handleSave}
              disabled={saving || !form.name.trim()}
              className={primaryBtnClass}
            >
              {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              {editingId ? 'Update' : `Add ${terms.task_type}`}
            </button>
            <button
              onClick={resetForm}
              className={secondaryBtnClass}
            >
              Cancel
            </button>
          </div>
        </SettingsSection>
      )}

      {/* Table */}
      <div className="rounded-2xl border border-slate-200/70 overflow-hidden flex flex-col" style={{ maxHeight: 'calc(100vh - 280px)' }}>
        <div className="overflow-auto flex-1">
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border/60 bg-slate-50/80">
                {['', 'Code', 'Name', 'Billable', 'Default Rate', 'Sort', 'Status', ...(canManage ? ['Actions'] : [])].map((h, i) => (
                  <th
                    key={i}
                    className={cn(
                      'px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500',
                      h === 'Actions' ? 'text-right' : 'text-left'
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {loading ? (
                <tr>
                  <td colSpan={canManage ? 8 : 7} className="text-center py-14">
                    <RefreshCw className="w-5 h-5 text-primary animate-spin mx-auto" />
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={canManage ? 8 : 7} className="text-center py-14">
                    <Tag className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                    {search || statusFilter !== 'all' ? (
                      <>
                        <p className="font-semibold text-slate-500">No task types match your filter</p>
                        <button onClick={() => { setSearch(''); setStatusFilter('all'); }} className="mt-2 text-sm text-primary hover:underline">
                          Clear filters
                        </button>
                      </>
                    ) : (
                      <>
                        <p className="font-semibold text-slate-500">No task types yet</p>
                        {canManage && (
                          <button
                            onClick={() => setShowAdd(true)}
                            className={`${primaryBtnClass} mt-3`}
                          >
                            <Plus className="w-3.5 h-3.5" />Add {terms.task_type}
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ) : filtered.map(tt => (
                <tr key={tt.id} className="hover:bg-slate-50/60 transition-colors">
                  <td className="px-4 py-3 w-12">
                    <span
                      className="block w-4 h-4 rounded shrink-0"
                      style={{ backgroundColor: tt.color || '#94a3b8' }}
                    />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs font-semibold text-slate-700">{tt.code}</td>
                  <td className="px-4 py-3 font-semibold text-slate-800">{tt.name}</td>
                  <td className="px-4 py-3">
                    {tt.is_billable ? (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">
                        <Check className="w-3 h-3" /> Billable
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {tt.default_rate ? <>${tt.default_rate}<span className="text-slate-400">/hr</span></> : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{tt.sort_order}</td>
                  <td className="px-4 py-3">
                    <span className={cn(
                      'text-xs px-2 py-0.5 rounded-full font-semibold border',
                      tt.is_active ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-100 text-slate-400 border-slate-200'
                    )}>
                      {tt.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  {canManage && (
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleEdit(tt)}
                          className="p-1.5 text-slate-400 hover:text-primary hover:bg-primary/8 rounded-lg transition-colors"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(tt)}
                          className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </SettingsPage>
  );
}