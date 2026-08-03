// src/components/WeeklyTimesheet.tsx
// Read-only weekly timesheet, styled to match the refreshed Daily Review "Lightning"
// look (faint teal ground, quiet dotted rows, billable/non-billable badges).
// "Summary" drills client → category; "By day" drills day → client → category.
// Time is auto-captured by the desktop agent, so cells are not editable here —
// adjustments happen in Daily Review.

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  ChevronLeft, ChevronRight, ChevronDown, Clock, CheckCircle2, Lock,
  AlertTriangle, Info, RefreshCw, Search, X, Layers, CalendarDays, Sparkles, Copy,
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

// One captured block from the timesheet-detail timeline (block-level drill).
interface DetailBlock {
  id: number;
  started_at: string | null;
  ended_at: string | null;
  duration_minutes: number;
  client_name: string | null;
  task_type_name: string | null;
  is_billable: boolean;
  window_title: string | null;
  application: string | null;
  taxpayer_name: string | null;
}

interface TimesheetDetail {
  timesheet_id: number;
  days: { date: string; blocks: DetailBlock[]; total_minutes: number }[];
}

// Index blocks by client + category (and by day) so a category row can list its
// captured blocks. Detail blocks carry names (no ids), so we join on the same
// fallbacks the weekly grid uses: null client → "Unassigned", null task → "General".
const blockClientKey = (name: string | null) => name || 'Unassigned';
const blockCatKey    = (name: string | null) => name || 'General';
const wKey = (clientName: string, taskName: string) => `${clientName}||${taskName}`;
const dKey = (date: string, clientName: string, taskName: string) => `${date}||${clientName}||${taskName}`;

// A friendly one-line label for a captured block.
const blockLabel = (b: DetailBlock): string =>
  (b.window_title || b.application || b.taxpayer_name || b.task_type_name || 'Captured activity').trim();

const formatClock = (iso: string | null): string => {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
};

// Week-view block rows span days, so lead with a weekday; day view uses the clock.
const formatBlockWhen = (iso: string | null, withDay: boolean): string => {
  if (!iso) return '';
  const d = new Date(iso);
  const t = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(/\s/g, '').toLowerCase();
  return withDay ? `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${t}` : formatClock(iso);
};

const formatMinutes = (m: number): string => {
  if (!m) return '—';
  const h = Math.floor(m / 60);
  const min = m % 60;
  if (h === 0) return `${min}m`;
  if (min === 0) return `${h}h`;
  return `${h}h ${min}m`;
};

