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

// ── Why it looks like a ledger ──────────────────────────────────────────────
// Earlier passes labelled every row ("now on X → suggested Y") and stacked four
// lines per finding. Read down a list, those labels are the same six words over
// and over — furniture, not information. A table says them ONCE, in the header,
// and every row below is only the values that differ: what was open, where it
// is filed, where it looks like it belongs.
//
// Rules carried over from those passes, because they still hold:
//   · GREEN IS THE ANSWER, RED IS THE PROBLEM. The move control is green — it
//     is the button you are meant to press, and nothing that fixes something
//     should be coloured like a hazard.
//   · A TIE NEVER LOOKS LIKE A RECOMMENDATION. Where the detector returned more
//     than one candidate they are listed as choices instead of one being
//     dressed up as the answer.
//   · A CLICK NEVER COSTS A RELOAD. Rows resolve optimistically, requests never
//     serialise, and the payload reconciles quietly once the clicking stops.

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, RefreshCw,
  ScanSearch, Undo2, Check, X,
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

/** A row flattened for the table, with what it needs to render and act. */
interface LedgerRow {
  row: Row;
  targets: { id: number; name: string }[];
  /** Exactly one target, and the machine is confident about it. */
  confident: boolean;
  /** Nobody has accepted this block yet. */
  pending: boolean;
  week: Week | undefined;
}

// ── Title cleanup ─────────────────────────────────────────────────────────────
//
// A raw window title is mostly chrome: a date the filename already carries, an
// extension, and the application advertising itself. None of it helps a person
// recognise the work, and all of it makes the column unreadable at a glance.
// The untouched title stays on hover, so nothing is actually hidden.
//
//   "8-30-2026 St. John's Cemetery bills etc_.pdf - Work - Microsoft Edge"
//     -> "St. John's Cemetery bills"
//   "champions fitness_CAMEZA - File Explorer"  ->  "champions fitness_CAMEZA"
const APP_TAIL = new RegExp(
  '^(' + [
    'file explorer', 'explorer', 'microsoft\\s*edge', 'google chrome', 'chrome',
    'firefox', 'safari', 'outlook', 'excel', 'word', 'powerpoint', 'onenote',
    'microsoft teams', 'teams', 'adobe acrobat.*', 'acrobat.*', 'work', 'personal',
    'quickbooks.*', 'ultratax.*', 'notepad',
  ].join('|') + ')$', 'i'
);

