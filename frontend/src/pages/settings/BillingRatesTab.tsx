// src/pages/settings/BillingRatesTab.tsx
import { useState } from 'react';
import { DollarSign, Plus, Pencil, Trash2, RefreshCw, Check } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { getUserDisplayName } from './types';
import type { BillingRate, TeamMember, Client } from './types';

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
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-primary" />
          Billing Rates
          <span className="text-sm font-semibold text-slate-400">({rates.length})</span>
        </h2>
        <button onClick={() => { resetForm(); setShowAdd(true); }} className="flex items-center gap-1.5 px-3 py-2 bg-primary text-white rounded-lg font-semibold text-sm hover:opacity-90 transition-all">
          <Plus className="w-3.5 h-3.5" /> Add Rate
        </button>
      </div>

      {/* Default rate banner */}
      <div className="mb-5 p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold text-emerald-600 uppercase tracking-wider mb-0.5">Organization Default Rate</p>
          <p className="text-xl font-extrabold text-emerald-700">${parseFloat(orgDefaultRate).toFixed(2)}/hr</p>
        </div>
        <span className="text-xs bg-emerald-100 text-emerald-700 font-semibold px-2.5 py-1 rounded-full">Fallback Rate</span>
      </div>

      {/* Add/edit form */}
      {showAdd && (
        <div className="mb-5 p-4 bg-slate-50 border border-dashed border-slate-300 rounded-xl">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4">
            {editingId ? 'Edit Rate' : 'Add Rate Override'}
          </p>
          <div className="grid grid-cols-4 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Employee</label>
              <select value={form.user} onChange={e => setForm({ ...form, user: e.target.value })} className="w-full border border-border/60 rounded-lg px-3 py-2 text-sm bg-white focus:border-primary focus:outline-none">
                <option value="">All Employees</option>
                {users.map(u => <option key={u.id} value={u.id}>{getUserDisplayName(u)}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Client</label>
              <select value={form.client} onChange={e => setForm({ ...form, client: e.target.value })} className="w-full border border-border/60 rounded-lg px-3 py-2 text-sm bg-white focus:border-primary focus:outline-none">
                <option value="">All Clients</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Hourly Rate *</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                <input type="number" step="0.01" min="0" value={form.rate} onChange={e => setForm({ ...form, rate: e.target.value })} placeholder="175.00" className="w-full pl-7 pr-3 py-2 border border-border/60 rounded-lg text-sm bg-white focus:border-primary focus:outline-none" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Effective Date</label>
              <input type="date" value={form.effective_date} onChange={e => setForm({ ...form, effective_date: e.target.value })} className="w-full border border-border/60 rounded-lg px-3 py-2 text-sm bg-white focus:border-primary focus:outline-none" />
            </div>
          </div>
          <div className="flex gap-2 mt-4 pt-4 border-t border-border/50">
            <button onClick={handleSave} disabled={saving || !form.rate} className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white rounded-lg font-semibold text-sm hover:opacity-90 disabled:opacity-50">
              {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              {editingId ? 'Update' : 'Add'}
            </button>
            <button onClick={resetForm} className="px-4 py-2 border border-border/60 rounded-lg font-semibold text-sm text-slate-600 hover:bg-slate-100">Cancel</button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="border border-border/60 rounded-xl overflow-hidden">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border/60 bg-slate-50/80">
              {['Employee', 'Client', 'Rate', 'Effective', 'Actions'].map(h => (
                <th key={h} className={`px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 ${h === 'Actions' ? 'text-right' : 'text-left'}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {rates.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-center py-12">
                  <DollarSign className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                  <p className="font-semibold text-slate-500">No rate overrides yet</p>
                  <p className="text-xs text-slate-400 mt-1">Using default: ${parseFloat(orgDefaultRate).toFixed(2)}/hr</p>
                </td>
              </tr>
            ) : rates.map(rate => (
              <tr key={rate.id} className="hover:bg-slate-50/60 transition-colors">
                <td className="px-4 py-3 text-slate-700">{rate.user_name || <span className="text-slate-400 italic">All</span>}</td>
                <td className="px-4 py-3 text-slate-700">{rate.client_name || <span className="text-slate-400 italic">All</span>}</td>
                <td className="px-4 py-3 font-bold text-emerald-700">${parseFloat(rate.rate || rate.hourly_rate || '0').toFixed(2)}/hr</td>
                <td className="px-4 py-3 text-slate-400 text-xs">{new Date(rate.effective_date).toLocaleDateString()}</td>
                <td className="px-4 py-3 text-right">
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
    </div>
  );
}