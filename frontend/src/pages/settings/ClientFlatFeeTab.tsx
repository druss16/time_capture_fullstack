// src/pages/settings/ClientFlatFeeTab.tsx
// Per-client billing arrangement (ClientBillingProfile) surfaced on Economics:
// billing type + flat-fee/retainer amount + cadence. Feeds flat-fee revenue in
// Analytics. Reuses the existing billing-profile endpoints (same data as the
// Clients tab receipt icon).
import { useEffect, useState } from 'react';
import { Check, RefreshCw } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { primaryBtnClass } from './ui';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface Row { id: number; name: string; billing_type: string; flat_amount: string; flat_period: string; dirty?: boolean; }
interface Props { onSuccess: (m: string) => void; onError: (m: string) => void; }

const PERIODS = [
  { v: 'monthly', label: 'Monthly' },
  { v: 'quarterly', label: 'Quarterly' },
  { v: 'annual', label: 'Annual' },
  { v: 'per_project', label: 'Per project' },
];

export default function ClientFlatFeeTab({ onSuccess, onError }: Props) {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const clients = await safeFetchJson<any[]>(`${API_BASE}/settings/clients/`);
      const active = (clients || []).filter(c => c.is_active !== false);
      const profiles = await Promise.all(active.map(c =>
        safeFetchJson<any>(`${API_BASE}/billing/clients/${c.id}/billing-profile/`).catch(() => ({})),
      ));
      setRows(active.map((c, i) => ({
        id: c.id,
        name: c.name,
        billing_type: profiles[i]?.billing_type || 'hourly',
        flat_amount: profiles[i]?.flat_amount ?? '',
        flat_period: profiles[i]?.flat_period || '',
      })));
    } catch (e: any) {
      onError(e?.message || 'Failed to load clients');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const edit = (id: number, field: 'billing_type' | 'flat_amount' | 'flat_period', val: string) =>
    setRows(rs => rs.map(r => (r.id === id ? { ...r, [field]: val, dirty: true } : r)));

  const dirtyCount = rows.filter(r => r.dirty).length;

  const save = async () => {
    const dirty = rows.filter(r => r.dirty);
    if (!dirty.length) return;
    setSaving(true);
    try {
      await Promise.all(dirty.map(r => safeFetchJson(`${API_BASE}/billing/clients/${r.id}/billing-profile/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          billing_type: r.billing_type,
          flat_amount: r.billing_type === 'flat_fee' ? (r.flat_amount || null) : null,
          flat_period: r.billing_type === 'flat_fee' ? (r.flat_period || 'monthly') : '',
        }),
      })));
      onSuccess('Client billing saved');
      await load();
    } catch (e: any) {
      onError(e?.message || 'Failed to save client billing');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-slate-400 text-sm py-3">Loading clients…</div>;

  const filtered = rows.filter(r => r.name.toLowerCase().includes(q.toLowerCase()));
  const flatCount = rows.filter(r => r.billing_type === 'flat_fee').length;

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-3">
        <input
          value={q} onChange={e => setQ(e.target.value)} placeholder="Search clients…"
          className="w-56 max-w-full px-3 py-1.5 border border-border/60 rounded-lg text-sm text-slate-800 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
        />
        <span className="text-[12px] text-slate-400">{flatCount} on flat fee · {rows.length} clients</span>
      </div>

      <div className="rounded-2xl border border-slate-200/70 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/80 text-[10px] uppercase tracking-widest text-slate-400">
            <tr>
              <th className="text-left px-4 py-2 font-bold">Client</th>
              <th className="text-left px-4 py-2 font-bold">Billing type</th>
              <th className="text-left px-4 py-2 font-bold">Flat amount</th>
              <th className="text-left px-4 py-2 font-bold">Cadence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map(r => {
              const isFlat = r.billing_type === 'flat_fee';
              return (
                <tr key={r.id}>
                  <td className="px-4 py-2 font-medium text-slate-800">{r.name}</td>
                  <td className="px-4 py-2">
                    <select
                      value={r.billing_type} onChange={e => edit(r.id, 'billing_type', e.target.value)}
                      className="border border-border/60 rounded-lg px-2 py-1 text-sm bg-white text-slate-700"
                    >
                      <option value="hourly">Hourly</option>
                      <option value="flat_fee">Flat fee / retainer</option>
                      <option value="non_billable">Non-billable</option>
                    </select>
                  </td>
                  <td className="px-4 py-2">
                    <div className="relative w-28">
                      <span className={`absolute left-2.5 top-1/2 -translate-y-1/2 text-sm ${isFlat ? 'text-slate-400' : 'text-slate-200'}`}>$</span>
                      <input
                        type="number" step="0.01" min="0" disabled={!isFlat}
                        value={r.flat_amount} onChange={e => edit(r.id, 'flat_amount', e.target.value)}
                        placeholder={isFlat ? '0.00' : '—'}
                        className="w-full pl-6 pr-2 py-1 border border-border/60 rounded-lg text-sm text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white disabled:bg-slate-50 disabled:text-slate-300"
                      />
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <select
                      value={r.flat_period || 'monthly'} onChange={e => edit(r.id, 'flat_period', e.target.value)}
                      disabled={!isFlat}
                      className="border border-border/60 rounded-lg px-2 py-1 text-sm bg-white text-slate-700 disabled:bg-slate-50 disabled:text-slate-300"
                    >
                      {PERIODS.map(p => <option key={p.v} value={p.v}>{p.label}</option>)}
                    </select>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-[13px] text-slate-400">No clients match.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <button onClick={save} disabled={saving || dirtyCount === 0} className={`${primaryBtnClass} mt-3`}>
        {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
        Save{dirtyCount ? ` (${dirtyCount})` : ''}
      </button>
    </div>
  );
}
