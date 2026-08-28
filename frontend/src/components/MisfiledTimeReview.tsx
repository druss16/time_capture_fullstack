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
// the server), pointed at the weeks in front of the reviewer.
//
// ── Design rules ────────────────────────────────────────────────────────────
// 1. EVERY CLIENT NAME APPEARS ONCE. The candidate IS the button. Naming a
//    client in a chip and again in a "Move to <chip>" button doubled the text
//    in the densest part of the row for no added meaning.
// 2. THE ROW IS A SENTENCE WITH NO PROSE. `booked → [target] [target]` says
//    "it's here, these are the alternatives" without connectives. Which bucket
//    a row is in is already stated by its section header; repeating "the title
//    names someone else" on every row is saying it twice.
// 3. GREEN IS THE ANSWER; RED IS THE PROBLEM. The destination button is the
//    thing you are meant to press, so it is green — filled when the detector
//    named one client, outlined when it only got there by elimination. Red is
//    reserved for the rail and the count, which mark that something is wrong.
//    A same-family tie gets neutral buttons and no green at all: colouring one
//    of them would invent a winner the detector explicitly refused to pick.
// 4. THE EVIDENCE IS THE HEADLINE. The window title is the reason the row is
//    here and the only thing that settles it, so it gets read weight, not a
//    dim monospace footnote.
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, RefreshCw,
  ScanSearch, Undo2, HelpCircle,
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

// Colour is split by JOB, not by bucket, because the two were fighting.
//
// TONES marks the PROBLEM — the rail down the row and the count badge. Red
// there means "this one is wrong", which is what red is for.
//
// ACTIONS marks the ANSWER, and is always green, because green is the button
// you are meant to press. Painting the fix red made the remedy look like the
// hazard: a reviewer saw a red button labelled with a client name and hesitated
// over the one click that puts the time where it belongs.
const TONES: Record<Tone, { rail: string; count: string }> = {
  red:   { rail: 'bg-red-400',   count: 'bg-red-100 text-red-700' },
  amber: { rail: 'bg-amber-400', count: 'bg-amber-100 text-amber-800' },
  slate: { rail: 'bg-slate-300', count: 'bg-slate-100 text-slate-600' },
};

