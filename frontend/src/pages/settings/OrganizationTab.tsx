// src/pages/settings/OrganizationTab.tsx
import { useEffect, useState } from 'react';
import {
  Sparkles, Pencil, Check, RefreshCw,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import type { OrgInfo, PlanType } from './types';
import { SettingsPage, SettingsSection, inputClass, labelClass, primaryBtnClass, secondaryBtnClass } from './ui';

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
    <SettingsPage
      title="Organization"
      subtitle="Your firm's name and billing contact details."
      actions={!editing && (
        <button onClick={() => setEditing(true)} className={secondaryBtnClass}>
          <Pencil className="w-3.5 h-3.5" /> Edit
        </button>
      )}
    >
      {/* Org info — edit or view */}
      {editing ? (
        <SettingsSection title="Edit organization info">
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'Organization Name', key: 'name', type: 'text' },
              { label: 'Billing Email',     key: 'billing_email', type: 'email' },
              { label: 'Billing Contact',   key: 'billing_contact', type: 'text' },
            ].map(({ label, key, type }) => (
              <div key={key} className={key === 'name' ? 'col-span-2 sm:col-span-1' : ''}>
                <label className={labelClass}>{label}</label>
                <input
                  type={type}
                  value={(form as any)[key]}
                  onChange={e => setForm({ ...form, [key]: e.target.value })}
                  className={inputClass}
                />
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-4 pt-4 border-t border-slate-200/70">
            <button onClick={handleOrgSave} disabled={saving} className={primaryBtnClass}>
              {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              Save Changes
            </button>
            <button onClick={() => setEditing(false)} className={secondaryBtnClass}>
              Cancel
            </button>
          </div>
        </SettingsSection>
      ) : (
        <div className="space-y-4">
          <SettingsSection>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[
                { label: 'Organization',    value: orgInfo.name },
                { label: 'Billing Email',   value: orgInfo.billing_email || '—' },
                { label: 'Billing Contact', value: orgInfo.billing_contact || '—' },
              ].map(({ label, value }) => (
                <div key={label} className="min-w-0">
                  <p className={labelClass}>{label}</p>
                  <p className="font-semibold text-slate-900 text-sm truncate">{value}</p>
                </div>
              ))}
            </div>
          </SettingsSection>
          <div className={cn(
            'rounded-2xl border px-4 py-3 flex items-center justify-between',
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
    </SettingsPage>
  );
}