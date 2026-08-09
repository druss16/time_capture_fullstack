// src/pages/settings/OrganizationTab.tsx
import { useEffect, useState } from 'react';
import {
  Building2, DollarSign, Sparkles, Pencil, Check,
  RefreshCw, Brain, ChevronDown,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import type { OrgInfo, PlanType } from './types';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

const SENSITIVITY_PRESETS = [
  { value: 10,  label: 'Conservative',    color: '#6366f1' },
  { value: 35,  label: 'Cautious',        color: '#3b82f6' },
  { value: 50,  label: 'Balanced',        color: '#10b981' },
  { value: 70,  label: 'Aggressive',      color: '#f59e0b' },
  { value: 90,  label: 'Very Aggressive', color: '#ef4444' },
];

const SENSITIVITY_DESCRIPTIONS: Record<string, string> = {
  Conservative:      'Only switches when the full client name appears in a window title. Zero false positives.',
  Cautious:          'Requires a strong name match. Partial words are ignored.',
  Balanced:          'Default setting. Full-name matches auto-switch; partial words show a suggestion toast.',
  Aggressive:        'Partial words trigger auto-switch. Best for firms with unique client names.',
  'Very Aggressive': 'Very short name fragments trigger switches. May produce occasional false positives.',
};

function getSensitivityLabel(v: number) {
  if (v <= 20) return 'Conservative';
  if (v <= 40) return 'Cautious';
  if (v <= 60) return 'Balanced';
  if (v <= 80) return 'Aggressive';
  return 'Very Aggressive';
}

function getSensitivityColor(v: number) {
  return SENSITIVITY_PRESETS.reduce((closest, p) =>
    Math.abs(p.value - v) < Math.abs(closest.value - v) ? p : closest
  ).color;
}

function computeThresholds(s: number) {
  const pct = Math.max(0, Math.min(100, s)) / 100;
  return {
    local:   Math.round((0.90 - pct * 0.40) * 100),
    ai:      Math.round((0.85 - pct * 0.40) * 100),
    suggest: Math.round((0.70 - pct * 0.35) * 100),
    partial: pct >= 0.40,
    minWord: pct < 0.40 ? null : pct < 0.70 ? 6 : pct < 0.90 ? 4 : 3,
  };
}

interface Props {
  orgInfo: OrgInfo | null;
  orgPlan: PlanType;
  onUpdate: (org: OrgInfo) => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
  currentUserRole: string;
}

export default function OrganizationTab({
  orgInfo, orgPlan, onUpdate, onSuccess, onError, currentUserRole,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [saving,  setSaving]  = useState(false);
  const [form, setForm] = useState({
    name: '', billing_email: '', billing_contact: '', billing_rate_default: '150.00',
    cost_rate_default: '75.00', target_utilization: '75',
  });

  useEffect(() => {
    if (orgInfo) {
      setForm({
        name:                 orgInfo.name || '',
        billing_email:        orgInfo.billing_email || '',
        billing_contact:      orgInfo.billing_contact || '',
        billing_rate_default: orgInfo.billing_rate_default || '150.00',
        cost_rate_default:    orgInfo.cost_rate_default || '75.00',
        target_utilization:   orgInfo.target_utilization || '75',
      });
    }
  }, [orgInfo]);

  const handleOrgSave = async () => {
    setSaving(true);
    try {
      const updated = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      onUpdate(updated);
      setForm({
        name: updated.name || '', billing_email: updated.billing_email || '',
        billing_contact: updated.billing_contact || '',
        billing_rate_default: updated.billing_rate_default || '150.00',
        cost_rate_default: updated.cost_rate_default || '75.00',
        target_utilization: updated.target_utilization || '75',
      });
      setEditing(false);
      onSuccess('Organization updated');
    } catch (err: any) {
      onError(err?.message || 'Failed to update');
    } finally {
      setSaving(false);
    }
  };

  const isAdmin = currentUserRole === 'admin' || currentUserRole === 'owner';
  const [sensitivity,    setSensitivity]    = useState(50);
  const [savedSens,      setSavedSens]      = useState(50);
  const [sensLoading,    setSensLoading]    = useState(true);
  const [sensSaving,     setSensSaving]     = useState(false);
  const [showThresholds, setShowThresholds] = useState(false);

  useEffect(() => {
    const v = (orgInfo as any)?.ai_sensitivity ?? 50;
    setSensitivity(v);
    setSavedSens(v);
    setSensLoading(false);
  }, [orgInfo]);

  const handleSensSave = async () => {
    setSensSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/org/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ai_sensitivity: sensitivity }),
      });
      setSavedSens(sensitivity);
      onSuccess('Sensitivity saved. Agents will update at next sync.');
    } catch {
      onError('Failed to save sensitivity.');
    } finally {
      setSensSaving(false);
    }
  };

  if (!orgInfo) return <div className="text-slate-500 p-4">No organization data</div>;

  const planLabel  = orgPlan === 'executive' ? '💎 Executive' : orgPlan === 'professional' ? '⭐ Professional' : '🚫 No Plan';
  const sensLabel  = getSensitivityLabel(sensitivity);
  const sensColor  = getSensitivityColor(sensitivity);
  const thresholds = computeThresholds(sensitivity);
  const sensDesc   = SENSITIVITY_DESCRIPTIONS[sensLabel] ?? '';
  const sensChanged = sensitivity !== savedSens;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Building2 className="w-5 h-5 text-primary" />
          Organization
        </h2>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm border border-border/60 rounded-lg font-semibold text-slate-700 hover:bg-slate-50 transition-all"
          >
            <Pencil className="w-3.5 h-3.5" /> Edit
          </button>
        )}
      </div>

      {/* Org info — edit or view */}
      {editing ? (
        <div className="bg-slate-50 border border-dashed border-slate-300 rounded-xl p-5 mb-6">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4">Edit Organization Info</p>
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'Organization Name', key: 'name', type: 'text' },
              { label: 'Billing Email',     key: 'billing_email', type: 'email' },
              { label: 'Billing Contact',   key: 'billing_contact', type: 'text' },
            ].map(({ label, key, type }) => (
              <div key={key} className={key === 'name' ? 'col-span-2 sm:col-span-1' : ''}>
                <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">{label}</label>
                <input
                  type={type}
                  value={(form as any)[key]}
                  onChange={e => setForm({ ...form, [key]: e.target.value })}
                  className="w-full border border-border/60 rounded-lg px-3 py-2 text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all bg-white"
                />
              </div>
            ))}
            <div className="col-span-2 mt-2 pt-4 border-t border-slate-200">
              <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-1">Firm Economics</p>
              <p className="text-xs text-slate-400 mb-3">
                Powers the Analytics dashboard — margin, effective rate, and utilization benchmarks.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {/* Default bill rate */}
                <div>
                  <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Default Bill Rate</label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                    <input
                      type="number" step="0.01" min="0"
                      value={form.billing_rate_default}
                      onChange={e => setForm({ ...form, billing_rate_default: e.target.value })}
                      className="w-full pl-7 pr-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all bg-white"
                    />
                  </div>
                  <p className="text-[11px] text-slate-400 mt-1">Fallback client rate when no specific rate is set. Drives realization.</p>
                </div>

                {/* Blended cost / hour — admin/owner only */}
                {isAdmin && (
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Blended Cost / Hour</label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                      <input
                        type="number" step="0.01" min="0"
                        value={form.cost_rate_default}
                        onChange={e => setForm({ ...form, cost_rate_default: e.target.value })}
                        className="w-full pl-7 pr-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all bg-white"
                      />
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">Loaded employee cost (salary + overhead ÷ hours). Drives margin.</p>
                  </div>
                )}

                {/* Target billable utilization */}
                <div>
                  <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Target Billable %</label>
                  <div className="relative">
                    <input
                      type="number" step="1" min="0" max="100"
                      value={form.target_utilization}
                      onChange={e => setForm({ ...form, target_utilization: e.target.value })}
                      className="w-full pl-3 pr-7 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all bg-white"
                    />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">%</span>
                  </div>
                  <p className="text-[11px] text-slate-400 mt-1">Your utilization goal. Sets the benchmark band on the KPI.</p>
                </div>
              </div>
            </div>
          </div>
          <div className="flex gap-2 mt-4 pt-4 border-t border-border/50">
            <button
              onClick={handleOrgSave} disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-50 transition-all"
            >
              {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              Save Changes
            </button>
            <button onClick={() => setEditing(false)} className="px-4 py-2 border border-border/60 rounded-lg text-sm font-semibold text-slate-600 hover:bg-slate-100 transition-all">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mb-6">
          <div className="grid grid-cols-3 gap-px bg-slate-200 rounded-xl overflow-hidden border border-slate-200 mb-4">
            {[
              { label: 'Organization',    value: orgInfo.name },
              { label: 'Billing Email',   value: orgInfo.billing_email || '—' },
              { label: 'Billing Contact', value: orgInfo.billing_contact || '—' },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white px-4 py-3">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">{label}</p>
                <p className="font-semibold text-slate-900 text-sm truncate">{value}</p>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className={cn(
              'rounded-xl border px-4 py-3 flex items-center justify-between',
              orgPlan === 'executive' ? 'bg-primary/5 border-primary/20' : 'bg-amber-50 border-amber-200'
            )}>
              <div>
                <p className={cn('text-[10px] font-bold uppercase tracking-widest mb-1', orgPlan === 'executive' ? 'text-primary/60' : 'text-amber-600')}>Current Plan</p>
                <p className={cn('text-base font-extrabold', orgPlan === 'executive' ? 'text-primary' : 'text-amber-700')}>{planLabel}</p>
              </div>
              {orgPlan !== 'executive' && (
                <a href="/account/billing" className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-semibold rounded-lg hover:opacity-90 transition-all">
                  <Sparkles className="w-3 h-3" /> Upgrade
                </a>
              )}
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-center justify-between">
              <div>
                <p className="text-[10px] font-bold text-emerald-600/70 uppercase tracking-widest mb-1 flex items-center gap-1">
                  <DollarSign className="w-3 h-3" /> Default Rate
                </p>
                <p className="text-base font-extrabold text-emerald-700">
                  ${parseFloat(orgInfo.billing_rate_default || '150.00').toFixed(2)}<span className="text-xs font-semibold text-emerald-600/70">/hr</span>
                </p>
              </div>
              <span className="text-[10px] bg-emerald-100 text-emerald-700 font-bold px-2 py-0.5 rounded-full">Firm Default</span>
            </div>
          </div>
          {isAdmin && (
            <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-slate-500">
              <span>Blended cost: <b className="text-slate-700">${parseFloat(orgInfo.cost_rate_default || '75.00').toFixed(2)}/hr</b></span>
              <span>Target utilization: <b className="text-slate-700">{parseFloat(orgInfo.target_utilization || '75').toFixed(0)}%</b></span>
              <span className="text-slate-400">Used by the Analytics dashboard</span>
            </div>
          )}
        </div>
      )}

      {/* AI Sensitivity — admin/owner only */}
      {isAdmin && (
        <>
          <div className="flex items-center gap-3 my-5">
            <div className="flex-1 h-px bg-slate-200" />
            <span className="flex items-center gap-1.5 text-xs font-bold text-slate-400 uppercase tracking-widest">
              <Brain className="w-3.5 h-3.5" /> AI Settings
            </span>
            <div className="flex-1 h-px bg-slate-200" />
          </div>

          <div>
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900">Client Detection Sensitivity</h3>
                <p className="text-xs text-slate-500 mt-0.5">How aggressively the desktop agent matches windows to clients.</p>
              </div>
              {!sensLoading && (
                <span className="text-xs font-bold px-2.5 py-1 rounded-full text-white shrink-0 ml-4" style={{ backgroundColor: sensColor }}>
                  {sensitivity} — {sensLabel}
                </span>
              )}
            </div>

            {sensLoading ? (
              <div className="h-8 bg-slate-100 animate-pulse rounded-lg" />
            ) : (
              <>
                <div className="mb-4">
                  <input
                    type="range" min={0} max={100} step={1} value={sensitivity}
                    onChange={e => setSensitivity(Number(e.target.value))}
                    className="w-full h-2 rounded-full appearance-none cursor-pointer"
                    style={{
                      background: `linear-gradient(to right, ${sensColor} ${sensitivity}%, #e2e8f0 ${sensitivity}%)`,
                      accentColor: sensColor,
                    }}
                  />
                  <div className="flex justify-between mt-1.5">
                    {['Conservative', 'Cautious', 'Balanced', 'Aggressive', 'Max'].map(t => (
                      <span key={t} className="text-[10px] text-slate-400">{t}</span>
                    ))}
                  </div>
                </div>

                <div className="text-xs text-slate-600 bg-slate-50 rounded-lg px-3 py-2.5 mb-3 border-l-4" style={{ borderLeftColor: sensColor }}>
                  {sensDesc}
                </div>

                <div className="flex flex-wrap gap-1.5 mb-3">
                  {SENSITIVITY_PRESETS.map(p => (
                    <button
                      key={p.value}
                      onClick={() => setSensitivity(p.value)}
                      className="px-2.5 py-1 rounded-full border text-xs font-semibold transition-all"
                      style={sensitivity === p.value
                        ? { backgroundColor: p.color, color: 'white', borderColor: p.color }
                        : { borderColor: '#cbd5e1', color: '#475569' }
                      }
                    >
                      {p.label}
                    </button>
                  ))}
                </div>

                <button
                  onClick={() => setShowThresholds(v => !v)}
                  className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors mb-3"
                >
                  <ChevronDown className={cn('w-3 h-3 transition-transform', showThresholds && 'rotate-180')} />
                  {showThresholds ? 'Hide' : 'Show'} confidence thresholds
                </button>

                {showThresholds && (
                  <div className="grid grid-cols-2 gap-2 mb-4 text-xs">
                    {[
                      { label: 'Full-name auto-switch', value: `≥ ${thresholds.local}%` },
                      { label: 'AI auto-switch',        value: `≥ ${thresholds.ai}%` },
                      { label: 'Suggestion toast',      value: `≥ ${thresholds.suggest}%` },
                      { label: 'Partial-word matching', value: thresholds.partial ? `On (min ${thresholds.minWord} chars)` : 'Off' },
                    ].map(({ label, value }) => (
                      <div key={label} className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                        <div className="text-slate-500">{label}</div>
                        <div className="font-bold mt-0.5" style={{ color: sensColor }}>{value}</div>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex items-center gap-3 pt-3 border-t border-border/50">
                  <button
                    onClick={handleSensSave}
                    disabled={sensSaving || !sensChanged}
                    className="px-4 py-2 rounded-lg text-xs font-bold text-white transition-all disabled:opacity-40"
                    style={{ backgroundColor: sensChanged ? sensColor : '#94a3b8' }}
                  >
                    {sensSaving ? 'Saving…' : 'Save Sensitivity'}
                  </button>
                  {sensChanged && !sensSaving && <span className="text-xs text-slate-400">Unsaved changes</span>}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}