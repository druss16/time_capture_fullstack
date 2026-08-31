// src/components/ApprovalQueue.tsx
// Manager dashboard — styled to match WeeklyTimesheet design system

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  CheckCircle2, XCircle, Clock, RefreshCw, AlertTriangle,
  ChevronRight, User, CalendarDays, DollarSign, Info, Search,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { TimesheetDetailDrawer } from './TimesheetDetailDrawer';
import MisfiledTimeReview from './MisfiledTimeReview';

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

const TimesheetRow: React.FC<{
  timesheet: Timesheet;
  /** Blocks in this week the misfile sweep flagged as on the wrong client. */
  misfiled?: { count: number; minutes: number } | undefined;
  onApprove: (id: number) => Promise<void>;
  onReject:  (id: number, reason: string) => Promise<void>;
  onView:    (id: number) => void;
}> = ({ timesheet, misfiled, onApprove, onReject, onView }) => {
  const [expanded,        setExpanded]        = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason,    setRejectReason]    = useState('');
  const [processing,      setProcessing]      = useState(false);

  const nonBillable = timesheet.total_hours - timesheet.billable_hours;

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
    <>
      {/* Main row */}
      <tr
        onClick={() => onView(timesheet.id)}
        className={cn(
          'group cursor-pointer transition-colors',
          timesheet.auto_submitted ? 'bg-amber-50/30' : 'bg-white',
          'hover:bg-slate-100/70',
        )}
      >
        {/* Employee */}
        <td className={cn(
          'sticky left-0 z-10 px-4 py-2.5 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]',
          timesheet.auto_submitted ? 'bg-amber-50' : 'bg-white',
          'group-hover:bg-slate-100'
        )}>
          {timesheet.auto_submitted && (
            <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-amber-400 rounded-r" aria-hidden />
          )}
          <div className="flex items-center gap-2.5">
            <Avatar name={timesheet.user_name} />
            <div className="min-w-0">
              <p className="font-semibold text-slate-800 text-sm leading-tight truncate">{timesheet.user_name}</p>
              <p className="text-xs text-slate-400 truncate">{timesheet.user_email}</p>
            </div>
          </div>
        </td>

        {/* Week */}
        <td className="px-3 py-2.5 text-sm text-slate-600 whitespace-nowrap">
          {formatWeekRange(timesheet.week_start, timesheet.week_end)}
        </td>

        {/* Hours — all three in one cell, horizontal */}
        <td className="px-3 py-2.5 whitespace-nowrap">
          <div className="flex items-center gap-3 justify-end tabular-nums">
            <div className="text-right">
              <p className="text-sm font-bold text-primary leading-none">{formatHours(timesheet.billable_hours)}</p>
              <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-400 mt-0.5">Bill</p>
            </div>
            <div className="text-right">
              <p className="text-sm font-bold text-slate-400 leading-none">{formatHours(nonBillable)}</p>
              <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-400 mt-0.5">Non</p>
            </div>
            <div className="text-right border-l border-border/40 pl-3">
              <p className="text-sm font-bold text-slate-700 leading-none">{formatHours(timesheet.total_hours)}</p>
              <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-400 mt-0.5">Total</p>
            </div>
          </div>
        </td>

        {/* Amount */}
        <td className="px-3 py-2.5 text-right tabular-nums whitespace-nowrap">
          <span className="text-sm font-semibold text-slate-700">{formatCurrency(timesheet.total_amount)}</span>
        </td>

        {/* Actions + inline badges */}
        <td className={cn(
          'sticky right-0 z-10 px-4 py-2.5 shadow-[-2px_0_4px_-2px_rgba(0,0,0,0.06)]',
          timesheet.auto_submitted ? 'bg-amber-50' : 'bg-white',
          'group-hover:bg-slate-100'
        )}>
          <div className="flex items-center justify-end gap-1.5 flex-nowrap">
            {/* Badges */}
            {misfiled && misfiled.count > 0 && (
              <span
                title={`${misfiled.count} confirmed block${misfiled.count === 1 ? '' : 's'} (${formatHours(misfiled.minutes / 60)}) look booked to the wrong client — open "Check for misfiled time" above`}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-red-50 text-red-700 border border-red-200 whitespace-nowrap"
              >
                <AlertTriangle className="w-3 h-3 shrink-0" /> {misfiled.count} misfiled
              </span>
            )}
            {timesheet.auto_submitted && (
              <span
                title="Auto-submitted at the Tuesday deadline — the employee did not review this week before it was sent"
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 whitespace-nowrap"
              >
                <Clock className="w-3 h-3 shrink-0" /> Auto
              </span>
            )}
            {timesheet.days_pending > 0 && (
              <span className={cn(
                'inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold border whitespace-nowrap',
                timesheet.days_pending >= 3 ? 'bg-red-50 text-red-600 border-red-200' : 'bg-amber-50 text-amber-700 border-amber-200'
              )}>
                {timesheet.days_pending}d
              </span>
            )}
            {/* Notes expand */}
            {(timesheet.submitted_notes && !timesheet.submitted_notes.startsWith('[Auto-submitted')) && (
              <button
                onClick={(e) => { e.stopPropagation(); setExpanded(v => !v); }}
                className={cn(
                  'p-1 rounded-lg text-slate-300 hover:text-primary hover:bg-primary/5 transition-colors',
                  expanded && 'text-primary bg-primary/5'
                )}
                title="View notes"
              >
                <Info className="w-3.5 h-3.5" />
              </button>
            )}
            {/* View details */}

            {/* Reject */}
            <button
              onClick={(e) => { e.stopPropagation(); setShowRejectModal(true); }}
              disabled={processing}
              className="px-2.5 py-1.5 text-xs font-semibold text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-colors disabled:opacity-50 whitespace-nowrap"
            >
              Reject
            </button>
            {/* Approve */}
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
        </td>
      </tr>

      {/* Expanded notes row */}
      {expanded && timesheet.submitted_notes && (
        <tr className="bg-primary/3 border-t-0">
          <td colSpan={5} className="px-4 pb-3 pt-0">
            <div className="ml-10 flex items-start gap-2 p-3 bg-primary/5 rounded-lg border border-primary/15">
              <Info className="w-3.5 h-3.5 text-primary/60 mt-0.5 shrink-0" />
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-primary/60 mb-0.5">Employee note</p>
                <p className="text-sm text-slate-700">{timesheet.submitted_notes}</p>
              </div>
            </div>
          </td>
        </tr>
      )}

      {/* The full-width "did not manually review" row used to sit under every
          auto-submitted timesheet. With most weeks auto-submitting, that doubled
          the row count for a sentence that was identical every time — 40 people
          became 80 rows to scroll. The amber row tint, the "Auto" badge and its
          tooltip carry the same fact without costing a line each. */}

      {/* Reject Modal */}
      {showRejectModal && (
        <tr>
          <td colSpan={5} className="p-0">
            <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
              <div className="bg-white rounded-2xl shadow-xl max-w-md w-full mx-4 overflow-hidden">
                <div className="px-6 py-4 border-b border-border/50">
                  <h3 className="text-base font-bold text-slate-800">Reject Timesheet</h3>
                  <p className="text-sm text-slate-500 mt-0.5">
                    {timesheet.user_name} · {formatWeekRange(timesheet.week_start, timesheet.week_end)}
                  </p>
                </div>
                <div className="p-6 space-y-4">
                  {timesheet.auto_submitted && (
                    <div className="flex items-start gap-2.5 p-3 bg-amber-50 rounded-lg border border-amber-200 text-sm text-amber-700">
                      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                      <span>This timesheet was auto-submitted. The employee may not have reviewed their entries.</span>
                    </div>
                  )}
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">
                      Rejection reason <span className="text-red-500">*</span>
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
                  <p className="text-xs text-slate-400">
                    The employee will be notified and can edit and resubmit.
                  </p>
                </div>
                <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex justify-end gap-2">
                  <button
                    onClick={() => { setShowRejectModal(false); setRejectReason(''); }}
                    className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleReject}
                    disabled={!rejectReason.trim() || processing}
                    className="px-5 py-2 bg-red-600 text-white text-sm font-semibold rounded-lg hover:bg-red-700 transition-all disabled:opacity-50 flex items-center gap-2"
                  >
                    {processing
                      ? <><RefreshCw className="w-4 h-4 animate-spin" /> Rejecting...</>
                      : <><XCircle className="w-4 h-4" /> Reject Timesheet</>
                    }
                  </button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

const ApprovalQueue: React.FC = () => {
  const [loading,        setLoading]        = useState(true);
  const [error,          setError]          = useState<string | null>(null);
  const [queueData,      setQueueData]      = useState<QueueData>({ count: 0, timesheets: [] });
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
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

  const showSuccess = (msg: string) => {
    setSuccessMessage(msg);
    setTimeout(() => setSuccessMessage(null), 3000);
  };

  const handleApprove = async (id: number) => {
    try {
      await safeFetchJson(`${API_BASE}/billing/timesheets/${id}/approve/`, {
        method: 'POST',
        body: JSON.stringify({ notes: '' }),
      });
      showSuccess('Timesheet approved');
      fetchQueue();
      setSweepKey(k => k + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Approve failed');
    }
  };

  const handleReject = async (id: number, reason: string) => {
    try {
      await safeFetchJson(`${API_BASE}/billing/timesheets/${id}/reject/`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      showSuccess('Timesheet rejected');
      fetchQueue();
      setSweepKey(k => k + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reject failed');
    }
  };

  const handleView = (id: number) => { setDrawerTimesheetId(id); };

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return queueData.timesheets;
    return queueData.timesheets.filter(t =>
      t.user_name.toLowerCase().includes(needle) ||
      t.user_email.toLowerCase().includes(needle));
  }, [queueData.timesheets, q]);

  const autoCount   = queueData.timesheets.filter(t => t.auto_submitted).length;
  const totalBillable = queueData.timesheets.reduce((s, t) => s + t.billable_hours, 0);
  const totalAmount   = queueData.timesheets.reduce((s, t) => s + t.total_amount,   0);

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
          {queueData.count > 0 ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-amber-50 text-amber-700 border-amber-200">
              <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />
              {queueData.count} pending
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
          to answer BEFORE approving, not after — approvals are final and trigger
          billing. Numbering it says so without a paragraph of instructions, and
          the marker turns into a green tick once this step is clear. */}
      <MisfiledTimeReview step={1} onCounts={setMisfiled} refreshKey={sweepKey} />

      {/* ── STEP 2 ─────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="px-5 py-3 flex items-center justify-between gap-4 border-b border-border/60 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <span className="w-6 h-6 rounded-full shrink-0 inline-flex items-center justify-center text-xs font-bold bg-slate-800 text-white">
              2
            </span>
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-800">Approve the weeks</p>
              <p className="text-xs text-slate-400 truncate">
                {queueData.count === 0
                  ? 'Nothing waiting'
                  : q.trim()
                  ? `${shown.length} of ${queueData.count} shown`
                  : `${queueData.count} timesheet${queueData.count === 1 ? '' : 's'} · ${formatHours(totalBillable)} billable · ${formatCurrency(totalAmount)}`}
              </p>
            </div>
          </div>
          {/* Appears only once the list is long enough to need it — a search
              box above six rows is furniture, above forty it is the feature. */}
          {queueData.timesheets.length >= 8 && (
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
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-sm" style={{ minWidth: 620 }}>

            {/* Sticky col headers */}
            <thead className="sticky top-0 z-20">
              <tr className="border-b border-border/60 bg-white">
                <th className="sticky left-0 z-20 text-left px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 min-w-[200px] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  Employee
                </th>
                <th className="text-left px-3 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                  Week
                </th>
                <th className="text-right px-3 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                  Hours
                </th>
                <th className="text-right px-3 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                  Amount
                </th>
                {/* Pinned right for the same reason Employee is pinned left:
                    at 40 rows the horizontal scroll is real, and Approve is the
                    one control that must never be the thing scrolled off. */}
                <th className="sticky right-0 z-20 text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 shadow-[-2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  Actions
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-border/30">
              {shown.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center py-16 text-slate-400">
                    <CheckCircle2 className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                    <p className="font-medium text-slate-500">
                      {q.trim() ? `Nobody matching “${q.trim()}”` : 'No timesheets pending approval'}
                    </p>
                    <p className="text-sm mt-1">
                      {q.trim() ? 'Try a different name' : "You're all caught up"}
                    </p>
                  </td>
                </tr>
              ) : (
                shown.map(ts => (
                  <TimesheetRow
                    key={ts.id}
                    timesheet={ts}
                    misfiled={misfiled[String(ts.id)]}
                    onApprove={handleApprove}
                    onReject={handleReject}
                    onView={handleView}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between bg-slate-50/40 shrink-0">
          <p className="text-xs text-slate-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
            Approvals are final and trigger billing workflow
          </p>

        </div>
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