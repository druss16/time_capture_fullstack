/**
 * Budgets — hours tracked against the month's budgeted hours, client by
 * client and project by project.
 *
 * An agency prices each client's monthly fee off estimated hours per project,
 * so the question every account manager asks mid-month is simply "how many
 * hours are left?". Each client row is the sum of its projects (plus time on
 * the client that is not on a project yet, which still spends the budget);
 * each project row is its own budget. The last column is the delta: budget
 * minus hours used — positive is hours left, negative is over.
 *
 * Hours only, on purpose: Analytics → Projects carries the money (fees,
 * effective rate, margin). This page is the one an AM can work from daily.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { cn } from '@/lib/design-system';
import { useWhoAmI } from '@/lib/useWhoAmI';
import { useTerminology } from '@/lib/terminology';

type Row = {
  project_id: number; project: string; client_id: number; client: string; is_active: boolean;
  budget_hours: number | null; actual_hours: number; delta_hours: number | null;
};
type ClientTotal = {
  client_id: number; client: string; budget_hours: number; actual_hours: number;
  unassigned_hours: number; delta_hours: number | null; projects: number; unbudgeted_projects: number;
};
type Summary = { month: string; month_elapsed: number; rows: Row[]; clients: ClientTotal[] };

const thisMonth = () => new Date().toISOString().slice(0, 7);
const shiftMonth = (m: string, by: number) => {
  const [y, mo] = m.split('-').map(Number);
  const d = new Date(Date.UTC(y, mo - 1 + by, 1));
  return d.toISOString().slice(0, 7);
};
const monthLabel = (m: string) =>
  new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
const h = (n: number | null | undefined) => (n == null ? '—' : `${n.toFixed(1)}h`);

/** Budget minus used. Positive = hours left, negative = over. */
function Delta({ value }: { value: number | null }) {
  if (value == null) return <span className="text-slate-300">—</span>;
  const over = value < 0;
  return (
    <span className={cn('font-semibold tabular-nums', over ? 'text-rose-600' : 'text-emerald-700')}>
      {over ? '−' : '+'}{Math.abs(value).toFixed(1)}h
      <span className="ml-1 text-[11px] font-normal text-slate-400">{over ? 'over' : 'left'}</span>
    </span>
  );
}

/** Used against budget, with a tick where the calendar is. */
function Bar({ used, budget, elapsed }: { used: number; budget: number | null; elapsed: number }) {
  if (!budget) return <div className="h-1.5 w-full rounded-full bg-slate-100" />;
  const pct = Math.min(100, (used / budget) * 100);
  const over = used > budget;
  const ahead = !over && used / budget > elapsed + 0.15 && elapsed < 1;
  return (
    <div className="relative h-1.5 w-full rounded-full bg-slate-100">
      <div className={cn('h-1.5 rounded-full', over ? 'bg-rose-500' : ahead ? 'bg-amber-400' : 'bg-primary')}
        style={{ width: `${pct}%` }} />
      {elapsed > 0 && elapsed < 1 && (
        <div className="absolute -top-1 h-3.5 w-px bg-slate-400" style={{ left: `${elapsed * 100}%` }}
          title={`${Math.round(elapsed * 100)}% of the month gone`} />
      )}
    </div>
  );
}

