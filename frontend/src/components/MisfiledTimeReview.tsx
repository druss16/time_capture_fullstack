// src/components/MisfiledTimeReview.tsx
//
// "Check for misfiled time" — the misfile sweep on the Approvals tab.
//
// A manager approving somebody else's week never saw the windows the time came
// from. The Certain bucket is the risky half of that week: time the classifier
// committed on its own, which nothing re-examines afterwards, so a block on the
// wrong client stays silent until the client is billed for it.
//
// This runs the same detector as the MavOps Mismatches tab (one shared core on
// the server), pointed at the weeks in front of the reviewer. Three verdicts,
// deliberately not merged into one list, because they want different responses:
//
//   client   — the title distinctively names a DIFFERENT client. One nameable
//              target, so one click fixes it. This is the bucket that costs money.
//   unsure   — the booked client isn't in its own title, but same-family rivals
//              tie. Ranked candidates, no auto-fix: the tie IS the finding.
//   internal — the same disagreement against a firm/admin bucket. Real, never a
//              billing error, so it stays collapsed and out of the headline count.
//
// ── Design rules this file follows ──────────────────────────────────────────
// 1. BUTTON WEIGHT TRACKS MACHINE CONFIDENCE. A solid, filled action means the
//    detector named one target and is confident. An outlined action means it
//    could NOT decide and the human is the one choosing. Two solid buttons side
//    by side for a tie would claim a certainty that doesn't exist.
// 2. ONE COLOUR, ONE MEANING. Red = booked to the wrong client. Amber = worth a
//    look, undecided. Green = confirm it's fine. Slate = context, never a verdict.
// 3. MINUTES ARE THE MATERIALITY CUE. A 1-minute block and a 3-hour block are
//    the same row without them, so they are the one number set large.
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, RefreshCw,
  ScanSearch, Undo2, HelpCircle, UserCheck, ArrowRight,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Candidate {
  client_id: number;
  client_name: string;
  coverage: number;
  abs_hit: number;
}

interface Row {
  block_id: number;
  user: string | null;
  user_id: number | null;
  minutes: number;
  timesheet_id: number | null;
  date: string;
  window_title: string;
  app_name: string;
  booked_client_id: number;
  booked_client_name: string;
  looks_like_client_id?: number;
  looks_like_client_name?: string;
  bucket: 'client' | 'internal' | 'unsure';
  verdict?: 'booked_absent';
  set_by?: 'user' | 'classifier';
  candidates?: Candidate[];
  confidence: {
    looks_like_coverage?: number;
    top_candidate_coverage?: number;
    booked_coverage: number;
    abs_hit: number;
  };
}

interface Bucket {
  total: number;
  returned: number;
  top_pairs: { pair: string; count: number }[];
  mismatches: Row[];
}

interface Week {
  timesheet_id: number;
  user_id: number | null;
  user_name: string | null;
  week_start: string;
  status: string;
  editable: boolean;
}

export interface MisfiledResponse {
  params: { org_id: number; scope: string; timesheet_ids: number[] };
  weeks: Week[];
  scanned_blocks: number;
  dismissed_blocks: number;
  by_timesheet: Record<string, { count: number; minutes: number }>;
  uncommitted_blocks: number;
  client: Bucket;
  internal: Bucket;
  unsure: Bucket;
  clients: { id: number; name: string }[];
}

type Tone = 'red' | 'amber' | 'slate';

