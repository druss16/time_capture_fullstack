// src/components/ClientBillingProfilePanel.tsx
// Per-client billing profile editor (owner/admin only). Rendered inside the
// ClientsTab "Billing" modal. The profile is the coordination layer the
// timesheet→billing export reads: how the client is billed (hourly / flat-fee /
// non-billable), which system the time lands in, and the customer/item mapping.
// Hourly RATES are not edited here (one source of truth = Billing Rates); the
// effective rate is shown read-only.
import { useEffect, useState } from 'react';
import { Loader2, RefreshCw, Save, Info } from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

type BillingType = 'hourly' | 'flat_fee' | 'non_billable';
type BillingSystem = 'qb_desktop' | 'qbo' | 'xero' | 'csv_other';
type FlatPeriod = '' | 'monthly' | 'quarterly' | 'annual' | 'per_project';

interface BillingProfile {
  billing_type: BillingType;
  flat_amount: string | null;
  flat_period: FlatPeriod;
  billing_system: BillingSystem;
  external_customer_id: string;
  external_customer_name: string;
  default_item_name: string;
  notes: string;
  counts_billable_utilization: boolean;
  fallback_customer_id: string | null;
  effective_hourly_rate: string | null;
}

const BILLING_TYPES: { id: BillingType; label: string; hint: string }[] = [
  { id: 'hourly', label: 'Hourly', hint: 'Bill captured hours × rate' },
  { id: 'flat_fee', label: 'Flat fee / retainer', hint: 'Fixed amount per period' },
  { id: 'non_billable', label: 'Non-billable', hint: 'Tracked, never billed' },
];
const SYSTEMS: { id: BillingSystem; label: string }[] = [
  { id: 'qb_desktop', label: 'QuickBooks Desktop' },
  { id: 'qbo', label: 'QuickBooks Online' },
  { id: 'xero', label: 'Xero' },
  { id: 'csv_other', label: 'CSV / other' },
];
const PERIODS: { id: FlatPeriod; label: string }[] = [
  { id: 'monthly', label: 'Monthly' },
  { id: 'quarterly', label: 'Quarterly' },
  { id: 'annual', label: 'Annual' },
  { id: 'per_project', label: 'Per project' },
];

const FIELD = 'w-full px-3 py-2 text-sm border border-border/60 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary/40 transition-all';
const LABEL = 'block text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5';

