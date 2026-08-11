// src/pages/settings/EconomicsTab.tsx
// Everything that feeds Analytics revenue/cost/margin, framed by the two
// resolution ladders (bill + cost): most-specific wins. Ordered tiers (main
// setup) -> firm defaults (fallback).
import { useEffect, useState, type ReactNode } from 'react';
import { DollarSign, Check, RefreshCw, Layers } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import type { OrgInfo, BillingRate, EmployeeCostRate, TeamMember, Client } from './types';
import { SettingsPage, SettingsSection, inputClass, labelClass, primaryBtnClass } from './ui';
import CostTiers from './CostTiers';

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

// ── Precedence badge ─────────────────────────────────────────────────────────
function Badge({ tone, children }: { tone: 'primary' | 'fallback'; children: ReactNode }) {
  const cls = tone === 'primary'
    ? 'bg-primary/8 text-primary border-primary/20'
    : 'bg-slate-100 text-slate-400 border-slate-200';
  return (
    <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-full border whitespace-nowrap ${cls}`}>
      {children}
    </span>
  );
}

// ── One rung of a ladder (rank + name only) ──────────────────────────────────
function Rung({ rank, name, tone }: { rank: string; name: string; tone: 'win' | 'fall' }) {
  const toneCls = tone === 'win' ? 'border-primary/40 bg-white' : 'border-slate-200/70 bg-transparent';
  return (
    <div className={`flex-1 rounded-xl border px-3 py-2.5 ${toneCls}`}>
      <p className="text-[10px] font-extrabold uppercase tracking-wider text-slate-400">{rank}</p>
      <p className="text-[13px] font-bold text-slate-900 mt-0.5">{name}</p>
    </div>
  );
}

const Arrow = () => (
  <div className="hidden sm:flex items-center px-1.5 text-slate-300 font-bold select-none">→</div>
);

function Track({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span className="w-2 h-2 rounded-sm bg-primary" />
        <span className="text-[12.5px] font-bold text-slate-900">{label}</span>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-stretch gap-2 sm:gap-0">{children}</div>
    </div>
  );
}

function RateLadder({ billDefault, costDefault }: { billDefault: string; costDefault: string }) {
  return (
    <div className="rounded-2xl border border-slate-200/70 bg-[#f7faf9] p-4 sm:p-5">
      <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Start here</p>
      <p className="text-[15px] font-extrabold tracking-[-0.01em] text-slate-900 mt-0.5">How a rate is chosen</p>
      <p className="text-[12px] text-slate-500 mt-1 mb-4">The most specific rate that's set wins — left to right.</p>

      <div className="space-y-3">
        <Track label="What you charge">
          <Rung tone="win" rank="1 · Most specific" name="Client rate" />
          <Arrow />
          <Rung tone="win" rank="2 · Tier" name="Tier bill rate" />
          <Arrow />
          <Rung tone="fall" rank="3 · Fallback" name={`Firm default · $${billDefault}`} />
        </Track>

        <Track label="What you pay">
          <Rung tone="win" rank="1 · Most specific" name="Per-person cost" />
          <Arrow />
          <Rung tone="win" rank="2 · Tier" name="Tier cost" />
          <Arrow />
          <Rung tone="fall" rank="3 · Fallback" name={`Firm default · $${costDefault}`} />
        </Track>
      </div>
    </div>
  );
}

export default function EconomicsTab({
  orgInfo, currentUserRole, onUpdateOrg, onSuccess, onError,
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
    <SettingsPage
      title="Economics"
      subtitle="What Analytics uses for revenue, cost, and margin."
    >
      <RateLadder billDefault={form.billing_rate_default} costDefault={form.cost_rate_default} />

      <div className="space-y-4 mt-4">
        {/* Tiers — the main setup */}
        <SettingsSection
          tint
          icon={<Layers className="w-4 h-4 text-primary" />}
          title="Tiers & assignments"
          sub="Set cost and bill per seniority tier, then assign people."
          actions={<Badge tone="primary">Level 2 · main setup</Badge>}
        >
          <div className="-mt-2">
            <CostTiers onSuccess={onSuccess} onError={onError} />
          </div>
        </SettingsSection>

        {/* Firm defaults — the fallback */}
        <SettingsSection
          icon={<DollarSign className="w-4 h-4 text-primary" />}
          title="Firm defaults"
          sub="Used only when no tier or client rate applies."
          actions={<Badge tone="fallback">Level 3 · fallback</Badge>}
        >
          <div className={`grid gap-4 ${isAdmin ? 'sm:grid-cols-4' : 'sm:grid-cols-3'}`}>
            <div>
              <label className={labelClass}>Default Bill Rate</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                <input type="number" step="0.01" min="0" value={form.billing_rate_default}
                  onChange={e => setForm({ ...form, billing_rate_default: e.target.value })}
                  className={`${inputClass} pl-7`} />
              </div>
            </div>
            {isAdmin && (
              <div>
                <label className={labelClass}>Blended Cost / Hour</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                  <input type="number" step="0.01" min="0" value={form.cost_rate_default}
                    onChange={e => setForm({ ...form, cost_rate_default: e.target.value })}
                    className={`${inputClass} pl-7`} />
                </div>
              </div>
            )}
            <div>
              <label className={labelClass}>Target Billable %</label>
              <div className="relative">
                <input type="number" step="1" min="0" max="100" value={form.target_utilization}
                  onChange={e => setForm({ ...form, target_utilization: e.target.value })}
                  className={`${inputClass} pr-7`} />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">%</span>
              </div>
            </div>
            <div>
              <label className={labelClass}>Capacity (hrs/wk)</label>
              <input type="number" step="0.5" min="0" max="168" value={form.capacity_hours_per_week}
                onChange={e => setForm({ ...form, capacity_hours_per_week: e.target.value })}
                className={inputClass} />
              <p className="text-[11px] text-slate-400 mt-1">Denominator for utilization.</p>
            </div>
          </div>
          <button onClick={saveDefaults} disabled={saving} className={`${primaryBtnClass} mt-4`}>
            {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Save Defaults
          </button>
        </SettingsSection>
      </div>
    </SettingsPage>
  );
}
