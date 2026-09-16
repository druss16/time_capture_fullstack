// src/components/FeeBasis.tsx
/**
 * What to charge each client, this month, worked one at a time.
 *
 * This firm re-prices monthly off the hours — a client who took 28 hours is
 * not charged what they were charged for 5 — so the decision this page exists
 * to support happens twelve times a year, per client, and the hours ARE the
 * input. That is why it sits between Daily Review, which settles whose time it
 * was, and the invoice the partner raises in their own system.
 *
 * It records the FEE, never the invoice. What was actually sent, and when, is
 * QuickBooks' fact; a copy of it here would be unverifiable and would drift.
 * What the firm decided to charge, on the other hand, is made right here out
 * of our own numbers — and, kept next to the time at standard rates, it is
 * realization without a single invoice imported from anywhere.
 *
 * This was a report for a long time and it read like one: eighty-two rows, no
 * beginning and no end, nothing to show which clients you had already settled.
 * A partner would read a row, raise the invoice in QuickBooks — that is where
 * the money moves; it does not move here — and come back to a page that looked
 * exactly as it had before.
 *
 * So the list is now finite. Every row ends in a number you charged, "Left to
 * do" hides the ones you have settled, and the count in the header answers
 * "am I nearly finished". The decision is also the anchor the page could never
 * show before: next month this client's row says what you charged them this
 * one, from your own record, with no invoice imported from anywhere.
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
  RefreshCw, Users, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Info,
  Check, Loader2, Tag, X, Copy,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

type Work = { name: string; hours: number };

/** The firm's own record of what it charged, for one client for one period. */
type Decision = {
  amount: number;
  note: string;
  decided_at: string;
  decided_by: string;
};

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
  /** The fee set for this period, once somebody has set it. */
  decision?: Decision | null;
  /** False for the sub-hour tail: shown, but not in the way. */
  material?: boolean;
  /** What they were charged for the period before this one. */
  last_charged?: { amount: number; period: string } | null;
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
  decided?: { clients: number; amount: number };
  tail?: { clients: number; hours: number; value: number };
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

  // ── Working the list ───────────────────────────────────────────────────
  // "Left to do" is the default because the page's job is to run out of rows.
  const [show, setShow] = useState<'todo' | 'done' | 'all'>('todo');
  const [charge, setCharge] = useState<Record<number, string>>({});
  const [deciding, setDeciding] = useState<number | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const [decideErr, setDecideErr] = useState<string | null>(null);
  const [showTail, setShowTail] = useState(false);

  const decide = async (c: FeeClient, amount: number) => {
    if (!range) return;
    setDeciding(c.client_id);
    setDecideErr(null);
    try {
      const res = await safeFetchJson<{ decision: Decision }>(
        `${API_BASE}/billing/fee-decision/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            client_id: c.client_id, start: range.start, end: range.end, amount,
          }),
        }
      );
      // Patch the one row rather than refetching the period: the row is about
      // to leave the list, and a full reload here makes settling a client feel
      // like the slowest thing on the page.
      setData((d) => d && ({
        ...d,
        clients: d.clients.map((x) =>
          x.client_id === c.client_id ? { ...x, decision: res.decision } : x),
        decided: {
          clients: (d.decided?.clients ?? 0) + (c.decision ? 0 : 1),
          amount: round2((d.decided?.amount ?? 0) - (c.decision?.amount ?? 0) + amount),
        },
      }));
      setCharge((m) => { const n = { ...m }; delete n[c.client_id]; return n; });
    } catch (e: any) {
      setDecideErr(e?.message || "Couldn't record that");
    } finally {
      setDeciding(null);
    }
  };

  const undecide = async (c: FeeClient) => {
    if (!range || !c.decision) return;
    setDeciding(c.client_id);
    setDecideErr(null);
    const was = c.decision.amount;
    try {
      await safeFetchJson(`${API_BASE}/billing/fee-decision/`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: c.client_id, start: range.start, end: range.end,
        }),
      });
      setData((d) => d && ({
        ...d,
        clients: d.clients.map((x) =>
          x.client_id === c.client_id ? { ...x, decision: null } : x),
        decided: {
          clients: Math.max(0, (d.decided?.clients ?? 1) - 1),
          amount: round2((d.decided?.amount ?? was) - was),
        },
      }));
    } catch (e: any) {
      setDecideErr(e?.message || "Couldn't undo that");
    } finally {
      setDeciding(null);
    }
  };

  const copyAmount = async (c: FeeClient, amount: number) => {
    // The invoice is raised in their own system, so the number's last job here
    // is to be easy to carry across.
    try {
      await navigator.clipboard.writeText(amount.toFixed(2));
      setCopied(c.client_id);
      window.setTimeout(() => setCopied((x) => (x === c.client_id ? null : x)), 1500);
    } catch {
      /* clipboard refused (permissions, http) — the number is on screen anyway */
    }
  };

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
  const doneCount = data.decided?.clients ?? 0;
  const decidedAmount = data.decided?.amount ?? 0;
  const todoCount = data.clients.filter((c) => !c.decision).length;
  const shownClients = data.clients.filter((c) =>
    show === 'all' ? true : show === 'done' ? !!c.decision : !c.decision);
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

      {/* ── How much of the month is settled ───────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[13px] text-muted-foreground">
          <span className="font-semibold text-foreground">
            {doneCount} of {totals.clients}
          </span>{' '}
          {/* Plural follows the total, not the count done: "1 of 103 client
              priced" is the kind of wrong that makes a page look unfinished. */}
          {totals.clients === 1 ? 'client' : 'clients'} priced
          {decidedAmount > 0 && (
            <>
              {' · '}
              <span className="font-mono tabular-nums font-semibold text-foreground">
                {money(decidedAmount)}
              </span>{' '}
              this month
            </>
          )}
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-border/60 bg-card p-0.5">
          {([['todo', `Left to do${todoCount ? ` (${todoCount})` : ''}`],
             ['done', 'Priced'],
             ['all', 'All']] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setShow(key)}
              className={cn(
                'rounded-lg px-3 py-1.5 text-[12.5px] font-semibold transition-colors',
                show === key
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {decideErr && (
        <p className="px-1 text-[12.5px] font-medium text-amber-700">{decideErr}</p>
      )}

      {/* ── One row per client ─────────────────────────────────────────── */}
      <div className="overflow-hidden rounded-2xl border border-border/60 bg-card">
        {data.clients.length === 0 && (
          <div className="p-8 text-center text-sm text-muted-foreground">
            No time captured in this period.
          </div>
        )}
        {data.clients.length > 0 && shownClients.length === 0 && (
          // Running out of rows is the goal, so say so rather than showing an
          // empty box that reads like a failure.
          <div className="p-8 text-center">
            <p className="text-sm font-semibold text-foreground">
              {show === 'todo' ? "Every client has a fee for this month."
                : 'No fees set yet for this month.'}
            </p>
            <p className="mt-1 text-[12.5px] text-muted-foreground">
              {show === 'todo'
                ? `${totals.clients} of ${totals.clients} settled.`
                : 'Set a fee below and it will appear here.'}
            </p>
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
            const isOpen = openClient === c.client_id;
            // Never an empty box: the fee they agreed to if the firm has told
            // us one, otherwise this month's time at standard rates.
            const proposed = (c.budget_is_fee && c.budget_amount)
              ? c.budget_amount
              : c.value_at_rates;
            const typedCharge = charge[c.client_id];
            const chargeValue = typedCharge ?? (proposed ? String(Math.round(proposed)) : '');
            const busy = deciding === c.client_id;
            // What he is giving away, shown while he decides it rather than
            // discovered in a report three months later. Only meaningful
            // against time at standard rates, so a flat-fee client — whose
            // number was never derived from hours — gets nothing.
            const typedNum = Number(chargeValue.replace(/[$,\s]/g, ''));
            const vsStandard =
              !c.budget_is_fee && c.value_at_rates > 0 && Number.isFinite(typedNum) && typedNum > 0
                ? (typedNum - c.value_at_rates) / c.value_at_rates
                : null;
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
                    {isOpen ? 'Close' : 'Standing fee'}
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

                {/* ── The row's ending ──────────────────────────────────
                    Every client here is a decision waiting to be made. The
                    money moves in the firm's own system, so the most useful
                    thing this can do is hand over the number and remember that
                    the call was made. */}
                {c.decision ? (
                  <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px]">
                    <span className="inline-flex items-center gap-1.5 rounded-lg bg-primary/8 px-2.5 py-1 font-semibold text-primary">
                      <Check className="h-3.5 w-3.5" />
                      This month {money(c.decision.amount)}
                    </span>
                    {!c.budget_is_fee && c.value_at_rates > 0 && (
                      <span className="text-muted-foreground">
                        {pctOfStandard(c.decision.amount, c.value_at_rates)}
                      </span>
                    )}
                    <span className="text-muted-foreground/70">
                      {c.decision.decided_by || 'someone'} ·{' '}
                      {new Date(c.decision.decided_at).toLocaleDateString('en-US',
                        { month: 'short', day: 'numeric' })}
                    </span>
                    <span className="flex-1" />
                    <button
                      onClick={() => void undecide(c)}
                      disabled={busy}
                      className="rounded-lg px-2 py-1 text-[12px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                    >
                      {busy ? 'Clearing…' : 'Change'}
                    </button>
                  </div>
                ) : (
                  <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
                    <span className="text-[12.5px] text-muted-foreground">This month</span>
                    <div className="flex items-center gap-1">
                      <span className="text-[13px] text-muted-foreground">$</span>
                      <input
                        value={chargeValue}
                        onChange={(e) =>
                          setCharge((m) => ({ ...m, [c.client_id]: e.target.value }))}
                        onKeyDown={(e) => {
                          if (e.key !== 'Enter') return;
                          const n = Number(chargeValue.replace(/[$,\s]/g, ''));
                          if (Number.isFinite(n) && n >= 0) void decide(c, n);
                        }}
                        inputMode="decimal"
                        className="w-28 rounded-lg border border-border bg-card px-2 py-1 font-mono text-[13px] tabular-nums outline-none focus:border-primary/50"
                      />
                    </div>
                    <button
                      onClick={() => {
                        const n = Number(chargeValue.replace(/[$,\s]/g, ''));
                        if (Number.isFinite(n)) void copyAmount(c, n);
                      }}
                      title="Copy the amount, for the invoice in your own system"
                      className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[11.5px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {copied === c.client_id
                        ? <><Check className="h-3 w-3" /> Copied</>
                        : <><Copy className="h-3 w-3" /> Copy</>}
                    </button>
                    {vsStandard != null ? (
                      <span className={cn(
                        'text-[11.5px] font-medium',
                        vsStandard <= -0.2 ? 'text-amber-700' : 'text-muted-foreground'
                      )}>
                        {pctOfStandard(typedNum, c.value_at_rates)}
                      </span>
                    ) : proposed != null && (
                      <span className="text-[11.5px] text-muted-foreground">
                        {c.budget_is_fee ? 'their standing fee' : 'time at standard rates'}
                      </span>
                    )}
                    {/* When the fee moves with the hours every month, what you
                        charged last month is the number the next one is argued
                        against. */}
                    {c.last_charged && (
                      <span className="text-[11.5px] text-muted-foreground">
                        last {periodIsMonth ? 'month' : 'period'}{' '}
                        <span className="font-mono tabular-nums text-foreground/80">
                          {money(c.last_charged.amount)}
                        </span>
                      </span>
                    )}
                    <span className="flex-1" />
                    <button
                      onClick={() => {
                        const n = Number(chargeValue.replace(/[$,\s]/g, ''));
                        if (!Number.isFinite(n) || n < 0) {
                          setDecideErr('Enter the amount as a number.');
                          return;
                        }
                        void decide(c, n);
                      }}
                      disabled={busy || !chargeValue.trim()}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] font-semibold transition-all',
                        busy || !chargeValue.trim()
                          ? 'cursor-not-allowed bg-muted text-muted-foreground'
                          : 'bg-primary text-primary-foreground hover:opacity-90'
                      )}
                    >
                      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      {busy ? 'Saving' : "Set this month's fee"}
                    </button>
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
        actually agreed. “Typical {periodIsMonth ? 'month' : 'period'}” is this client's usual
        share of the firm's work, at this {periodIsMonth ? 'month' : 'period'}'s size, so a
        {' '}{periodIsMonth ? 'month' : 'period'} where more of the firm was captured does not
        read as a client doing more. “Budget” appears only where the firm entered a fee itself.
      </p>
    </div>
  );
}
