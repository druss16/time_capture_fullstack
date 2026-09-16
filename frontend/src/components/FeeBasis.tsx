/**
 * The number a partner prices from, and how much of it we actually saw.
 *
 * This firm sets each client's fee monthly off the hours: QuickBooks is open,
 * they look up what went into the account, they arrive at a fair figure, and
 * they invoice it from their own system. So nothing is decided here and
 * nothing is recorded here. Earlier passes put a fee box, a "mark billed"
 * button and a "0 of 103 priced" counter on this page; all of it was data
 * entry that made the product feel complete and the partner slower, and it has
 * been taken back out.
 *
 * What is left is the part he cannot get from QuickBooks, his memory, or the
 * Reports client table: our hours, carrying the honesty that makes a reference
 * worth respecting. The number is a FLOOR — org 21 captures about 45% of
 * scheduled time — so the page says so once at the top, and every row says how
 * completely the people who did that client's work were captured. A partner
 * pricing off a silent under-count either loses money or applies a private gut
 * multiplier, and in the second case his instinct is the barometer and we are
 * decoration.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  RefreshCw, Users, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Info,
  AlertTriangle,
} from 'lucide-react';
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
  /** True only when every budget behind this row came from the firm's own fee
   *  schedule (budget_source 'manual'), the one kind worth quoting back. */
  budget_is_fee?: boolean;
  /** False for the sub-hour tail: shown, but not in the way. */
  material?: boolean;
  /** 0..1 — how much of the scheduled time of the people who worked this
   *  client we actually captured, weighted by how much each of them did. */
  capture?: number | null;
  /** What they were charged for the period before this one. */
  last_charged?: { amount: number; period: string } | null;
  /** What this client's usual share of the firm's period comes to in this
   *  one's hours. Null until they have two prior periods to take a share of. */
  typical_hours?: number | null;
  prior_year_billed: number | null;
  last_invoice: { date: string; amount: number } | null;
};

type Payload = {
  period: { start: string; end: string };
  totals: { clients: number; hours: number; value: number; unapproved_hours: number };
  tail?: { clients: number; hours: number; value: number };
  /** capture: 0..1 of scheduled time the firm's people actually recorded.
   *  unassigned_hours: captured time this period with no client on it. */
  completeness?: { capture: number | null; unassigned_billable_hours: number };
  uses_approval?: boolean;
  clients: FeeClient[];
};

const money = (n: number) =>
  n >= 1000 ? `$${Math.round(n).toLocaleString()}` : `$${n.toFixed(0)}`;

const round2 = (n: number) => Math.round(n * 100) / 100;

/** "23% under standard" / "at standard" — what the fee gives away, in the
 *  vocabulary of the decision rather than as a raw write-down figure. */
function pctOfStandard(amount: number, standard: number) {
  const pct = Math.round(((amount - standard) / standard) * 100);
  if (pct === 0) return 'at standard';
  return pct < 0 ? `${Math.abs(pct)}% under standard` : `${pct}% over standard`;
}