const ClientBillingProfilePanel: React.FC<{
  clientId: number;
  canManage: boolean;
  onSuccess: (m: string) => void;
  onError: (m: string) => void;
}> = ({ clientId, canManage, onSuccess, onError }) => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [p, setP] = useState<BillingProfile | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    safeFetchJson<BillingProfile>(`${API_BASE}/billing/clients/${clientId}/billing-profile/`)
      .then(data => { if (alive) setP(data); })
      .catch(e => { if (alive) onError(e instanceof Error ? e.message : 'Could not load billing profile'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [clientId]);

  const set = <K extends keyof BillingProfile>(k: K, v: BillingProfile[K]) =>
    setP(prev => (prev ? { ...prev, [k]: v } : prev));

  const save = async () => {
    if (!p) return;
    setSaving(true);
    try {
      const body = {
        billing_type: p.billing_type,
        flat_amount: p.billing_type === 'flat_fee' && p.flat_amount ? p.flat_amount : null,
        flat_period: p.billing_type === 'flat_fee' ? p.flat_period : '',
        billing_system: p.billing_system,
        external_customer_id: p.external_customer_id,
        external_customer_name: p.external_customer_name,
        default_item_name: p.default_item_name,
        counts_billable_utilization: p.counts_billable_utilization,
        notes: p.notes,
      };
      const updated = await safeFetchJson<BillingProfile>(
        `${API_BASE}/billing/clients/${clientId}/billing-profile/`,
        { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      );
      setP(updated);
      onSuccess('Billing profile saved');
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not save billing profile');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-slate-400"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  }
  if (!p) {
    return <div className="py-8 text-center text-sm text-slate-500">Couldn’t load this client’s billing profile.</div>;
  }

  const disabled = !canManage;

  return (
    <div className="space-y-6">
      {/* Billing type */}
      <div>
        <label className={LABEL}>Billing type</label>
        <div className="grid grid-cols-3 gap-2">
          {BILLING_TYPES.map(t => (
            <button
              key={t.id}
              disabled={disabled}
              onClick={() => set('billing_type', t.id)}
              className={cn(
                'text-left rounded-xl border p-3 transition-all disabled:opacity-60',
                p.billing_type === t.id ? 'border-primary bg-primary/5 ring-1 ring-primary/30' : 'border-border/60 hover:border-border'
              )}
            >
              <div className="text-sm font-semibold text-slate-800">{t.label}</div>
              <div className="text-[11px] text-slate-400 mt-0.5 leading-snug">{t.hint}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Hourly → effective rate (read-only, sourced from Billing Rates) */}
      {p.billing_type === 'hourly' && (
        <div className="flex items-start gap-2 rounded-lg bg-slate-50 border border-border/50 px-3 py-2.5">
          <Info className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
          <div className="text-xs text-slate-600">
            Effective hourly rate:{' '}
            <b className="tabular-nums text-slate-800">{p.effective_hourly_rate ? `$${p.effective_hourly_rate}` : 'not set'}</b>.
            {' '}Rates are managed in <span className="font-semibold">Settings → Billing Rates</span> (client &gt; task &gt; org default).
          </div>
        </div>
      )}

      {/* Flat fee → amount + period */}
      {p.billing_type === 'flat_fee' && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={LABEL}>Flat amount</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
              <input
                type="number" min="0" step="0.01" disabled={disabled}
                value={p.flat_amount ?? ''}
                onChange={e => set('flat_amount', e.target.value)}
                placeholder="0.00"
                className={cn(FIELD, 'pl-7 tabular-nums')}
              />
            </div>
          </div>
          <div>
            <label className={LABEL}>Period</label>
            <select disabled={disabled} value={p.flat_period} onChange={e => set('flat_period', e.target.value as FlatPeriod)} className={FIELD}>
              <option value="">Select…</option>
              {PERIODS.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
            </select>
          </div>
        </div>
      )}

      {/* Target system */}
      {p.billing_type !== 'non_billable' && (
        <div>
          <label className={LABEL}>Billing system <span className="text-slate-400 normal-case font-normal">(sets the export format)</span></label>
          <select disabled={disabled} value={p.billing_system} onChange={e => set('billing_system', e.target.value as BillingSystem)} className={FIELD}>
            {SYSTEMS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      )}

      {/* Customer + item mapping */}
      {p.billing_type !== 'non_billable' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={LABEL}>Customer / Job ID</label>
              <input
                disabled={disabled} value={p.external_customer_id}
                onChange={e => set('external_customer_id', e.target.value)}
                placeholder={p.fallback_customer_id ? `Default: ${p.fallback_customer_id}` : 'e.g. Customer:Job'}
                className={FIELD}
              />
              {p.fallback_customer_id && (
                <p className="text-[11px] text-slate-400 mt-1">Leave blank to use the linked QuickBooks ID ({p.fallback_customer_id}).</p>
              )}
            </div>
            <div>
              <label className={LABEL}>Customer name <span className="text-slate-400 normal-case font-normal">(optional)</span></label>
              <input disabled={disabled} value={p.external_customer_name} onChange={e => set('external_customer_name', e.target.value)} placeholder="Display name in billing system" className={FIELD} />
            </div>
          </div>
          <div>
            <label className={LABEL}>Default service / item <span className="text-slate-400 normal-case font-normal">(optional)</span></label>
            <input disabled={disabled} value={p.default_item_name} onChange={e => set('default_item_name', e.target.value)} placeholder="Falls back to the task type's mapped item" className={FIELD} />
          </div>
        </div>
      )}

      {/* Billable-effort toggle — count toward utilization without invoicing */}
      <label className="flex items-start gap-2.5 rounded-lg border border-border/60 bg-slate-50/50 px-3 py-2.5 cursor-pointer">
        <input
          type="checkbox" disabled={disabled}
          checked={!!p.counts_billable_utilization}
          onChange={e => set('counts_billable_utilization', e.target.checked)}
          className="h-4 w-4 mt-0.5 accent-primary"
        />
        <span className="text-[13px] text-slate-700 leading-snug">
          <span className="font-semibold">Count as billable for utilization</span>
          <span className="block text-[12px] text-slate-500">
            Counts this client's time as billable in utilization analytics even though it isn't
            invoiced through the system (e.g. tax work billed outside, parked under an Internal client).
            Doesn't touch billing or export.
          </span>
        </span>
      </label>

      {/* Notes */}
      <div>
        <label className={LABEL}>Notes <span className="text-slate-400 normal-case font-normal">(optional)</span></label>
        <textarea disabled={disabled} value={p.notes} onChange={e => set('notes', e.target.value)} rows={2} placeholder="Anything the billing admin should know…" className={cn(FIELD, 'resize-none')} />
      </div>

      {canManage && (
        <div className="flex justify-end pt-1">
          <button
            onClick={save} disabled={saving}
            className="inline-flex items-center gap-2 px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all disabled:opacity-50"
          >
            {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save billing profile
          </button>
        </div>
      )}
    </div>
  );
};

export default ClientBillingProfilePanel;
