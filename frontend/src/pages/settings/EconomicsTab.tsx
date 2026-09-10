// src/pages/settings/EconomicsTab.tsx
// One place for everything Analytics uses for revenue, cost, and margin:
// tiers (main setup), per-client rate overrides, and firm-wide defaults.
import { useEffect, useState } from 'react';
import { DollarSign, Check, RefreshCw, Layers, Briefcase, Upload, Receipt, Tag, CalendarDays, Gauge, ClipboardCheck } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import type { OrgInfo, BillingRate, EmployeeCostRate, TeamMember, Client } from './types';
import { SettingsPage, SettingsSection, inputClass, labelClass, primaryBtnClass, secondaryBtnClass } from './ui';
import CostTiers from './CostTiers';
import WorkCalendarSettings from './WorkCalendarSettings';
import BillingRatesTab from './BillingRatesTab';
import ClientFlatFeeTab from './ClientFlatFeeTab';
import TaskTypeRatesTab from './TaskTypeRatesTab';
import EngagementBudgetsTab from './EngagementBudgetsTab';
import SetupReadiness from './SetupReadiness';
import EconomicsImportModal from './EconomicsImportModal';

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

export default function EconomicsTab({
  orgInfo, billingRates, users, clients,
  currentUserRole, onUpdateOrg, onRefresh, onSuccess, onError,
}: Props) {
  const isAdmin = currentUserRole === 'admin' || currentUserRole === 'owner';
  const [saving, setSaving] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // Accordion: at most one section open at a time.
  const [openSection, setOpenSection] = useState<string | null>(null);
  const acc = (id: string) => ({
    collapsible: true as const,
    open: openSection === id,
    onToggle: () => setOpenSection(s => (s === id ? null : id)),
  });
  const [form, setForm] = useState({
    billing_rate_default: '150.00', cost_rate_default: '75.00', payroll_burden_multiplier: '1.00', target_utilization: '75',
    capacity_hours_per_week: '40',
  });

  useEffect(() => {
    if (orgInfo) {
      setForm({
        billing_rate_default: orgInfo.billing_rate_default || '150.00',
        cost_rate_default: orgInfo.cost_rate_default || '75.00',
        payroll_burden_multiplier: orgInfo.payroll_burden_multiplier || '1.00',
        target_utilization: orgInfo.target_utilization || '75',
        capacity_hours_per_week: orgInfo.capacity_hours_per_week || '40',
      });
    }
  }, [orgInfo]);

  // Show the multiplier's effect on a real number — "1.25x" means nothing on
  // its own, "$25.00 wage becomes $31.25" is the thing an owner can sanity-check.
  // The two defaults are only meaningful against each other. Org 21 sat at a
  // $75 bill rate with a $75 wage default and a 1.15 burden — an $86.25 cost
  // against a $75 rate, a guaranteed loss on anyone who fell through to it, and
  // nothing on screen said so.
  const impliedMargin = (() => {
    const bill = parseFloat(form.billing_rate_default);
    const wage = parseFloat(form.cost_rate_default);
    const b = parseFloat(form.payroll_burden_multiplier) || 1;
    if (!bill || !wage) return null;
    const loaded = wage * b;
    return { loaded, pct: ((bill - loaded) / bill) * 100 };
  })();

  const burdenHint = (() => {
    const b = parseFloat(form.payroll_burden_multiplier);
    if (!b || b === 1) return 'Rates you enter are already fully loaded.';
    const wage = parseFloat(form.cost_rate_default);
    if (!wage) return `Every cost rate is multiplied by ${b}.`;
    return `A $${wage.toFixed(2)} wage costs $${(wage * b).toFixed(2)}.`;
  })();

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
      actions={isAdmin ? (
        <button onClick={() => setShowImport(true)} className={secondaryBtnClass}>
          <Upload className="w-3.5 h-3.5" /> Import CSV
        </button>
      ) : undefined}
    >
      {showImport && (
        <EconomicsImportModal
          onClose={() => setShowImport(false)}
          onImported={() => { setReloadKey(k => k + 1); onRefresh(); onSuccess('Roster imported'); }}
        />
      )}

      <div className="space-y-4">
        {/* Tiers — the main setup */}
        <SettingsSection
          {...acc('readiness')}
          icon={<ClipboardCheck className="w-4 h-4 text-primary" />}
          title="Setup checklist"
          sub="What we have from you, and what's still missing."
        >
          <SetupReadiness />
        </SettingsSection>

        <SettingsSection
          {...acc('tiers')}
          icon={<Layers className="w-4 h-4 text-primary" />}
          title="Tiers & assignments"
          sub="Set cost and bill per tier, then assign people."
        >
          <div className="-mt-2">
            <CostTiers key={reloadKey} onSuccess={onSuccess} onError={onError} />
          </div>
        </SettingsSection>

        {/* Work calendar — the capacity denominator for utilization */}
        <SettingsSection
          {...acc('workcalendar')}
          icon={<CalendarDays className="w-4 h-4 text-primary" />}
          title="Work calendar & capacity"
          sub="Hours/day, working days, summer Fridays, holidays, PTO — drives utilization capacity."
        >
          <div className="-mt-2">
            <WorkCalendarSettings onSuccess={onSuccess} onError={onError} />
          </div>
        </SettingsSection>

        {/* Client rates — per-client hourly override */}
        <SettingsSection
          {...acc('rates')}
          icon={<Briefcase className="w-4 h-4 text-primary" />}
          title="Custom bill rates"
          sub="Set a bill rate for a specific client, employee, or both."
        >
          <BillingRatesTab
            rates={billingRates} users={users} clients={clients}
            orgDefaultRate={orgInfo?.billing_rate_default || '150.00'}
            onRefresh={onRefresh} onSuccess={onSuccess} onError={onError}
          />
        </SettingsSection>

        {/* Flat-fee & retainer — per-client billing arrangement */}
        <SettingsSection
          {...acc('flatfee')}
          icon={<Receipt className="w-4 h-4 text-primary" />}
          title="Flat-fee & retainer clients"
          sub="Bill a client a fixed fee instead of hourly. Feeds flat-fee revenue in Analytics."
        >
          <ClientFlatFeeTab onSuccess={onSuccess} onError={onError} />
        </SettingsSection>

        {/* Task types — billable flag + default rate */}
        <SettingsSection
          {...acc('tasktypes')}
          icon={<Tag className="w-4 h-4 text-primary" />}
          title="Task types"
          sub="Mark which task types count as billable and set an optional default rate."
        >
          <TaskTypeRatesTab onSuccess={onSuccess} onError={onError} />
        </SettingsSection>

        <SettingsSection
          {...acc('engagement_budgets')}
          icon={<Gauge className="w-4 h-4 text-primary" />}
          title="Engagement budgets"
          sub="What each recurring job is worth, so burn-vs-pace means something."
        >
          <EngagementBudgetsTab onSuccess={onSuccess} onError={onError} />
        </SettingsSection>

        {/* Firm defaults — the fallback */}
        <SettingsSection
          {...acc('defaults')}
          icon={<DollarSign className="w-4 h-4 text-primary" />}
          title="Firm defaults"
          sub="Used when no tier or client rate applies."
        >
          <div className={`grid gap-4 ${isAdmin ? 'sm:grid-cols-2 lg:grid-cols-5' : 'sm:grid-cols-3'}`}>
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
                <label className={labelClass}>Blended Wage / Hour</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                  <input type="number" step="0.01" min="0" value={form.cost_rate_default}
                    onChange={e => setForm({ ...form, cost_rate_default: e.target.value })}
                    className={`${inputClass} pl-7`} />
                </div>
                <p className="text-[11px] text-slate-400 mt-1">
                  A wage, like every per-person rate. Burden applies on top.
                </p>
              </div>
            )}
            {isAdmin && (
              <div>
                <label className={labelClass}>Payroll Burden</label>
                <div className="relative">
                  <input type="number" step="0.05" min="1" max="3" value={form.payroll_burden_multiplier}
                    onChange={e => setForm({ ...form, payroll_burden_multiplier: e.target.value })}
                    className={`${inputClass} pr-7`} />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">×</span>
                </div>
                <p className="text-[11px] text-slate-400 mt-1">
                  {burdenHint}
                </p>
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

          {isAdmin && impliedMargin && (
            <div
              className={`mt-3 rounded-lg px-3 py-2 text-[12px] ${
                impliedMargin.pct <= 0
                  ? 'bg-rose-50 text-rose-700 border border-rose-200'
                  : 'bg-slate-50 text-slate-600 border border-slate-200'
              }`}
            >
              {impliedMargin.pct <= 0 ? (
                <>
                  <strong>These defaults lose money.</strong> A $
                  {parseFloat(form.cost_rate_default).toFixed(2)} wage costs $
                  {impliedMargin.loaded.toFixed(2)} loaded, against a $
                  {parseFloat(form.billing_rate_default).toFixed(2)} bill rate —{' '}
                  {impliedMargin.pct.toFixed(1)}% margin on anyone who falls
                  through to them. Lower the wage or raise the bill rate.
                </>
              ) : (
                <>
                  Implied margin on the defaults:{' '}
                  <strong>{impliedMargin.pct.toFixed(1)}%</strong> — $
                  {impliedMargin.loaded.toFixed(2)} loaded cost against a $
                  {parseFloat(form.billing_rate_default).toFixed(2)} bill rate.
                </>
              )}
            </div>
          )}

          <button onClick={saveDefaults} disabled={saving} className={`${primaryBtnClass} mt-4`}>
            {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Save Defaults
          </button>
        </SettingsSection>
      </div>
    </SettingsPage>
  );
}
