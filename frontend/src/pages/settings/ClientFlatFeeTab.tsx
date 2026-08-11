// src/pages/settings/ClientFlatFeeTab.tsx
// Flat-fee / retainer clients on Economics. Shows ONLY the clients on a flat
// fee (most clients are hourly), with an "Add flat-fee client" action — so it's
// a short focused list, not a grid of every client. Loads all profiles in one
// call (billing-profiles batch) with a per-client fallback.
import { useEffect, useState } from 'react';
import { Plus, Check, RefreshCw, X } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { primaryBtnClass, secondaryBtnClass } from './ui';

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
  const [all, setAll] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addForm, setAddForm] = useState({ client: '', amount: '', period: 'monthly' });

  const load = async () => {
    setLoading(true);
    try {
      let list: any[] | null = null;
      try {
        // Fast path — all profiles in one call.
        const data = await safeFetchJson<any[]>(`${API_BASE}/billing/clients/billing-profiles/`);
        if (Array.isArray(data)) {
          list = data.map(r => ({ id: r.client_id, name: r.name, billing_type: r.billing_type || 'hourly', flat_amount: r.flat_amount ?? '', flat_period: r.flat_period || '' }));
        }
      } catch { list = null; }

      if (!list) {
        // Fallback for older backend without the batch endpoint.
        const clients = await safeFetchJson<any[]>(`${API_BASE}/settings/clients/`);
        const active = (clients || []).filter(c => c.is_active !== false);
        const profiles = await Promise.all(active.map(c =>
          safeFetchJson<any>(`${API_BASE}/billing/clients/${c.id}/billing-profile/`).catch(() => ({})),
        ));
        list = active.map((c, i) => ({ id: c.id, name: c.name, billing_type: profiles[i]?.billing_type || 'hourly', flat_amount: profiles[i]?.flat_amount ?? '', flat_period: profiles[i]?.flat_period || '' }));
      }
      setAll(list);
    } catch (e: any) {
      onError(e?.message || 'Failed to load clients');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const put = (clientId: number, body: Record<string, any>) =>
    safeFetchJson(`${API_BASE}/billing/clients/${clientId}/billing-profile/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

  const flat = all.filter(r => r.billing_type === 'flat_fee');
  const hourly = all.filter(r => r.billing_type !== 'flat_fee').sort((a, b) => a.name.localeCompare(b.name));
  const dirtyCount = flat.filter(r => r.dirty).length;

  const editRow = (id: number, field: 'flat_amount' | 'flat_period', val: string) =>
    setAll(a => a.map(r => (r.id === id ? { ...r, [field]: val, dirty: true } : r)));

  const addFlat = async () => {
    if (!addForm.client || !addForm.amount) return;
    setBusy(true);
    try {
      await put(Number(addForm.client), { billing_type: 'flat_fee', flat_amount: addForm.amount, flat_period: addForm.period });
      onSuccess('Flat fee set');
      setAdding(false);
      setAddForm({ client: '', amount: '', period: 'monthly' });
      await load();
    } catch (e: any) {
      onError(e?.message || 'Failed to save');
    } finally { setBusy(false); }
  };

  const saveEdits = async () => {
    const dirty = flat.filter(r => r.dirty);
    if (!dirty.length) return;
    setBusy(true);
    try {
      await Promise.all(dirty.map(r => put(r.id, { billing_type: 'flat_fee', flat_amount: r.flat_amount || null, flat_period: r.flat_period || 'monthly' })));
      onSuccess('Saved');
      await load();
    } catch (e: any) {
      onError(e?.message || 'Failed to save');
    } finally { setBusy(false); }
  };

  const removeFlat = async (r: Row) => {
    if (!confirm(`Remove the flat fee for ${r.name}? It will bill hourly.`)) return;
    setBusy(true);
    try {
      await put(r.id, { billing_type: 'hourly', flat_amount: null, flat_period: '' });
      onSuccess('Set back to hourly');
      await load();
    } catch (e: any) {
      onError(e?.message || 'Failed to update');
    } finally { setBusy(false); }
  };

  if (loading) return <div className="text-slate-400 text-sm py-3">Loading…</div>;

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-3">
        <p className="text-[12px] text-slate-400">
          {flat.length > 0 ? `${flat.length} flat-fee / retainer client${flat.length === 1 ? '' : 's'}` : 'No flat-fee clients yet — everyone bills hourly.'}
        </p>
        {!adding && (
          <button onClick={() => setAdding(true)} className={primaryBtnClass}>
            <Plus className="w-3.5 h-3.5" /> Add flat-fee client
          </button>
        )}
      </div>

      {/* Add form */}
      {adding && (
        <div className="mb-4 rounded-xl border border-slate-200/70 bg-slate-50/60 p-4 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[180px]">
            <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Client</label>
            <select
              value={addForm.client} onChange={e => setAddForm({ ...addForm, client: e.target.value })}
              className="w-full border border-border/60 rounded-lg px-2 py-1.5 text-sm bg-white text-slate-700"
            >
              <option value="">Choose a client…</option>
              {hourly.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Amount</label>
            <div className="relative w-28">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
              <input
                type="number" step="0.01" min="0" value={addForm.amount}
                onChange={e => setAddForm({ ...addForm, amount: e.target.value })} placeholder="0.00"
                className="w-full pl-6 pr-2 py-1.5 border border-border/60 rounded-lg text-sm text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
              />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Cadence</label>
            <select
              value={addForm.period} onChange={e => setAddForm({ ...addForm, period: e.target.value })}
              className="border border-border/60 rounded-lg px-2 py-1.5 text-sm bg-white text-slate-700"
            >
              {PERIODS.map(p => <option key={p.v} value={p.v}>{p.label}</option>)}
            </select>
          </div>
          <button onClick={addFlat} disabled={busy || !addForm.client || !addForm.amount} className={primaryBtnClass}>
            {busy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />} Add
          </button>
          <button onClick={() => { setAdding(false); setAddForm({ client: '', amount: '', period: 'monthly' }); }} className={secondaryBtnClass}>Cancel</button>
        </div>
      )}

      {/* Flat-fee client list */}
      {flat.length > 0 && (
        <div className="rounded-2xl border border-slate-200/70 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50/80 text-[10px] uppercase tracking-widest text-slate-400">
              <tr>
                <th className="text-left px-4 py-2 font-bold">Client</th>
                <th className="text-left px-4 py-2 font-bold">Flat amount</th>
                <th className="text-left px-4 py-2 font-bold">Cadence</th>
                <th className="px-4 py-2 w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {flat.map(r => (
                <tr key={r.id}>
                  <td className="px-4 py-2 font-medium text-slate-800">{r.name}</td>
                  <td className="px-4 py-2">
                    <div className="relative w-28">
                      <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                      <input
                        type="number" step="0.01" min="0" value={r.flat_amount}
                        onChange={e => editRow(r.id, 'flat_amount', e.target.value)}
                        className="w-full pl-6 pr-2 py-1 border border-border/60 rounded-lg text-sm text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
                      />
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <select
                      value={r.flat_period || 'monthly'} onChange={e => editRow(r.id, 'flat_period', e.target.value)}
                      className="border border-border/60 rounded-lg px-2 py-1 text-sm bg-white text-slate-700"
                    >
                      {PERIODS.map(p => <option key={p.v} value={p.v}>{p.label}</option>)}
                    </select>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => removeFlat(r)} title="Set back to hourly" className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dirtyCount > 0 && (
        <button onClick={saveEdits} disabled={busy} className={`${primaryBtnClass} mt-3`}>
          {busy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
          Save changes ({dirtyCount})
        </button>
      )}
    </div>
  );
}
