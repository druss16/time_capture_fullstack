/**
 * SetupReadiness — what the firm has given us, and what's still missing.
 *
 * Every figure in Analytics rests on data somebody has to supply, and nothing
 * used to say which of it had arrived. A firm could read a revenue number for
 * weeks without knowing it was an estimate because no invoice had ever been
 * imported. The data being missing wasn't the problem; its absence being
 * invisible was.
 *
 * Ordered most-blocking first, and each row answers the only three questions
 * that matter: is it done, what does it unlock, where do I go. Finished rows
 * collapse to a line — this is a to-do list, not a dashboard.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, AlertCircle, CircleDashed, RefreshCw } from 'lucide-react';
import { API_BASE, safeFetchJson } from '@/lib/api';

interface Check {
  id: string;
  title: string;
  status: 'ok' | 'partial' | 'missing';
  detail: string;
  unlocks: string;
  where: string;
  link: string;
}
interface Payload {
  checks: Check[];
  summary: { total: number; done: number; blocking: number };
}

const STYLE = {
  ok:      { Icon: CheckCircle2, ring: 'text-emerald-600', row: '' },
  partial: { Icon: CircleDashed, ring: 'text-amber-600',
             row: 'bg-amber-50/60 border-amber-200' },
  missing: { Icon: AlertCircle,  ring: 'text-rose-600',
             row: 'bg-rose-50/60 border-rose-200' },
} as const;

export default function SetupReadiness() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setData(await safeFetchJson<Payload>(`${API_BASE}/settings/readiness/`));
      } catch {
        /* a checklist that can't load shouldn't break the settings page */
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400 py-4">
        <RefreshCw className="w-4 h-4 animate-spin" /> Checking your setup…
      </div>
    );
  }
  if (!data) return null;

  const { checks, summary } = data;
  const outstanding = checks.filter(c => c.status !== 'ok');
  const finished = checks.filter(c => c.status === 'ok');

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-semibold text-slate-900 tabular-nums">
          {summary.done} of {summary.total} ready
        </span>
        {summary.blocking > 0 && (
          <span className="text-[12px] text-rose-600">
            {summary.blocking} still {summary.blocking === 1 ? 'blocks' : 'block'} numbers you'd want to show a client
          </span>
        )}
      </div>

      {outstanding.map(c => {
        const s = STYLE[c.status];
        return (
          <div key={c.id}
               className={`rounded-lg border border-border/70 p-3 flex gap-3 ${s.row}`}>
            <s.Icon className={`w-4 h-4 shrink-0 mt-0.5 ${s.ring}`} />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-900">{c.title}</div>
              <p className="text-[12.5px] text-slate-600 mt-0.5">{c.detail}</p>
              <p className="text-[12px] text-slate-500 mt-1">
                <span className="text-slate-400">Unlocks: </span>{c.unlocks}
              </p>
              <Link to={c.link}
                    className="text-[12px] font-medium text-primary hover:underline mt-1.5 inline-block">
                {c.where} →
              </Link>
            </div>
          </div>
        );
      })}

      {finished.length > 0 && (
        <div className="rounded-lg border border-border/70 bg-white px-3 py-2">
          {finished.map(c => (
            <div key={c.id} className="flex items-center gap-2 py-0.5 text-[12.5px]">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
              <span className="text-slate-700">{c.title}</span>
              <span className="text-slate-400 truncate">— {c.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
