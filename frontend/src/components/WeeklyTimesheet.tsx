// src/components/WeeklyTimesheet.tsx
// Read-only weekly timesheet. Default "Summary" view ranks clients by time with a
// billable/non-billable split bar; "By day" view keeps the full Mon–Sun matrix.
// Time is auto-captured by the desktop agent, so cells are not editable here —
// adjustments happen in Daily Review.

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  ChevronLeft, ChevronRight, ChevronDown, Clock, CheckCircle2, Lock,
  AlertTriangle, Info, RefreshCw, Search, X, Layers, CalendarDays,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

// ── Types ─────────────────────────────────────────────────────────────────────

interface TimesheetEntry {
  client_id: number | null;
  client_name: string;
  task_type_id: number | null;
  task_type_name: string;
  is_billable: boolean;
  days: Record<string, number>;
  total: number;
}

interface TimesheetData {
  week_start: string;
  week_end: string;
  timesheet_id: number;
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'locked';
  entries: TimesheetEntry[];
  daily_totals: Record<string, number>;
  grand_total: number;
  billable_total: number;
  auto_submitted?: boolean;
  submitted_at?: string | null;
  rejection_reason?: string;
}

interface DayHeader {
  date: string;
  label: string;
  dayNum: number;
  isWeekend: boolean;
  isToday: boolean;
}

// A client aggregated across all its task rows for the Summary view.
interface ClientAgg {
  key: string;
  clientName: string;
  total: number;
  billable: number;
  nonBillable: number;
  taskCount: number;
  primaryTask: string;
  allBillable: boolean;
  allNonBillable: boolean;
  entries: TimesheetEntry[];
}

// Clients whose whole week is under this many hours get rolled into one row.
const TAIL_THRESHOLD_HOURS = 0.25; // 15 minutes

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

const getMonday = (date: Date): Date => {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.setDate(diff));
};

