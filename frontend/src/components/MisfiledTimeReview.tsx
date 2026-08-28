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
// 5. A CLICK NEVER COSTS A RELOAD. Resolving a row used to re-run the whole
//    server sweep — thousands of blocks — behind a spinner, and a global `busy`
//    flag disabled every other button until it came back. Reviewing is a
//    rhythm: look, decide, click, next. So a resolved row is hidden instantly,
//    the request goes out in the background, requests never serialise, and the
//    payload is reconciled quietly once the clicking stops. Same fix as Daily
//    Review's Needs-you lane, for the same reason.
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
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
  /** Present on unconfirmed rows: the fix the classifier has already staged. */
  proposed_client_id?: number;
  proposed_client_name?: string;
  proposed_confidence?: number;
  confirmed?: boolean;
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
  /** Flagged rows nobody has confirmed yet, plus the size of that whole pile.
   *  Optional: frontend and backend deploy separately, so a new bundle can
   *  briefly talk to an API that predates this bucket. */
  unconfirmed?: Bucket & { blocks: number; minutes: number };
  clients: { id: number; name: string }[];
}

type Tone = 'red' | 'amber' | 'slate';

/** A block and the client it currently sits on — enough to reverse a move. */
interface Ref { id: number; clientId: number }

/** One resolved row, with everything needed to put it back. */
interface Done {
  ids: number[];
  label: string;
  /** The client each block sat on before, so a move can be reversed exactly. */
  from: Ref[];
  kind: 'move' | 'keep';
}

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
  onMove: (rows: Ref[], clientId: number, clientName: string) => void;
  onCorrect: (rows: Ref[]) => void;
}> = ({ row, tone, week, clients, selected, onToggle, onMove, onCorrect }) => {
  const [picking, setPicking] = useState(false);
  const [pick, setPick] = useState<number | ''>('');
  const t = TONES[tone];
  const locked = week ? !week.editable : false;

  // One render path for both buckets. A wrong-client row carries a single named
  // target; a tie carries ranked candidates. Either way they are the choices,
  // so they are the buttons.
  const isTie = row.verdict === 'booked_absent';
  const detected = isTie
    ? (row.candidates || []).map((c) => ({ id: c.client_id, name: c.client_name }))
    : row.looks_like_client_id
    ? [{ id: row.looks_like_client_id, name: row.looks_like_client_name || '?' }]
    : [];
  // On an unconfirmed row the classifier has usually ALREADY staged the fix.
  // That proposal leads, because making a reviewer re-derive an answer the
  // system already worked out is the nagging this panel exists to avoid.
  const proposed = row.proposed_client_id && row.proposed_client_name
    ? [{ id: row.proposed_client_id, name: row.proposed_client_name }]
    : [];
  const targets = [
    ...proposed,
    ...detected.filter((d) => !proposed.some((p) => p.id === d.id)),
  ];

  // Green marks the answer, and only where there IS one. Two candidates means
  // the detector abstained, so neither gets to look like the recommendation.
  const styleFor = (i: number) => {
    if (proposed.length) return i === 0 ? ACTIONS.recommend : ACTIONS.choice;
    if (!isTie) return ACTIONS.recommend;
    return targets.length === 1 ? ACTIONS.suggest : ACTIONS.choice;
  };

  // What this row needs to be undone: itself, and where it currently sits.
  const self: Ref[] = [{ id: row.block_id, clientId: row.booked_client_id }];

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
          {row.confirmed === false && (
            <span
              className="text-[10px] font-semibold text-slate-500 bg-slate-100 border border-slate-200 rounded px-1.5 py-px"
              title="Nobody has accepted this block yet — it is still sitting in this person's Daily Review"
            >
              not confirmed
            </span>
          )}
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

            {targets.map((tg, i) => (
              <button
                key={tg.id}
                onClick={() => onMove(self, tg.id, tg.name)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-semibold transition-colors max-w-[280px] truncate',
                  styleFor(i)
                )}
                title={`Move this block to ${tg.name}`}
              >
                {tg.name}
              </button>
            ))}

            <span className="w-px h-4 bg-border/70" aria-hidden />

            <button
              onClick={() => onCorrect(self)}
              className="px-2 py-1 rounded-md text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
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
                  disabled={!pick}
                  onClick={() => {
                    const c = clients.find((x) => x.id === pick);
                    if (!c) return;
                    onMove(self, c.id, c.name);
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
  note?: string;
  tone: Tone;
  bucket: Bucket;
  weeks: Map<number, Week>;
  clients: { id: number; name: string }[];
  selected: Set<number>;
  toggle: (id: number) => void;
  hidden: Set<number>;
  onMove: (rows: Ref[], clientId: number, clientName: string) => void;
  onCorrect: (rows: Ref[]) => void;
  defaultOpen: boolean;
}> = ({ title, note, tone, bucket, weeks, clients, selected, toggle, hidden, onMove, onCorrect, defaultOpen }) => {
  const [open, setOpen] = useState(defaultOpen);
  const t = TONES[tone];
  // Resolved rows leave immediately; the count follows them out rather than
  // waiting for the server, so the section can empty itself as you work.
  const rows = bucket.mismatches.filter((r) => !hidden.has(r.block_id));
  const total = bucket.total - (bucket.mismatches.length - rows.length);
  if (total <= 0) return null;

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
          {total}
        </span>
        <span className="text-xs font-bold text-slate-700 uppercase tracking-wide">{title}</span>
        {note && <span className="text-xs text-slate-400 truncate hidden sm:inline">{note}</span>}
      </button>

      {open && (
        <div>
          {rows.map((row) => (
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
            />
          ))}
          {rows.length < total && (
            <p className="px-4 py-2 text-xs text-slate-400 border-t border-border/40">
              Showing {rows.length} of {total}.
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
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkClient, setBulkClient] = useState<number | ''>('');
  const [open, setOpen] = useState(false);
  // Rows the reviewer has dealt with, hidden the moment they click. The server
  // is still catching up; the screen is not made to wait for it.
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  // What has been done, newest first — the count people watch tick up, and the
  // way back from a mis-click. Optimistic hiding makes a wrong click cheaper to
  // make and quieter to notice, so undo stops being a nicety here.
  const [log, setLog] = useState<Done[]>([]);

  // A ref, not state: the reconcile has to read the CURRENT number of in-flight
  // requests, and a closure would capture a stale one and un-hide live rows.
  const inflight = useRef(0);
  const reconcileTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const d = await safeFetchJson<MisfiledResponse>(`${API_BASE}/review/misfiled/?scope=open`);
      setData(d);
      // Anything successfully resolved is simply absent from the fresh payload,
      // and anything still in it was never applied — so a clean reload makes
      // the optimistic set redundant either way.
      setHidden(new Set());
      if (!silent) {
        setSelected(new Set());
        setLog([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not run the check');
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  // Quietly re-sync once the clicking stops. Deliberately never while a request
  // is still out: reconciling mid-flight would flash a resolved row back.
  const scheduleReconcile = useCallback(() => {
    if (reconcileTimer.current) clearTimeout(reconcileTimer.current);
    reconcileTimer.current = setTimeout(() => {
      if (inflight.current === 0) load(true);
    }, 2500);
  }, [load]);

  useEffect(() => () => {
    if (reconcileTimer.current) clearTimeout(reconcileTimer.current);
  }, []);

  const weeks = useMemo(
    () => new Map((data?.weeks || []).map((w) => [w.timesheet_id, w])),
    [data]
  );

  // Bulk actions only carry block ids, but undoing a move needs the client
  // each block came from — so look them up before firing.
  const refsFor = useCallback(
    (ids: number[]): Ref[] => {
      const byId = new Map<number, number>();
      for (const b of [data?.client, data?.unsure, data?.internal]) {
        for (const r of b?.mismatches || []) byId.set(r.block_id, r.booked_client_id);
      }
      return ids.map((id) => ({ id, clientId: byId.get(id) ?? 0 }));
    },
    [data]
  );

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  // Fires and returns; callers do NOT await before updating the screen. No
  // global busy flag either — one row's request must never disable another's
  // button, which is what stopped people clicking straight down the list.
  const send = useCallback(async (body: Record<string, unknown>) => {
    inflight.current += 1;
    try {
      return await safeFetchJson<any>(`${API_BASE}/review/misfiled/resolve/`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    } finally {
      inflight.current -= 1;
    }
  }, []);

  /** Put rows back on screen when the server would not take the change. */
  const unhide = useCallback((ids: number[], why: string) => {
    if (!ids.length) {
      setError(why);
      return;
    }
    const back = new Set(ids);
    setHidden((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
    // Subtract only the refused rows. A bulk move where three landed and one
    // was refused must keep undo for the three that actually moved.
    setLog((prev) =>
      prev
        .map((d) => ({
          ...d,
          ids: d.ids.filter((id) => !back.has(id)),
          from: d.from.filter((f) => !back.has(f.id)),
        }))
        .filter((d) => d.ids.length > 0)
    );
    setError(why);
  }, []);

  const hide = useCallback((ids: number[]) => {
    setHidden((prev) => new Set([...prev, ...ids]));
    setSelected((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }, []);

  const onMove = useCallback(
    (rows: { id: number; clientId: number }[], clientId: number, clientName: string) => {
      const ids = rows.map((r) => r.id);
      hide(ids);
      setLog((prev) => [{ ids, label: `Moved to ${clientName}`, from: rows, kind: 'move' }, ...prev]);

      send({ block_ids: ids, action: 'move', client_id: clientId })
        .then((r) => {
          // The server refuses invoiced time and approved weeks. Showing those
          // as moved would be a lie the reviewer only discovers at billing, so
          // the rows come back with the reason attached.
          if (r?.skipped) {
            const reasons = (r.skips || [])
              .map((x: any) => x.reason)
              .filter((v: string, i: number, a: string[]) => a.indexOf(v) === i)
              .join('; ');
            const refused = (r.skips || []).map((x: any) => x.block_id);
            unhide(refused, `${r.skipped} left alone — ${reasons}.`);
          }
          scheduleReconcile();
        })
        .catch((err) => unhide(ids, err instanceof Error ? err.message : 'Move failed'));
    },
    [hide, send, unhide, scheduleReconcile]
  );

  const onCorrect = useCallback(
    (rows: { id: number; clientId: number }[]) => {
      const ids = rows.map((r) => r.id);
      hide(ids);
      setLog((prev) => [
        { ids, label: `Kept as filed`, from: rows, kind: 'keep' },
        ...prev,
      ]);
      send({ block_ids: ids, action: 'correct' })
        .then(() => scheduleReconcile())
        .catch((err) => unhide(ids, err instanceof Error ? err.message : 'Could not clear that'));
    },
    [hide, send, unhide, scheduleReconcile]
  );

  /** Reverse the most recent action and drop it from the log. */
  const undoLast = useCallback(() => {
    const last = log[0];
    if (!last) return;
    setLog((prev) => prev.slice(1));
    setHidden((prev) => {
      const next = new Set(prev);
      last.ids.forEach((id) => next.delete(id));
      return next;
    });

    if (last.kind === 'keep') {
      send({ block_ids: last.ids, action: 'reopen' }).then(() => scheduleReconcile());
      return;
    }
    // A move is undone by moving each block back to the client it came from.
    // Grouped by destination, because the endpoint takes one client per call.
    // A zero clientId means the origin was never resolved, and sending it would
    // just 404 — so those are skipped rather than guessed at.
    const byClient = new Map<number, number[]>();
    last.from.forEach((f) => {
      if (!f.clientId) return;
      byClient.set(f.clientId, [...(byClient.get(f.clientId) || []), f.id]);
    });
    Promise.all(
      [...byClient.entries()].map(([cid, ids]) =>
        send({ block_ids: ids, action: 'move', client_id: cid })
      )
    ).then(() => scheduleReconcile());
  }, [log, send, scheduleReconcile]);

  // Counts follow the optimistic hides, so header badges, section counts and
  // the queue-row badges all drain together as rows are resolved.
  const visible = useCallback(
    (b: Bucket | undefined) =>
      b ? b.total - b.mismatches.filter((r) => hidden.has(r.block_id)).length : 0,
    [hidden]
  );

  // One place computes what the parent badges show, so they can never disagree
  // with what is on screen.
  useEffect(() => {
    if (!data) return;
    const counts: Record<string, { count: number; minutes: number }> = {};
    for (const row of data.client.mismatches) {
      if (hidden.has(row.block_id) || row.timesheet_id == null) continue;
      const k = String(row.timesheet_id);
      const c = counts[k] || (counts[k] = { count: 0, minutes: 0 });
      c.count += 1;
      c.minutes += row.minutes || 0;
    }
    onCounts?.(counts);
  }, [data, hidden, onCounts]);

  const clientTotal = visible(data?.client);
  const unsureTotal = visible(data?.unsure);
  // Counted for whether the panel has anything to show, but badged separately:
  // unconfirmed time is not what is being approved, so it must never inflate
  // the "wrong client" number a reviewer acts on.
  const unconfTotal = visible(data?.unconfirmed);
  const flagged = clientTotal + unsureTotal + unconfTotal;

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
                  {unconfTotal > 0 && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-slate-50 text-slate-600 border-slate-200">
                      {unconfTotal} unconfirmed
                    </span>
                  )}
                </>
              )
            )}
            <button
              onClick={() => load()}
              disabled={loading}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-40"
              title="Re-run the check"
            >
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
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
                  disabled={!bulkClient}
                  onClick={() => {
                    const c = data.clients.find((x) => x.id === bulkClient);
                    if (!c) return;
                    onMove(refsFor([...selected]), c.id, c.name);
                    setBulkClient('');
                  }}
                  className="px-3 py-1.5 rounded-md text-xs font-semibold bg-primary text-white hover:opacity-90 disabled:opacity-40"
                >
                  Move
                </button>
                <button
                  onClick={() => onCorrect(refsFor([...selected]))}
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
              hidden={hidden}
              onMove={onMove}
              onCorrect={onCorrect}
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
              hidden={hidden}
              onMove={onMove}
              onCorrect={onCorrect}
              defaultOpen={data.client.total === 0}
            />
            {data.unconfirmed && (
            <Section
              title="Not confirmed yet"
              note="nobody has accepted these — the system already suggests a fix"
              tone="slate"
              bucket={data.unconfirmed}
              weeks={weeks}
              clients={data.clients}
              selected={selected}
              toggle={toggle}
              hidden={hidden}
              onMove={onMove}
              onCorrect={onCorrect}
              defaultOpen={clientTotal === 0}
            />
            )}
            <Section
              title="Internal & admin"
              tone="slate"
              bucket={data.internal}
              weeks={weeks}
              clients={data.clients}
              selected={selected}
              toggle={toggle}
              hidden={hidden}
              onMove={onMove}
              onCorrect={onCorrect}
              defaultOpen={false}
            />
            {!!data.unconfirmed?.blocks && (
              <p className="border-t border-border/40 px-4 py-2.5 text-[11px] text-slate-400">
                {data.unconfirmed.blocks.toLocaleString()} blocks
                {' '}({Math.round(data.unconfirmed.minutes / 60)}h) in these weeks are still
                unconfirmed. They stay in each person&rsquo;s Daily Review — only the ones whose
                title contradicts their client are listed above.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Undo / error strips — outside the card so they read as transient */}
      {log.length > 0 && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border bg-emerald-50 border-emerald-200 text-sm">
          <span className="text-emerald-800 font-medium">
            {log.length} resolved
            <span className="text-emerald-700/70 font-normal"> · {log[0].label}</span>
          </span>
          <button
            onClick={undoLast}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-800 hover:underline shrink-0"
          >
            <Undo2 className="w-3.5 h-3.5" /> Undo last
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