function isWholeMonth(startIso: string, endIso: string) {
  const start = new Date(startIso + 'T00:00:00');
  const end = new Date(endIso + 'T00:00:00');
  const lastOfMonth = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  return start.getDate() === 1 && end.getTime() === lastOfMonth.getTime();
}

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
  const [showTail, setShowTail] = useState(false);

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
  // The stepper only ever produces whole months, but the endpoint accepts any
  // range, so the label follows the data rather than assuming.
  const periodIsMonth = isWholeMonth(data.period.start, data.period.end);
  const capture = data.completeness?.capture ?? null;
  const shownClients = data.clients;
  // The sub-hour tail is real work the firm still charges for, so it is never
  // dropped — but 44 rounding errors standing between a partner and the eight
  // clients that need thinking about is how a page stops being used.
  const mainRows = shownClients.filter((c) => c.material !== false);
  const tailRows = shownClients.filter((c) => c.material === false);

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

      {/* ── What the numbers below are standing on ─────────────────────
          Said once, plainly, because a partner pricing off a silent
          under-count either loses money or applies a private gut multiplier —
          and in the second case his instinct is the barometer and this page is
          decoration. */}
      {capture != null && capture < 0.9 && (
        <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
          <p className="text-[13px] leading-relaxed text-amber-900">
            Your team's agents captured about{' '}
            <span className="font-semibold">{Math.round(capture * 100)}%</span> of their
            scheduled time this {periodIsMonth ? 'month' : 'period'}, so every figure below
            is a floor — hours we saw, not hours worked.
            {data.completeness && data.completeness.unassigned_billable_hours >= 1 && (
              <>
                {' '}A further{' '}
                <span className="font-semibold">
                  {data.completeness.unassigned_billable_hours.toFixed(1)}h
                </span>{' '}
                of billable time was captured with no client on it.{' '}
                <a href="/daily" className="font-medium underline underline-offset-2">
                  Settle it in Daily Review
                </a>{' '}
                and it lands on these rows.
              </>
            )}
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
          {(showTail ? [...mainRows, ...tailRows] : mainRows).map((c) => {
            const delta = priorYearDelta(c);
            const feeBudget =
              c.budget_is_fee && c.budget_hours != null && c.budget_hours > 0
                ? c.budget_hours
                : null;
            const overBudget = feeBudget != null && c.hours > feeBudget;
            const typical = feeBudget == null ? c.typical_hours ?? null : null;
            const typicalDelta = typical != null ? c.hours - typical : 0;
            // How completely the people who did THIS client's work were
            // captured. A firm-wide average would hide both the client worked
            // by someone the agent sees all day and the one worked by someone
            // who barely runs it.
            const seen = c.capture ?? null;
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
                  {/* The doubt belongs next to the people, because that is
                      where it comes from: this is their capture, weighted by
                      how much of this client's work each of them did. */}
                  {seen != null && seen < 0.9 && (
                    <span
                      className={cn(
                        'font-medium',
                        seen < 0.5 ? 'text-amber-700' : 'text-muted-foreground'
                      )}
                      title={`We captured about ${Math.round(seen * 100)}% of the scheduled time of the people who worked this client, so their hours here are a floor.`}
                    >
                      {Math.round(seen * 100)}% of their time captured
                    </span>
                  )}
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
                {(delta || feeBudget || typical || c.prior_year_billed || c.last_invoice) && (
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
                    {feeBudget != null && (
                      <span className={cn(overBudget ? 'font-medium text-amber-700' : 'text-muted-foreground')}>
                        Budget{' '}
                        <span className="font-mono tabular-nums">{feeBudget.toFixed(1)}h</span>
                        {overBudget && ` · over by ${(c.hours - feeBudget).toFixed(1)}h`}
                      </span>
                    )}
                    {typical != null && (
                      <span className="text-muted-foreground">
                        {periodIsMonth ? 'Typical month' : 'Typical period'}{' '}
                        <span className="font-mono tabular-nums text-foreground/80">
                          {typical.toFixed(1)}h
                        </span>
                        {Math.abs(typicalDelta) >= 0.1 && (
                          <span className="font-mono tabular-nums">
                            {` · ${typicalDelta > 0 ? '+' : '−'}${Math.abs(typicalDelta).toFixed(1)}h`}
                          </span>
                        )}
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

      {tailRows.length > 0 && (
        <button
          onClick={() => setShowTail((v) => !v)}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-border/70 px-4 py-2.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
        >
          {showTail ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {showTail ? 'Hide' : 'Show'} {tailRows.length} client
          {tailRows.length === 1 ? '' : 's'} under an hour
          {data.tail && !showTail && (
            <span className="text-muted-foreground/70">
              · {data.tail.hours.toFixed(1)}h · {money(data.tail.value)} between them
            </span>
          )}
        </button>
      )}

      <p className="px-1 text-[12px] leading-relaxed text-muted-foreground">
        These figures are a reference, not an invoice. Value shown is time at standard rates —
        what the work would come to before any judgement about scope, relationship, or what was
        actually agreed. Hours are what the agents captured, never what was worked — treat
        every figure as a minimum. “Typical {periodIsMonth ? 'month' : 'period'}” is this
        client's usual share of the firm's work, at this{' '}
        {periodIsMonth ? 'month' : 'period'}'s size, so a {periodIsMonth ? 'month' : 'period'}{' '}
        where more of the firm was captured does not read as a client doing more. Fees are set
        in Settings → Economics; nothing on this page changes anything.
      </p>
    </div>
  );
}
