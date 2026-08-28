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
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, RefreshCw,
  ScanSearch, Undo2, HelpCircle, Building2,
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

// ── Utilities ─────────────────────────────────────────────────────────────────

const formatMinutes = (m: number): string => {
  if (!m) return '—';
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (!h) return `${mm}m`;
  return mm ? `${h}h ${mm}m` : `${h}h`;
};

const formatDate = (iso: string): string =>
  new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

const formatWeek = (iso: string): string => {
  const start = new Date(iso + 'T00:00:00');
  const end = new Date(start.getTime() + 6 * 86400000);
  return `${start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
};

// ── Client badge ──────────────────────────────────────────────────────────────

const ClientChip: React.FC<{ name: string; tone: 'booked' | 'target' | 'muted' }> = ({ name, tone }) => (
  <span
    className={cn(
      'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold border max-w-[240px] truncate',
      tone === 'booked' && 'bg-slate-50 text-slate-600 border-slate-200',
      tone === 'target' && 'bg-red-50 text-red-700 border-red-200',
      tone === 'muted' && 'bg-amber-50 text-amber-700 border-amber-200'
    )}
    title={name}
  >
    {name}
  </span>
);

// ── One flagged block ─────────────────────────────────────────────────────────

const FlagRow: React.FC<{
  row: Row;
  week: Week | undefined;
  clients: { id: number; name: string }[];
  selected: boolean;
  onToggle: () => void;
  onMove: (blockIds: number[], clientId: number, clientName: string) => Promise<void>;
  onCorrect: (blockIds: number[]) => Promise<void>;
  busy: boolean;
}> = ({ row, week, clients, selected, onToggle, onMove, onCorrect, busy }) => {
  const [picking, setPicking] = useState(false);
  const [pick, setPick] = useState<number | ''>('');
  const locked = week ? !week.editable : false;

  return (
    <div
      className={cn(
        'px-4 py-3 border-b border-border/30 last:border-b-0 transition-colors',
        selected ? 'bg-primary/5' : 'hover:bg-slate-50/60'
      )}
    >
      {/* Line 1 — who / when / how long */}
      <div className="flex items-center gap-2.5 flex-wrap text-xs">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          disabled={locked}
          className="accent-primary cursor-pointer disabled:cursor-not-allowed"
        />
        <span className="font-semibold text-slate-700">{row.user || 'Unknown'}</span>
        <span className="text-slate-400">{formatDate(row.date)}</span>
        <span className="font-semibold tabular-nums text-slate-600">{formatMinutes(row.minutes)}</span>
        {/* A person deliberately allocating time reads identically to a
            classifier error in the numbers, so the row says which it was. */}
        {row.set_by === 'user' && (
          <span
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200"
            title="A person put this block on this client — likely deliberate, not a classifier error"
          >
            set by hand
          </span>
        )}
        {locked && (
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
            week {week?.status} — reopen to change
          </span>
        )}
      </div>

      {/* Line 2 — the disagreement */}
      <div className="flex items-center gap-2 flex-wrap mt-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">on</span>
        <ClientChip name={row.booked_client_name} tone="booked" />
        <span className="text-slate-300">→</span>
        {row.verdict === 'booked_absent' ? (
          <>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              not in title; could be
            </span>
            {(row.candidates || []).map((c, i) => (
              <span key={c.client_id} className="inline-flex items-center gap-1.5">
                {i > 0 && <span className="text-[10px] text-slate-400">or</span>}
                <ClientChip name={c.client_name} tone="muted" />
              </span>
            ))}
          </>
        ) : (
          <>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              title says
            </span>
            <ClientChip name={row.looks_like_client_name || '?'} tone="target" />
          </>
        )}
      </div>

      {/* Line 3 — the evidence, verbatim */}
      <p className="mt-2 text-xs text-slate-500 font-mono bg-slate-50 rounded-md px-2.5 py-1.5 break-all border border-border/40">
        {row.app_name && <span className="text-slate-400">{row.app_name} — </span>}
        {row.window_title}
      </p>

      {/* Line 4 — what to do about it */}
      {!locked && (
        <div className="flex items-center gap-2 flex-wrap mt-2.5">
          {row.looks_like_client_id && row.looks_like_client_name && (
            <button
              disabled={busy}
              onClick={() => onMove([row.block_id], row.looks_like_client_id!, row.looks_like_client_name!)}
              className="px-2.5 py-1 rounded-md text-xs font-semibold bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              Move to {row.looks_like_client_name}
            </button>
          )}
          {(row.candidates || []).map((c) => (
            <button
              key={c.client_id}
              disabled={busy}
              onClick={() => onMove([row.block_id], c.client_id, c.client_name)}
              className="px-2.5 py-1 rounded-md text-xs font-semibold bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
            >
              Move to {c.client_name}
            </button>
          ))}
          <button
            disabled={busy}
            onClick={() => onCorrect([row.block_id])}
            className="px-2.5 py-1 rounded-md text-xs font-semibold text-emerald-700 border border-emerald-200 bg-emerald-50 hover:bg-emerald-100 disabled:opacity-50 transition-colors"
          >
            It's right
          </button>
          {/* Escape hatch for the case neither the target nor the candidates
              cover — the row is wrong but the answer is a third client. */}
          {picking ? (
            <span className="inline-flex items-center gap-1.5">
              <select
                value={pick}
                onChange={(e) => setPick(e.target.value ? Number(e.target.value) : '')}
                className="text-xs border border-border/60 rounded-md px-2 py-1 max-w-[220px]"
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
              className="text-xs text-slate-400 hover:text-slate-600 underline underline-offset-2"
            >
              someone else…
            </button>
          )}
        </div>
      )}
    </div>
  );
};

// ── One verdict section ───────────────────────────────────────────────────────

const Section: React.FC<{
  title: string;
  blurb: string;
  tone: 'red' | 'amber' | 'slate';
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
  if (!bucket.total) return null;

  return (
    <div className="bg-white rounded-xl border border-border/60 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-3 flex items-center gap-2.5 hover:bg-slate-50/60 transition-colors text-left"
      >
        {open ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
        <span
          className={cn(
            'inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-full text-xs font-bold',
            tone === 'red' && 'bg-red-100 text-red-700',
            tone === 'amber' && 'bg-amber-100 text-amber-700',
            tone === 'slate' && 'bg-slate-100 text-slate-500'
          )}
        >
          {bucket.total}
        </span>
        <span className="text-sm font-bold text-slate-800">{title}</span>
        <span className="text-xs text-slate-400 hidden sm:inline">{blurb}</span>
      </button>

      {open && (
        <div className="border-t border-border/40">
          {bucket.mismatches.map((row) => (
            <FlagRow
              key={row.block_id}
              row={row}
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
            <p className="px-4 py-2.5 text-xs text-slate-400 border-t border-border/30">
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

  const flagged = (data?.client.total || 0) + (data?.unsure.total || 0);
  const clientTotal = data?.client.total || 0;

  // ── Collapsed header ────────────────────────────────────────────────────────
  return (
    <div className="shrink-0 space-y-2">
      <div
        className={cn(
          'bg-white rounded-xl border px-5 py-3 flex items-center justify-between gap-4',
          clientTotal > 0 ? 'border-red-200' : 'border-border/60'
        )}
      >
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-3 text-left min-w-0"
        >
          {open ? <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" /> : <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />}
          <ScanSearch className={cn('w-4 h-4 shrink-0', clientTotal > 0 ? 'text-red-500' : 'text-slate-400')} />
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-800">Check for misfiled time</p>
            <p className="text-xs text-slate-400 truncate">
              {loading
                ? 'Scanning committed time…'
                : data
                ? `${data.scanned_blocks.toLocaleString()} confirmed blocks across ${data.weeks.length} week${data.weeks.length === 1 ? '' : 's'}`
                : '—'}
            </p>
          </div>
        </button>

        <div className="flex items-center gap-3 shrink-0">
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
                {(data.unsure.total || 0) > 0 && (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-amber-50 text-amber-700 border-amber-200">
                    <HelpCircle className="w-3.5 h-3.5" /> {data.unsure.total} to check
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

      {/* Undo / error strips */}
      {undo && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border bg-emerald-50 border-emerald-200 text-sm">
          <span className="text-emerald-700 font-medium">{undo.label} — they won't be flagged again.</span>
          <button
            onClick={onUndo}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-800 hover:underline"
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

      {/* ── Expanded body ─────────────────────────────────────────────────── */}
      {open && data && !loading && (
        <div className="space-y-2 max-h-[52vh] overflow-auto pr-0.5">
          {flagged === 0 && (
            <div className="bg-white rounded-xl border border-border/60 px-5 py-8 text-center">
              <CheckCircle2 className="w-9 h-9 text-emerald-200 mx-auto mb-3" />
              <p className="text-sm font-semibold text-slate-600">
                Every confirmed block names the client it's booked to
              </p>
              <p className="text-xs text-slate-400 mt-1">
                Checked {data.scanned_blocks.toLocaleString()} blocks
                {data.dismissed_blocks > 0 && ` · ${data.dismissed_blocks} previously marked correct`}
              </p>
            </div>
          )}

          {/* Bulk bar — only worth showing once something is picked. */}
          {selected.size > 0 && (
            <div className="bg-white rounded-xl border border-primary/40 px-4 py-2.5 flex items-center gap-3 flex-wrap sticky top-0 z-10">
              <span className="text-xs font-bold text-slate-700">{selected.size} selected</span>
              <div className="flex-1" />
              <select
                value={bulkClient}
                onChange={(e) => setBulkClient(e.target.value ? Number(e.target.value) : '')}
                className="text-xs border border-border/60 rounded-md px-2 py-1.5 max-w-[240px]"
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
                className="px-3 py-1.5 rounded-md text-xs font-semibold text-emerald-700 border border-emerald-200 bg-emerald-50 hover:bg-emerald-100 disabled:opacity-40"
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
          <div className="flex items-center gap-2 px-4 py-2.5 text-xs text-slate-400">
            <Building2 className="w-3.5 h-3.5 shrink-0" />
            <span>
              Weeks still in progress are included, so a misfile can be caught before it's submitted.
              {data.uncommitted_blocks > 0 &&
                ` ${data.uncommitted_blocks} block${data.uncommitted_blocks === 1 ? '' : 's'} in these weeks nobody has confirmed yet — those stay in each person's Daily Review.`}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default MisfiledTimeReview;
