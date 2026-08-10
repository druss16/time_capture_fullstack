// src/pages/settings/CostTiers.tsx
// Firm-defined labor cost tiers + member assignment. The analytics engine
// resolves each user's cost as: per-person override > tier rate > org default.
import { useEffect, useMemo, useState } from 'react';
import { Layers, Check, RefreshCw, Plus, Trash2 } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface Tier { id?: number; label: string; cost_rate: string; bill_rate: string; hours_per_week: string; member_count?: number; }
interface Member { id: number; name: string; role: string; cost_tier_id: number | null; override_rate: string | null; }
interface Props { onSuccess: (m: string) => void; onError: (m: string) => void; }

export default function CostTiers({ onSuccess, onError }: Props) {
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [deletedIds, setDeletedIds] = useState<number[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [defaultCost, setDefaultCost] = useState('75.00');
  const [defaultBill, setDefaultBill] = useState('150.00');
  const [defaultCapacity, setDefaultCapacity] = useState('40');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkTier, setBulkTier] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await safeFetchJson<{ default_cost: string; default_bill: string; default_capacity: string; tiers: Tier[]; members: Member[] }>(
        `${API_BASE}/settings/cost-rates/`,
      );
      setTiers(data.tiers || []);
      setMembers(data.members || []);
      setDefaultCost(data.default_cost || '75.00');
      setDefaultBill(data.default_bill || '150.00');
      setDefaultCapacity(data.default_capacity || '40');
      setDeletedIds([]);
      setSelected(new Set());
    } catch (e: any) {
      onError(e?.message || 'Failed to load cost tiers');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // Only saved tiers (with an id) can receive assignments.
  const savedTiers = useMemo(() => tiers.filter(t => t.id != null), [tiers]);
  const tierLabel = (id: number | null) =>
    id == null ? '—' : (tiers.find(t => t.id === id)?.label || 'Unknown');

  const editTier = (i: number, field: 'label' | 'cost_rate' | 'bill_rate' | 'hours_per_week', v: string) =>
    setTiers(ts => ts.map((t, idx) => (idx === i ? { ...t, [field]: v } : t)));
  const addTier = () =>
    setTiers(ts => [...ts, { label: '', cost_rate: defaultCost, bill_rate: '', hours_per_week: '' }]);
  const removeTier = (i: number) => {
    const t = tiers[i];
    if (t.id != null) setDeletedIds(d => [...d, t.id!]);
    setTiers(ts => ts.filter((_, idx) => idx !== i));
  };

  const assign = (userId: number, tierId: number | null) =>
    setMembers(ms => ms.map(m => (m.id === userId ? { ...m, cost_tier_id: tierId } : m)));

  const toggleSel = (userId: number) =>
    setSelected(s => { const n = new Set(s); n.has(userId) ? n.delete(userId) : n.add(userId); return n; });
  const toggleAll = () =>
    setSelected(s => (s.size === members.length ? new Set() : new Set(members.map(m => m.id))));
  const applyBulk = () => {
    if (!bulkTier) return;
    const tid = bulkTier === 'none' ? null : Number(bulkTier);
    setMembers(ms => ms.map(m => (selected.has(m.id) ? { ...m, cost_tier_id: tid } : m)));
  };

  const save = async () => {
    setSaving(true);
    try {
      const tierPayload = [
        ...tiers
          .filter(t => t.label.trim() && t.cost_rate !== '' && t.cost_rate != null)
          .map((t, idx) => ({ id: t.id, label: t.label.trim(), cost_rate: t.cost_rate, bill_rate: t.bill_rate, hours_per_week: t.hours_per_week, sort_order: idx })),
        ...deletedIds.map(id => ({ id, _delete: true })),
      ];
      const assignments = members.map(m => ({ user_id: m.id, cost_tier_id: m.cost_tier_id }));
      await safeFetchJson(`${API_BASE}/settings/cost-rates/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tiers: tierPayload, assignments }),
      });
      onSuccess('Cost tiers saved');
      await load();
    } catch (e: any) {
      onError(e?.message || 'Failed to save cost tiers');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-slate-400 text-sm p-4">Loading cost tiers…</div>;

  return (
    <div className="mt-6 pt-6 border-t border-slate-200">
      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1 flex items-center gap-1.5">
        <Layers className="w-3 h-3" /> Labor Cost Tiers · powers Gross Margin
      </p>
      <p className="text-xs text-slate-400 mb-4">
        Set a loaded <b>cost</b> (what you pay), standard <b>bill</b> rate (what you charge), and weekly
        <b> hours</b> (capacity) per tier, then assign people. Blank cost → ${defaultCost}/hr; blank bill →
        {' '}${defaultBill}/hr (a client rate always wins); blank hours → {defaultCapacity}/wk. Hrs/wk is the
        denominator for utilization (billable ÷ available). Tip: (annual salary × 1.25) ÷ 2,000 ≈ loaded cost.
      </p>

      {/* Column headers */}
      <div className="flex items-center gap-2 px-1 mb-1 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
        <span className="flex-1">Tier</span>
        <span className="w-28 text-center">Cost $/hr</span>
        <span className="w-28 text-center">Bill $/hr</span>
        <span className="w-24 text-center">Hrs/wk</span>
        <span className="w-14" />
        <span className="w-8" />
      </div>

      {/* Tier rates */}
      <div className="space-y-2 mb-3">
        {tiers.map((t, i) => (
          <div key={t.id ?? `new-${i}`} className="flex items-center gap-2">
            <input
              type="text" placeholder="Tier name"
              value={t.label}
              onChange={e => editTier(i, 'label', e.target.value)}
              className="flex-1 border border-border/60 rounded-lg px-3 py-2 text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
            />
            <div className="relative w-28">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
              <input
                type="number" step="0.01" min="0" placeholder={defaultCost}
                value={t.cost_rate}
                onChange={e => editTier(i, 'cost_rate', e.target.value)}
                className="w-full pl-7 pr-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
              />
            </div>
            <div className="relative w-28">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
              <input
                type="number" step="0.01" min="0" placeholder={defaultBill}
                value={t.bill_rate}
                onChange={e => editTier(i, 'bill_rate', e.target.value)}
                className="w-full pl-7 pr-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
              />
            </div>
            <div className="w-24">
              <input
                type="number" step="0.5" min="0" max="168" placeholder={defaultCapacity}
                value={t.hours_per_week}
                onChange={e => editTier(i, 'hours_per_week', e.target.value)}
                className="w-full px-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white text-center"
              />
            </div>
            <span className="text-[11px] text-slate-400 w-14 text-right">
              {t.member_count ? `${t.member_count} ppl` : ''}
            </span>
            <button onClick={() => removeTier(i)} title="Remove tier"
              className="p-2 text-slate-400 hover:text-rose-500 transition-colors">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
      <button onClick={addTier}
        className="flex items-center gap-1.5 px-3 py-1.5 mb-5 text-xs font-semibold text-primary border border-primary/30 rounded-lg hover:bg-primary/5 transition-all">
        <Plus className="w-3.5 h-3.5" /> Add tier
      </button>

      {/* Bulk assign */}
      {members.length > 0 && (
        <>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-slate-500">{selected.size} selected</span>
            <select
              value={bulkTier} onChange={e => setBulkTier(e.target.value)}
              className="border border-border/60 rounded-lg px-2 py-1.5 text-sm bg-white text-slate-700"
            >
              <option value="">Assign selected to…</option>
              {savedTiers.map(t => <option key={t.id} value={String(t.id)}>{t.label}</option>)}
              <option value="none">— No tier (use default)</option>
            </select>
            <button
              onClick={applyBulk} disabled={!bulkTier || selected.size === 0}
              className="px-3 py-1.5 text-xs font-semibold border border-border/60 rounded-lg text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-all"
            >
              Apply
            </button>
          </div>

          <div className="rounded-xl border border-slate-200 overflow-x-auto mb-4">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[10px] uppercase tracking-widest text-slate-400">
                <tr>
                  <th className="px-3 py-2 w-8">
                    <input type="checkbox"
                      checked={selected.size === members.length && members.length > 0}
                      onChange={toggleAll} />
                  </th>
                  <th className="text-left px-4 py-2 font-bold">Member</th>
                  <th className="text-left px-4 py-2 font-bold">Permission</th>
                  <th className="text-left px-4 py-2 font-bold">Cost tier</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {members.map(m => (
                  <tr key={m.id} className={selected.has(m.id) ? 'bg-primary/5' : ''}>
                    <td className="px-3 py-2 text-center">
                      <input type="checkbox" checked={selected.has(m.id)} onChange={() => toggleSel(m.id)} />
                    </td>
                    <td className="px-4 py-2 font-medium text-slate-800">
                      {m.name}
                      {m.override_rate && (
                        <span className="ml-2 text-[10px] text-amber-600" title="Per-person override">
                          override ${parseFloat(m.override_rate).toFixed(0)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-slate-400">{m.role}</td>
                    <td className="px-4 py-2">
                      <select
                        value={m.cost_tier_id == null ? '' : String(m.cost_tier_id)}
                        onChange={e => assign(m.id, e.target.value === '' ? null : Number(e.target.value))}
                        className="border border-border/60 rounded-lg px-2 py-1 text-sm bg-white text-slate-700"
                      >
                        <option value="">— default</option>
                        {savedTiers.map(t => (
                          <option key={t.id} value={String(t.id)}>{t.label}</option>
                        ))}
                      </select>
                      {m.cost_tier_id != null && !savedTiers.some(t => t.id === m.cost_tier_id) && (
                        <span className="ml-1 text-[10px] text-slate-400">({tierLabel(m.cost_tier_id)})</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <button
        onClick={save} disabled={saving}
        className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-50 transition-all"
      >
        {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
        Save Tiers & Assignments
      </button>
    </div>
  );
}
