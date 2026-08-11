// src/pages/settings/BillingRatesTab.tsx
// Per-client (and per-person-on-a-client) hourly bill-rate overrides. Rendered
// inside the Economics "Client rates" section, so it carries no title of its own.
import { useState } from 'react';
import { Plus, Pencil, Trash2, RefreshCw, Check } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { getUserDisplayName } from './types';
import type { BillingRate, TeamMember, Client } from './types';
import { inputClass, labelClass, primaryBtnClass, secondaryBtnClass } from './ui';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface Props {
  rates: BillingRate[];
  users: TeamMember[];
  clients: Client[];
  orgDefaultRate: string;
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

export default function BillingRatesTab({ rates, users, clients, orgDefaultRate, onRefresh, onSuccess, onError }: Props) {
  const [showAdd, setShowAdd]     = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving]       = useState(false);
  const [form, setForm] = useState({
    user: '', client: '', rate: '', effective_date: new Date().toISOString().split('T')[0],
  });

  const defaultRate = parseFloat(orgDefaultRate).toFixed(0);

  const resetForm = () => {
    setForm({ user: '', client: '', rate: '', effective_date: new Date().toISOString().split('T')[0] });
    setShowAdd(false);
    setEditingId(null);
  };

  const handleSave = async () => {
    if (!form.rate) return;
    setSaving(true);
    try {
      const payload = { user: form.user || null, client: form.client || null, rate: form.rate, effective_date: form.effective_date };
      if (editingId) {
        await safeFetchJson(`${API_BASE}/billing/rates/${editingId}/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Rate updated');
      } else {
        await safeFetchJson(`${API_BASE}/billing/rates/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Rate added');
      }
      resetForm();
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (rate: BillingRate) => {
    setForm({ user: rate.user?.toString() || '', client: rate.client?.toString() || '', rate: rate.rate || rate.hourly_rate || '', effective_date: rate.effective_date });
    setEditingId(rate.id);
    setShowAdd(true);
  };

  const handleDelete = async (rateId: number) => {
    if (!confirm('Delete this rate?')) return;
    try {
      await safeFetchJson(`${API_BASE}/billing/rates/${rateId}/`, { method: 'DELETE' });
      onSuccess('Rate deleted');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  return (
    <div>
      {/* Slim header: hint + add */}
      <div className="flex items-center justify-between gap-3 mb-3">
        <p className="text-[12px] text-slate-400">
          {rates.length > 0
            ? `${rates.length} client rate${rates.length === 1 ? '' : 's'} set`
            : `No client rates yet — everything uses the tier or $${defaultRate} default.`}
        </p>
        {!showAdd && (
          <button onClick={() => { resetForm(); setShowAdd(true); }} className={primaryBtnClass}>
            <Plus className="w-3.5 h-3.5" /> Add rate
          </button>
        )}
      </div>

      {/* Add / edit form */}
      {showAdd && (
        <div className="mb-4 rounded-xl border border-slate-200/70 bg-slate-50/60 p-4">
          <div className="grid gap-3 sm:grid-cols-4">
            <div>
              <label className={labelClass}>Employee</label>
              <select value={form.user} onChange={e => setForm({ ...form, user: e.target.value })} className={inputClass}>
                <option value="">All employees</option>
                {users.map(u => <option key={u.id} value={u.id}>{getUserDisplayName(u)}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Client</label>
              <select value={form.client} onChange={e => setForm({ ...form, client: e.target.value })} className={inputClass}>
                <option value="">All clients</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Hourly Rate *</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                <input type="number" step="0.01" min="0" value={form.rate} onChange={e => setForm({ ...form, rate: e.target.value })} placeholder="175.00" className={`${inputClass} pl-7`} />
              </div>
            </div>
            <div>
              <label className={labelClass}>Effective Date</label>
              <input type="date" value={form.effective_date} onChange={e => setForm({ ...form, effective_date: e.target.value })} className={inputClass} />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={handleSave} disabled={saving || !form.rate} className={primaryBtnClass}>
              {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              {editingId ? 'Update' : 'Add'}
            </button>
            <button onClick={resetForm} className={secondaryBtnClass}>Cancel</button>
          </div>
        </div>
      )}

      {/* Table — only when there are overrides */}
      {rates.length > 0 && (
        <div className="rounded-2xl border border-slate-200/70 overflow-hidden">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-slate-50/80">
                {['Employee', 'Client', 'Rate', 'Effective', 'Actions'].map(h => (
                  <th key={h} className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-500 ${h === 'Actions' ? 'text-right' : 'text-left'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rates.map(rate => (
                <tr key={rate.id} className="hover:bg-slate-50/60 transition-colors">
                  <td className="px-4 py-2.5 text-slate-700">{rate.user_name || <span className="text-slate-400 italic">All</span>}</td>
                  <td className="px-4 py-2.5 text-slate-700">{rate.client_name || <span className="text-slate-400 italic">All</span>}</td>
                  <td className="px-4 py-2.5 font-semibold text-slate-900">${parseFloat(rate.rate || rate.hourly_rate || '0').toFixed(2)}/hr</td>
                  <td className="px-4 py-2.5 text-slate-400 text-xs">{new Date(rate.effective_date).toLocaleDateString()}</td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => handleEdit(rate)} className="p-1.5 text-slate-400 hover:text-primary hover:bg-primary/8 rounded-lg transition-colors"><Pencil className="w-3.5 h-3.5" /></button>
                      <button onClick={() => handleDelete(rate.id)} className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
