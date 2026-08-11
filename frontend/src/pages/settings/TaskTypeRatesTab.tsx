// src/pages/settings/TaskTypeRatesTab.tsx
// Task-type billable flag + default rate surfaced on Economics. `is_billable`
// drives utilization/billable metrics; `default_rate` is a bill-rate fallback.
// Reuses the task-management endpoints (same data as the Task Types tab).
import { useEffect, useState } from 'react';
import { Check, RefreshCw } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { primaryBtnClass } from './ui';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;
const TM = `${API_BASE}/task-management`;

interface Row { id: number; name: string; is_billable: boolean; default_rate: string; dirty?: boolean; }
interface Props { onSuccess: (m: string) => void; onError: (m: string) => void; }

export default function TaskTypeRatesTab({ onSuccess, onError }: Props) {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const data = await safeFetchJson<any>(`${TM}/task-types/`);
      const list = Array.isArray(data) ? data : (data?.results || data?.task_types || []);
      setRows(list.map((t: any) => ({
        id: t.id,
        name: t.name,
        is_billable: t.is_billable !== false,
        default_rate: t.default_rate ?? '',
      })));
    } catch (e: any) {
      onError(e?.message || 'Failed to load task types');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const edit = (id: number, patch: Partial<Row>) =>
    setRows(rs => rs.map(r => (r.id === id ? { ...r, ...patch, dirty: true } : r)));

  const dirtyCount = rows.filter(r => r.dirty).length;

  const save = async () => {
    const dirty = rows.filter(r => r.dirty);
    if (!dirty.length) return;
    setSaving(true);
    try {
      await Promise.all(dirty.map(r => safeFetchJson(`${TM}/task-types/${r.id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_billable: r.is_billable, default_rate: String(r.default_rate).trim() || null }),
      })));
      onSuccess('Task types saved');
      await load();
    } catch (e: any) {
      onError(e?.message || 'Failed to save task types');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-slate-400 text-sm py-3">Loading task types…</div>;
  if (rows.length === 0) return <div className="text-slate-400 text-sm py-3">No task types yet.</div>;

  const filtered = rows.filter(r => r.name.toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <p className="text-[12px] text-slate-400 leading-snug mb-3">
        <span className="font-semibold text-slate-500">Default rate</span> is the bill rate for that kind of work
        when no client rate applies — it beats the firm default but loses to a client rate. Optional; most firms
        leave it blank and rely on tiers &amp; client rates.
      </p>
      {rows.length > 8 && (
        <input
          value={q} onChange={e => setQ(e.target.value)} placeholder="Search task types…"
          className="w-56 max-w-full mb-3 px-3 py-1.5 border border-border/60 rounded-lg text-sm text-slate-800 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
        />
      )}
      <div className="rounded-2xl border border-slate-200/70 overflow-auto max-h-[22rem]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-[10px] uppercase tracking-widest text-slate-400 shadow-[0_1px_0_rgba(0,0,0,0.05)]">
            <tr>
              <th className="text-left px-4 py-2 font-bold">Task type</th>
              <th className="text-left px-4 py-2 font-bold">Billable</th>
              <th className="text-left px-4 py-2 font-bold">Default rate <span className="text-slate-300 normal-case">(optional)</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map(r => (
              <tr key={r.id}>
                <td className="px-4 py-2 font-medium text-slate-800">{r.name}</td>
                <td className="px-4 py-2">
                  <button
                    onClick={() => edit(r.id, { is_billable: !r.is_billable })}
                    className={`relative w-9 h-5 rounded-full transition-colors ${r.is_billable ? 'bg-primary' : 'bg-slate-200'}`}
                    role="switch" aria-checked={r.is_billable} title={r.is_billable ? 'Billable' : 'Non-billable'}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${r.is_billable ? 'translate-x-4' : ''}`} />
                  </button>
                </td>
                <td className="px-4 py-2">
                  <div className="relative w-28">
                    <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                    <input
                      type="number" step="0.01" min="0"
                      value={r.default_rate} onChange={e => edit(r.id, { default_rate: e.target.value })}
                      placeholder="—"
                      className="w-full pl-6 pr-2 py-1 border border-border/60 rounded-lg text-sm text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white"
                    />
                  </div>
                </td>
              </tr>
            ))}
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
