// src/pages/settings/OrganizationTab.tsx
import { useEffect, useState } from 'react';
import {
  Building2, DollarSign, Sparkles, Pencil, Check, RefreshCw,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import type { OrgInfo, PlanType } from './types';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

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

  if (!orgInfo) return <div className="text-slate-500 p-4">No organization data</div>;

  const planLabel  = orgPlan === 'executive' ? '💎 Executive' : orgPlan === 'professional' ? '⭐ Professional' : '🚫 No Plan';

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
          <div className={cn(
            'rounded-xl border px-4 py-3 flex items-center justify-between mb-4',
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

          {/* Firm Economics — persists in view mode; powers the Analytics dashboard */}
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-1.5">
              <DollarSign className="w-3 h-3" /> Firm Economics · used by the Analytics dashboard
            </p>
            <div className={cn('grid gap-3', isAdmin ? 'grid-cols-3' : 'grid-cols-2')}>
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                <p className="text-[10px] font-bold text-emerald-600/70 uppercase tracking-widest mb-1">Default Bill Rate</p>
                <p className="text-base font-extrabold text-emerald-700">
                  ${parseFloat(orgInfo.billing_rate_default || '150.00').toFixed(2)}<span className="text-xs font-semibold text-emerald-600/70">/hr</span>
                </p>
              </div>
              {isAdmin && (
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">Blended Cost</p>
                  <p className="text-base font-extrabold text-slate-900">
                    ${parseFloat(orgInfo.cost_rate_default || '75.00').toFixed(2)}<span className="text-xs font-semibold text-slate-400">/hr</span>
                  </p>
                </div>
              )}
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">Target Billable</p>
                <p className="text-base font-extrabold text-slate-900">
                  {parseFloat(orgInfo.target_utilization || '75').toFixed(0)}<span className="text-xs font-semibold text-slate-400">%</span>
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}