// Every colour decision for a verdict lives here rather than being spelled out
// at each use site, so "amber means undecided" can't quietly drift row by row.
const TONES: Record<Tone, {
  rail: string; count: string; chip: string; solid: string; outline: string;
}> = {
  red: {
    rail: 'bg-red-400',
    count: 'bg-red-100 text-red-700',
    chip: 'bg-red-50 text-red-700 border-red-200',
    solid: 'bg-red-600 text-white hover:bg-red-700 border border-red-600',
    outline: 'bg-white text-red-700 border border-red-300 hover:bg-red-50',
  },
  amber: {
    rail: 'bg-amber-400',
    count: 'bg-amber-100 text-amber-800',
    chip: 'bg-amber-50 text-amber-800 border-amber-200',
    solid: 'bg-amber-500 text-white hover:bg-amber-600 border border-amber-500',
    outline: 'bg-white text-amber-800 border border-amber-300 hover:bg-amber-50',
  },
  slate: {
    rail: 'bg-slate-300',
    count: 'bg-slate-100 text-slate-600',
    chip: 'bg-slate-50 text-slate-600 border-slate-200',
    solid: 'bg-slate-700 text-white hover:bg-slate-800 border border-slate-700',
    outline: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50',
  },
};

// ── Utilities ─────────────────────────────────────────────────────────────────

const formatMinutes = (m: number): string => {
  if (!m) return '0m';
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (!h) return `${mm}m`;
  return mm ? `${h}h ${mm}m` : `${h}h`;
};

const formatDate = (iso: string): string =>
  new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

// ── Client name ───────────────────────────────────────────────────────────────

const ClientChip: React.FC<{ name: string; variant: 'booked' | Tone }> = ({ name, variant }) => (
  <span
    className={cn(
      'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold border max-w-[260px] truncate align-middle',
      variant === 'booked'
        ? 'bg-white text-slate-700 border-slate-300'
        : TONES[variant].chip
    )}
    title={name}
  >
    {name}
  </span>
);

// ── One flagged block ─────────────────────────────────────────────────────────

