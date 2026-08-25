// src/components/FeeBasis.tsx
/**
 * What a partner opens at billing time to decide what to charge.
 *
 * Firms do not bill out of TimeTracker — they weigh it against their own
 * judgement — so this screen is built to be argued with rather than exported.
 * Each row carries the evidence (hours, who, what the work was) next to the
 * anchors a fee actually gets set against: last year's invoice, the engagement
 * budget, the standing arrangement.
 *
 * It counts every captured block, including time nobody has reviewed. On a
 * screen whose job is to stop a firm underbilling, hiding hours is the one
 * unrecoverable mistake — a fee set from a number that was quietly 90% short
 * is money gone for good.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { RefreshCw, Users, ChevronLeft, ChevronRight, Info } from 'lucide-react';
import { cn } from '@/lib/design-system';

type Work = { name: string; hours: number };

type FeeClient = {
  client_id: number;
  name: string;
  code: string;
  hours: number;
  billable_hours: number;
  unapproved_hours: number;
  value_at_rates: number;
  people: number;
  work: Work[];
  arrangement: { type: string; amount: number | null; period: string | null };
  budget_hours: number | null;
  budget_amount: number | null;
  prior_year_billed: number | null;
  last_invoice: { date: string; amount: number } | null;
};

type Payload = {
  period: { start: string; end: string };
  totals: { clients: number; hours: number; value: number; unapproved_hours: number };
  uses_approval?: boolean;
  clients: FeeClient[];
};

const money = (n: number) =>
  n >= 1000 ? `$${Math.round(n).toLocaleString()}` : `$${n.toFixed(0)}`;

const monthLabel = (iso: string) =>
  new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

function shiftMonth(startIso: string, delta: number) {
  const d = new Date(startIso + 'T00:00:00');
  d.setMonth(d.getMonth() + delta);
  const start = new Date(d.getFullYear(), d.getMonth(), 1);
  const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  const fmt = (x: Date) =>
    `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  return { start: fmt(start), end: fmt(end) };
}

/** How this period's time compares with what the client was charged a year ago. */
function priorYearDelta(c: FeeClient): { pct: number; tone: string; label: string } | null {
  if (!c.prior_year_billed || c.prior_year_billed <= 0 || c.value_at_rates <= 0) return null;
  const pct = Math.round(((c.value_at_rates - c.prior_year_billed) / c.prior_year_billed) * 100);
  if (Math.abs(pct) < 10) return { pct, tone: 'text-muted-foreground', label: 'in line with last year' };
  return pct > 0
    ? { pct, tone: 'text-emerald-700', label: `${pct}% above last year` }
    : { pct, tone: 'text-amber-700', label: `${Math.abs(pct)}% below last year` };
}