const formatWeekRange = (weekStart: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return `${start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
};

const isWeekEnded = (weekStart: string): boolean => {
  const start = new Date(weekStart + 'T00:00:00');
  const weekEnd = new Date(start);
  weekEnd.setDate(weekEnd.getDate() + 6);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return today > weekEnd;
};

const getCanSubmitDate = (weekStart: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const monday = new Date(start);
  monday.setDate(monday.getDate() + 7);
  return monday.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
};

const getDaysUntilSubmit = (weekStart: string): number => {
  const start = new Date(weekStart + 'T00:00:00');
  const weekEnd = new Date(start);
  weekEnd.setDate(weekEnd.getDate() + 6);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = weekEnd.getTime() - today.getTime();
  return Math.ceil(diff / (1000 * 60 * 60 * 24)) + 1;
};

const todayIso = () => new Date().toISOString().split('T')[0];

const pct = (part: number, whole: number): number =>
  whole > 0 ? Math.max(0, Math.min(100, (part / whole) * 100)) : 0;

// ── Status Badge ──────────────────────────────────────────────────────────────

const StatusBadge: React.FC<{ status: TimesheetData['status']; autoSubmitted?: boolean }> = ({
  status, autoSubmitted,
}) => {
  const map: Record<string, { cls: string; label: string }> = {
    draft:     { cls: 'bg-slate-100 text-slate-600 border-slate-200',      label: 'Draft' },
    submitted: { cls: 'bg-amber-50 text-amber-700 border-amber-200',       label: 'Pending Approval' },
    approved:  { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: 'Approved' },
    rejected:  { cls: 'bg-red-50 text-red-600 border-red-200',             label: 'Rejected' },
    locked:    { cls: 'bg-slate-100 text-slate-500 border-slate-200',      label: 'Locked' },
  };
  const { cls, label } = map[status] || map.draft;
  return (
    <div className="flex items-center gap-2">
      <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border', cls)}>
        {status === 'draft'     && <span className="w-1.5 h-1.5 bg-slate-400 rounded-full" />}
        {status === 'submitted' && <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />}
        {status === 'approved'  && <CheckCircle2 className="w-3.5 h-3.5" />}
        {status === 'locked'    && <Lock className="w-3 h-3" />}
        {label}
      </span>
      {autoSubmitted && (
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-600 border border-amber-200">
          <Clock className="w-3 h-3" /> Auto-submitted
        </span>
      )}
    </div>
  );
};

// ── Banner ────────────────────────────────────────────────────────────────────

const Banner: React.FC<{
  type: 'info' | 'warning' | 'error';
  title: string;
  message: React.ReactNode;
}> = ({ type, title, message }) => {
  const styles = {
    info:    { wrap: 'bg-primary/5 border-primary/20',  icon: 'text-primary',   text: 'text-primary/80',  Title: 'text-primary' },
    warning: { wrap: 'bg-amber-50 border-amber-200',    icon: 'text-amber-500', text: 'text-amber-700',   Title: 'text-amber-800' },
    error:   { wrap: 'bg-red-50 border-red-200',        icon: 'text-red-500',   text: 'text-red-600',     Title: 'text-red-700' },
  }[type];
  const Icon = type === 'info' ? Info : AlertTriangle;
  return (
    <div className={cn('flex items-start gap-3 px-4 py-3 rounded-lg border text-sm', styles.wrap)}>
      <Icon className={cn('w-4 h-4 mt-0.5 shrink-0', styles.icon)} />
      <div>
        <p className={cn('font-semibold', styles.Title)}>{title}</p>
        <p className={cn('mt-0.5', styles.text)}>{message}</p>
      </div>
    </div>
  );
};

// ── Billable-split bar (shared: headline + per-row) ─────────────────────────────

const SplitBar: React.FC<{
  billable: number;
  nonBillable: number;
  /** Fraction (0–100) of the track this bar should fill. Defaults to full width. */
  fill?: number;
  className?: string;
}> = ({ billable, nonBillable, fill = 100, className }) => {
  const total = billable + nonBillable;
  return (
    <div className={cn('rounded-full bg-slate-100 overflow-hidden', className)}>
      <div className="h-full flex" style={{ width: `${fill}%` }}>
        <div className="h-full bg-primary" style={{ width: `${pct(billable, total)}%` }} />
        <div className="h-full bg-slate-300" style={{ width: `${pct(nonBillable, total)}%` }} />
      </div>
    </div>
  );
};

const ClientDot: React.FC<{ agg: Pick<ClientAgg, 'allBillable' | 'allNonBillable'> }> = ({ agg }) => {
  if (agg.allNonBillable) return <span className="w-2.5 h-2.5 rounded-full bg-slate-300 shrink-0" />;
  if (agg.allBillable)    return <span className="w-2.5 h-2.5 rounded-full bg-primary shrink-0" />;
  // Mixed billable + non-billable: half primary, half slate.
  return (
    <span className="w-2.5 h-2.5 rounded-full shrink-0 overflow-hidden flex" aria-hidden>
      <span className="w-1/2 h-full bg-primary" />
      <span className="w-1/2 h-full bg-slate-300" />
    </span>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

type ViewMode = 'summary' | 'byday';

const WeeklyTimesheet: React.FC = () => {
  const [loading, setLoading]               = useState(true);
  const [error, setError]                   = useState<string | null>(null);
  const [weekStart, setWeekStart]           = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    const p = params.get('week');
    if (p && /^\d{4}-\d{2}-\d{2}$/.test(p)) return p;
    return getMonday(new Date()).toISOString().split('T')[0];
  });
  const [timesheetData, setTimesheetData]   = useState<TimesheetData | null>(null);
  const [submitting, setSubmitting]         = useState(false);
  const [submitNotes, setSubmitNotes]       = useState('');
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [search, setSearch]                 = useState('');
  const [view, setView]                     = useState<ViewMode>('summary');
  const [expanded, setExpanded]             = useState<Set<string>>(new Set());
  const [tailOpen, setTailOpen]             = useState(false);

  const searchRef = useRef<HTMLInputElement>(null);

  const fetchTimesheet = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await safeFetchJson<TimesheetData>(
        `${API_BASE}/billing/weekly/?week_start=${weekStart}`
      );
      setTimesheetData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load timesheet');
    } finally {
      setLoading(false);
    }
  }, [weekStart]);

  useEffect(() => { fetchTimesheet(); }, [fetchTimesheet]);
  useEffect(() => { setSearch(''); setExpanded(new Set()); setTailOpen(false); }, [weekStart]);

  const goToWeek = (dir: number) => {
    const d = new Date(weekStart + 'T00:00:00');
    d.setDate(d.getDate() + dir * 7);
    setWeekStart(d.toISOString().split('T')[0]);
  };

  const daysUntilSubmit = useMemo(() => {
    if (!timesheetData) return 0;
    return getDaysUntilSubmit(timesheetData.week_start);
  }, [timesheetData]);

  // Entries filtered by the search box (client or task name).
  const searchedEntries = useMemo(() => {
    const entries = (timesheetData?.entries ?? []).filter(e => e.total > 0);
    if (!search.trim()) return entries;
    const q = search.toLowerCase();
    return entries.filter(e =>
      e.client_name.toLowerCase().includes(q) ||
      e.task_type_name.toLowerCase().includes(q)
    );
  }, [timesheetData?.entries, search]);

  // Aggregate task rows into one row per client, ranked by total desc.
  const clients = useMemo<ClientAgg[]>(() => {
    const map = new Map<string, ClientAgg>();
    for (const e of searchedEntries) {
      const key = String(e.client_id ?? e.client_name);
      let agg = map.get(key);
      if (!agg) {
        agg = {
          key, clientName: e.client_name, total: 0, billable: 0, nonBillable: 0,
          taskCount: 0, primaryTask: e.task_type_name, allBillable: true, allNonBillable: true,
          entries: [],
        };
        map.set(key, agg);
      }
      agg.total += e.total;
      agg.billable += e.is_billable ? e.total : 0;
      agg.nonBillable += e.is_billable ? 0 : e.total;
      agg.taskCount += 1;
      agg.entries.push(e);
      if (e.is_billable) agg.allNonBillable = false; else agg.allBillable = false;
    }
    const list = Array.from(map.values());
    // Pick the biggest task as the "primary" label; sort tasks within a client.
    for (const agg of list) {
      agg.entries.sort((a, b) => b.total - a.total);
      agg.primaryTask = agg.entries[0]?.task_type_name ?? agg.primaryTask;
    }
    return list.sort((a, b) => b.total - a.total);
  }, [searchedEntries]);

  const { mainClients, tailClients, maxTotal } = useMemo(() => {
    const main = clients.filter(c => c.total >= TAIL_THRESHOLD_HOURS);
    const tail = clients.filter(c => c.total < TAIL_THRESHOLD_HOURS);
    const max = clients.reduce((m, c) => Math.max(m, c.total), 0);
    return { mainClients: main, tailClients: tail, maxTotal: max };
  }, [clients]);

  const tailTotals = useMemo(() => {
    return tailClients.reduce(
      (acc, c) => ({ billable: acc.billable + c.billable, nonBillable: acc.nonBillable + c.nonBillable, total: acc.total + c.total }),
      { billable: 0, nonBillable: 0, total: 0 }
    );
  }, [tailClients]);

  const toggleExpand = (key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (!timesheetData?.timesheet_id) return;
    setSubmitting(true);
    setError(null);
    try {
      await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetData.timesheet_id}/submit/`,
        { method: 'POST', body: JSON.stringify({ notes: submitNotes }) }
      );
      setShowSubmitModal(false);
      setSubmitNotes('');
      fetchTimesheet();
    } catch (err: any) {
      const d = err?.data || {};
      setError(d.can_submit_on
        ? `Cannot submit yet. Available starting ${d.can_submit_on}.`
        : err instanceof Error ? err.message : 'Submit failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReopen = async () => {
    if (!timesheetData?.timesheet_id) return;
    try {
      await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetData.timesheet_id}/reopen/`,
        { method: 'POST' }
      );
      fetchTimesheet();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reopen');
    }
  };

  const getDayHeaders = (): DayHeader[] => {
    if (!timesheetData) return [];
    const today = todayIso();
    const start = new Date(timesheetData.week_start + 'T00:00:00');
    return Array.from({ length: 7 }, (_, i) => {
      const day = new Date(start);
      day.setDate(day.getDate() + i);
      const date = day.toISOString().split('T')[0];
      return {
        date,
        label: day.toLocaleDateString('en-US', { weekday: 'short' }),
        dayNum: day.getDate(),
        isWeekend: i >= 5,
        isToday: date === today,
      };
    });
  };

  const days          = getDayHeaders();
  const weekHasEnded  = timesheetData ? isWeekEnded(timesheetData.week_start) : false;
  const nonBillable   = (timesheetData?.grand_total ?? 0) - (timesheetData?.billable_total ?? 0);
  const billable      = timesheetData?.billable_total ?? 0;
  const grandTotal    = timesheetData?.grand_total ?? 0;
  const totalClients  = clients.length;
  const billablePctLabel = grandTotal > 0 ? Math.round(pct(billable, grandTotal)) : 0;
  const isEmpty       = totalClients === 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
      </div>
    );
  }

  const submitButton = (() => {
    if (timesheetData?.status === 'draft') {
      return weekHasEnded ? (
        <button
          onClick={() => setShowSubmitModal(true)}
          className="px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all flex items-center gap-1.5"
        >
          <CheckCircle2 className="w-4 h-4" /> Submit for Approval
        </button>
      ) : (
        <button disabled className="px-4 py-2 bg-slate-100 text-slate-400 text-sm font-semibold rounded-lg cursor-not-allowed flex items-center gap-1.5">
          <Clock className="w-4 h-4" /> Submit opens {getCanSubmitDate(timesheetData.week_start)}
        </button>
      );
    }
    if (timesheetData?.status === 'rejected') {
      return (
        <>
          <button onClick={handleReopen} className="px-4 py-2 bg-slate-100 text-slate-700 text-sm font-semibold rounded-lg hover:bg-slate-200 transition-all">
            Edit
          </button>
          <button onClick={() => setShowSubmitModal(true)} className="px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all">
            Resubmit
          </button>
        </>
      );
    }
    return null;
  })();

  return (
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2.5">

      {/* ── Toolbar: title / status / week nav ─────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 h-14 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3 shrink-0">
          <h2 className="text-base font-bold text-slate-800">My Timesheet</h2>
          {timesheetData && (
            <StatusBadge status={timesheetData.status} autoSubmitted={timesheetData.auto_submitted ?? false} />
          )}
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-0.5 bg-muted/60 border border-border/50 rounded-lg overflow-hidden">
            <button onClick={() => goToWeek(-1)} className="px-1.5 py-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted transition-all">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setWeekStart(getMonday(new Date()).toISOString().split('T')[0])}
              className="px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-muted transition-all"
            >
              This week
            </button>
            <button onClick={() => goToWeek(1)} className="px-1.5 py-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted transition-all">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
          <span className="text-sm font-medium text-slate-600 whitespace-nowrap tabular-nums">
            {timesheetData && formatWeekRange(timesheetData.week_start)}
          </span>
        </div>
      </div>

      {/* ── Headline: total + billable split ───────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 py-3.5 flex items-center gap-5 shrink-0">
        <div className="flex flex-col shrink-0">
          <span className="text-2xl font-extrabold tracking-tight text-slate-800 leading-none tabular-nums">
            {formatHours(grandTotal)}
          </span>
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mt-1">This week</span>
        </div>
        <div className="flex-1 min-w-0">
          <SplitBar billable={billable} nonBillable={nonBillable} className="h-4" />
          <div className="flex flex-wrap gap-x-6 gap-y-1 mt-2">
            <span className="flex items-center gap-2 text-xs text-slate-500">
              <span className="w-2.5 h-2.5 rounded-sm bg-primary inline-block" />
              <b className="text-slate-700 font-bold tabular-nums">{formatHours(billable)}</b> billable · {billablePctLabel}%
            </span>
            <span className="flex items-center gap-2 text-xs text-slate-500">
              <span className="w-2.5 h-2.5 rounded-sm bg-slate-300 inline-block" />
              <b className="text-slate-700 font-bold tabular-nums">{formatHours(nonBillable)}</b> non-billable · {100 - billablePctLabel}%
            </span>
          </div>
        </div>
      </div>

      {/* ── Banners: errors + rejections only ─────────────────────────── */}
      {(error || timesheetData?.status === 'rejected') && (
        <div className="space-y-2 shrink-0">
          {error && <Banner type="error" title="Error" message={error} />}
          {timesheetData?.status === 'rejected' && (
            <Banner
              type="error"
              title="Timesheet Rejected"
              message={timesheetData.rejection_reason || 'Please review and make corrections before resubmitting.'}
            />
          )}
        </div>
      )}

      {/* ── Grid card ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">

        {/* Controls: count / search / view toggle */}
        <div className="flex items-center gap-3 px-4 h-11 border-b border-border/40 bg-slate-50/40 shrink-0">
          <span className="text-xs text-slate-500 shrink-0">
            <b className="text-slate-700 font-semibold">{totalClients}</b> client{totalClients !== 1 ? 's' : ''} this week
          </span>
          <div className="relative w-52">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search clients…"
              className="w-full pl-8 pr-7 py-1.5 text-sm bg-white border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
            />
            {search && (
              <button
                onClick={() => { setSearch(''); searchRef.current?.focus(); }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="ml-auto flex bg-slate-100 border border-border/50 rounded-lg p-0.5">
            {([
              { id: 'summary', label: 'Summary', icon: Layers },
              { id: 'byday',   label: 'By day',  icon: CalendarDays },
            ] as { id: ViewMode; label: string; icon: React.ElementType }[]).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setView(id)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-md transition-all',
                  view === id ? 'bg-white text-primary shadow-sm' : 'text-slate-500 hover:text-slate-700'
                )}
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="overflow-auto flex-1">
          {isEmpty ? (
            <div className="text-center py-20 text-slate-400">
              {search ? (
                <>
                  <Search className="w-8 h-8 text-slate-200 mx-auto mb-3" />
                  <p className="font-medium text-slate-500">No clients match “{search}”</p>
                  <button onClick={() => setSearch('')} className="mt-2 text-sm text-primary hover:underline">Clear search</button>
                </>
              ) : (
                <>
                  <Clock className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                  <p className="font-medium text-slate-500">No time tracked this week</p>
                  <p className="text-sm mt-1">Time appears here as it's captured by your desktop agent</p>
                </>
              )}
            </div>
          ) : view === 'summary' ? (
            <SummaryView
              mainClients={mainClients}
              tailClients={tailClients}
              tailTotals={tailTotals}
              maxTotal={maxTotal}
              expanded={expanded}
              tailOpen={tailOpen}
              onToggle={toggleExpand}
              onToggleTail={() => setTailOpen(o => !o)}
            />
          ) : (
            <ByDayView clients={clients} days={days} dailyTotals={timesheetData?.daily_totals ?? {}} grandTotal={grandTotal} />
          )}
        </div>

        {/* Footer: week total + read-only note + submit */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between gap-4 bg-slate-50/40 shrink-0">
          <div className="flex items-baseline gap-2.5">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Week total</span>
            <span className="text-base font-extrabold text-slate-800 tabular-nums">{formatHours(grandTotal)}</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden sm:flex items-center gap-1.5 text-xs text-slate-400">
              <Lock className="w-3.5 h-3.5 text-slate-300" />
              Auto-captured ·{' '}
              <a href="/daily" className="text-primary font-medium hover:underline">Adjust in Daily Review →</a>
            </span>
            {submitButton}
          </div>
        </div>
      </div>

      {/* ── Submit Modal ──────────────────────────────────────────────── */}
      {showSubmitModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full mx-4 overflow-hidden">
            <div className="px-6 py-4 border-b border-border/50">
              <h3 className="text-base font-bold text-slate-800">Submit Timesheet</h3>
              <p className="text-sm text-slate-500 mt-0.5">
                {timesheetData && formatWeekRange(timesheetData.week_start)}
              </p>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Total',    value: formatHours(grandTotal), cls: 'text-slate-800' },
                  { label: 'Billable', value: formatHours(billable),   cls: 'text-primary' },
                  { label: 'Non-bill', value: formatHours(nonBillable), cls: 'text-slate-400' },
                ].map(({ label, value, cls }) => (
                  <div key={label} className="text-center p-3 bg-slate-50 rounded-lg border border-border/50">
                    <p className={cn('text-lg font-bold tabular-nums', cls)}>{value}</p>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mt-0.5">{label}</p>
                  </div>
                ))}
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">
                  Notes <span className="text-slate-400 normal-case font-normal">(optional)</span>
                </label>
                <textarea
                  value={submitNotes}
                  onChange={(e) => setSubmitNotes(e.target.value)}
                  placeholder="Anything your manager should know..."
                  className="w-full px-3 py-2.5 text-sm border border-border/60 rounded-lg focus:ring-2 focus:ring-primary/30 focus:border-primary resize-none"
                  rows={3}
                />
              </div>
              <p className="text-xs text-slate-400">
                Once submitted, you won't be able to edit until your manager reviews it.
              </p>
            </div>
            <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex justify-end gap-2">
              <button
                onClick={() => setShowSubmitModal(false)}
                className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all disabled:opacity-50 flex items-center gap-2"
              >
                {submitting
                  ? <><RefreshCw className="w-4 h-4 animate-spin" /> Submitting...</>
                  : <><CheckCircle2 className="w-4 h-4" /> Submit for Approval</>
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Summary View ──────────────────────────────────────────────────────────────

const ClientRow: React.FC<{
  agg: ClientAgg;
  maxTotal: number;
  isExpanded: boolean;
  onToggle: (key: string) => void;
}> = ({ agg, maxTotal, isExpanded, onToggle }) => {
  const multi = agg.taskCount > 1;
  const sub = multi
    ? `${agg.primaryTask} · +${agg.taskCount - 1} task${agg.taskCount - 1 !== 1 ? 's' : ''}`
    : agg.primaryTask;

  const rowClass = 'w-full grid grid-cols-[1fr_minmax(120px,200px)_84px_24px] items-center gap-4 px-5 py-3 text-left';
  const inner = (
    <>
      <div className="flex items-center gap-3 min-w-0">
        <ClientDot agg={agg} />
        <div className="min-w-0">
          <p className="text-sm font-bold text-slate-800 truncate leading-tight">{agg.clientName}</p>
          <p className="text-[11px] text-slate-400 truncate mt-0.5">{sub}</p>
        </div>
      </div>
      <div className="hidden sm:block">
        <SplitBar billable={agg.billable} nonBillable={agg.nonBillable} fill={pct(agg.total, maxTotal)} className="h-2.5" />
      </div>
      <span className="text-right text-[15px] font-extrabold text-slate-800 tabular-nums">{formatHours(agg.total)}</span>
      <span className="flex justify-center text-slate-300">
        {multi && <ChevronRight className={cn('w-4 h-4 transition-transform', isExpanded && 'rotate-90')} />}
      </span>
    </>
  );

  return (
    <>
      {multi ? (
        <button onClick={() => onToggle(agg.key)} className={cn(rowClass, 'hover:bg-slate-50/70 transition-colors')}>
          {inner}
        </button>
      ) : (
        <div className={rowClass}>{inner}</div>
      )}

      {isExpanded && multi && (
        <div className="bg-slate-50/50 border-t border-border/20">
          {agg.entries.map(e => (
            <div
              key={`${e.client_id}-${e.task_type_id}`}
              className="grid grid-cols-[1fr_84px_24px] items-center gap-4 pl-14 pr-5 py-2"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', e.is_billable ? 'bg-primary' : 'bg-slate-300')} />
                <span className="text-[13px] text-slate-600 truncate">{e.task_type_name}</span>
                {!e.is_billable && <span className="text-[10px] text-slate-400 shrink-0">non-billable</span>}
              </div>
              <span className="text-right text-[13px] font-semibold text-slate-600 tabular-nums">{formatHours(e.total)}</span>
              <span />
            </div>
          ))}
        </div>
      )}
    </>
  );
};

const SummaryView: React.FC<{
  mainClients: ClientAgg[];
  tailClients: ClientAgg[];
  tailTotals: { billable: number; nonBillable: number; total: number };
  maxTotal: number;
  expanded: Set<string>;
  tailOpen: boolean;
  onToggle: (key: string) => void;
  onToggleTail: () => void;
}> = ({ mainClients, tailClients, tailTotals, maxTotal, expanded, tailOpen, onToggle, onToggleTail }) => (
  <div className="divide-y divide-border/30">
    {mainClients.map(agg => (
      <ClientRow key={agg.key} agg={agg} maxTotal={maxTotal} isExpanded={expanded.has(agg.key)} onToggle={onToggle} />
    ))}

    {tailClients.length > 0 && (
      <>
        <button
          onClick={onToggleTail}
          className="w-full grid grid-cols-[1fr_minmax(120px,200px)_84px_24px] items-center gap-4 px-5 py-2.5 text-left bg-slate-50/50 hover:bg-slate-100/60 transition-colors"
        >
          <div className="flex items-center gap-3 min-w-0">
            <span className="w-2.5 h-2.5 rounded-full bg-slate-200 shrink-0" />
            <p className="text-[13px] font-semibold text-slate-500 truncate">
              {tailClients.length} more client{tailClients.length !== 1 ? 's' : ''} under 15 min
            </p>
          </div>
          <div className="hidden sm:block">
            <SplitBar billable={tailTotals.billable} nonBillable={tailTotals.nonBillable} fill={pct(tailTotals.total, maxTotal)} className="h-2.5" />
          </div>
          <span className="text-right text-[13px] font-bold text-slate-500 tabular-nums">{formatHours(tailTotals.total)}</span>
          <span className="flex justify-center text-slate-400">
            <ChevronDown className={cn('w-4 h-4 transition-transform', tailOpen && 'rotate-180')} />
          </span>
        </button>

        {tailOpen && tailClients.map(agg => (
          <ClientRow key={agg.key} agg={agg} maxTotal={maxTotal} isExpanded={expanded.has(agg.key)} onToggle={onToggle} />
        ))}
      </>
    )}
  </div>
);

// ── By-day View (read-only matrix) ──────────────────────────────────────────────

const ByDayView: React.FC<{
  clients: ClientAgg[];
  days: DayHeader[];
  dailyTotals: Record<string, number>;
  grandTotal: number;
}> = ({ clients, days, dailyTotals, grandTotal }) => (
  <table className="w-full border-collapse text-sm" style={{ minWidth: 720 }}>
    <thead className="sticky top-0 z-20">
      <tr className="border-b border-border/60 bg-white">
        <th className="sticky left-0 z-20 text-left px-5 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 min-w-[220px] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
          Client / Task
        </th>
        {days.map(day => (
          <th
            key={day.date}
            className={cn(
              'text-center px-2 py-3 font-semibold min-w-[68px]',
              day.isWeekend ? 'bg-slate-50/80 text-slate-400' : 'bg-slate-50 text-slate-600',
            )}
          >
            <div className="text-[10px] uppercase tracking-wider font-semibold">{day.label}</div>
            <div className={cn(
              'text-sm font-bold mt-0.5 w-6 h-6 flex items-center justify-center rounded-full mx-auto',
              day.isToday ? 'bg-primary text-white' : ''
            )}>
              {day.dayNum}
            </div>
          </th>
        ))}
        <th className="text-center px-4 py-3 bg-slate-50 font-semibold text-slate-600 text-xs uppercase tracking-wider min-w-[72px]">
          Total
        </th>
      </tr>
    </thead>

    <tbody className="divide-y divide-border/30">
      {clients.map(agg => {
        const multi = agg.taskCount > 1;
        return (
          <React.Fragment key={agg.key}>
            {multi && (
              <tr className="bg-slate-50/70">
                <td className="sticky left-0 z-10 px-5 py-2 bg-slate-50/90 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  <div className="flex items-center gap-2">
                    <ClientDot agg={agg} />
                    <span className="font-semibold text-slate-700 text-xs">{agg.clientName}</span>
                    <span className="text-[10px] text-slate-400">{agg.taskCount} tasks</span>
                  </div>
                </td>
                {days.map(day => {
                  const dayTotal = agg.entries.reduce((s, e) => s + (e.days[day.date] || 0), 0);
                  return (
                    <td key={day.date} className={cn(
                      'text-right px-3 py-2 text-xs tabular-nums',
                      day.isWeekend ? 'bg-slate-50/60' : '',
                      dayTotal > 0 ? 'font-semibold text-slate-600' : 'text-slate-200'
                    )}>
                      {formatHours(dayTotal)}
                    </td>
                  );
                })}
                <td className={cn('text-right px-3 py-2 text-xs tabular-nums font-bold', agg.total > 0 ? 'text-slate-700' : 'text-slate-200')}>
                  {formatHours(agg.total)}
                </td>
              </tr>
            )}

            {agg.entries.map(entry => (
              <tr key={`${entry.client_id}-${entry.task_type_id}`} className="hover:bg-slate-50/50 transition-colors">
                <td className={cn(
                  'sticky left-0 z-10 px-5 py-2.5 bg-white shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]',
                  multi && 'pl-10'
                )}>
                  <div className="flex items-center gap-3">
                    <div className={cn('w-1 h-6 rounded-full shrink-0', entry.is_billable ? 'bg-primary' : 'bg-slate-200')} />
                    <div>
                      <p className={cn('leading-tight', multi ? 'text-slate-600 font-medium text-sm' : 'font-semibold text-slate-800')}>
                        {multi ? entry.task_type_name : entry.client_name}
                      </p>
                      {!multi && <p className="text-xs text-slate-400 mt-0.5">{entry.task_type_name}</p>}
                    </div>
                  </div>
                </td>
                {days.map(day => {
                  const v = entry.days[day.date] || 0;
                  return (
                    <td key={day.date} className={cn('border-l border-border/20', day.isWeekend ? 'bg-slate-50/40' : '')}>
                      <div className={cn(
                        'px-3 py-2.5 text-right text-sm tabular-nums',
                        v > 0 ? 'text-slate-700 font-medium' : 'text-slate-300'
                      )}>
                        {formatHours(v)}
                      </div>
                    </td>
                  );
                })}
                <td className="border-l border-border/40 bg-slate-50/40">
                  <div className={cn('px-3 py-2.5 text-right text-sm font-bold tabular-nums', entry.total > 0 ? 'text-slate-800' : 'text-slate-300')}>
                    {formatHours(entry.total)}
                  </div>
                </td>
              </tr>
            ))}
          </React.Fragment>
        );
      })}
    </tbody>

    <tfoot className="sticky bottom-0 z-10">
      <tr className="border-t-2 border-border/60 bg-slate-50">
        <td className="sticky left-0 z-20 px-5 py-2.5 text-xs font-bold uppercase tracking-wider text-slate-500 bg-slate-50 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
          Daily Totals
        </td>
        {days.map(day => (
          <td key={day.date} className={cn(
            'text-center px-3 py-2.5 font-bold text-slate-700 tabular-nums border-l border-border/30 text-sm',
            day.isWeekend ? 'bg-slate-100/80' : ''
          )}>
            {formatHours(dailyTotals[day.date] || 0)}
          </td>
        ))}
        <td className="text-center px-4 py-2.5 font-bold text-primary tabular-nums border-l border-border/50 text-sm">
          {formatHours(grandTotal)}
        </td>
      </tr>
    </tfoot>
  </table>
);

export default WeeklyTimesheet;