// A client aggregated across all its task rows for the Summary view.
interface ClientAgg {
  key: string;
  clientId: number | null;
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

// The unassigned bucket ("No client") always sorts to the bottom of the list.
const isNoClient = (agg: Pick<ClientAgg, 'clientId'>) => agg.clientId == null;
const displayClientName = (agg: Pick<ClientAgg, 'clientId' | 'clientName'>) =>
  isNoClient(agg) ? 'No client' : agg.clientName;

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

// ── Design language (shared by Summary + By-day drills) ─────────────────────────
// Faint teal ground + quiet dotted rows + calm billable/non-billable badges,
// matching the refreshed Daily Review "Lightning" look.
const GROUND      = '#eef4f3';                         // faint teal canvas
const DOT_BILL    = 'w-2 h-2 rounded-full bg-primary shrink-0';
const DOT_NON     = 'w-2 h-2 rounded-full bg-slate-300 shrink-0';
const BADGE_BILL  = 'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide bg-primary/10 text-primary';
const BADGE_NON   = 'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide bg-slate-100 text-slate-500';
const HOURS_CELL  = 'text-right text-[13px] font-bold text-slate-800 tabular-nums shrink-0 w-[64px]';

const Badge: React.FC<{ billable: boolean }> = ({ billable }) => (
  <span className={billable ? BADGE_BILL : BADGE_NON}>{billable ? 'Billable' : 'Non-billable'}</span>
);

// ── Main Component ────────────────────────────────────────────────────────────

type ViewMode = 'summary' | 'byday' | 'work_summary';

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
  const [detail, setDetail]                 = useState<TimesheetDetail | null>(null);
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
      // Block-level detail powers the category → block drill. Best-effort:
      // if it fails, the page still works (categories just don't expand).
      setDetail(null);
      if (data?.timesheet_id) {
        safeFetchJson<TimesheetDetail>(
          `${API_BASE}/billing/timesheets/${data.timesheet_id}/detail/`
        ).then(setDetail).catch(() => setDetail(null));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load timesheet');
    } finally {
      setLoading(false);
    }
  }, [weekStart]);

  // Index detail blocks by client+category (week) and day+client+category.
  const { weekBlocks, dayBlocks } = useMemo(() => {
    const week = new Map<string, DetailBlock[]>();
    const day  = new Map<string, DetailBlock[]>();
    const push = (m: Map<string, DetailBlock[]>, k: string, b: DetailBlock) => {
      const arr = m.get(k);
      if (arr) arr.push(b); else m.set(k, [b]);
    };
    for (const d of detail?.days ?? []) {
      for (const b of d.blocks) {
        if (!b.duration_minutes) continue;
        const ck = blockClientKey(b.client_name);
        const tk = blockCatKey(b.task_type_name);
        push(week, wKey(ck, tk), b);
        push(day, dKey(d.date, ck, tk), b);
      }
    }
    return { weekBlocks: week, dayBlocks: day };
  }, [detail]);

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
          key, clientId: e.client_id, clientName: e.client_name, total: 0, billable: 0, nonBillable: 0,
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
    // Rank by time, but the "No client" bucket always sinks to the bottom.
    return list.sort((a, b) => {
      const au = isNoClient(a) ? 1 : 0;
      const bu = isNoClient(b) ? 1 : 0;
      if (au !== bu) return au - bu;
      return b.total - a.total;
    });
  }, [searchedEntries]);

  const { mainClients, tailClients } = useMemo(() => {
    const main = clients.filter(c => c.total >= TAIL_THRESHOLD_HOURS);
    const tail = clients.filter(c => c.total < TAIL_THRESHOLD_HOURS);
    return { mainClients: main, tailClients: tail };
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
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2.5 bg-[#eef4f3] p-2.5 rounded-2xl">

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

      {/* ── Hero: week total + billable split (Lightning look) ─────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 py-4 shrink-0">
        <div className="flex items-baseline justify-between gap-4">
          <div className="flex items-baseline gap-2.5 min-w-0">
            <span className="text-[26px] font-extrabold tracking-tight text-slate-900 leading-none tabular-nums">
              {formatHours(grandTotal)}
            </span>
            <span className="text-[13px] font-semibold text-slate-500 truncate">
              tracked this week · <b className="text-primary tabular-nums">{billablePctLabel}%</b> billable
            </span>
          </div>
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 shrink-0">
            {totalClients} client{totalClients !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="mt-2.5 h-2.5 rounded-full bg-slate-100 overflow-hidden flex">
          <div className="h-full bg-gradient-to-r from-primary to-accent" style={{ width: `${pct(billable, grandTotal)}%` }} />
          <div className="h-full bg-slate-300" style={{ width: `${pct(nonBillable, grandTotal)}%` }} />
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-1 mt-2">
          <span className="flex items-center gap-2 text-xs text-slate-500">
            <span className="w-2.5 h-2.5 rounded-sm bg-gradient-to-r from-primary to-accent inline-block" />
            <b className="text-slate-700 font-bold tabular-nums">{formatHours(billable)}</b> billable
          </span>
          <span className="flex items-center gap-2 text-xs text-slate-500">
            <span className="w-2.5 h-2.5 rounded-sm bg-slate-300 inline-block" />
            <b className="text-slate-700 font-bold tabular-nums">{formatHours(nonBillable)}</b> non-billable
          </span>
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
              { id: 'work_summary', label: 'Work summary', icon: Sparkles },
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
              expanded={expanded}
              tailOpen={tailOpen}
              onToggle={toggleExpand}
              onToggleTail={() => setTailOpen(o => !o)}
              weekBlocks={weekBlocks}
            />
          ) : view === 'byday' ? (
            <ByDayView clients={clients} days={days} dailyTotals={timesheetData?.daily_totals ?? {}} grandTotal={grandTotal} dayBlocks={dayBlocks} />
          ) : (
            <WorkSummaryView clients={clients} weekEnd={timesheetData?.week_end ?? weekStart} weekLabel={formatWeekRange(weekStart)} />
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

// One captured block, listed under its category (read-only drill).
const BlockRow: React.FC<{ block: DetailBlock; withDay: boolean }> = ({ block, withDay }) => (
  <div className="flex items-center gap-2.5 pl-[76px] pr-5 py-1.5 min-w-0">
    <span className="text-[11px] text-slate-400 tabular-nums shrink-0 w-[72px] whitespace-nowrap">{formatBlockWhen(block.started_at, withDay)}</span>
    <span className="flex-1 text-[12px] text-slate-500 truncate">{blockLabel(block)}</span>
    <span className="text-[12px] text-slate-400 tabular-nums shrink-0 w-[52px] text-right">{formatMinutes(block.duration_minutes)}</span>
  </div>
);

// A single billable/non-billable category row inside a client (or a day→client).
// `hours` lets callers pass a day-scoped subtotal; defaults to the week total.
// `blocks` (when present) makes the row expand to its captured blocks.
const CategoryRow: React.FC<{ entry: TimesheetEntry; hours?: number; blocks?: DetailBlock[] | undefined; blocksWithDay?: boolean }> = ({ entry, hours, blocks, blocksWithDay = false }) => {
  const [open, setOpen] = useState(false);
  const hasBlocks = !!blocks && blocks.length > 0;
  return (
    <>
      <div
        role={hasBlocks ? 'button' : undefined}
        onClick={hasBlocks ? () => setOpen(o => !o) : undefined}
        className={cn('flex items-center gap-3 pl-[52px] pr-5 py-2 min-w-0', hasBlocks && 'cursor-pointer hover:bg-black/[0.02]')}
      >
        {hasBlocks
          ? <ChevronRight className={cn('w-3 h-3 text-slate-300 shrink-0 -ml-[18px] transition-transform', open && 'rotate-90')} />
          : <span className="w-3 shrink-0 -ml-[18px]" />}
        <span className={entry.is_billable ? DOT_BILL : DOT_NON} />
        <span className="flex-1 text-[13px] text-slate-600 truncate">{entry.task_type_name}</span>
        {hasBlocks && <span className="text-[10px] text-slate-300 tabular-nums shrink-0 hidden sm:inline">{blocks!.length}</span>}
        <Badge billable={entry.is_billable} />
        <span className={HOURS_CELL}>{formatHours(hours ?? entry.total)}</span>
      </div>
      {hasBlocks && open && (
        <div className="border-t border-black/[0.04]">
          {blocks!.map(b => <BlockRow key={b.id} block={b} withDay={blocksWithDay} />)}
        </div>
      )}
    </>
  );
};

const ClientRow: React.FC<{
  agg: ClientAgg;
  isExpanded: boolean;
  onToggle: (key: string) => void;
  weekBlocks: Map<string, DetailBlock[]>;
}> = ({ agg, isExpanded, onToggle, weekBlocks }) => {
  const noClient = isNoClient(agg);
  return (
    <>
      <button
        onClick={() => onToggle(agg.key)}
        className="w-full flex items-center gap-3 px-5 py-3 text-left hover:bg-black/[0.02] transition-colors"
      >
        <ChevronRight className={cn('w-3.5 h-3.5 text-slate-300 shrink-0 transition-transform', isExpanded && 'rotate-90')} />
        <ClientDot agg={agg} />
        <span className={cn('flex-1 text-sm font-bold truncate leading-tight',
          noClient ? 'italic text-slate-400 font-semibold' : 'text-slate-800')}>
          {displayClientName(agg)}
        </span>
        <span className="text-[11px] text-slate-400 tabular-nums shrink-0 hidden sm:inline">
          {agg.taskCount} categor{agg.taskCount !== 1 ? 'ies' : 'y'}
        </span>
        <span className="text-right text-[15px] font-extrabold text-slate-800 tabular-nums shrink-0 w-[64px]">
          {formatHours(agg.total)}
        </span>
      </button>

      {isExpanded && (
        <div className="border-t border-border/20" style={{ background: GROUND }}>
          {agg.entries.map(e => (
            <CategoryRow
              key={`${e.client_id}-${e.task_type_id}`}
              entry={e}
              blocks={weekBlocks.get(wKey(blockClientKey(e.client_name), blockCatKey(e.task_type_name)))}
              blocksWithDay
            />
          ))}
        </div>
      )}
    </>
  );
};

// ── Work summary: an AI-drafted, client-ready narrative of the week's work ──────
// Opt-in, read-only. Reuses GET /api/clients/<id>/work-summary/ scoped to this
// timesheet week (date=week_end, days=7) — a draft to review before it becomes a
// submission note or an invoice narrative. Never touches time or billing.
const isInternalName = (name: string) => {
  const n = (name || '').trim().toLowerCase();
  return n === 'internal' || n.startsWith('internal -');
};

type SummaryCell = { loading: boolean; text?: string; empty?: boolean; error?: boolean };

const WorkSummaryView: React.FC<{
  clients: ClientAgg[];
  weekEnd: string;
  weekLabel: string;
}> = ({ clients, weekEnd, weekLabel }) => {
  const [state, setState] = useState<Record<string, SummaryCell>>({});
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Real, billable-to clients only — skip Unassigned (null) and internal buckets.
  const real = useMemo(
    () => clients.filter(c => (c.entries[0]?.client_id ?? null) != null && !isInternalName(c.clientName)),
    [clients]
  );

  const gen = useCallback(async (key: string, clientId: number) => {
    setState(p => ({ ...p, [key]: { loading: true } }));
    try {
      const d = await safeFetchJson<{ summary: string; empty?: boolean; message?: string }>(
        `${API_BASE}/clients/${clientId}/work-summary/?date=${weekEnd}&days=7`
      );
      const cell: SummaryCell = d.empty
        ? { loading: false, empty: true, ...(d.message ? { text: d.message } : {}) }
        : { loading: false, text: d.summary || '' };
      setState(p => ({ ...p, [key]: cell }));
    } catch {
      setState(p => ({ ...p, [key]: { loading: false, error: true } }));
    }
  }, [weekEnd]);

  const genAll = () => {
    real.forEach(c => {
      const id = c.entries[0]?.client_id;
      if (id != null && !state[c.key]?.text && !state[c.key]?.loading) gen(c.key, id);
    });
  };

  const anyBusy = real.some(c => state[c.key]?.loading);
  const anyDone = real.some(c => state[c.key]?.text);

  const copy = (key: string, text: string) => {
    try {
      navigator.clipboard?.writeText(text);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(k => (k === key ? null : k)), 1500);
    } catch { /* noop */ }
  };
  const copyAll = () => {
    const parts = real
      .map(c => (state[c.key]?.text ? `${c.clientName}\n${state[c.key]!.text}` : null))
      .filter((x): x is string => !!x);
    if (parts.length) copy('__all__', parts.join('\n\n'));
  };

  if (!real.length) {
    return (
      <div className="text-center py-20 text-slate-400">
        <Sparkles className="w-10 h-10 text-slate-200 mx-auto mb-3" />
        <p className="font-medium text-slate-500">No client work to summarize this week</p>
        <p className="text-sm mt-1">Summaries cover billable client time — not unassigned or internal work.</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
          <Sparkles className="w-3.5 h-3.5 text-primary" /> Work summary · {weekLabel}
        </div>
        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">AI draft — review before sending</span>
        <span className="flex-1" />
        <button onClick={genAll} disabled={anyBusy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/15 disabled:opacity-40">
          <Sparkles className="w-3.5 h-3.5" /> {anyBusy ? 'Generating…' : 'Generate all'}
        </button>
        {anyDone && (
          <button onClick={copyAll}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">
            <Copy className="w-3.5 h-3.5" /> {copiedKey === '__all__' ? 'Copied' : 'Copy all'}
          </button>
        )}
      </div>

      <div className="flex flex-col gap-2">
        {real.map(c => {
          const id = c.entries[0]?.client_id as number;
          const s = state[c.key];
          const idle = !s || (!s.loading && !s.text && !s.error && !s.empty);
          return (
            <div key={c.key} className="rounded-xl border border-border bg-white p-3">
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-800">{c.clientName}</span>
                <span className="text-xs tabular-nums text-slate-400">{formatHours(c.total)}</span>
                <span className="flex-1" />
                {idle ? (
                  <button onClick={() => gen(c.key, id)}
                    className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-2.5 py-1 text-[11px] font-semibold text-primary hover:bg-primary/15">
                    <Sparkles className="w-3 h-3" /> Generate
                  </button>
                ) : s?.text ? (
                  <div className="flex items-center gap-2">
                    <button onClick={() => copy(c.key, s.text!)} className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline">
                      <Copy className="w-3 h-3" /> {copiedKey === c.key ? 'Copied' : 'Copy'}
                    </button>
                    <button onClick={() => gen(c.key, id)} className="text-[11px] font-medium text-slate-400 hover:text-slate-600">Regenerate</button>
                  </div>
                ) : null}
              </div>
              {s?.loading ? (
                <div className="text-[12px] text-slate-400">Writing a summary…</div>
              ) : s?.error ? (
                <div className="text-[12px] text-slate-500">Couldn’t generate. <button onClick={() => gen(c.key, id)} className="font-medium text-primary hover:underline">Try again</button></div>
              ) : s?.empty ? (
                <div className="text-[12px] text-slate-400">{s.text}</div>
              ) : s?.text ? (
                <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-slate-700">{s.text}</div>
              ) : (
                <div className="text-[12px] text-slate-400">Click Generate for a client-ready summary of this week’s work.</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const SummaryView: React.FC<{
  mainClients: ClientAgg[];
  tailClients: ClientAgg[];
  tailTotals: { billable: number; nonBillable: number; total: number };
  expanded: Set<string>;
  tailOpen: boolean;
  onToggle: (key: string) => void;
  onToggleTail: () => void;
  weekBlocks: Map<string, DetailBlock[]>;
}> = ({ mainClients, tailClients, tailTotals, expanded, tailOpen, onToggle, onToggleTail, weekBlocks }) => (
  <div className="divide-y divide-border/30">
    {mainClients.map(agg => (
      <ClientRow key={agg.key} agg={agg} isExpanded={expanded.has(agg.key)} onToggle={onToggle} weekBlocks={weekBlocks} />
    ))}

    {tailClients.length > 0 && (
      <>
        <button
          onClick={onToggleTail}
          className="w-full flex items-center gap-3 px-5 py-2.5 text-left hover:bg-black/[0.02] transition-colors"
        >
          <ChevronDown className={cn('w-3.5 h-3.5 text-slate-300 shrink-0 transition-transform', tailOpen && 'rotate-180')} />
          <span className="w-2 h-2 rounded-full bg-slate-200 shrink-0" />
          <span className="flex-1 text-[13px] font-semibold text-slate-500 truncate">
            {tailClients.length} more client{tailClients.length !== 1 ? 's' : ''} under 15 min
          </span>
          <span className="text-right text-[13px] font-bold text-slate-500 tabular-nums shrink-0 w-[64px]">{formatHours(tailTotals.total)}</span>
        </button>

        {tailOpen && tailClients.map(agg => (
          <ClientRow key={agg.key} agg={agg} isExpanded={expanded.has(agg.key)} onToggle={onToggle} weekBlocks={weekBlocks} />
        ))}
      </>
    )}
  </div>
);

// ── By-day View (day → client → category drill, mirrors Summary) ────────────────

type DayClient = { agg: ClientAgg; dayTotal: number; entries: TimesheetEntry[] };
type DayGroup  = { day: DayHeader; total: number; clients: DayClient[] };

const ByDayClientRow: React.FC<{
  dc: DayClient;
  date: string;
  isOpen: boolean;
  onToggle: (id: string) => void;
  dayBlocks: Map<string, DetailBlock[]>;
}> = ({ dc, date, isOpen, onToggle, dayBlocks }) => {
  const { agg } = dc;
  const noClient = isNoClient(agg);
  const id = `${date}::${agg.key}`;
  return (
    <>
      <button
        onClick={() => onToggle(id)}
        className="w-full flex items-center gap-3 pl-9 pr-5 py-2.5 text-left hover:bg-black/[0.02] transition-colors"
      >
        <ChevronRight className={cn('w-3.5 h-3.5 text-slate-300 shrink-0 transition-transform', isOpen && 'rotate-90')} />
        <ClientDot agg={agg} />
        <span className={cn('flex-1 text-[13px] font-bold truncate leading-tight',
          noClient ? 'italic text-slate-400 font-semibold' : 'text-slate-800')}>
          {displayClientName(agg)}
        </span>
        <span className={HOURS_CELL}>{formatHours(dc.dayTotal)}</span>
      </button>
      {isOpen && (
        <div style={{ background: GROUND }}>
          {dc.entries.map(e => (
            <CategoryRow
              key={`${e.client_id}-${e.task_type_id}`}
              entry={e}
              hours={e.days[date] || 0}
              blocks={dayBlocks.get(dKey(date, blockClientKey(e.client_name), blockCatKey(e.task_type_name)))}
            />
          ))}
        </div>
      )}
    </>
  );
};

const ByDayView: React.FC<{
  clients: ClientAgg[];
  days: DayHeader[];
  dailyTotals: Record<string, number>;
  grandTotal: number;
  dayBlocks: Map<string, DetailBlock[]>;
}> = ({ clients, days, dailyTotals, grandTotal, dayBlocks }) => {
  // One group per day that had time; clients ranked by that day's minutes, No client last.
  const groups = useMemo<DayGroup[]>(() =>
    days.map(day => {
      const dayClients: DayClient[] = clients
        .map(agg => {
          const entries = agg.entries.filter(e => (e.days[day.date] || 0) > 0);
          const dayTotal = entries.reduce((s, e) => s + (e.days[day.date] || 0), 0);
          return { agg, dayTotal, entries };
        })
        .filter(c => c.dayTotal > 0)
        .sort((a, b) => {
          const au = isNoClient(a.agg) ? 1 : 0;
          const bu = isNoClient(b.agg) ? 1 : 0;
          if (au !== bu) return au - bu;
          return b.dayTotal - a.dayTotal;
        });
      return { day, clients: dayClients, total: dailyTotals[day.date] || dayClients.reduce((s, c) => s + c.dayTotal, 0) };
    }).filter(g => g.clients.length > 0),
  [clients, days, dailyTotals]);

  // Days open by default (a day is open unless collapsed); clients closed by default.
  const [closedDays, setClosedDays]   = useState<Set<string>>(new Set());
  const [openClients, setOpenClients] = useState<Set<string>>(new Set());
  const toggleDay    = (d: string) => setClosedDays(p => { const n = new Set(p); n.has(d) ? n.delete(d) : n.add(d); return n; });
  const toggleClient = (id: string) => setOpenClients(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });

  if (!groups.length) {
    return (
      <div className="text-center py-20 text-slate-400">
        <CalendarDays className="w-10 h-10 text-slate-200 mx-auto mb-3" />
        <p className="font-medium text-slate-500">No time tracked on any day this week</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/40">
      {groups.map(({ day, total, clients: dayClients }) => {
        const dayOpen = !closedDays.has(day.date);
        return (
          <div key={day.date}>
            <button
              onClick={() => toggleDay(day.date)}
              className={cn('w-full flex items-center gap-3 px-5 py-2.5 text-left transition-colors',
                day.isWeekend ? 'bg-slate-50/40' : '', 'hover:bg-black/[0.02]')}
            >
              <ChevronDown className={cn('w-3.5 h-3.5 text-slate-400 shrink-0 transition-transform', !dayOpen && '-rotate-90')} />
              <span className={cn('text-[10px] font-bold uppercase tracking-widest shrink-0 w-9',
                day.isToday ? 'text-primary' : 'text-slate-400')}>
                {day.label}
              </span>
              <span className={cn('text-sm font-bold shrink-0 tabular-nums',
                day.isToday ? 'text-primary' : 'text-slate-700')}>
                {day.dayNum}
              </span>
              {day.isToday && <span className="text-[10px] font-bold text-primary">Today</span>}
              <span className="flex-1" />
              <span className="text-[11px] text-slate-400 tabular-nums shrink-0 hidden sm:inline">
                {dayClients.length} client{dayClients.length !== 1 ? 's' : ''}
              </span>
              <span className="text-right text-[15px] font-extrabold text-slate-800 tabular-nums shrink-0 w-[64px]">
                {formatHours(total)}
              </span>
            </button>
            {dayOpen && (
              <div className="divide-y divide-border/20 border-t border-border/20">
                {dayClients.map(dc => (
                  <ByDayClientRow
                    key={dc.agg.key}
                    dc={dc}
                    date={day.date}
                    isOpen={openClients.has(`${day.date}::${dc.agg.key}`)}
                    onToggle={toggleClient}
                    dayBlocks={dayBlocks}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      <div className="flex items-center gap-3 px-5 py-3 bg-white border-t-2 border-border/50">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Week total</span>
        <span className="flex-1" />
        <span className="text-right text-[15px] font-extrabold text-primary tabular-nums w-[64px]">{formatHours(grandTotal)}</span>
      </div>
    </div>
  );
};

export default WeeklyTimesheet;
