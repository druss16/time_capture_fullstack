// src/pages/settings/EconomicsTab.tsx
// One home for everything that feeds Analytics revenue/cost/margin, ordered by
// the resolution hierarchy: firm defaults -> tiers -> client rates -> per-person.
import { useEffect, useState, type ReactNode } from 'react';
import { DollarSign, Check, RefreshCw, Layers, Briefcase, User } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import type { OrgInfo, BillingRate, EmployeeCostRate, TeamMember, Client } from './types';
import CostTiers from './CostTiers';
import BillingRatesTab from './BillingRatesTab';
import EmployeeCostRatesTab from './EmployeeCostRatesTab';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface Props {
  orgInfo: OrgInfo | null;
  billingRates: BillingRate[];
  employeeCostRates: EmployeeCostRate[];
  users: TeamMember[];
  clients: Client[];
  currentUserRole: string;
  onUpdateOrg: (org: OrgInfo) => void;
  onRefresh: () => void;
  onSuccess: (m: string) => void;
  onError: (m: string) => void;
}

function SectionHeader({ icon, title, sub }: { icon: ReactNode; title: string; sub: string }) {
  return (
    <div className="mb-3">
      <p className="text-sm font-extrabold text-slate-900 flex items-center gap-2">{icon}{title}</p>
      <p className="text-xs text-slate-400 mt-0.5">{sub}</p>
    </div>
  );
}

export default function EconomicsTab({
  orgInfo, billingRates, employeeCostRates, users, clients,
  currentUserRole, onUpdateOrg, onRefresh, onSuccess, onError,
}: Props) {
  const isAdmin = currentUserRole === 'admin' || currentUserRole === 'owner';
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    billing_rate_default: '150.00', cost_rate_default: '75.00', target_utilization: '75',
    capacity_hours_per_week: '40',
  });

  useEffect(() => {
    if (orgInfo) {
      setForm({
        billing_rate_default: orgInfo.billing_rate_default || '150.00',
        cost_rate_default: orgInfo.cost_rate_default || '75.00',
        target_utilization: orgInfo.target_utilization || '75',
        capacity_hours_per_week: orgInfo.capacity_hours_per_week || '40',
      });
    }
  }, [orgInfo]);

  const saveDefaults = async () => {
    setSaving(true);
    try {
      const updated = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      onUpdateOrg(updated);
      onSuccess('Firm defaults updated');
    } catch (e: any) {
      onError(e?.message || 'Failed to update defaults');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-primary" /> Economics
        </h2>
      </div>
      <p className="text-xs text-slate-400 mb-6 -mt-4">
        Everything the Analytics dashboard uses for revenue, cost, and margin. Rates resolve most-specific
        first: a block or client rate wins, then the tier rate, then these firm defaults.
      </p>

      {/* 1 — Firm defaults */}
      <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-5 mb-6">
        <SectionHeader
          icon={<DollarSign className="w-4 h-4 text-primary" />}
          title="Firm defaults"
          sub="Fallback rates and your utilization target — used when nothing more specific is set."
        />
        <div className={`grid gap-4 ${isAdmin ? 'sm:grid-cols-4' : 'sm:grid-cols-3'}`}>
          <div>
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Default Bill Rate</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
              <input type="number" step="0.01" min="0" value={form.billing_rate_default}
                onChange={e => setForm({ ...form, billing_rate_default: e.target.value })}
                className="w-full pl-7 pr-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white" />
            </div>
          </div>
          {isAdmin && (
            <div>
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Blended Cost / Hour</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                <input type="number" step="0.01" min="0" value={form.cost_rate_default}
                  onChange={e => setForm({ ...form, cost_rate_default: e.target.value })}
                  className="w-full pl-7 pr-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white" />
              </div>
            </div>
          )}
          <div>
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Target Billable %</label>
            <div className="relative">
              <input type="number" step="1" min="0" max="100" value={form.target_utilization}
                onChange={e => setForm({ ...form, target_utilization: e.target.value })}
                className="w-full pl-3 pr-7 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white" />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">%</span>
            </div>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Capacity (hrs/wk)</label>
            <input type="number" step="0.5" min="0" max="168" value={form.capacity_hours_per_week}
              onChange={e => setForm({ ...form, capacity_hours_per_week: e.target.value })}
              className="w-full px-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white" />
            <p className="text-[11px] text-slate-400 mt-1">Available hours/week per person. Denominator for utilization.</p>
          </div>
        </div>
        <button onClick={saveDefaults} disabled={saving}
          className="flex items-center gap-1.5 px-4 py-2 mt-4 bg-primary text-white rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-50 transition-all">
          {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
          Save Defaults
        </button>
      </div>

      {/* 2 — Cost & bill tiers (self-contained; loads its own data) */}
      <div className="rounded-xl border border-slate-200 p-5 mb-6">
        <SectionHeader
          icon={<Layers className="w-4 h-4 text-primary" />}
          title="Cost & bill tiers"
          sub="Set cost (what you pay) and bill (what you charge) per seniority tier, then assign people."
        />
        <div className="-mt-2">
          <CostTiers onSuccess={onSuccess} onError={onError} />
        </div>
      </div>

      {/* 3 — Client-specific rates (advanced) */}
      <div className="rounded-xl border border-slate-200 p-5 mb-6">
        <SectionHeader
          icon={<Briefcase className="w-4 h-4 text-primary" />}
          title="Client-specific rates"
          sub="Per-client / per-person bill rates. These override the tier bill rate for those clients."
        />
        <BillingRatesTab
          rates={billingRates} users={users} clients={clients}
          orgDefaultRate={orgInfo?.billing_rate_default || '150.00'}
          onRefresh={onRefresh} onSuccess={onSuccess} onError={onError}
        />
      </div>

      {/* 4 — Per-person cost overrides (advanced) */}
      {isAdmin && (
        <div className="rounded-xl border border-slate-200 p-5">
          <SectionHeader
            icon={<User className="w-4 h-4 text-primary" />}
            title="Per-person cost overrides"
            sub="Exact loaded cost for a specific employee. Overrides their tier cost."
          />
          <EmployeeCostRatesTab
            rates={employeeCostRates} users={users}
            onRefresh={onRefresh} onSuccess={onSuccess} onError={onError}
          />
        </div>
      )}
    </div>
  );
}