const cleanTitle = (title: string, app: string): string => {
  const raw = (title || '').trim();
  if (!raw) return '';
  const parts = raw.split(/\s+[-–—]\s+/).map((p) => p.trim()).filter(Boolean);
  const appName = (app || '').replace(/\.exe$/i, '').trim().toLowerCase();
  while (parts.length > 1) {
    const last = parts[parts.length - 1].toLowerCase();
    if (APP_TAIL.test(last) || (appName && last === appName)) parts.pop();
    else break;
  }
  let out = parts.join(' - ');
  out = out.replace(/^\d{1,4}[-._/]\d{1,2}[-._/]\d{2,4}\s+/, '');   // leading date
  out = out.replace(/\.(pdf|xlsx?|docx?|pptx?|csv|qbw|txt|msg|eml)$/i, '');
  out = out.replace(/[\s_\-.]+$/, '');
  out = out.replace(/\s+etc$/i, '');
  // Never hand back something shorter than useless.
  return out.trim().length >= 3 ? out.trim() : raw;
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

// ── One ledger line ───────────────────────────────────────────────────────────

const LedgerLine: React.FC<{
  item: LedgerRow;
  clients: { id: number; name: string }[];
  onMove: (rows: Ref[], clientId: number, clientName: string) => void;
  onCorrect: (rows: Ref[]) => void;
}> = ({ item, clients, onMove, onCorrect }) => {
  const { row, targets, confident, pending, week } = item;
  const [picking, setPicking] = useState(false);
  const locked = week ? !week.editable : false;
  const self: Ref[] = [{ id: row.block_id, clientId: row.booked_client_id }];
  const one = targets.length === 1 ? targets[0] : null;

  return (
    <tr className="border-b border-border/40 last:border-b-0 hover:bg-slate-50/70 transition-colors">
      {/* What was open */}
      <td className="px-4 py-3 max-w-0 w-[42%]">
        <p className="text-sm font-semibold text-slate-800 truncate" title={row.window_title}>
          {cleanTitle(row.window_title, row.app_name)}
        </p>
        <p className="text-xs text-slate-400 truncate mt-0.5">
          {row.user} · {formatDate(row.date)} · {formatMinutes(row.minutes)}
          {pending && ' · not accepted yet'}
          {row.set_by === 'user' && (
            <span className="text-amber-600"
              title="A person put this block on this client by hand — likely deliberate">
              {' '}· set by hand
            </span>
          )}
        </p>
      </td>

      {/* Filed under */}
      <td className="px-3 py-3 max-w-0 w-[20%]">
        <span className="block text-sm text-slate-500 truncate" title={row.booked_client_name}>
          {row.booked_client_name}
        </span>
      </td>

      <td className="w-5 text-center text-slate-300" aria-hidden>→</td>

      {/* Looks like */}
      <td className="px-3 py-3 max-w-0 w-[22%]">
        {one ? (
          <span className="block text-sm font-bold text-emerald-700 truncate" title={one.name}>
            {one.name}
          </span>
        ) : (
          /* A tie: list them rather than pick one. Clicking a name files it there. */
          <span className="flex flex-col items-start gap-0.5">
            {targets.map((t) => (
              <button
                key={t.id}
                disabled={locked}
                onClick={() => onMove(self, t.id, t.name)}
                title={`File this under ${t.name}`}
                className="max-w-full text-left text-sm font-semibold text-slate-700 hover:text-emerald-700 hover:underline truncate disabled:text-slate-400 disabled:no-underline"
              >
                {t.name}
              </button>
            ))}
          </span>
        )}
      </td>

      {/* Move? */}
      <td className="px-4 py-3 text-right whitespace-nowrap">
        {locked ? (
          <span className="text-[11px] text-slate-400">week {week?.status}</span>
        ) : picking ? (
          <span className="inline-flex items-center gap-1.5">
            <select
              autoFocus
              defaultValue=""
              onChange={(e) => {
                const c = clients.find((x) => x.id === Number(e.target.value));
                if (c) { onMove(self, c.id, c.name); setPicking(false); }
              }}
              className="text-xs border border-border/60 rounded-md px-2 py-1 max-w-[190px] bg-white"
            >
              <option value="" disabled>choose a client…</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button onClick={() => setPicking(false)}
              className="text-xs text-slate-400 hover:text-slate-600">cancel</button>
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            {one && (
              <button
                onClick={() => onMove(self, one.id, one.name)}
                title={`Move to ${one.name}`}
                className={cn(
                  'w-8 h-8 rounded-lg inline-flex items-center justify-center border transition-colors',
                  confident
                    ? 'bg-emerald-600 border-emerald-600 text-white hover:bg-emerald-700'
                    : 'bg-white border-emerald-300 text-emerald-700 hover:bg-emerald-50'
                )}
              >
                <Check className="w-4 h-4" strokeWidth={3} />
              </button>
            )}
            <button
              onClick={() => onCorrect(self)}
              title={`Leave it on ${row.booked_client_name} and stop flagging it`}
              className="w-8 h-8 rounded-lg inline-flex items-center justify-center border border-slate-200 bg-white text-slate-400 hover:text-slate-700 hover:border-slate-300 transition-colors"
            >
              <X className="w-4 h-4" strokeWidth={3} />
            </button>
            <button
              onClick={() => setPicking(true)}
              title="File it under a different client"
              className="w-8 h-8 rounded-lg inline-flex items-center justify-center text-slate-300 hover:text-slate-600 hover:bg-slate-100 transition-colors text-lg leading-none"
            >
              ⋯
            </button>
          </span>
        )}
      </td>
    </tr>
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
  const [open, setOpen] = useState(false);
  const [showInternal, setShowInternal] = useState(false);
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  const [log, setLog] = useState<Done[]>([]);

  const inflight = useRef(0);
  const reconcileTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const d = await safeFetchJson<MisfiledResponse>(`${API_BASE}/review/misfiled/?scope=queue`);
      setData(d);
      // Anything applied is absent from the fresh payload, and anything still in
      // it was never applied — so a clean reload makes the optimistic set moot.
      setHidden(new Set());
      if (!silent) setLog([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not run the check');
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  // Quietly re-sync once the clicking stops, and never while a request is still
  // out — reconciling mid-flight would flash a resolved row back onto the page.
  const scheduleReconcile = useCallback(() => {
    if (reconcileTimer.current) clearTimeout(reconcileTimer.current);
    reconcileTimer.current = setTimeout(() => {
      if (inflight.current === 0) load(true);
    }, 2500);
  }, [load]);

  useEffect(() => () => {
    if (reconcileTimer.current) clearTimeout(reconcileTimer.current);
  }, []);

  // Fires and returns; callers do NOT await before updating the screen, and
  // there is no global busy flag — one row's request must never disable
  // another's button, which is what stopped people clicking down the list.
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
    if (!ids.length) { setError(why); return; }
    const back = new Set(ids);
    setHidden((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
    // Subtract only the refused rows, so a bulk action that partly landed keeps
    // undo for the part that did.
    setLog((prev) => prev
      .map((d) => ({
        ...d,
        ids: d.ids.filter((id) => !back.has(id)),
        from: d.from.filter((f) => !back.has(f.id)),
      }))
      .filter((d) => d.ids.length > 0));
    setError(why);
  }, []);

  const hide = useCallback((ids: number[]) => {
    setHidden((prev) => new Set([...prev, ...ids]));
  }, []);

  const onMove = useCallback((rows: Ref[], clientId: number, clientName: string) => {
    const ids = rows.map((r) => r.id);
    hide(ids);
    setLog((prev) => [{ ids, label: `Moved to ${clientName}`, from: rows, kind: 'move' }, ...prev]);
    send({ block_ids: ids, action: 'move', client_id: clientId })
      .then((r) => {
        // The server refuses invoiced time and approved weeks. Showing those as
        // moved would be a lie the reviewer only discovers at billing.
        if (r?.skipped) {
          const reasons = (r.skips || []).map((x: any) => x.reason)
            .filter((v: string, i: number, a: string[]) => a.indexOf(v) === i).join('; ');
          unhide((r.skips || []).map((x: any) => x.block_id),
                 `${r.skipped} left alone — ${reasons}.`);
        }
        scheduleReconcile();
      })
      .catch((err) => unhide(ids, err instanceof Error ? err.message : 'Move failed'));
  }, [hide, send, unhide, scheduleReconcile]);

  const onCorrect = useCallback((rows: Ref[]) => {
    const ids = rows.map((r) => r.id);
    hide(ids);
    setLog((prev) => [{ ids, label: 'Left as filed', from: rows, kind: 'keep' }, ...prev]);
    send({ block_ids: ids, action: 'correct' })
      .then(() => scheduleReconcile())
      .catch((err) => unhide(ids, err instanceof Error ? err.message : 'Could not clear that'));
  }, [hide, send, unhide, scheduleReconcile]);

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
    // Each block goes back to the client it came from, grouped by destination
    // because the endpoint takes one client per call. A zero id means the origin
    // was never resolved, and sending it would only 404.
    const byClient = new Map<number, number[]>();
    last.from.forEach((f) => {
      if (!f.clientId) return;
      byClient.set(f.clientId, [...(byClient.get(f.clientId) || []), f.id]);
    });
    Promise.all([...byClient.entries()].map(([cid, ids]) =>
      send({ block_ids: ids, action: 'move', client_id: cid })
    )).then(() => scheduleReconcile());
  }, [log, send, scheduleReconcile]);

  const weekMap = useMemo(
    () => new Map((data?.weeks || []).map((w) => [w.timesheet_id, w])),
    [data]
  );

  const build = useCallback((r: Row, pending: boolean): LedgerRow => {
    const detected = r.verdict === 'booked_absent'
      ? (r.candidates || []).map((c) => ({ id: c.client_id, name: c.client_name }))
      : r.looks_like_client_id
      ? [{ id: r.looks_like_client_id, name: r.looks_like_client_name || '?' }]
      : [];
    // On a pending row the classifier has usually already staged the fix, and
    // that proposal is the answer — no point making a reviewer re-derive it.
    const proposed = r.proposed_client_id && r.proposed_client_name
      ? [{ id: r.proposed_client_id, name: r.proposed_client_name }]
      : [];
    const targets = [...proposed, ...detected.filter((d) => !proposed.some((p) => p.id === d.id))];
    return {
      row: r,
      targets,
      confident: targets.length === 1 && (proposed.length > 0 || r.verdict !== 'booked_absent'),
      pending,
      week: r.timesheet_id != null ? weekMap.get(r.timesheet_id) : undefined,
    };
  }, [weekMap]);

  // One flat list. The three verdicts still exist underneath — they decide the
  // order and how confident the control looks — they just stop being furniture.
  const rows = useMemo<LedgerRow[]>(() => {
    if (!data) return [];
    return [
      ...data.client.mismatches.map((r) => build(r, false)),
      ...data.unsure.mismatches.map((r) => build(r, false)),
      ...(data.unconfirmed?.mismatches || []).map((r) => build(r, true)),
    ].filter((i) => !hidden.has(i.row.block_id) && i.targets.length > 0);
  }, [data, hidden, build]);

  const internalRows = useMemo<LedgerRow[]>(() => {
    if (!data) return [];
    return data.internal.mismatches
      .map((r) => build(r, false))
      .filter((i) => !hidden.has(i.row.block_id) && i.targets.length > 0);
  }, [data, hidden, build]);

  // Parent badges read the same optimistic set, so they can never disagree with
  // what is on screen.
  useEffect(() => {
    if (!data) return;
    const counts: Record<string, { count: number; minutes: number }> = {};
    for (const r of data.client.mismatches) {
      if (hidden.has(r.block_id) || r.timesheet_id == null) continue;
      const k = String(r.timesheet_id);
      const c = counts[k] || (counts[k] = { count: 0, minutes: 0 });
      c.count += 1;
      c.minutes += r.minutes || 0;
    }
    onCounts?.(counts);
  }, [data, hidden, onCounts]);

  const total = rows.length;
  const wrongClient = rows.filter((i) => !i.pending && i.confident).length;

  const HEAD = (
    <thead className="sticky top-0 z-10">
      <tr className="bg-slate-50 border-b border-border/60">
        <th className="text-left px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">What was open</th>
        <th className="text-left px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">Filed under</th>
        <th />
        <th className="text-left px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">Looks like</th>
        <th className="text-right px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">Move?</th>
      </tr>
    </thead>
  );

  return (
    <div className="shrink-0 space-y-2">
      <div className={cn(
        'bg-white rounded-xl border overflow-hidden',
        wrongClient > 0 ? 'border-red-200' : 'border-border/60'
      )}>
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="px-5 py-3 flex items-center justify-between gap-4">
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-3 text-left min-w-0"
            disabled={total === 0 && !loading}
          >
            {total > 0 && (open
              ? <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
              : <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />)}
            <ScanSearch className="w-4 h-4 shrink-0 text-primary" />
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-800">Check for misfiled time</p>
              <p className="text-xs text-slate-400 truncate">
                {loading ? 'Scanning…'
                  : data ? `${data.scanned_blocks.toLocaleString()} confirmed blocks checked` : '—'}
              </p>
            </div>
          </button>

          <div className="flex items-center gap-2 shrink-0">
            {!loading && data && (total === 0 ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-emerald-50 text-emerald-700 border-emerald-200">
                <CheckCircle2 className="w-3.5 h-3.5" /> All filed correctly
              </span>
            ) : (
              <span className={cn(
                'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border',
                wrongClient > 0
                  ? 'bg-red-50 text-red-700 border-red-200'
                  : 'bg-amber-50 text-amber-800 border-amber-200'
              )}>
                {wrongClient > 0 && <AlertTriangle className="w-3.5 h-3.5" />}
                {total} to review
              </span>
            ))}
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

        {/* ── The ledger ─────────────────────────────────────────────────── */}
        {open && data && !loading && total > 0 && (
          <div className="border-t border-border/60 max-h-[52vh] overflow-auto">
            <table className="w-full table-fixed border-collapse" style={{ minWidth: 720 }}>
              {HEAD}
              <tbody>
                {rows.map((item) => (
                  <LedgerLine key={item.row.block_id} item={item} clients={data.clients}
                    onMove={onMove} onCorrect={onCorrect} />
                ))}
              </tbody>
            </table>

            {/* Firm/admin buckets: real, never a client billing error, so they
                stay out of the count and behind a click. */}
            {internalRows.length > 0 && (
              <>
                <button
                  onClick={() => setShowInternal((v) => !v)}
                  className="w-full px-4 py-2 flex items-center gap-2 text-left border-t border-border/60 hover:bg-slate-50/70 transition-colors"
                >
                  {showInternal
                    ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
                    : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
                  <span className="text-xs text-slate-500">
                    {internalRows.length} internal &amp; admin — real, but not a client billing error
                  </span>
                </button>
                {showInternal && (
                  <table className="w-full table-fixed border-collapse" style={{ minWidth: 720 }}>
                    <tbody>
                      {internalRows.map((item) => (
                        <LedgerLine key={item.row.block_id} item={item} clients={data.clients}
                          onMove={onMove} onCorrect={onCorrect} />
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}

            {!!data.unconfirmed?.blocks && (
              <p className="border-t border-border/40 px-4 py-2.5 text-[11px] text-slate-400">
                {data.unconfirmed.blocks.toLocaleString()} blocks
                {' '}({Math.round(data.unconfirmed.minutes / 60)}h) in these weeks are still
                unaccepted. They stay in each person&rsquo;s Daily Review — only the ones whose
                title contradicts their client are listed here.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Transient strips, outside the card */}
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