const FlagRow: React.FC<{
  row: Row;
  tone: Tone;
  week: Week | undefined;
  clients: { id: number; name: string }[];
  selected: boolean;
  onToggle: () => void;
  onMove: (blockIds: number[], clientId: number, clientName: string) => Promise<void>;
  onCorrect: (blockIds: number[]) => Promise<void>;
  busy: boolean;
}> = ({ row, tone, week, clients, selected, onToggle, onMove, onCorrect, busy }) => {
  const [picking, setPicking] = useState(false);
  const [pick, setPick] = useState<number | ''>('');
  const t = TONES[tone];
  const locked = week ? !week.editable : false;

  // A tie the detector could not resolve gets OUTLINED actions: the machine is
  // not recommending either one, the person is choosing. A single named target
  // gets a solid button, because there the machine is making a call.
  const isTie = row.verdict === 'booked_absent';
  const actionCls = isTie ? t.outline : t.solid;

  // A person deliberately allocating time reads identically to a classifier
  // error in the numbers, but it is the strongest signal that nothing is wrong
  // — so it gets a sentence, not a chip the eye slides past.
  const byHand = row.set_by === 'user';
  // Sub-2-minute blocks are real but rarely worth a manager's attention; they
  // stay visible and stay dimmed rather than being hidden.
  const trivial = row.minutes < 2;

  return (
    <div
      className={cn(
        'relative flex gap-3 pl-4 pr-4 py-3.5 border-t border-border/40 transition-colors',
        selected ? 'bg-primary/[0.04]' : 'hover:bg-slate-50/70'
      )}
    >
      {/* Verdict rail — groups the four stacked lines into one visual unit */}
      <span className={cn('absolute left-0 top-0 bottom-0 w-[3px]', t.rail)} aria-hidden />

      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        disabled={locked}
        className="mt-0.5 accent-primary cursor-pointer disabled:cursor-not-allowed shrink-0"
        aria-label={`Select block ${row.block_id}`}
      />

      <div className="min-w-0 flex-1">
        {/* Line 1 — who, when, and how much time is at stake */}
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm font-bold text-slate-800">{row.user || 'Unknown'}</span>
          <span className="text-xs text-slate-400">{formatDate(row.date)}</span>
          <span
            className={cn(
              'text-sm font-bold tabular-nums',
              trivial ? 'text-slate-300' : 'text-slate-600'
            )}
          >
            {formatMinutes(row.minutes)}
          </span>
          {locked && (
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
              week {week?.status} — reopen to change
            </span>
          )}
        </div>

        {/* Line 2 — the disagreement, as a sentence rather than caption soup */}
        <div className="flex items-center gap-1.5 flex-wrap mt-1.5 text-xs text-slate-500">
          <span>Booked to</span>
          <ClientChip name={row.booked_client_name} variant="booked" />
          <ArrowRight className="w-3.5 h-3.5 text-slate-300 shrink-0" />
          {isTie ? (
            <>
              <span>not named in the title. Could be</span>
              {(row.candidates || []).map((c, i) => (
                <React.Fragment key={c.client_id}>
                  {i > 0 && <span className="text-slate-400">or</span>}
                  <ClientChip name={c.client_name} variant={tone} />
                </React.Fragment>
              ))}
            </>
          ) : (
            <>
              <span>but the title names</span>
              <ClientChip name={row.looks_like_client_name || '?'} variant={tone} />
            </>
          )}
        </div>

        {/* Line 3 — the evidence, verbatim and quiet */}
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500 font-mono bg-slate-50/80 rounded-md px-2.5 py-1.5 break-all border border-border/40">
          {row.app_name && <span className="text-slate-400">{row.app_name} — </span>}
          {row.window_title}
        </p>

        {/* The one qualifier that most often means "leave it alone" */}
        {byHand && (
          <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-amber-700">
            <UserCheck className="w-3.5 h-3.5 shrink-0 mt-px" />
            <span>A person put this on {row.booked_client_name} by hand — likely deliberate.</span>
          </p>
        )}

        {/* Line 4 — what to do about it */}
        {!locked && (
          <div className="flex items-center gap-2 flex-wrap mt-2.5">
            {row.looks_like_client_id && row.looks_like_client_name && (
              <button
                disabled={busy}
                onClick={() => onMove([row.block_id], row.looks_like_client_id!, row.looks_like_client_name!)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-semibold disabled:opacity-50 transition-colors',
                  actionCls
                )}
              >
                Move to {row.looks_like_client_name}
              </button>
            )}
            {(row.candidates || []).map((c) => (
              <button
                key={c.client_id}
                disabled={busy}
                onClick={() => onMove([row.block_id], c.client_id, c.client_name)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-semibold disabled:opacity-50 transition-colors',
                  actionCls
                )}
              >
                Move to {c.client_name}
              </button>
            ))}

            <span className="w-px h-4 bg-border/70" aria-hidden />

            <button
              disabled={busy}
              onClick={() => onCorrect([row.block_id])}
              className="px-2.5 py-1 rounded-md text-xs font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 transition-colors"
            >
              It&rsquo;s right
            </button>

            {/* Escape hatch for the case neither the target nor the candidates
                cover — the row is wrong but the answer is a third client. */}
            {picking ? (
              <span className="inline-flex items-center gap-1.5">
                <select
                  value={pick}
                  autoFocus
                  onChange={(e) => setPick(e.target.value ? Number(e.target.value) : '')}
                  className="text-xs border border-border/60 rounded-md px-2 py-1 max-w-[220px] bg-white"
                >
                  <option value="">choose a client…</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
                <button
                  disabled={!pick || busy}
                  onClick={() => {
                    const c = clients.find((x) => x.id === pick);
                    if (!c) return;
                    onMove([row.block_id], c.id, c.name);
                    setPicking(false);
                    setPick('');
                  }}
                  className="px-2 py-1 rounded-md text-xs font-semibold bg-slate-700 text-white hover:bg-slate-800 disabled:opacity-40"
                >
                  Move
                </button>
                <button
                  onClick={() => { setPicking(false); setPick(''); }}
                  className="text-xs text-slate-400 hover:text-slate-600 px-1"
                >
                  cancel
                </button>
              </span>
            ) : (
              <button
                onClick={() => setPicking(true)}
                className="px-2.5 py-1 rounded-md text-xs font-medium text-slate-500 hover:bg-slate-100 transition-colors"
              >
                Someone else…
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// ── One verdict section ───────────────────────────────────────────────────────

const Section: React.FC<{
  title: string;
  blurb: string;
  tone: Tone;
  bucket: Bucket;
  weeks: Map<number, Week>;
  clients: { id: number; name: string }[];
  selected: Set<number>;
  toggle: (id: number) => void;
  onMove: (blockIds: number[], clientId: number, clientName: string) => Promise<void>;
  onCorrect: (blockIds: number[]) => Promise<void>;
  busy: boolean;
  defaultOpen: boolean;
}> = ({ title, blurb, tone, bucket, weeks, clients, selected, toggle, onMove, onCorrect, busy, defaultOpen }) => {
  const [open, setOpen] = useState(defaultOpen);
  const t = TONES[tone];
  if (!bucket.total) return null;

  return (
    <div className="border-t border-border/60">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-2.5 flex items-center gap-2.5 hover:bg-slate-50/70 transition-colors text-left"
      >
        {open
          ? <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
          : <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />}
        <span
          className={cn(
            'inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full text-[11px] font-bold shrink-0',
            t.count
          )}
        >
          {bucket.total}
        </span>
        <span className="text-sm font-bold text-slate-800 shrink-0">{title}</span>
        <span className="text-xs text-slate-400 truncate hidden sm:inline">{blurb}</span>
      </button>

      {open && (
        <div>
          {bucket.mismatches.map((row) => (
            <FlagRow
              key={row.block_id}
              row={row}
              tone={tone}
              week={row.timesheet_id != null ? weeks.get(row.timesheet_id) : undefined}
              clients={clients}
              selected={selected.has(row.block_id)}
              onToggle={() => toggle(row.block_id)}
              onMove={onMove}
              onCorrect={onCorrect}
              busy={busy}
            />
          ))}
          {bucket.returned < bucket.total && (
            <p className="px-4 py-2.5 text-xs text-slate-400 border-t border-border/40">
              Showing {bucket.returned} of {bucket.total}. Fix these and reload to see the rest.
            </p>
          )}
        </div>
      )}
    </div>
  );
};

// ── Main ──────────────────────────────────────────────────────────────────────

const MisfiledTimeReview: React.FC<{
  /** Lets the Approvals table badge each week before anyone clicks Approve. */
  onCounts?: (counts: Record<string, { count: number; minutes: number }>) => void;
  /** Re-run the sweep whenever the queue changes underneath it. */
  refreshKey?: number;
}> = ({ onCounts, refreshKey = 0 }) => {
  const [data, setData] = useState<MisfiledResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkClient, setBulkClient] = useState<number | ''>('');
  const [open, setOpen] = useState(false);
  // "It's right" is one click on a dense list and it WILL get mis-clicked, so
  // the way back is right there rather than a database edit.
  const [undo, setUndo] = useState<{ blockIds: number[]; label: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await safeFetchJson<MisfiledResponse>(`${API_BASE}/review/misfiled/?scope=open`);
      setData(d);
      setSelected(new Set());
      onCounts?.(d.by_timesheet || {});
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not run the check');
    } finally {
      setLoading(false);
    }
  }, [onCounts]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const weeks = useMemo(
    () => new Map((data?.weeks || []).map((w) => [w.timesheet_id, w])),
    [data]
  );

  // "18 weeks" reads as eighteen calendar weeks when it's really eighteen
  // person-weeks, so say what was actually covered.
  const coverage = useMemo(() => {
    const ws = data?.weeks || [];
    const people = new Set(ws.map((w) => w.user_id)).size;
    const spans = new Set(ws.map((w) => w.week_start)).size;
    return { people, spans };
  }, [data]);

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const resolve = async (body: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      return await safeFetchJson<any>(`${API_BASE}/review/misfiled/resolve/`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    } finally {
      setBusy(false);
    }
  };

  const onMove = async (blockIds: number[], clientId: number, clientName: string) => {
    try {
      const r = await resolve({ block_ids: blockIds, action: 'move', client_id: clientId });
      // Report honestly: the server refuses invoiced time and approved weeks,
      // and silently showing "moved" for those would be a lie the reviewer
      // only discovers at billing.
      if (r?.skipped) {
        setError(
          `Moved ${r.moved} to ${clientName}. ${r.skipped} left alone — ` +
          `${(r.skips || []).map((s: any) => s.reason).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i).join('; ')}.`
        );
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Move failed');
    }
  };

  const onCorrect = async (blockIds: number[]) => {
    try {
      await resolve({ block_ids: blockIds, action: 'correct' });
      setUndo({ blockIds, label: `${blockIds.length} marked correct` });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not clear that');
    }
  };

  const onUndo = async () => {
    if (!undo) return;
    try {
      await resolve({ block_ids: undo.blockIds, action: 'reopen' });
      setUndo(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Undo failed');
    }
  };

  const clientTotal = data?.client.total || 0;
  const unsureTotal = data?.unsure.total || 0;
  const flagged = clientTotal + unsureTotal;

  return (
    <div className="shrink-0 space-y-2">
      {/* One card owns the header AND the findings, so the sections read as
          living inside the check rather than floating beside it. */}
      <div
        className={cn(
          'bg-white rounded-xl border overflow-hidden',
          clientTotal > 0 ? 'border-red-200' : 'border-border/60'
        )}
      >
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="px-5 py-3 flex items-center justify-between gap-4">
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-3 text-left min-w-0 group"
            disabled={flagged === 0 && !loading}
          >
            {flagged > 0 && (
              open
                ? <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
                : <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
            )}
            <ScanSearch
              className={cn(
                'w-4 h-4 shrink-0',
                clientTotal > 0 ? 'text-red-500' : unsureTotal > 0 ? 'text-amber-500' : 'text-slate-400'
              )}
            />
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-800">Check for misfiled time</p>
              <p className="text-xs text-slate-400 truncate">
                {loading
                  ? 'Scanning confirmed time…'
                  : data
                  ? `${data.scanned_blocks.toLocaleString()} confirmed blocks · ${coverage.people} ${coverage.people === 1 ? 'person' : 'people'} · ${coverage.spans} ${coverage.spans === 1 ? 'week' : 'weeks'}`
                  : '—'}
              </p>
            </div>
          </button>

          <div className="flex items-center gap-2 shrink-0">
            {!loading && data && (
              flagged === 0 ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-emerald-50 text-emerald-700 border-emerald-200">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Nothing looks misfiled
                </span>
              ) : (
                <>
                  {clientTotal > 0 && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-red-50 text-red-700 border-red-200">
                      <AlertTriangle className="w-3.5 h-3.5" /> {clientTotal} wrong client
                    </span>
                  )}
                  {unsureTotal > 0 && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-amber-50 text-amber-800 border-amber-200">
                      <HelpCircle className="w-3.5 h-3.5" /> {unsureTotal} to check
                    </span>
                  )}
                </>
              )
            )}
            <button
              onClick={load}
              disabled={loading || busy}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-40"
              title="Re-run the check"
            >
              <RefreshCw className={cn('w-4 h-4', (loading || busy) && 'animate-spin')} />
            </button>
          </div>
        </div>

        {/* ── Findings ───────────────────────────────────────────────────── */}
        {open && data && !loading && flagged > 0 && (
          <div className="max-h-[52vh] overflow-auto">
            {/* Bulk bar — only worth showing once something is picked. */}
            {selected.size > 0 && (
              <div className="border-t border-border/60 bg-slate-50/80 px-4 py-2.5 flex items-center gap-3 flex-wrap sticky top-0 z-10">
                <span className="text-xs font-bold text-slate-700">{selected.size} selected</span>
                <div className="flex-1" />
                <select
                  value={bulkClient}
                  onChange={(e) => setBulkClient(e.target.value ? Number(e.target.value) : '')}
                  className="text-xs border border-border/60 rounded-md px-2 py-1.5 max-w-[240px] bg-white"
                >
                  <option value="">move all to…</option>
                  {data.clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
                <button
                  disabled={!bulkClient || busy}
                  onClick={() => {
                    const c = data.clients.find((x) => x.id === bulkClient);
                    if (!c) return;
                    onMove([...selected], c.id, c.name);
                    setBulkClient('');
                  }}
                  className="px-3 py-1.5 rounded-md text-xs font-semibold bg-primary text-white hover:opacity-90 disabled:opacity-40"
                >
                  Move
                </button>
                <button
                  disabled={busy}
                  onClick={() => onCorrect([...selected])}
                  className="px-3 py-1.5 rounded-md text-xs font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                >
                  These are right
                </button>
                <button
                  onClick={() => setSelected(new Set())}
                  className="text-xs text-slate-400 hover:text-slate-600 px-1"
                >
                  clear
                </button>
              </div>
            )}

            <Section
              title="Looks like the wrong client"
              blurb="the title names someone else"
              tone="red"
              bucket={data.client}
              weeks={weeks}
              clients={data.clients}
              selected={selected}
              toggle={toggle}
              onMove={onMove}
              onCorrect={onCorrect}
              busy={busy}
              defaultOpen
            />
            <Section
              title="Worth a look"
              blurb="the booked client isn't in the title, and the runners-up tie"
              tone="amber"
              bucket={data.unsure}
              weeks={weeks}
              clients={data.clients}
              selected={selected}
              toggle={toggle}
              onMove={onMove}
              onCorrect={onCorrect}
              busy={busy}
              defaultOpen={data.client.total === 0}
            />
            <Section
              title="Internal & admin buckets"
              blurb="real, but not a client billing error"
              tone="slate"
              bucket={data.internal}
              weeks={weeks}
              clients={data.clients}
              selected={selected}
              toggle={toggle}
              onMove={onMove}
              onCorrect={onCorrect}
              busy={busy}
              defaultOpen={false}
            />

            {/* Context a reviewer needs but that isn't a mismatch. */}
            <p className="border-t border-border/40 px-4 py-2.5 text-[11px] leading-relaxed text-slate-400">
              Weeks still in progress are included, so a misfile can be caught before it&rsquo;s submitted.
              {data.dismissed_blocks > 0 &&
                ` ${data.dismissed_blocks} previously marked correct.`}
              {data.uncommitted_blocks > 0 &&
                ` ${data.uncommitted_blocks} block${data.uncommitted_blocks === 1 ? '' : 's'} nobody has confirmed yet stay in each person's Daily Review.`}
            </p>
          </div>
        )}
      </div>

      {/* Undo / error strips — outside the card so they read as transient */}
      {undo && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border bg-emerald-50 border-emerald-200 text-sm">
          <span className="text-emerald-700 font-medium">{undo.label} — they won&rsquo;t be flagged again.</span>
          <button
            onClick={onUndo}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-800 hover:underline shrink-0"
          >
            <Undo2 className="w-3.5 h-3.5" /> Undo
          </button>
        </div>
      )}
      {error && (
        <div className="flex items-start gap-3 px-4 py-3 rounded-lg border bg-amber-50 border-amber-200 text-sm">
          <AlertTriangle className="w-4 h-4 mt-0.5 text-amber-500 shrink-0" />
          <p className="text-amber-800">{error}</p>
        </div>
      )}
    </div>
  );
};

export default MisfiledTimeReview;
