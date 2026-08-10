// src/pages/settings/OrganizationTab.tsx
import { useEffect, useState } from 'react';
import {
  Building2, Sparkles, Pencil, Check, RefreshCw,
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
  orgInfo, orgPlan, onUpdate, onSuccess, onError,
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
        </div>
      )}

    </div>
  );
}