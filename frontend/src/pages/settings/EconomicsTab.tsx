// src/pages/settings/EconomicsTab.tsx
// One home for everything that feeds Analytics revenue/cost/margin. The page is
// framed around the two resolution ladders (bill + cost): most-specific wins,
// so it's ordered tiers (main setup) -> firm defaults (fallback) -> overrides.
import { useEffect, useState, type ReactNode } from 'react';
import { DollarSign, Check, RefreshCw, Layers, Briefcase, User, ChevronRight } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import type { OrgInfo, BillingRate, EmployeeCostRate, TeamMember, Client } from './types';
import { SettingsPage, SettingsSection, inputClass, labelClass, primaryBtnClass } from './ui';
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

// ── Precedence badge (ties each section to a ladder rung) ────────────────────
function Badge({ tone, children }: { tone: 'primary' | 'fallback' | 'override'; children: ReactNode }) {
  const cls =
    tone === 'primary'  ? 'bg-primary/8 text-primary border-primary/20'
    : tone === 'fallback' ? 'bg-slate-100 text-slate-400 border-slate-200'
    : 'bg-blue-50 text-blue-600 border-blue-200';
  return (
    <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-full border whitespace-nowrap ${cls}`}>
      {children}
    </span>
  );
}

// ── One rung of a resolution ladder ──────────────────────────────────────────
function Rung({
  rank, name, desc, tone, usual,
}: {
  rank: string; name: string; desc: string;
  tone: 'win-charge' | 'win-pay' | 'mid' | 'fall'; usual?: boolean;
}) {
  const toneCls =
    tone === 'win-charge' ? 'border-primary/30 bg-primary/5'
    : tone === 'win-pay'  ? 'border-blue-200 bg-blue-50/60'
    : tone === 'fall'     ? 'border-dashed border-slate-200 bg-slate-50/70'
    : 'border-slate-200/70 bg-white';
  return (
    <div className={`flex-1 rounded-xl border p-3 ${toneCls}`}>
      <p className="text-[10px] font-extrabold uppercase tracking-wider text-slate-400">{rank}</p>
      <p className="text-[13px] font-bold text-slate-900 mt-0.5">{name}</p>
      <p className="text-[11.5px] text-slate-400 mt-1 leading-snug">{desc}</p>
      {usual && (
        <span className="inline-block mt-2 text-[10px] font-bold uppercase tracking-wide text-primary bg-primary/8 border border-primary/20 rounded-full px-2 py-0.5">
          Most firms live here
        </span>
      )}
    </div>
  );
}

const Arrow = () => (
  <div className="hidden sm:flex items-center px-1.5 text-slate-300 font-bold select-none">→</div>
);

function Track({ dot, label, unit, children }: { dot: string; label: string; unit: string; children: ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2.5">
        <span className={`w-2 h-2 rounded-sm ${dot}`} />
        <span className="text-[12.5px] font-bold text-slate-900">{label}</span>
        <span className="text-[11.5px] font-semibold text-slate-400">{unit}</span>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-stretch gap-2 sm:gap-0">
        {children}
      </div>
    </div>
  );
}

// ── The centerpiece: how a rate is chosen ────────────────────────────────────
function RateLadder({ billDefault, costDefault }: { billDefault: string; costDefault: string }) {
  return (
    <div className="rounded-2xl border border-slate-200/70 p-4 sm:p-5">
      <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Start here</p>
      <p className="text-[15px] font-extrabold tracking-[-0.01em] text-slate-900 mt-0.5">How a rate is chosen</p>
      <p className="text-[12px] text-slate-500 mt-1 mb-4 leading-snug">
        For every tracked block, Analytics walks each ladder left → right and stops at the first rate that's set.
        You don't need to fill all three — just the level you care about.
      </p>

      <div className="space-y-4">
        <Track dot="bg-primary" label="What you charge" unit="· bill $/hr → revenue">
          <Rung tone="win-charge" rank="1 · Most specific" name="Client rate"
            desc="A rate set for a specific client (or client + task)." />
          <Arrow />
          <Rung tone="mid" usual rank="2 · If none above" name="Tier bill rate"
            desc="The bill rate on the person's seniority tier." />
          <Arrow />
          <Rung tone="fall" rank="3 · Fallback" name={`Firm default · $${billDefault}`}
            desc="Used only when neither above is set." />
        </Track>

        <Track dot="bg-blue-500" label="What you pay" unit="· cost $/hr → margin">
          <Rung tone="win-pay" rank="1 · Most specific" name="Per-person cost"
            desc="An exact loaded cost set for one employee." />
          <Arrow />
          <Rung tone="mid" usual rank="2 · If none above" name="Tier cost"
            desc="The cost rate on the person's seniority tier." />
          <Arrow />
          <Rung tone="fall" rank="3 · Fallback" name={`Firm default · $${costDefault}`}
            desc="Used only when neither above is set." />
        </Track>
      </div>

      <div className="flex items-start gap-2 mt-4 pt-3.5 border-t border-slate-100 text-[12px] text-slate-500 leading-snug">
        <span aria-hidden>💡</span>
        <span>
          <span className="font-semibold text-slate-700">Bill</span> and{' '}
          <span className="font-semibold text-slate-700">cost</span> are separate ladders — one drives revenue,
          the other margin. Set tiers once and most people are fully covered.
        </span>
      </div>
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
    <SettingsPage
      title="Economics"
      subtitle="Set what you charge and what you pay so Analytics can show revenue, cost, and margin."
    >
      {/* How a rate is chosen — read this first */}
      <RateLadder billDefault={form.billing_rate_default} costDefault={form.cost_rate_default} />

      <div className="space-y-4 mt-4">
        {/* 1 — Tiers (the main setup; self-contained, loads its own data) */}
        <SettingsSection
          icon={<Layers className="w-4 h-4 text-primary" />}
          title="Tiers & assignments"
          sub="Set cost (what you pay) and bill (what you charge) per seniority tier, then assign people. This covers most of your team in one place."
          actions={<Badge tone="primary">Level 2 · main setup</Badge>}
        >
          <div className="-mt-2">
            <CostTiers onSuccess={onSuccess} onError={onError} />
          </div>
        </SettingsSection>

        {/* 2 — Firm defaults (the fallback) */}
        <SettingsSection
          tint
          icon={<DollarSign className="w-4 h-4 text-primary" />}
          title="Firm defaults"
          sub="The safety net — used only when a block has no client rate, no tier, and no per-person override."
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
              <p className="text-[11px] text-slate-400 mt-1">Available hours/week per person. Denominator for utilization.</p>
            </div>
          </div>
          <button onClick={saveDefaults} disabled={saving} className={`${primaryBtnClass} mt-4`}>
            {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Save Defaults
          </button>
        </SettingsSection>

        {/* 3 — Advanced overrides (rare exceptions; collapsed by default) */}
        <details className="group rounded-2xl border border-slate-200/70 overflow-hidden">
          <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden flex items-center gap-3 p-4 sm:px-5 hover:bg-slate-50/60 transition-colors">
            <ChevronRight className="w-4 h-4 text-slate-400 shrink-0 transition-transform group-open:rotate-90" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[14px] font-bold text-slate-900">Advanced overrides</span>
                <Badge tone="override">Level 1 · exceptions</Badge>
              </div>
              <p className="text-[12px] text-slate-400 mt-0.5 leading-snug">
                Rare exceptions that beat the tier — a special client rate, or one person's exact cost. Skip unless you need them.
              </p>
            </div>
          </summary>

          <div className="px-4 sm:px-5 pb-5 space-y-4">
            {/* Client bill-rate overrides — charge side */}
            <div className="rounded-xl border border-slate-200/70 p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[13px] font-bold text-slate-900 flex items-center gap-1.5">
                  <Briefcase className="w-3.5 h-3.5 text-slate-300" /> Client bill-rate overrides
                </p>
                <span className="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full border bg-primary/8 text-primary border-primary/20 whitespace-nowrap">
                  Charge side
                </span>
              </div>
              <p className="text-[12px] text-slate-500 mt-1.5 mb-3 leading-snug">
                Use when a specific client is billed at a rate different from the tier. Beats the tier bill rate for that client only.
              </p>
              <BillingRatesTab
                rates={billingRates} users={users} clients={clients}
                orgDefaultRate={orgInfo?.billing_rate_default || '150.00'}
                onRefresh={onRefresh} onSuccess={onSuccess} onError={onError}
              />
            </div>

            {/* Per-person cost overrides — pay side (admin only) */}
            {isAdmin && (
              <div className="rounded-xl border border-slate-200/70 p-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[13px] font-bold text-slate-900 flex items-center gap-1.5">
                    <User className="w-3.5 h-3.5 text-slate-300" /> Per-person cost overrides
                  </p>
                  <span className="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full border bg-blue-50 text-blue-600 border-blue-200 whitespace-nowrap">
                    Pay side
                  </span>
                </div>
                <p className="text-[12px] text-slate-500 mt-1.5 mb-3 leading-snug">
                  Use when one employee's loaded cost isn't captured by their tier. Beats the tier cost for that person only.
                </p>
                <EmployeeCostRatesTab
                  rates={employeeCostRates} users={users}
                  onRefresh={onRefresh} onSuccess={onSuccess} onError={onError}
                />
              </div>
            )}
          </div>
        </details>
      </div>
    </SettingsPage>
  );
}