const ACTIONS = {
  // One target and the detector named it: this IS the right answer, so it is
  // filled. The strongest thing on the row.
  recommend: 'bg-emerald-600 text-white hover:bg-emerald-700 border border-emerald-600',
  // One target, but the detector only got there by elimination (the booked
  // client is simply absent from its own title). Green, because it is still the
  // answer — outlined, because the machine is suggesting rather than asserting.
  suggest: 'bg-white text-emerald-700 border border-emerald-300 hover:bg-emerald-50',
  // A same-family tie. Deliberately NOT green: with two candidates there is no
  // right choice to highlight, and colouring one green would invent a winner
  // the detector explicitly refused to pick.
  choice: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50',
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

/** "Qbw.Exe" → "Qbw". The .exe is noise in a sentence a person reads. */
const cleanApp = (app: string): string => (app || '').replace(/\.exe$/i, '');

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

  // One render path for both buckets. A wrong-client row carries a single named
  // target; a tie carries ranked candidates. Either way they are the choices,
  // so they are the buttons.
  const isTie = row.verdict === 'booked_absent';
  const targets = isTie
    ? (row.candidates || []).map((c) => ({ id: c.client_id, name: c.client_name }))
    : row.looks_like_client_id
    ? [{ id: row.looks_like_client_id, name: row.looks_like_client_name || '?' }]
    : [];
  // Green marks the answer, and only where there IS one. Two candidates means
  // the detector abstained, so neither gets to look like the recommendation.
  const actionCls = !isTie
    ? ACTIONS.recommend
    : targets.length === 1
    ? ACTIONS.suggest
    : ACTIONS.choice;

  const byHand = row.set_by === 'user';
  // Sub-2-minute blocks are real but rarely worth a manager's attention; they
  // stay visible and stay dimmed rather than being hidden.
  const trivial = row.minutes < 2;

  return (
    <div
      className={cn(
        'relative flex gap-3 pl-4 pr-4 py-3 border-t border-border/40 transition-colors',
        selected ? 'bg-primary/[0.04]' : 'hover:bg-slate-50/70'
      )}
    >
      <span className={cn('absolute left-0 top-0 bottom-0 w-[3px]', t.rail)} aria-hidden />

      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        disabled={locked}
        className="mt-1 accent-primary cursor-pointer disabled:cursor-not-allowed shrink-0 opacity-40 hover:opacity-100 checked:opacity-100"
        aria-label={`Select block ${row.block_id}`}
      />

      <div className="min-w-0 flex-1">
        {/* Who, when, how much — the materiality line, kept quiet */}
        <div className="flex items-baseline gap-2 flex-wrap text-xs">
          <span className="font-semibold text-slate-600">{row.user || 'Unknown'}</span>
          <span className="text-slate-400">{formatDate(row.date)}</span>
          <span className={cn('font-bold tabular-nums', trivial ? 'text-slate-300' : 'text-slate-500')}>
            {formatMinutes(row.minutes)}
          </span>
          {locked && (
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
              week {week?.status}
            </span>
          )}
        </div>

        {/* The evidence — the reason this row exists, so it leads */}
        <p
          className="mt-0.5 text-sm text-slate-800 font-medium leading-snug line-clamp-2"
          title={row.window_title}
        >
          {row.window_title}
          {row.app_name && (
            <span className="text-slate-400 font-normal"> · {cleanApp(row.app_name)}</span>
          )}
        </p>

        {/* The decision: where it is now → where it could go */}
        {!locked && (
          <div className="flex items-center gap-x-2 gap-y-1.5 flex-wrap mt-2">
            <span className="text-xs text-slate-500 truncate max-w-[220px]" title={row.booked_client_name}>
              {row.booked_client_name}
            </span>
            {byHand && (
              <span
                className="text-[10px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-px"
                title="A person put this block on this client by hand — likely deliberate, not a classifier error"
              >
                by hand
              </span>
            )}
            <span className="text-slate-300" aria-hidden>→</span>

            {targets.map((tg) => (
              <button
                key={tg.id}
                disabled={busy}
                onClick={() => onMove([row.block_id], tg.id, tg.name)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-semibold disabled:opacity-50 transition-colors max-w-[280px] truncate',
                  actionCls
                )}
                title={`Move this block to ${tg.name}`}
              >
                {tg.name}
              </button>
            ))}

            <span className="w-px h-4 bg-border/70" aria-hidden />

            <button
              disabled={busy}
              onClick={() => onCorrect([row.block_id])}
              className="px-2 py-1 rounded-md text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 disabled:opacity-50 transition-colors"
              title={`Leave it on ${row.booked_client_name} and stop flagging it`}
            >
              Keep
            </button>

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
                className="px-2 py-1 rounded-md text-xs font-medium text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
                title="Move it to a client that isn't offered here"
              >
                Other…
              </button>
            )}
          </div>
        )}

        {locked && (
          <p className="mt-2 text-xs text-slate-400">
            On {row.booked_client_name} — this week is {week?.status}, reopen it to make changes.
          </p>
        )}
      </div>
    </div>
  );
};

// ── One verdict section ───────────────────────────────────────────────────────

const Section: React.FC<{
  title: string;
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
}> = ({ title, tone, bucket, weeks, clients, selected, toggle, onMove, onCorrect, busy, defaultOpen }) => {
  const [open, setOpen] = useState(defaultOpen);
  const t = TONES[tone];
  if (!bucket.total) return null;

  return (
    <div className="border-t border-border/60">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-2 flex items-center gap-2.5 hover:bg-slate-50/70 transition-colors text-left"
      >
        {open
          ? <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          : <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
        <span
          className={cn(
            'inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full text-[11px] font-bold shrink-0',
            t.count
          )}
        >
          {bucket.total}
        </span>
        <span className="text-xs font-bold text-slate-700 uppercase tracking-wide">{title}</span>
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
            <p className="px-4 py-2 text-xs text-slate-400 border-t border-border/40">
              Showing {bucket.returned} of {bucket.total}.
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
  // "Keep" is one click on a dense list and it WILL get mis-clicked, so the way
  // back is right there rather than a database edit.
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
      setUndo({ blockIds, label: `${blockIds.length} kept as filed` });
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
            className="flex items-center gap-3 text-left min-w-0"
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
                  ? 'Scanning…'
                  : data
                  ? `${data.scanned_blocks.toLocaleString()} confirmed blocks checked`
                  : '—'}
              </p>
            </div>
          </button>

          <div className="flex items-center gap-2 shrink-0">
            {!loading && data && (
              flagged === 0 ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-emerald-50 text-emerald-700 border-emerald-200">
                  <CheckCircle2 className="w-3.5 h-3.5" /> All filed correctly
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
                  className="px-3 py-1.5 rounded-md text-xs font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-100 disabled:opacity-40"
                >
                  Keep
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
              title="Wrong client"
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
              title="Internal & admin"
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
          </div>
        )}
      </div>

      {/* Undo / error strips — outside the card so they read as transient */}
      {undo && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border bg-emerald-50 border-emerald-200 text-sm">
          <span className="text-emerald-700 font-medium">{undo.label} — won&rsquo;t be flagged again.</span>
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
