// src/components/BulkBillingModal.tsx
// Apply billing-profile fields to many selected clients at once (owner/admin).
// Only the fields the user actually sets are sent — each control defaults to
// "leave unchanged" so you can bulk-set e.g. the billing system across 30
// clients without touching their type. Per-client details stay in the
// single-client Billing modal.
import { useState } from 'react';
import { X, RefreshCw, Receipt } from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

const UNCHANGED = '__keep__';

const FIELD = 'w-full px-3 py-2 text-sm border border-border/60 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary/40 transition-all';
const LABEL = 'block text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5';

const BulkBillingModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  clientIds: number[];
  onSuccess: (m: string) => void;
  onError: (m: string) => void;
}> = ({ isOpen, onClose, clientIds, onSuccess, onError }) => {
  const [billingType, setBillingType] = useState<string>(UNCHANGED);
  const [billingSystem, setBillingSystem] = useState<string>(UNCHANGED);
  const [flatAmount, setFlatAmount] = useState<string>('');
  const [flatPeriod, setFlatPeriod] = useState<string>('');
  const [defaultItem, setDefaultItem] = useState<string>('');
  const [saving, setSaving] = useState(false);

  if (!isOpen) return null;

  const n = clientIds.length;

  const build = () => {
    const body: Record<string, unknown> = { client_ids: clientIds };
    if (billingType !== UNCHANGED) body.billing_type = billingType;
    if (billingSystem !== UNCHANGED) body.billing_system = billingSystem;
    if (billingType === 'flat_fee') {
      if (flatAmount.trim()) body.flat_amount = flatAmount.trim();
      if (flatPeriod) body.flat_period = flatPeriod;
    }
    if (defaultItem.trim()) body.default_item_name = defaultItem.trim();
    return body;
  };

  const nothingToApply = () => {
    const b = build();
    // client_ids is always present; need at least one real field.
    return Object.keys(b).length <= 1;
  };

  const apply = async () => {
    if (nothingToApply()) {
      onError('Pick at least one field to apply.');
      return;
    }
    setSaving(true);
    try {
      const res = await safeFetchJson<{ updated: number }>(
        `${API_BASE}/billing/clients/bulk-billing-profile/`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(build()) }
      );
      onSuccess(`Billing applied to ${res.updated} client${res.updated !== 1 ? 's' : ''}`);
      onClose();
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not apply billing settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
          <div className="flex items-center gap-2.5">
            <Receipt className="w-4 h-4 text-primary" />
            <div>
              <h2 className="text-base font-bold text-slate-900">Set billing · {n} client{n !== 1 ? 's' : ''}</h2>
              <p className="text-xs text-slate-400">Only the fields you set below are changed; the rest stay as-is per client.</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-4 h-4 text-slate-400" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={LABEL}>Billing type</label>
              <select value={billingType} onChange={e => setBillingType(e.target.value)} className={FIELD}>
                <option value={UNCHANGED}>— leave unchanged —</option>
                <option value="hourly">Hourly</option>
                <option value="flat_fee">Flat fee / retainer</option>
                <option value="non_billable">Non-billable</option>
              </select>
            </div>
            <div>
              <label className={LABEL}>Billing system</label>
              <select value={billingSystem} onChange={e => setBillingSystem(e.target.value)} className={FIELD}>
                <option value={UNCHANGED}>— leave unchanged —</option>
                <option value="qb_desktop">QuickBooks Desktop</option>
                <option value="qbo">QuickBooks Online</option>
                <option value="xero">Xero</option>
                <option value="csv_other">CSV / other</option>
              </select>
            </div>
          </div>

          {billingType === 'flat_fee' && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={LABEL}>Flat amount <span className="text-slate-400 normal-case font-normal">(optional)</span></label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                  <input type="number" min="0" step="0.01" value={flatAmount} onChange={e => setFlatAmount(e.target.value)} placeholder="Same for all" className={cn(FIELD, 'pl-7 tabular-nums')} />
                </div>
              </div>
              <div>
                <label className={LABEL}>Period <span className="text-slate-400 normal-case font-normal">(optional)</span></label>
                <select value={flatPeriod} onChange={e => setFlatPeriod(e.target.value)} className={FIELD}>
                  <option value="">— leave unchanged —</option>
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                  <option value="annual">Annual</option>
                  <option value="per_project">Per project</option>
                </select>
              </div>
            </div>
          )}

          <div>
            <label className={LABEL}>Default service / item <span className="text-slate-400 normal-case font-normal">(optional)</span></label>
            <input value={defaultItem} onChange={e => setDefaultItem(e.target.value)} placeholder="Leave blank to skip" className={FIELD} />
          </div>

          <p className="text-xs text-slate-400">
            Tip: bulk-set the common bits (type + system) here, then fine-tune per-client amounts/mapping from each client’s Billing button.
          </p>
        </div>

        <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors">Cancel</button>
          <button onClick={apply} disabled={saving} className="inline-flex items-center gap-2 px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all disabled:opacity-50">
            {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Receipt className="w-4 h-4" />}
            Apply to {n}
          </button>
        </div>
      </div>
    </div>
  );
};

export default BulkBillingModal;
