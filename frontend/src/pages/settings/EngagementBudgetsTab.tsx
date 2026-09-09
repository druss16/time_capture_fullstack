/**
 * EngagementBudgetsTab — set the budget for a client's recurring job.
 *
 * Grain is client x job type, not the individual engagement, because a firm
 * thinks "Assumption Church bookkeeping is a $450 job" rather than "engagement
 * 467 needs 6.15 hours". The fee belongs to the arrangement, so saving one row
 * writes every open period at once. Same grain as the CSV importer on purpose —
 * the page and the file must not disagree about what a budget belongs to.
 *
 * Why anyone should bother: without a budget here, the nightly pass derives one
 * from the PRIOR PERIOD'S ACTUAL HOURS. While the agent only sees part of the
 * working week that is circular — a month we barely captured becomes next
 * month's budget, and the month after reads several hundred percent burn. A fee
 * is the one number that doesn't depend on how much we managed to record.
 */
import { useEffect, useMemo, useState } from 'react';
import { Check, RefreshCw, Search, AlertTriangle } from 'lucide-react';
import { API_BASE, safeFetchJson } from '@/lib/api';
import { inputClass, labelClass, primaryBtnClass } from './ui';

interface Row {
  client_id: number;
  client_name: string;
  engagement_type: string;
  open_periods: number;
  budget_hours: number | null;
  budget_mixed: boolean;
  budget_fee: number | null;
  budget_source: string;
}
interface Payload {
  bill_rate: number;
  rows: Row[];
  summary: { total: number; unset: number; derived: number; manual: number };
}

const SOURCE_LABEL: Record<string, string> = {
  manual: 'You set this',
  prior_year: 'Guessed from last period',
  comparable: 'Guessed from similar jobs',
  mixed: 'Varies by period',
  none: 'Not set',
  '': 'Not set',
};

export default function EngagementBudgetsTab({
  onSuccess, onError,
}: {
  onSuccess: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [onlyUnset, setOnlyUnset] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const key = (r: Row) => `${r.client_id}:${r.engagement_type}`;

  const load = async () => {
    setLoading(true);
    try {
      const d = await safeFetchJson<Payload>(`${API_BASE}/engagements/budget-setup/`);
      setData(d);
    } catch (e: any) {
      onError(e?.message || 'Could not load engagement budgets');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const visible = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    return data.rows.filter(r => {
      if (onlyUnset && r.budget_hours !== null) return false;
      if (!needle) return true;
      return r.client_name.toLowerCase().includes(needle)
          || r.engagement_type.includes(needle);
    });
  }, [data, q, onlyUnset]);

  const save = async (r: Row, raw: string) => {
    const fee = parseFloat(raw);
    if (!raw.trim() || Number.isNaN(fee) || fee <= 0) {
      onError('Enter a fee greater than zero');
      return;
    }
    setSavingKey(key(r));
    try {
      const body = await safeFetchJson<{ budget_hours: number; periods_updated: number }>(
        `${API_BASE}/engagements/budget-group/`, {
          method: 'POST',
          body: JSON.stringify({
            client_id: r.client_id,
            engagement_type: r.engagement_type,
            monthly_fee: fee,
          }),
        });
      onSuccess(
        `${r.client_name} ${r.engagement_type}: ${body.budget_hours}h ` +
        `across ${body.periods_updated} period${body.periods_updated === 1 ? '' : 's'}`,
      );
      setDrafts(d => { const n = { ...d }; delete n[key(r)]; return n; });
      load();
    } catch (e: any) {
      onError(e?.message || 'Could not save');
    } finally {
      setSavingKey(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500 py-6">
        <RefreshCw className="w-4 h-4 animate-spin" /> Loading engagements…
      </div>
    );
  }
  if (!data) return null;

  const { summary, bill_rate } = data;

  return (
    <div className="space-y-4">
      {/* Why this matters, stated once, only while it's still true */}
      {summary.derived > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800 flex gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            <strong>{summary.derived} of {summary.total}</strong> budgets were guessed
            from previously recorded hours. Those are only as good as what the agent
            captured — enter the fee you actually charge and the guess is replaced for
            good.
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Find a client…"
            className={`${inputClass} pl-8`}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
          <input
            type="checkbox"
            checked={onlyUnset}
            onChange={e => setOnlyUnset(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
          />
          Only those with no fee set ({summary.unset})
        </label>
        <span className="text-[12px] text-slate-400 tabular-nums">
          {visible.length} of {summary.total}
        </span>
      </div>

      <div className="overflow-x-auto border border-border/70 rounded-lg bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-slate-400 border-b border-border/70">
              <th className="px-3 py-2 font-medium">Client</th>
              <th className="px-3 py-2 font-medium">Job</th>
              <th className="px-3 py-2 font-medium text-right">Periods</th>
              <th className="px-3 py-2 font-medium text-right">Budget</th>
              <th className="px-3 py-2 font-medium">Where it came from</th>
              <th className="px-3 py-2 font-medium">Fee per period</th>
            </tr>
          </thead>
          <tbody>
            {visible.map(r => {
              const k = key(r);
              const draft = drafts[k] ?? '';
              return (
                <tr key={k} className="border-b border-border/40 last:border-0">
                  <td className="px-3 py-2 text-slate-800">{r.client_name}</td>
                  <td className="px-3 py-2 text-slate-500">
                    {r.engagement_type.replace('_', ' ')}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                    {r.open_periods}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.budget_mixed
                      ? <span className="text-amber-600">varies</span>
                      : r.budget_hours !== null
                        ? <>{r.budget_hours}h{r.budget_fee ? <span className="text-slate-400"> · ${r.budget_fee.toLocaleString()}</span> : null}</>
                        : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <span className={
                      r.budget_source === 'manual'
                        ? 'text-emerald-700 text-[12px]'
                        : 'text-slate-400 text-[12px]'
                    }>
                      {SOURCE_LABEL[r.budget_source] ?? r.budget_source}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <div className="relative w-28">
                        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                        <input
                          type="number" step="0.01" min="0" placeholder="0.00"
                          value={draft}
                          onChange={e => setDrafts(d => ({ ...d, [k]: e.target.value }))}
                          onKeyDown={e => { if (e.key === 'Enter') save(r, draft); }}
                          className={`${inputClass} pl-6 py-1 text-sm`}
                        />
                      </div>
                      <button
                        onClick={() => save(r, draft)}
                        disabled={!draft.trim() || savingKey === k}
                        className={`${primaryBtnClass} px-2 py-1 disabled:opacity-40`}
                        title={bill_rate > 0
                          ? `Divided by your $${bill_rate}/h rate to get hours`
                          : 'Set a firm bill rate first'}
                      >
                        {savingKey === k
                          ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          : <Check className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-400 text-sm">
                Nothing matches that filter.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <p className={labelClass}>
        A fee is divided by your firm bill rate (${bill_rate}/h) to get hours, and
        applies to every open period for that client and job. Saved budgets are never
        overwritten by the nightly pass.
      </p>
    </div>
  );
}