export default function BudgetsPage() {
  const me = useWhoAmI();
  const terms = useTerminology();
  const [month, setMonth] = useState(thisMonth());
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setData(await safeFetchJson<Summary>(`${API_BASE}/projects/budgets/?month=${month}`));
    } catch (e: any) {
      setErr(e?.message || 'Could not load budgets');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => { load(); }, [load]);

  const byClient = useMemo(() => {
    const m = new Map<number, Row[]>();
    for (const r of data?.rows ?? []) m.set(r.client_id, [...(m.get(r.client_id) || []), r]);
    return m;
  }, [data]);

  const totals = useMemo(() => {
    const cs = data?.clients ?? [];
    const budget = cs.reduce((s, c) => s + c.budget_hours, 0);
    const used = cs.reduce((s, c) => s + c.actual_hours, 0);
    return { budget, used, delta: budget ? budget - used : null };
  }, [data]);

  const role = me?.role;
  if (me && !['owner', 'admin'].includes(role || '')) {
    return <div className="p-8 text-sm text-slate-500">Budgets are visible to owners and admins.</div>;
  }
  if (me && !me.local_projects) {
    return <div className="p-8 text-sm text-slate-500">Budgets are for firms that track work by {terms.project.toLowerCase()}.</div>;
  }

  const elapsed = data?.month_elapsed ?? 0;
  const toggle = (id: number) => setCollapsed((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  return (
    <div className="mx-auto max-w-5xl px-4 py-6" style={{ fontFamily: '"Inter", sans-serif' }}>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Budgets</div>
          <h1 className="mt-1 text-[22px] font-bold tracking-[-0.01em] text-slate-900">Hours vs budget</h1>
          <p className="mt-0.5 text-[13px] text-slate-500">
            Hours tracked against each {terms.client.toLowerCase()}'s and {terms.project.toLowerCase()}'s budget for the month.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setMonth((m) => shiftMonth(m, -1))} title="Previous month"
            className="rounded-lg border border-border bg-card p-1.5 text-slate-500 hover:bg-muted">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <div className="min-w-[9.5rem] text-center text-[14px] font-semibold text-slate-800">{monthLabel(month)}</div>
          <button onClick={() => setMonth((m) => shiftMonth(m, 1))} title="Next month"
            className="rounded-lg border border-border bg-card p-1.5 text-slate-500 hover:bg-muted">
            <ChevronRight className="h-4 w-4" />
          </button>
          {month !== thisMonth() && (
            <button onClick={() => setMonth(thisMonth())}
              className="rounded-lg px-2 py-1 text-[12px] font-medium text-primary hover:underline">This month</button>
          )}
          <button onClick={load} title="Refresh" className="rounded-lg p-1.5 text-slate-400 hover:bg-muted">
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {data && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          {[
            ['Budgeted', h(totals.budget)],
            ['Tracked', h(totals.used)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-2xl border border-border/60 bg-card px-4 py-3">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
              <div className="mt-1 text-[22px] font-bold tabular-nums text-slate-900">{value}</div>
            </div>
          ))}
          <div className="rounded-2xl border border-border/60 bg-card px-4 py-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Delta · {Math.round(elapsed * 100)}% of month gone
            </div>
            <div className="mt-1 text-[22px]"><Delta value={totals.delta} /></div>
          </div>
        </div>
      )}

      {err && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{err}</div>}

      {!err && data && data.clients.length === 0 && (
        <div className="rounded-2xl border border-border/60 bg-card p-8 text-center text-sm text-slate-500">
          No {terms.projects.toLowerCase()} with a budget or time in {monthLabel(month)}. Set monthly hours in
          Settings → {terms.clients} → {terms.projects}.
        </div>
      )}

      {data && data.clients.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-border/60 bg-card">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border/60 bg-slate-50/80 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="px-4 py-2.5">{terms.client} / {terms.project}</th>
                <th className="px-3 py-2.5 text-right">Budgeted</th>
                <th className="px-3 py-2.5 text-right">Tracked</th>
                <th className="w-[22%] px-3 py-2.5" />
                <th className="px-4 py-2.5 text-right">Delta</th>
              </tr>
            </thead>
            <tbody>
              {data.clients.map((c) => {
                const open = !collapsed.has(c.client_id);
                const projects = (byClient.get(c.client_id) || [])
                  .slice().sort((a, b) => a.project.localeCompare(b.project));
                return (
                  <Fragment key={c.client_id}>
                    <tr className="cursor-pointer border-t border-border/50 bg-white hover:bg-slate-50/70"
                      onClick={() => toggle(c.client_id)}>
                      <td className="px-4 py-2.5 font-semibold text-slate-900">
                        <ChevronDown className={cn('mr-1.5 inline h-3.5 w-3.5 text-slate-400 transition-transform', !open && '-rotate-90')} />
                        {c.client}
                        {c.unbudgeted_projects > 0 && (
                          <span className="ml-2 text-[11px] font-normal text-amber-600">
                            {c.unbudgeted_projects} without a budget
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-slate-800">{c.budget_hours ? h(c.budget_hours) : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-slate-800">{h(c.actual_hours)}</td>
                      <td className="px-3 py-2.5"><Bar used={c.actual_hours} budget={c.budget_hours || null} elapsed={elapsed} /></td>
                      <td className="px-4 py-2.5 text-right"><Delta value={c.delta_hours} /></td>
                    </tr>
                    {open && projects.map((p) => (
                      <tr key={p.project_id} className="border-t border-border/30">
                        <td className={cn('py-2 pl-10 pr-4 text-slate-700', !p.is_active && 'text-slate-400')}>
                          {p.project}{!p.is_active && <span className="ml-1.5 text-[11px]">(closed)</span>}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-slate-600">{h(p.budget_hours)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-slate-600">{h(p.actual_hours)}</td>
                        <td className="px-3 py-2"><Bar used={p.actual_hours} budget={p.budget_hours} elapsed={elapsed} /></td>
                        <td className="px-4 py-2 text-right"><Delta value={p.delta_hours} /></td>
                      </tr>
                    ))}
                    {open && c.unassigned_hours > 0 && (
                      <tr className="border-t border-border/30">
                        <td className="py-2 pl-10 pr-4 italic text-amber-700"
                          title="Time on this client that is not on a project yet — file it in Daily Review">
                          No {terms.project.toLowerCase()} yet
                        </td>
                        <td className="px-3 py-2 text-right text-slate-300">—</td>
                        <td className="px-3 py-2 text-right tabular-nums text-amber-700">{h(c.unassigned_hours)}</td>
                        <td className="px-3 py-2" />
                        <td className="px-4 py-2 text-right text-slate-300">—</td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data && data.clients.length > 0 && (
        <p className="mt-3 text-[12px] text-slate-400">
          Delta = budgeted − tracked. A {terms.client.toLowerCase()}'s tracked hours include time not yet on a {terms.project.toLowerCase()}.
          The tick on each bar is how much of the month has gone.
        </p>
      )}
    </div>
  );
}
