// src/components/clients/ClientTaskTypesPanel.tsx
// Per-client TaskType allow-list configuration.
// Embeds in the Client detail view.

import { useEffect, useMemo, useState } from 'react';
import {
  Tag, RefreshCw, Save, AlertCircle, Lock,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;
const TM = `${API_BASE}/task-management`;

// ── Types ─────────────────────────────────────────────────────────────────────

type Mode = 'default' | 'set' | 'custom';

interface AllowedTaskType {
  id: number;
  code: string;
  name: string;
  color: string;
}

interface Override {
  task_type_id: number;
  code: string;
  name: string;
  allowed: boolean;
  override_rate: string | null;
  source: 'manual' | 'cch_axcess_sync';
}

interface Config {
  client_id: number;
  client_name: string;
  mode: Mode;
  default_task_type_set_id: number | null;
  overrides: Override[];
  allowed_task_types: AllowedTaskType[];
}

interface TaskTypeSetOption {
  id: number;
  name: string;
  member_count: number;
}

interface OrgTaskType {
  id: number;
  code: string;
  name: string;
  color: string;
}

interface Props {
  clientId: number;
  canManage?: boolean;
  onSuccess?: (msg: string) => void;
  onError?: (msg: string) => void;
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function ClientTaskTypesPanel({
  clientId,
  canManage = true,
  onSuccess,
  onError,
}: Props) {
  const [config,   setConfig]   = useState<Config | null>(null);
  const [sets,     setSets]     = useState<TaskTypeSetOption[]>([]);
  const [orgTypes, setOrgTypes] = useState<OrgTaskType[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [saving,   setSaving]   = useState(false);

  // Local edit state
  const [mode,          setMode]          = useState<Mode>('default');
  const [selectedSetId, setSelectedSetId] = useState<number | null>(null);
  const [overrides,     setOverrides]     = useState<Map<number, boolean>>(new Map());

  const load = async () => {
    setLoading(true);
    try {
      const [cfg, setData, types] = await Promise.all([
        safeFetchJson<Config>(`${TM}/clients/${clientId}/task-types/`),
        safeFetchJson<TaskTypeSetOption[]>(`${TM}/task-type-sets/`),
        safeFetchJson<OrgTaskType[]>(`${TM}/task-types/`),
      ]);
      setConfig(cfg);
      setSets(setData || []);
      setOrgTypes(types || []);
      setMode(cfg.mode);
      setSelectedSetId(cfg.default_task_type_set_id);

      const ovMap = new Map<number, boolean>();
      for (const o of (cfg.overrides || [])) ovMap.set(o.task_type_id, o.allowed);
      setOverrides(ovMap);
    } catch (err: any) {
      onError?.(err?.message || 'Failed to load task type config');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [clientId]);

  const handleSave = async () => {
    if (!canManage) return;
    setSaving(true);
    try {
      const body: any = { mode };
      if (mode === 'set') {
        if (!selectedSetId) {
          onError?.('Pick a task type set first');
          setSaving(false);
          return;
        }
        body.default_task_type_set_id = selectedSetId;
      }
      if (mode === 'custom') {
        body.overrides = Array.from(overrides.entries()).map(([task_type_id, allowed]) => ({
          task_type_id, allowed,
        }));
      }
      await safeFetchJson(`${TM}/clients/${clientId}/task-types/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      onSuccess?.('Task type config saved');
      await load();
    } catch (err: any) {
      onError?.(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const allowedCount = useMemo(() => {
    if (!config) return 0;
    return config.allowed_task_types.length;
  }, [config]);

  // ── Render ──
  if (loading || !config) {
    return (
      <div className="flex items-center justify-center py-12 border border-border/60 rounded-xl bg-white">
        <RefreshCw className="w-5 h-5 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="bg-white border border-border/60 rounded-xl overflow-hidden">

      {/* Header */}
      <div className="px-5 py-4 border-b border-border/40 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Tag className="w-4 h-4 text-primary" />
          <h3 className="text-base font-bold text-slate-900">Task Types</h3>
          <span className="text-xs text-slate-400">({allowedCount} allowed)</span>
        </div>
        {!canManage && (
          <span className="text-xs text-slate-400 inline-flex items-center gap-1">
            <Lock className="w-3 h-3" /> Read-only
          </span>
        )}
      </div>

      <div className="p-5">

        {/* Mode selector */}
        <div className="space-y-2 mb-5">

          {/* Default */}
          <label className={cn(
            'flex items-start gap-3 p-3 border rounded-xl transition-all',
            canManage ? 'cursor-pointer hover:bg-slate-50/60' : 'opacity-80',
            mode === 'default' ? 'border-primary bg-primary/3' : 'border-border/60'
          )}>
            <input
              type="radio"
              checked={mode === 'default'}
              onChange={() => setMode('default')}
              disabled={!canManage}
              className="mt-0.5 w-4 h-4 text-primary focus:ring-primary/20"
            />
            <div className="flex-1">
              <p className={cn(
                'text-sm font-semibold',
                mode === 'default' ? 'text-primary' : 'text-slate-800'
              )}>
                Use firm default
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                This client uses whichever task type set is marked as the firm default.
              </p>
            </div>
          </label>

          {/* Set */}
          <label className={cn(
            'flex items-start gap-3 p-3 border rounded-xl transition-all',
            canManage ? 'cursor-pointer hover:bg-slate-50/60' : 'opacity-80',
            mode === 'set' ? 'border-primary bg-primary/3' : 'border-border/60'
          )}>
            <input
              type="radio"
              checked={mode === 'set'}
              onChange={() => setMode('set')}
              disabled={!canManage}
              className="mt-0.5 w-4 h-4 text-primary focus:ring-primary/20"
            />
            <div className="flex-1">
              <p className={cn(
                'text-sm font-semibold',
                mode === 'set' ? 'text-primary' : 'text-slate-800'
              )}>
                Use a specific set
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                Pick from your firm's named bundles (e.g. "Audit-Only").
              </p>
              {mode === 'set' && (
                <select
                  value={selectedSetId || ''}
                  onChange={e => setSelectedSetId(Number(e.target.value) || null)}
                  disabled={!canManage}
                  className="mt-2 w-full max-w-xs border border-border/60 rounded-lg px-3 py-1.5 text-sm bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
                >
                  <option value="">— Select a set —</option>
                  {sets.map(s => (
                    <option key={s.id} value={s.id}>{s.name} ({s.member_count} types)</option>
                  ))}
                </select>
              )}
            </div>
          </label>

          {/* Custom */}
          <label className={cn(
            'flex items-start gap-3 p-3 border rounded-xl transition-all',
            canManage ? 'cursor-pointer hover:bg-slate-50/60' : 'opacity-80',
            mode === 'custom' ? 'border-primary bg-primary/3' : 'border-border/60'
          )}>
            <input
              type="radio"
              checked={mode === 'custom'}
              onChange={() => setMode('custom')}
              disabled={!canManage}
              className="mt-0.5 w-4 h-4 text-primary focus:ring-primary/20"
            />
            <div className="flex-1 min-w-0">
              <p className={cn(
                'text-sm font-semibold',
                mode === 'custom' ? 'text-primary' : 'text-slate-800'
              )}>
                Custom (per-task allow/forbid)
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                Override the firm default with specific allow/forbid choices for this client.
              </p>
              {mode === 'custom' && (
                <div className="mt-3 border border-border/60 rounded-lg overflow-hidden">
                  {orgTypes.length === 0 ? (
                    <p className="text-xs text-slate-400 text-center py-6">No task types exist yet</p>
                  ) : (
                    orgTypes.map((tt, idx) => {
                      const explicit = overrides.has(tt.id);
                      const allowed  = overrides.get(tt.id);
                      const choice   = !explicit ? 'inherit' : (allowed ? 'allow' : 'forbid');
                      return (
                        <div
                          key={tt.id}
                          className={cn(
                            'flex items-center gap-3 px-3 py-2',
                            idx > 0 && 'border-t border-border/30'
                          )}
                        >
                          <span
                            className="w-2.5 h-2.5 rounded shrink-0"
                            style={{ backgroundColor: tt.color || '#94a3b8' }}
                          />
                          <span className="font-mono text-[11px] font-semibold text-slate-600 w-14 shrink-0">
                            {tt.code}
                          </span>
                          <span className="flex-1 text-sm text-slate-700 truncate">{tt.name}</span>
                          <select
                            value={choice}
                            disabled={!canManage}
                            onChange={e => {
                              const next = new Map(overrides);
                              const v = e.target.value;
                              if (v === 'inherit') next.delete(tt.id);
                              else next.set(tt.id, v === 'allow');
                              setOverrides(next);
                            }}
                            className={cn(
                              'text-xs font-semibold px-2 py-1 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary/20',
                              choice === 'allow' && 'bg-emerald-50 border-emerald-200 text-emerald-700',
                              choice === 'forbid' && 'bg-red-50 border-red-200 text-red-600',
                              choice === 'inherit' && 'bg-slate-50 border-border/60 text-slate-500'
                            )}
                          >
                            <option value="inherit">Inherit</option>
                            <option value="allow">Allow</option>
                            <option value="forbid">Forbid</option>
                          </select>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          </label>
        </div>

        {/* Sync notice */}
        {(config.overrides || []).some(o => o.source === 'cch_axcess_sync') && (
          <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-700">
              Some overrides on this client were synced from CCH Axcess Practice and will be refreshed on the next sync.
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-4 border-t border-border/40">
          <p className="text-xs text-slate-400">
            {allowedCount} task type{allowedCount !== 1 ? 's' : ''} currently allowed for {config.client_name}
          </p>
          {canManage && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white rounded-lg font-semibold text-sm hover:opacity-90 disabled:opacity-50 transition-all"
            >
              {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              Save
            </button>
          )}
        </div>
      </div>
    </div>
  );
}