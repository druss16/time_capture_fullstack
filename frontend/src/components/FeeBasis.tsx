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
 * An anchor is only shown when it was measured the same way as the number it
 * sits beside. "Budget" appears for a budget the firm typed in from its own fee
 * schedule; a budget the ladder derived from a month when the agent saw 42% of
 * the week is not shown, because comparing it against a better-captured month
 * reports an overrun nobody had. Those rows get the client's own typical period
 * instead, carried across as a share of the firm's month so that growing
 * coverage does not read as growing work — which answers what the partner is
 * really asking: is this month unusual for them?
 *
 * And the number can be set here. It could not before: this page showed the
 * evidence while the only place to record a decision was Settings → Economics
 * → Engagement budgets, two clicks away and showing none of it. Same endpoint,
 * same client x job-type grain as that tab and as the CSV importer — all three
 * must agree about what a fee belongs to — so a fee typed here is the same
 * `manual` budget, and the nightly derivation pass will not undo it.
 *
 * It counts every captured block, including time nobody has reviewed. On a
 * screen whose job is to stop a firm underbilling, hiding hours is the one
 * unrecoverable mistake — a fee set from a number that was quietly 90% short
 * is money gone for good.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  RefreshCw, Users, ChevronLeft, ChevronRight, Info,
  Check, Loader2, Tag, X,
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
  /** What this client's usual share of the firm's period comes to in this
   *  one's hours. Null until they have two prior periods to take a share of. */
  typical_hours?: number | null;
  prior_year_billed: number | null;
  last_invoice: { date: string; amount: number } | null;
};

/** One client x job type with an open engagement — the grain a fee belongs to.
 *  Straight from /engagements/budget-setup/, the same feed the Economics tab
 *  reads, so the two screens cannot drift apart. */
type Job = {
  client_id: number;
  client_name: string;
  engagement_type: string;
  open_periods: number;
  typical_hours: number;
  budget_hours: number | null;
  budget_fee: number | null;
  budget_source: string;
};

type Payload = {
  period: { start: string; end: string };
  totals: { clients: number; hours: number; value: number; unapproved_hours: number };
  uses_approval?: boolean;
  clients: FeeClient[];
};

const money = (n: number) =>
  n >= 1000 ? `$${Math.round(n).toLocaleString()}` : `$${n.toFixed(0)}`;