export default function FeeBasis() {
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async (r: { start: string; end: string } | null) => {
    setLoading(true);
    setErr(null);
    try {
      const qs = r ? `?start=${r.start}&end=${r.end}` : '';
      const d = await safeFetchJson<Payload>(`${API_BASE}/billing/fee-basis/${qs}`);
      setData(d);
      setRange(d.period);
    } catch (e: any) {
      setErr(e?.message || "Couldn't load the period");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(null);
  }, [load]);

  const step = (delta: number) => {
    if (!range) return;
    load(shiftMonth(range.start, delta));
  };

  const maxHours = useMemo(
    () => Math.max(1, ...(data?.clients || []).map((c) => c.hours)),
    [data]
  );

  if (loading && !data) {
    return <div className="p-6 text-sm text-muted-foreground">Loading the period…</div>;
  }
  if (err) {
    return (
      <div className="rounded-2xl border border-border/60 bg-card p-6">
        <p className="text-sm text-muted-foreground">{err}</p>
        <button
          onClick={() => load(range)}
          className="mt-3 inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-muted/50"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Retry
        </button>
      </div>
    );
  }
  if (!data) return null;

  const { totals } = data;

  return (
    <div className="space-y-4">
      {/* ── Period + firm totals ───────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">
            Setting fees for
          </div>
          <div className="mt-1 flex items-center gap-1">
            <button
              onClick={() => step(-1)}
              className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title="Previous month"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[9.5rem] text-center text-[19px] font-bold tracking-[-0.01em] text-foreground">
              {monthLabel(data.period.start)}
            </span>
            <button
              onClick={() => step(1)}
              className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title="Next month"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex items-end gap-6">
          <div>
            <div className="font-mono text-[22px] font-bold tabular-nums text-foreground">
              {totals.hours.toFixed(1)}h
            </div>
            <div className="text-[12px] text-muted-foreground">across {totals.clients} clients</div>
          </div>
          <div>
            <div className="font-mono text-[22px] font-bold tabular-nums text-primary">
              {money(totals.value)}
            </div>
            <div className="text-[12px] text-muted-foreground">at standard rates</div>
          </div>
        </div>
      </div>

      {/* Only shown where approvals actually discriminate — a firm that never
          approves anything is not behind, and a caveat that fires on every
          hour just teaches people to ignore it. */}
      {data.uses_approval && totals.unapproved_hours > 0 && (
        <div className="flex items-start gap-2.5 rounded-xl border border-border/60 bg-muted/40 px-4 py-3">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <p className="text-[13px] text-muted-foreground">
            <span className="font-semibold text-foreground">
              {totals.unapproved_hours.toFixed(1)}h
            </span>{' '}
            of this hasn't been through approval yet. It's included below — leaving it out
            would understate the work.
          </p>
        </div>
      )}

      {/* ── One row per client ─────────────────────────────────────────── */}
      <div className="overflow-hidden rounded-2xl border border-border/60 bg-card">
        {data.clients.length === 0 && (
          <div className="p-8 text-center text-sm text-muted-foreground">
            No time captured in this period.
          </div>
        )}

        <div className="divide-y divide-border/60">
          {data.clients.map((c) => {
            const delta = priorYearDelta(c);
            const overBudget =
              c.budget_hours != null && c.budget_hours > 0 && c.hours > c.budget_hours;
            return (
              <div key={c.client_id} className="px-5 py-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-[15px] font-bold tracking-[-0.01em] text-foreground">
                    {c.name}
                  </span>
                  {c.code && (
                    <span className="font-mono text-[11px] text-muted-foreground/70">{c.code}</span>
                  )}
                  {c.arrangement.type !== 'hourly' && (
                    <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {c.arrangement.type.replace('_', ' ')}
                      {c.arrangement.amount ? ` · ${money(c.arrangement.amount)}` : ''}
                    </span>
                  )}
                  <span className="flex-1" />
                  <span className="font-mono text-[15px] font-bold tabular-nums text-foreground">
                    {c.hours.toFixed(1)}h
                  </span>
                  <span className="font-mono text-[15px] font-bold tabular-nums text-primary">
                    {money(c.value_at_rates)}
                  </span>
                </div>

                {/* Relative scale — which clients ate the month, at a glance. */}
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary/70"
                    style={{ width: `${Math.max(2, (c.hours / maxHours) * 100)}%` }}
                  />
                </div>

                <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px]">
                  <span className="inline-flex items-center gap-1 text-muted-foreground">
                    <Users className="h-3 w-3" />
                    {c.people} {c.people === 1 ? 'person' : 'people'}
                  </span>
                  {c.work.slice(0, 4).map((w) => (
                    <span key={w.name} className="text-muted-foreground">
                      {w.name}{' '}
                      <span className="font-mono tabular-nums text-foreground/70">
                        {w.hours.toFixed(1)}h
                      </span>
                    </span>
                  ))}
                </div>

                {/* The anchors. Absent ones are simply not shown — an empty
                    row of dashes reads as broken rather than as "no history". */}
                {(delta || c.budget_hours || c.prior_year_billed || c.last_invoice) && (
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
                    {c.prior_year_billed != null && (
                      <span className="text-muted-foreground">
                        Last year{' '}
                        <span className="font-mono tabular-nums text-foreground/80">
                          {money(c.prior_year_billed)}
                        </span>
                      </span>
                    )}
                    {delta && <span className={cn('font-medium', delta.tone)}>{delta.label}</span>}
                    {c.budget_hours != null && (
                      <span className={cn(overBudget ? 'font-medium text-amber-700' : 'text-muted-foreground')}>
                        Budget{' '}
                        <span className="font-mono tabular-nums">{c.budget_hours.toFixed(1)}h</span>
                        {overBudget && ` · over by ${(c.hours - c.budget_hours).toFixed(1)}h`}
                      </span>
                    )}
                    {c.last_invoice && (
                      <span className="text-muted-foreground/70">
                        Last invoiced {c.last_invoice.date}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <p className="px-1 text-[12px] leading-relaxed text-muted-foreground">
        These figures are a reference, not an invoice. Value shown is time at standard rates —
        what the work would come to before any judgement about scope, relationship, or what was
        actually agreed.
      </p>
    </div>
  );
}
