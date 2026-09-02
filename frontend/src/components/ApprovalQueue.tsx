// src/components/ApprovalQueue.tsx
// Manager dashboard — styled to match WeeklyTimesheet design system

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  CheckCircle2, XCircle, Clock, RefreshCw, AlertTriangle,
  ChevronRight, ChevronDown, User, CalendarDays, DollarSign, Info, Search,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { TimesheetDetailDrawer } from './TimesheetDetailDrawer';
import MisfiledTimeReview from './MisfiledTimeReview';
import { fetchWhoAmI } from '@/lib/whoami';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Timesheet {
  id: number;
  user: number;
  user_name: string;
  user_email: string;
  week_start: string;
  week_end: string;
  status: string;
  total_hours: number;
  billable_hours: number;
  total_amount: number;
  submitted_at: string | null;
  submitted_notes: string;
  days_pending: number;
  auto_submitted?: boolean;
}

interface QueueData {
  count: number;
  timesheets: Timesheet[];
}

// ── Utilities ─────────────────────────────────────────────────────────────────

const formatHours = (hours: number | string): string => {
  const num = parseFloat(String(hours)) || 0;
  if (num === 0) return '—';
  const h = Math.floor(num);
  const m = Math.round((num - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
};

const formatCurrency = (amount: number | string): string => {
  const num = parseFloat(String(amount)) || 0;
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
};

const formatWeekRange = (weekStart: string, weekEnd: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const end   = new Date(weekEnd   + 'T00:00:00');
  return `${start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
};

// ── Avatar ────────────────────────────────────────────────────────────────────

const AVATAR_COLORS = [
  'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500',
  'bg-violet-500', 'bg-cyan-500', 'bg-orange-500', 'bg-indigo-500',
];

const Avatar: React.FC<{ name: string }> = ({ name }) => {
  const initials     = name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  const colorCls     = AVATAR_COLORS[name.length % AVATAR_COLORS.length];
  return (
    <div className={cn('w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0', colorCls)}>
      {initials}
    </div>
  );
};

// ── Pending badge ─────────────────────────────────────────────────────────────

const PendingBadge: React.FC<{ days: number }> = ({ days }) => {
  if (days <= 0) return null;
  const cls = days >= 3
    ? 'bg-red-50 text-red-600 border-red-200'
    : 'bg-amber-50 text-amber-700 border-amber-200';
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border', cls)}>
      <Clock className="w-3 h-3" />
      {days}d pending
    </span>
  );
};

// ── Timesheet Row ─────────────────────────────────────────────────────────────
//
// A flex row, not a table row.
//
// The table this replaces pinned the Employee column left AND the Actions
// column right over a 620px minimum width — a layout with no solution below
// that width, because the two pinned columns simply slide over the middle. On a
// real screen Amount was rendering as "$1,7", and the fix was a horizontal
// scrollbar under a list nobody wants to scroll sideways.
//
// A flex row has no minimum. The name truncates, the numbers keep their widths,
// and the row shrinks to whatever it is given. It is also how every other list
// on this screen is built — My Week's client rows, the misfile ledger above —
// so Approvals stops being the one panel with its own construction.
const TimesheetRow: React.FC<{
  timesheet: Timesheet;
  /** Blocks in this week the misfile sweep flagged as on the wrong client. */
  misfiled?: { count: number; minutes: number } | undefined;
  /** The queue spans more than one week, so each row has to name its own. */
  showWeek: boolean;
  // Deliberately not promises: these return the moment the row is hidden, so a
  // reviewer can move to the next row without waiting for the request.
  onApprove: (id: number) => void;
  onReject:  (id: number, reason: string) => void;
  onView:    (id: number) => void;
}> = ({ timesheet, misfiled, showWeek, onApprove, onReject, onView }) => {
  const [expanded,        setExpanded]        = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason,    setRejectReason]    = useState('');
  const [processing,      setProcessing]      = useState(false);

  const nonBillable = timesheet.total_hours - timesheet.billable_hours;
  const hasNote = Boolean(
    timesheet.submitted_notes && !timesheet.submitted_notes.startsWith('[Auto-submitted')
  );

  const handleApprove = async () => {
    setProcessing(true);
    await onApprove(timesheet.id);
    setProcessing(false);
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) return;
    setProcessing(true);
    await onReject(timesheet.id, rejectReason);
    setProcessing(false);
    setShowRejectModal(false);
    setRejectReason('');
  };

  return (
    <div>
      <div
        onClick={() => onView(timesheet.id)}
        className={cn(
          'group relative flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors',
          timesheet.auto_submitted
            ? 'bg-amber-50/40 hover:bg-amber-50/80'
            : 'hover:bg-muted/40',
        )}
      >
        {timesheet.auto_submitted && (
          <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-amber-400" aria-hidden />
        )}

        <Avatar name={timesheet.user_name} />

        {/* The person. `flex-1 min-w-0` is what lets the row shrink rather than
            scroll: the name is the only thing here that can afford to truncate,
            so it is the only thing allowed to. */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="font-sans text-[14px] font-semibold text-foreground truncate leading-tight">
              {timesheet.user_name}
            </span>
            {/* Badges ride with the name now. Three pills sharing the Actions
                cell with two buttons is what pushed Amount off the row. */}
            {misfiled && misfiled.count > 0 && (
              <span
                title={`${misfiled.count} confirmed block${misfiled.count === 1 ? '' : 's'} (${formatHours(misfiled.minutes / 60)}) look booked to the wrong client — open “Check the time is filed right” above`}
                className="inline-flex shrink-0 items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-red-50 text-red-700 border border-red-200"
              >
                <AlertTriangle className="w-3 h-3 shrink-0" /> {misfiled.count}
              </span>
            )}
            {timesheet.auto_submitted && (
              <span
                title="Auto-submitted at the Tuesday deadline — the employee did not review this week before it was sent"
                className="inline-flex shrink-0 items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200"
              >
                <Clock className="w-3 h-3 shrink-0" /> Auto
              </span>
            )}
            {timesheet.days_pending > 0 && (
              <span
                title={`Waiting ${timesheet.days_pending} day${timesheet.days_pending === 1 ? '' : 's'} for approval`}
                className={cn(
                  'inline-flex shrink-0 items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold border',
                  timesheet.days_pending >= 3
                    ? 'bg-red-50 text-red-600 border-red-200'
                    : 'bg-amber-50 text-amber-700 border-amber-200',
                )}
              >
                {timesheet.days_pending}d
              </span>
            )}
            {hasNote && (
              <button
                onClick={(e) => { e.stopPropagation(); setExpanded(v => !v); }}
                className={cn(
                  'shrink-0 p-0.5 rounded text-muted-foreground/50 hover:text-primary hover:bg-primary/5 transition-colors',
                  expanded && 'text-primary bg-primary/5',
                )}
                title="View note"
              >
                <Info className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          {/* The week only earns a line when the queue actually holds more than
              one. Auto-submit runs for last week only, so in the normal case
              every row carried an identical date — six copies of one fact,
              costing the widest column on the row. */}
          <p className="font-mono text-[11px] text-muted-foreground/70 truncate leading-tight mt-0.5">
            {showWeek && `${formatWeekRange(timesheet.week_start, timesheet.week_end)} · `}
            {timesheet.user_email}
          </p>
        </div>

        {/* The split, in the same words and the same type My Week uses for the
            same fact. It replaces three stacked columns that each printed a
            BILL / NON / TOTAL caption on every row — at forty reports, a
            hundred and twenty repetitions of a column heading. */}
        <span className="hidden lg:inline shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/70">
          {formatHours(timesheet.billable_hours)} billable · {formatHours(nonBillable)} non-bill
        </span>

        <span className="w-[66px] shrink-0 text-right font-mono text-[13px] font-semibold text-foreground tabular-nums">
          {formatHours(timesheet.total_hours)}
        </span>
        <span className="hidden sm:inline w-[84px] shrink-0 text-right font-mono text-[13px] font-semibold text-muted-foreground tabular-nums">
          {formatCurrency(timesheet.total_amount)}
        </span>

        <div className="flex shrink-0 items-center gap-1.5">
          <button
            onClick={(e) => { e.stopPropagation(); setShowRejectModal(true); }}
            disabled={processing}
            className="px-2.5 py-1.5 text-xs font-semibold text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-colors disabled:opacity-50 whitespace-nowrap"
          >
            Reject
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); handleApprove(); }}
            disabled={processing}
            className="px-2.5 py-1.5 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1 whitespace-nowrap"
          >
            {processing
              ? <RefreshCw className="w-3 h-3 animate-spin" />
              : <CheckCircle2 className="w-3 h-3" />
            }
            Approve
          </button>
        </div>
      </div>

      {/* The employee's note */}
      {expanded && hasNote && (
        <div className="px-4 pb-3 -mt-1">
          <div className="ml-11 flex items-start gap-2 p-3 bg-primary/5 rounded-lg border border-primary/15">
            <Info className="w-3.5 h-3.5 text-primary/60 mt-0.5 shrink-0" />
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-primary/60 mb-0.5">Employee note</p>
              <p className="text-sm text-foreground">{timesheet.submitted_notes}</p>
            </div>
          </div>
        </div>
      )}

      {/* The full-width "did not manually review" row used to sit under every
          auto-submitted timesheet. With most weeks auto-submitting, that doubled
          the row count for a sentence that was identical every time — 40 people
          became 80 rows to scroll. The amber row tint, the "Auto" badge and its
          tooltip carry the same fact without costing a line each. */}

      {/* Reject Modal */}
      {showRejectModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full mx-4 overflow-hidden">
            <div className="px-6 py-4 border-b border-border/50">
              <h3 className="text-base font-bold text-foreground">Send back to {timesheet.user_name.split(' ')[0]}</h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                {formatWeekRange(timesheet.week_start, timesheet.week_end)}
              </p>
            </div>
            <div className="p-6 space-y-4">
              {timesheet.auto_submitted && (
                <div className="flex items-start gap-2.5 p-3 bg-amber-50 rounded-lg border border-amber-200 text-sm text-amber-700">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>This week was auto-submitted. The employee may not have reviewed their entries.</span>
                </div>
              )}
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
                  What needs fixing <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={rejectReason}
                  onChange={e => setRejectReason(e.target.value)}
                  placeholder="Explain what needs to be corrected..."
                  className="w-full px-3 py-2.5 text-sm border border-border/60 rounded-lg focus:ring-2 focus:ring-red-300 focus:border-red-400 resize-none"
                  rows={3}
                  autoFocus
                />
              </div>
              <p className="text-xs text-muted-foreground">
                The employee will be notified and can edit and resubmit.
              </p>
            </div>
            <div className="px-6 py-4 bg-muted/40 border-t border-border/50 flex justify-end gap-2">
              <button
                onClick={() => { setShowRejectModal(false); setRejectReason(''); }}
                className="px-4 py-2 text-sm font-semibold text-muted-foreground hover:bg-muted rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || processing}
                className="px-5 py-2 bg-red-600 text-white text-sm font-semibold rounded-lg hover:bg-red-700 transition-all disabled:opacity-50 flex items-center gap-2"
              >
                {processing
                  ? <><RefreshCw className="w-4 h-4 animate-spin" /> Sending back...</>
                  : <><XCircle className="w-4 h-4" /> Send back</>
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

const ApprovalQueue: React.FC = () => {
  const [loading,        setLoading]        = useState(true);
  const [error,          setError]          = useState<string | null>(null);
  const [queueData,      setQueueData]      = useState<QueueData>({ count: 0, timesheets: [] });
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  // Rows already acted on. They leave the list the instant the button is
  // pressed; the queue refetch that follows is what eventually agrees.
  const [hiddenIds,      setHiddenIds]      = useState<Set<number>>(() => new Set());
  const inFlight  = useRef(0);
  const settleRef = useRef<number | null>(null);
  const [drawerTimesheetId, setDrawerTimesheetId] = useState<number | null>(null);
  // Per-week misfile counts from the sweep panel, so each row can warn before
  // anyone clicks Approve. Keyed by timesheet id (as a string, from JSON).
  const [misfiled, setMisfiled] = useState<Record<string, { count: number; minutes: number }>>({});
  // Bumped after an approve/reject so the sweep re-runs against the new queue.
  const [sweepKey, setSweepKey] = useState(0);
  // At 20-40 reports the queue stops being a list you read and becomes one
  // you search. Client-side on purpose: the whole queue is already loaded,
  // so a round trip per keystroke would buy nothing.
  const [q, setQ] = useState('');
  // Step 2 collapses like step 1, and by default it waits its turn.
  //
  // The page used to load with both steps expanded, which is two steps only in
  // the numbering — everything was on screen at once and nothing said where to
  // start. Now step one leads, and step two opens the moment step one comes
  // back clean. That handoff is the whole point of numbering them.
  //
  // null means the reviewer has not touched this disclosure, so it follows the
  // flow. One click and their choice sticks, in either direction: someone who
  // opens step two while findings are outstanding keeps it open, and someone
  // who closes it does not have it reopened underneath them.
  const [openStep2Pref, setOpenStep2Pref] = useState<boolean | null>(null);
  const [step1, setStep1] = useState<{ settled: boolean; total: number }>({
    settled: false, total: 0,
  });
  // Returning the previous object when nothing changed keeps this from looping:
  // step one reports on every render of its own, and a fresh object each time
  // would re-render the queue forever.
  const handleStep1Status = useCallback((s: { settled: boolean; total: number }) => {
    setStep1((prev) =>
      prev.settled === s.settled && prev.total === s.total ? prev : s);
  }, []);
  const openStep2 = openStep2Pref ?? (step1.settled && step1.total === 0);
  const setOpenStep2 = (next: boolean | ((v: boolean) => boolean)) =>
    setOpenStep2Pref(typeof next === 'function' ? next(openStep2) : next);
  // Where an approved week actually goes for THIS firm. The footer used to
  // promise a billing workflow to everyone; org 21 has approved 125 weeks and
  // has no integration, no invoice and no push to show for any of them.
  const [destination, setDestination] = useState<string | null>(null);

  // Background refetch: same request, no `loading` flip, so the list stays on
  // screen and keeps its scroll position while someone works down it.
  const refetchQuiet = useCallback(async () => {
    try {
      const data = await safeFetchJson<QueueData>(`${API_BASE}/billing/approval-queue/`);
      setQueueData(data);
    } catch {
      // A failed background refresh is not worth an error banner -- the
      // optimistic list is still correct, and the next settle will retry.
    }
  }, []);

  // After a burst of approvals goes quiet, true up once: refresh the queue and
  // re-run the mis-filed sweep. Doing that per click re-scanned hundreds of
  // blocks and was most of the cost of a single approve.
  const scheduleSettle = useCallback(() => {
    if (settleRef.current) window.clearTimeout(settleRef.current);
    settleRef.current = window.setTimeout(() => {
      if (inFlight.current > 0) { scheduleSettle(); return; }
      refetchQuiet();
      setSweepKey(k => k + 1);
    }, 1200);
  }, [refetchQuiet]);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await safeFetchJson<QueueData>(`${API_BASE}/billing/approval-queue/`);
      setQueueData(data);
    } catch (err) {
      setError(
        err instanceof Error && err.message.includes('403')
          ? 'You do not have permission to view the approval queue.'
          : err instanceof Error ? err.message : 'Failed to load queue'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchQueue(); }, [fetchQueue]);

  useEffect(() => {
    let alive = true;
    fetchWhoAmI()
      .then((me: any) => {
        if (!alive) return;
        const live: string[] = me?.primary_integrations || [];
        setDestination(live.includes('clio') ? 'Clio'
          : live.includes('karbon') ? 'Karbon'
          : live.length ? live[0] : null);
      })
      .catch(() => { if (alive) setDestination(null); });
    return () => { alive = false; };
  }, []);

  const showSuccess = (msg: string) => {
    setSuccessMessage(msg);
    setTimeout(() => setSuccessMessage(null), 3000);
  };

  // Hide the row, then fire. Requests are not awaited before the next click is
  // possible, so approving six weeks is six clicks at your own pace rather than
  // six round trips in series. A failure puts its row back.
  const act = (id: number, path: string, body: unknown, done: string, failed: string) => {
    setHiddenIds(prev => new Set(prev).add(id));
    setError(null);
    inFlight.current += 1;
    safeFetchJson(`${API_BASE}/billing/timesheets/${id}/${path}/`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
      .then(() => showSuccess(done))
      .catch((err) => {
        setHiddenIds(prev => { const next = new Set(prev); next.delete(id); return next; });
        setError(err instanceof Error ? err.message : failed);
      })
      .finally(() => {
        inFlight.current -= 1;
        scheduleSettle();
      });
  };

  const handleApprove = (id: number) =>
    act(id, 'approve', { notes: '' }, 'Timesheet approved', 'Approve failed');

  const handleReject = (id: number, reason: string) =>
    act(id, 'reject', { reason }, 'Timesheet rejected', 'Reject failed');

  const handleView = (id: number) => { setDrawerTimesheetId(id); };

  // Everything below counts from `pending`, not queueData.timesheets, so the
  // header total and the "N auto-submitted" warning fall as rows are actioned
  // instead of contradicting the list underneath them.
  const pending = useMemo(
    () => queueData.timesheets.filter(t => !hiddenIds.has(t.id)),
    [queueData.timesheets, hiddenIds],
  );

  useEffect(() => {
    // Once a refetch comes back without an id we optimistically hid, the server
    // agrees and we can stop tracking it. Anything still present stays hidden --
    // its request is likely still in flight.
    setHiddenIds(prev => {
      if (!prev.size) return prev;
      const live = new Set(queueData.timesheets.map(t => t.id));
      const next = new Set([...prev].filter(id => live.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [queueData.timesheets]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return pending;
    return pending.filter(t =>
      t.user_name.toLowerCase().includes(needle) ||
      t.user_email.toLowerCase().includes(needle));
  }, [pending, q]);

  const autoCount   = pending.filter(t => t.auto_submitted).length;
  const pendingCount = pending.length;
  // Auto-submit runs for last week only, so the queue is normally one week for
  // everybody. When it is, the date belongs in the header once instead of on
  // every row — it was the widest column on the row and said the same thing
  // six times. When the queue genuinely spans weeks, each row names its own.
  const weekKeys  = useMemo(
    () => Array.from(new Set(pending.map(t => t.week_start))).sort(),
    [pending],
  );
  const multiWeek = weekKeys.length > 1;
  const oneWeek   = weekKeys.length === 1
    ? pending.find(t => t.week_start === weekKeys[0])
    : undefined;
  const totalBillable = pending.reduce((s, t) => s + t.billable_hours, 0);
  const totalAmount   = pending.reduce((s, t) => s + t.total_amount,   0);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2">

      {/* ── Title ──────────────────────────────────────────────────────── */}
      {/* Deliberately thin. The billable/value/auto-sub cluster that used to sit
          here now lives in step 2's own header, next to the table those numbers
          describe — three stats floating above two numbered steps read as a
          fourth thing to deal with. */}
      <div className="bg-white rounded-xl border border-border/60 px-5 h-12 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3 shrink-0">
          <h2 className="text-base font-bold text-slate-800">Approvals</h2>
          {pendingCount > 0 ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-amber-50 text-amber-700 border-amber-200">
              <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />
              {pendingCount} pending
            </span>
          ) : !loading && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-emerald-50 text-emerald-700 border-emerald-200">
              <CheckCircle2 className="w-3.5 h-3.5" /> All caught up
            </span>
          )}
        </div>
        <button
          onClick={fetchQueue}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* ── Banners ────────────────────────────────────────────────────── */}
      {(error || successMessage) && (
        <div className="space-y-2 shrink-0">
          {successMessage && (
            <div className="flex items-center gap-3 px-4 py-3 rounded-lg border bg-emerald-50 border-emerald-200 text-sm">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
              <span className="text-emerald-700 font-medium">{successMessage}</span>
            </div>
          )}
          {error && (
            <div className="flex items-start gap-3 px-4 py-3 rounded-lg border bg-red-50 border-red-200 text-sm">
              <AlertTriangle className="w-4 h-4 mt-0.5 text-red-500 shrink-0" />
              <div>
                <p className="font-semibold text-red-700">Error</p>
                <p className="mt-0.5 text-red-600">{error}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── STEP 1 ─────────────────────────────────────────────────────── */}
      {/* Ordered on purpose. "Is any of this on the wrong client?" is a question
          to answer BEFORE approving, not after — approving is final, and where a
          firm has an integration connected it is what sends the week onward. Numbering it says so without a paragraph of instructions, and
          the marker turns into a green tick once this step is clear. */}
      <MisfiledTimeReview
        step={1}
        onCounts={setMisfiled}
        onStatus={handleStep1Status}
        refreshKey={sweepKey}
      />

      {/* ── STEP 2 ─────────────────────────────────────────────────────── */}
      <div className={cn(
        'bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col min-h-0',
        openStep2 ? 'flex-1' : 'shrink-0'
      )}>
        <div className={cn(
          'px-5 py-3 flex items-center justify-between gap-4 shrink-0',
          openStep2 && 'border-b border-border/60'
        )}>
          <button
            onClick={() => setOpenStep2((v) => !v)}
            className="flex items-center gap-3 min-w-0 text-left"
          >
            {openStep2
              ? <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
              : <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />}
            <span className="w-6 h-6 rounded-full shrink-0 inline-flex items-center justify-center text-xs font-bold bg-slate-800 text-white">
              2
            </span>
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-800">Approve the weeks</p>
              <p className="text-xs text-slate-400 truncate">
                {pendingCount === 0
                  ? 'Nothing waiting'
                  : q.trim()
                  ? `${shown.length} of ${pendingCount} shown`
                  : [
                      `${pendingCount} ${pendingCount === 1 ? 'week' : 'weeks'}`,
                      oneWeek && formatWeekRange(oneWeek.week_start, oneWeek.week_end),
                      `${formatHours(totalBillable)} billable`,
                      formatCurrency(totalAmount),
                    ].filter(Boolean).join(' · ')}
              </p>
            </div>
          </button>
          {/* Appears only once the list is long enough to need it — a search
              box above six rows is furniture, above forty it is the feature. */}
          {pending.length >= 8 && (
            <div className="relative shrink-0">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Find a person…"
                className="w-44 pl-8 pr-7 py-1.5 text-xs border border-border/60 rounded-lg focus:ring-2 focus:ring-primary/20 focus:border-primary/40 outline-none"
              />
              {q && (
                <button
                  onClick={() => setQ('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                  title="Clear"
                >
                  <XCircle className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}
          {autoCount > 0 && (
            <p className="text-xs text-amber-600 flex items-center gap-1.5 shrink-0 text-right">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              <span>{autoCount} auto-submitted — nobody reviewed {autoCount === 1 ? 'it' : 'them'}</span>
            </p>
          )}
        </div>
        {openStep2 && (
        <>
        {/* The list. `overflow-x-hidden` is deliberate and is half the fix: the
            rows below have no minimum width, so a horizontal scrollbar here
            could only ever mean something inside is misbehaving. Vertical
            scroll stays — at forty reports it is real. */}
        <div className="overflow-y-auto overflow-x-hidden flex-1 divide-y divide-border/30">
          {shown.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground">
              <CheckCircle2 className="w-10 h-10 text-muted-foreground/25 mx-auto mb-3" />
              <p className="font-medium text-foreground/70">
                {q.trim() ? `Nobody matching “${q.trim()}”` : 'No weeks waiting'}
              </p>
              <p className="text-sm mt-1">
                {q.trim() ? 'Try a different name' : "You're all caught up"}
              </p>
            </div>
          ) : (
            shown.map(ts => (
              <TimesheetRow
                key={ts.id}
                timesheet={ts}
                misfiled={misfiled[String(ts.id)]}
                showWeek={multiWeek}
                onApprove={handleApprove}
                onReject={handleReject}
                onView={handleView}
              />
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between bg-slate-50/40 shrink-0">
          {/* Say what approving actually does HERE. Promising a billing workflow
              to a firm that has none is the sentence teaching people this screen
              is about invoices — and it is the reason "timesheet" reads as a
              billing word rather than a record. */}
          <p className="text-xs text-slate-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
            {destination
              ? `Approving is final and sends the week to ${destination}`
              : 'Approving is final — the week becomes your firm’s record of the time'}
          </p>
        </div>
        </>
        )}
      </div>

      {/* ── Detail Drawer ──────────────────────────────────────────── */}
      <TimesheetDetailDrawer
        timesheetId={drawerTimesheetId}
        onClose={() => setDrawerTimesheetId(null)}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    </div>
  );
};

export default ApprovalQueue;