const jobLabel = (t: string) =>
  t.replace(/_/g, ' ').replace(/^./, (ch) => ch.toUpperCase());

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

  // ── Setting the fee ────────────────────────────────────────────────────
  // Jobs are fetched once, on the first row anyone opens. The list is small
  // (one row per client x job type) but it is beside the point on a page most
  // partners will only read, so it does not load with the period.
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [jobsErr, setJobsErr] = useState<string | null>(null);
  const [openClient, setOpenClient] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    setJobsErr(null);
    try {
      const d = await safeFetchJson<{ rows: Job[] }>(`${API_BASE}/engagements/budget-setup/`);
      setJobs(d.rows || []);
    } catch (e: any) {
      setJobsErr(e?.message || "Couldn't load this client's jobs");
      setJobs([]);
    }
  }, []);

  const toggleClient = (clientId: number) => {
    setSaved(null);
    // Clear the error with the row: a complaint about what was typed for one
    // client, still sitting under the next client's job, is worse than no
    // message at all.
    setJobsErr(null);
    setOpenClient((cur) => (cur === clientId ? null : clientId));
    if (jobs === null) void loadJobs();
  };

  const saveFee = async (job: Job) => {
    const key = `${job.client_id}:${job.engagement_type}`;
    const raw = (draft[key] ?? '').trim();
    if (!raw) return;
    const fee = Number(raw.replace(/[$,\s]/g, ''));
    if (!Number.isFinite(fee) || fee <= 0) {
      setJobsErr('Enter the fee as a number greater than zero.');
      return;
    }
    setSaving(key);
    setJobsErr(null);
    try {
      await safeFetchJson(`${API_BASE}/engagements/budget-group/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: job.client_id,
          engagement_type: job.engagement_type,
          monthly_fee: fee,
          set_in: 'Fees',
        }),
      });
      setDraft((d) => { const next = { ...d }; delete next[key]; return next; });
      setSaved(key);
      // Both feeds move: the job row shows the new fee, and the client's row
      // above it swaps its "typical" anchor for the budget that now exists.
      await Promise.all([loadJobs(), load(range)]);
    } catch (e: any) {
      setJobsErr(e?.message || 'Could not save that fee');
    } finally {
      setSaving(null);
    }
  };

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
            const feeBudget =
              c.budget_is_fee && c.budget_hours != null && c.budget_hours > 0
                ? c.budget_hours
                : null;
            const overBudget = feeBudget != null && c.hours > feeBudget;
            const typical = feeBudget == null ? c.typical_hours ?? null : null;
            const typicalDelta = typical != null ? c.hours - typical : 0;
            const isOpen = openClient === c.client_id;
            const clientJobs = (jobs || []).filter((j) => j.client_id === c.client_id);
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
                  <span className="flex-1" />
                  <button
                    onClick={() => toggleClient(c.client_id)}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1',
                      'text-[11.5px] font-semibold transition-colors',
                      isOpen
                        ? 'border-primary/30 bg-primary/8 text-primary'
                        : 'border-border text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                    )}
                  >
                    {isOpen ? <X className="h-3 w-3" /> : <Tag className="h-3 w-3" />}
                    {isOpen ? 'Close' : feeBudget != null ? 'Change fee' : 'Set fee'}
                  </button>
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

                {isOpen && (
                  <div className="mt-3 rounded-xl border border-border/70 bg-muted/30 p-3">
                    {jobs === null ? (
                      <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading this client's jobs…
                      </p>
                    ) : clientJobs.length === 0 ? (
                      // No recurring job means nothing to attach a fee to. Saying
                      // so beats an empty box that looks broken.
                      <p className="text-[12.5px] text-muted-foreground">
                        No recurring job on file for {c.name}, so there is nothing to price
                        yet. Recurring work appears here once it has been through a period.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {clientJobs.map((j) => {
                          const key = `${j.client_id}:${j.engagement_type}`;
                          const isSaving = saving === key;
                          const justSaved = saved === key;
                          const current = j.budget_source === 'manual' ? j.budget_fee : null;
                          return (
                            <div key={key} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                              <span className="min-w-[8.5rem] text-[12.5px] font-semibold text-foreground">
                                {jobLabel(j.engagement_type)}
                              </span>
                              <span className="text-[11.5px] text-muted-foreground">
                                usually{' '}
                                <span className="font-mono tabular-nums text-foreground/80">
                                  {j.typical_hours.toFixed(1)}h
                                </span>
                                {' · '}{j.open_periods} open {j.open_periods === 1 ? 'period' : 'periods'}
                              </span>
                              <span className="flex-1" />
                              {current != null && !justSaved && (
                                <span className="text-[11.5px] text-muted-foreground">
                                  now <span className="font-mono tabular-nums">{money(current)}</span>
                                </span>
                              )}
                              <div className="flex items-center gap-1.5">
                                <span className="text-[12.5px] text-muted-foreground">$</span>
                                <input
                                  value={draft[key] ?? ''}
                                  onChange={(e) =>
                                    setDraft((d) => ({ ...d, [key]: e.target.value }))
                                  }
                                  onKeyDown={(e) => { if (e.key === 'Enter') void saveFee(j); }}
                                  inputMode="decimal"
                                  placeholder={current != null ? String(Math.round(current)) : 'fee'}
                                  className="w-24 rounded-lg border border-border bg-card px-2 py-1 font-mono text-[12.5px] tabular-nums outline-none focus:border-primary/50"
                                />
                                <span className="text-[11.5px] text-muted-foreground">per period</span>
                                <button
                                  onClick={() => void saveFee(j)}
                                  disabled={isSaving || !(draft[key] ?? '').trim()}
                                  className={cn(
                                    'inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-[11.5px] font-semibold transition-all',
                                    (draft[key] ?? '').trim() && !isSaving
                                      ? 'bg-primary text-primary-foreground hover:opacity-90'
                                      : 'cursor-not-allowed bg-muted text-muted-foreground'
                                  )}
                                >
                                  {isSaving ? <Loader2 className="h-3 w-3 animate-spin" />
                                    : justSaved ? <Check className="h-3 w-3" /> : null}
                                  {isSaving ? 'Saving' : justSaved ? 'Saved' : 'Save'}
                                </button>
                              </div>
                            </div>
                          );
                        })}
                        <p className="pt-1 text-[11.5px] text-muted-foreground">
                          A fee saves across every open period of that job and will not be
                          overwritten by the nightly estimate. Pricing the whole firm at once?
                          Upload the schedule in{' '}
                          <a href="/settings?tab=economics" className="font-medium text-primary hover:underline">
                            Settings → Economics
                          </a>.
                        </p>
                      </div>
                    )}
                    {jobsErr && (
                      <p className="mt-2 text-[12px] font-medium text-amber-700">{jobsErr}</p>
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
        actually agreed. “Typical {periodIsMonth ? 'month' : 'period'}” is this client's usual
        share of the firm's work, at this {periodIsMonth ? 'month' : 'period'}'s size, so a
        {' '}{periodIsMonth ? 'month' : 'period'} where more of the firm was captured does not
        read as a client doing more. “Budget” appears only where the firm entered a fee itself.
      </p>
    </div>
  );
}
