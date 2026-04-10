// src/components/WeeklyTimesheet.tsx
// Two-row header: row 1 = title/status/stats/week-nav, row 2 = search/filter

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  ChevronLeft, ChevronRight, Clock, CheckCircle2, Lock,
  AlertTriangle, Info, RefreshCw, Search, X, Filter,
  ChevronDown,
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

interface TimeCellProps {
  value: number;
  onChange?: (val: number) => void;
  disabled?: boolean;
  isTotal?: boolean;
  isWeekend?: boolean;
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
  return monday.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
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

// ── Time Cell ─────────────────────────────────────────────────────────────────

const TimeCell: React.FC<TimeCellProps> = ({ value, onChange, disabled, isTotal, isWeekend }) => {
  const [editing, setEditing] = useState(false);
  const [localValue, setLocalValue] = useState(String(value));

  useEffect(() => { setLocalValue(String(value)); }, [value]);

  const handleBlur = () => {
    setEditing(false);
    const newValue = parseFloat(localValue) || 0;
    if (newValue !== value && onChange) onChange(newValue);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter')  (e.target as HTMLInputElement).blur();
    if (e.key === 'Escape') { setLocalValue(String(value)); setEditing(false); }
  };

  const hasValue = value > 0;

  if (isTotal) {
    return (
      <div className={cn(
        'px-3 py-2.5 text-right text-sm font-bold tabular-nums',
        hasValue ? 'text-slate-800' : 'text-slate-300'
      )}>
        {formatHours(value)}
      </div>
    );
  }

  if (disabled) {
    return (
      <div className={cn(
        'px-3 py-2.5 text-right text-sm tabular-nums',
        isWeekend ? 'bg-slate-50/60' : '',
        hasValue ? 'text-slate-700 font-medium' : 'text-slate-300'
      )}>
        {formatHours(value)}
      </div>
    );
  }

  return editing ? (
    <input
      type="number" step="0.25" min="0" max="24"
      value={localValue}
      onChange={(e) => setLocalValue(e.target.value)}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      className="w-full px-3 py-2.5 text-right text-sm bg-white border-2 border-primary rounded focus:outline-none tabular-nums"
      autoFocus
    />
  ) : (
    <button
      onClick={() => setEditing(true)}
      className={cn(
        'w-full px-3 py-2.5 text-right text-sm tabular-nums transition-colors rounded',
        isWeekend ? 'bg-slate-50/60' : '',
        hasValue
          ? 'text-slate-800 font-medium hover:bg-primary/5'
          : 'text-slate-300 hover:bg-primary/5 hover:text-slate-500'
      )}
    >
      {formatHours(value)}
    </button>
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

// ── Filter types ──────────────────────────────────────────────────────────────

type FilterMode = 'all' | 'has-hours' | 'billable' | 'non-billable';

const filterLabels: Record<FilterMode, string> = {
  'all':          'All clients',
  'has-hours':    'Has hours',
  'billable':     'Billable only',
  'non-billable': 'Non-billable only',
};

// ── Main Component ────────────────────────────────────────────────────────────

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
  const [filterMode, setFilterMode]         = useState<FilterMode>('has-hours');
  const [showFilterMenu, setShowFilterMenu] = useState(false);
  const [collapsed, setCollapsed]           = useState<Set<string>>(new Set());

  const filterMenuRef = useRef<HTMLDivElement>(null);
  const searchRef     = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (filterMenuRef.current && !filterMenuRef.current.contains(e.target as Node))
        setShowFilterMenu(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

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
  useEffect(() => { setSearch(''); }, [weekStart]);

  const goToWeek = (dir: number) => {
    const d = new Date(weekStart + 'T00:00:00');
    d.setDate(d.getDate() + dir * 7);
    setWeekStart(d.toISOString().split('T')[0]);
  };

  const daysUntilSubmit = useMemo(() => {
    if (!timesheetData) return 0;
    return getDaysUntilSubmit(timesheetData.week_start);
  }, [timesheetData]);

  const filteredEntries = useMemo(() => {
    if (!timesheetData?.entries) return [];
    let entries = timesheetData.entries;
    if (search.trim()) {
      const q = search.toLowerCase();
      entries = entries.filter(e =>
        e.client_name.toLowerCase().includes(q) ||
        e.task_type_name.toLowerCase().includes(q)
      );
    }
    if (filterMode === 'has-hours')    entries = entries.filter(e => e.total > 0);
    if (filterMode === 'billable')     entries = entries.filter(e => e.is_billable);
    if (filterMode === 'non-billable') entries = entries.filter(e => !e.is_billable);
    return entries;
  }, [timesheetData?.entries, search, filterMode]);

  const groupedEntries = useMemo(() => {
    const groups: Record<string, TimesheetEntry[]> = {};
    filteredEntries.forEach(e => {
      if (!groups[e.client_name]) groups[e.client_name] = [];
      groups[e.client_name].push(e);
    });
    return groups;
  }, [filteredEntries]);

  const toggleCollapse = (clientName: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      next.has(clientName) ? next.delete(clientName) : next.add(clientName);
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

  const days            = getDayHeaders();
  const isEditable      = ['draft', 'rejected'].includes(timesheetData?.status ?? '');
  const weekHasEnded    = timesheetData ? isWeekEnded(timesheetData.week_start) : false;
  const nonBillable     = (timesheetData?.grand_total ?? 0) - (timesheetData?.billable_total ?? 0);
  const totalClients    = timesheetData?.entries?.length ?? 0;
  const visibleCount    = filteredEntries.length;
  const hasActiveFilter = filterMode !== 'all' || search.trim() !== '';

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2">

      {/* ── ROW 1: Title / Status / Stats / Week nav ───────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 h-14 flex items-center justify-between gap-4 shrink-0">

        {/* Left: title + status */}
        <div className="flex items-center gap-3 shrink-0">
          <h2 className="text-base font-bold text-slate-800">My Timesheet</h2>
          {timesheetData && (
            <StatusBadge
              status={timesheetData.status}
              autoSubmitted={timesheetData.auto_submitted}
            />
          )}
        </div>

        {/* Right: stats + divider + week nav + date range */}
        <div className="flex items-center gap-4">

          {/* Stats */}
          {timesheetData && (
            <div className="flex items-center gap-5 pr-4 border-r border-border/50">
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-primary leading-none">
                  {formatHours(timesheetData.billable_total)}
                </p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Billable</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-slate-400 leading-none">
                  {formatHours(nonBillable)}
                </p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Non-bill</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-slate-700 leading-none">
                  {formatHours(timesheetData.grand_total)}
                </p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Total</p>
              </div>
            </div>
          )}

          {/* Week nav */}
          <div className="flex items-center gap-0.5 bg-muted/60 border border-border/50 rounded-lg overflow-hidden">
            <button onClick={() => goToWeek(-1)} className="px-1.5 py-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted transition-all">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setWeekStart(getMonday(new Date()).toISOString().split('T')[0])}
              className="px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-muted transition-all"
            >
              Today
            </button>
            <button onClick={() => goToWeek(1)} className="px-1.5 py-1.5 text-slate-400 hover:text-slate-700 hover:bg-muted transition-all">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <span className="text-sm font-medium text-slate-600 whitespace-nowrap">
            {timesheetData && formatWeekRange(timesheetData.week_start)}
          </span>
        </div>
      </div>

      {/* ── ROW 2: Search / Filter / Count ────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-4 h-11 flex items-center gap-3 shrink-0">

        {/* Search */}
        <div className="relative w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search clients..."
            className="w-full pl-8 pr-7 py-1.5 text-sm bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
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

        {/* Filter */}
        <div className="relative shrink-0" ref={filterMenuRef}>
          <button
            onClick={() => setShowFilterMenu(v => !v)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all',
              filterMode !== 'all'
                ? 'bg-primary/8 text-primary border-primary/25'
                : 'bg-slate-50 text-slate-600 border-border/50 hover:bg-slate-100'
            )}
          >
            <Filter className="w-3.5 h-3.5" />
            {filterLabels[filterMode]}
            <ChevronDown className="w-3 h-3" />
          </button>
          {showFilterMenu && (
            <div className="absolute top-full mt-1 left-0 bg-white rounded-xl border border-border/60 shadow-lg z-20 py-1 min-w-[180px]">
              {(Object.entries(filterLabels) as [FilterMode, string][]).map(([mode, label]) => (
                <button
                  key={mode}
                  onClick={() => { setFilterMode(mode); setShowFilterMenu(false); }}
                  className={cn(
                    'w-full text-left px-4 py-2 text-sm transition-colors',
                    filterMode === mode
                      ? 'text-primary font-semibold bg-primary/5'
                      : 'text-slate-600 hover:bg-slate-50'
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Count + clear */}
        <span className="text-xs text-slate-400 ml-1">
          {visibleCount === totalClients
            ? `${totalClients} client${totalClients !== 1 ? 's' : ''}`
            : <><span className="font-semibold text-slate-600">{visibleCount}</span> of {totalClients}</>
          }
          {hasActiveFilter && visibleCount < totalClients && (
            <button
              onClick={() => { setSearch(''); setFilterMode('all'); }}
              className="ml-2 text-primary hover:underline font-medium"
            >
              Clear
            </button>
          )}
        </span>

        {/* Status hint — right side of filter bar */}
        <div className="ml-auto">
          {timesheetData?.status === 'draft' && !weekHasEnded && (
            <span className="flex items-center gap-1.5 text-xs text-slate-400">
              <Info className="w-3.5 h-3.5 text-primary/60" />
              Submit available <span className="font-medium text-slate-600">{getCanSubmitDate(timesheetData.week_start)}</span>
            </span>
          )}
          {timesheetData?.status === 'submitted' && (
            <span className="flex items-center gap-1.5 text-xs text-amber-600 font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              Awaiting manager approval
            </span>
          )}
          {timesheetData?.status === 'approved' && (
            <span className="flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
              <CheckCircle2 className="w-3.5 h-3.5" /> Approved
            </span>
          )}
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

      {/* ── Grid ──────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-sm" style={{ minWidth: 720 }}>

            {/* Sticky col headers */}
            <thead className="sticky top-0 z-20">
              <tr className="border-b border-border/60 bg-white">
                <th className="sticky left-0 z-20 text-left px-5 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 min-w-[220px] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  Client / Task
                </th>
                {days.map((day) => (
                  <th
                    key={day.date}
                    className={cn(
                      'text-center px-2 py-3 font-semibold min-w-[72px]',
                      day.isWeekend ? 'bg-slate-50/80 text-slate-400' : 'bg-slate-50 text-slate-600',
                    )}
                  >
                    <div className="text-[10px] uppercase tracking-wider font-semibold">{day.label}</div>
                    <div className={cn(
                      'text-lg font-bold mt-0.5 w-8 h-8 flex items-center justify-center rounded-full mx-auto',
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
              {filteredEntries.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-16 text-slate-400">
                    {search || filterMode !== 'all' ? (
                      <>
                        <Search className="w-8 h-8 text-slate-200 mx-auto mb-3" />
                        <p className="font-medium text-slate-500">No clients match your filter</p>
                        <button
                          onClick={() => { setSearch(''); setFilterMode('all'); }}
                          className="mt-2 text-sm text-primary hover:underline"
                        >
                          Clear filters
                        </button>
                      </>
                    ) : (
                      <>
                        <Clock className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                        <p className="font-medium text-slate-500">No time entries for this week</p>
                        <p className="text-sm mt-1">Time will appear here as it's tracked by your desktop agent</p>
                      </>
                    )}
                  </td>
                </tr>
              ) : (
                Object.entries(groupedEntries).map(([clientName, clientEntries]) => {
                  const isCollapsed = collapsed.has(clientName);
                  const clientTotal = clientEntries.reduce((s, e) => s + e.total, 0);
                  const hasMultiple = clientEntries.length > 1;

                  return (
                    <React.Fragment key={clientName}>
                      {hasMultiple && (
                        <tr
                          className="bg-slate-50/70 cursor-pointer hover:bg-slate-100/80 transition-colors"
                          onClick={() => toggleCollapse(clientName)}
                        >
                          <td className="sticky left-0 z-10 px-5 py-2 bg-slate-50/90 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                            <div className="flex items-center gap-2">
                              {isCollapsed
                                ? <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                                : <ChevronDown  className="w-3.5 h-3.5 text-slate-400" />
                              }
                              <span className="font-semibold text-slate-700 text-xs">{clientName}</span>
                              <span className="text-[10px] text-slate-400">{clientEntries.length} tasks</span>
                            </div>
                          </td>
                          {days.map(day => {
                            const dayTotal = clientEntries.reduce((s, e) => s + (e.days[day.date] || 0), 0);
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
                          <td className={cn('text-right px-3 py-2 text-xs tabular-nums font-bold', clientTotal > 0 ? 'text-slate-700' : 'text-slate-200')}>
                            {formatHours(clientTotal)}
                          </td>
                        </tr>
                      )}

                      {!isCollapsed && clientEntries.map((entry) => (
                        <tr
                          key={`${entry.client_id}-${entry.task_type_id}`}
                          className="hover:bg-slate-50/50 transition-colors"
                        >
                          <td className={cn(
                            'sticky left-0 z-10 px-5 py-2.5 bg-white shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]',
                            hasMultiple && 'pl-10'
                          )}>
                            <div className="flex items-center gap-3">
                              <div className={cn('w-1 h-6 rounded-full shrink-0', entry.is_billable ? 'bg-primary' : 'bg-slate-200')} />
                              <div>
                                <p className={cn('leading-tight', hasMultiple ? 'text-slate-600 font-medium text-sm' : 'font-semibold text-slate-800')}>
                                  {hasMultiple ? entry.task_type_name : entry.client_name}
                                </p>
                                {!hasMultiple && <p className="text-xs text-slate-400 mt-0.5">{entry.task_type_name}</p>}
                              </div>
                            </div>
                          </td>
                          {days.map((day) => (
                            <td key={day.date} className={cn('border-l border-border/20', day.isWeekend ? 'bg-slate-50/40' : '')}>
                              <TimeCell
                                value={entry.days[day.date] || 0}
                                onChange={(val) => console.log('Update', entry.client_id, day.date, val)}
                                disabled={!isEditable}
                                isWeekend={day.isWeekend}
                              />
                            </td>
                          ))}
                          <td className="border-l border-border/40 bg-slate-50/40">
                            <TimeCell value={entry.total} isTotal />
                          </td>
                        </tr>
                      ))}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>

            {/* Sticky footer */}
            <tfoot className="sticky bottom-0 z-10">
              <tr className="border-t-2 border-border/60 bg-slate-50">
                <td className="sticky left-0 z-20 px-5 py-2.5 text-xs font-bold uppercase tracking-wider text-slate-500 bg-slate-50 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  Daily Totals
                </td>
                {days.map((day) => (
                  <td key={day.date} className={cn(
                    'text-center px-3 py-2.5 font-bold text-slate-700 tabular-nums border-l border-border/30 text-sm',
                    day.isWeekend ? 'bg-slate-100/80' : ''
                  )}>
                    {formatHours(timesheetData?.daily_totals?.[day.date] || 0)}
                  </td>
                ))}
                <td className="text-center px-4 py-2.5 font-bold text-primary tabular-nums border-l border-border/50 text-sm">
                  {formatHours(timesheetData?.grand_total || 0)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Footer actions */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between bg-slate-50/40 shrink-0">
          <p className="text-xs text-slate-400 flex items-center gap-1.5">
            {isEditable
              ? <><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" /> Click any cell to edit</>
              : <><span className="w-1.5 h-1.5 rounded-full bg-slate-300 inline-block" /> Locked for editing</>
            }
          </p>

          <div className="flex items-center gap-2">
            {timesheetData?.status === 'draft' && (
              weekHasEnded ? (
                <button
                  onClick={() => setShowSubmitModal(true)}
                  className="px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all flex items-center gap-1.5"
                >
                  <CheckCircle2 className="w-4 h-4" /> Submit for Approval
                </button>
              ) : (
                <button disabled className="px-4 py-2 bg-slate-100 text-slate-400 text-sm font-semibold rounded-lg cursor-not-allowed flex items-center gap-1.5">
                  <Clock className="w-4 h-4" /> Submit in {daysUntilSubmit} day{daysUntilSubmit !== 1 ? 's' : ''}
                </button>
              )
            )}
            {timesheetData?.status === 'rejected' && (
              <>
                <button onClick={handleReopen} className="px-4 py-2 bg-slate-100 text-slate-700 text-sm font-semibold rounded-lg hover:bg-slate-200 transition-all">
                  Edit
                </button>
                <button onClick={() => setShowSubmitModal(true)} className="px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all">
                  Resubmit
                </button>
              </>
            )}
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
                  { label: 'Total',    value: formatHours(timesheetData?.grand_total    || 0), cls: 'text-slate-800' },
                  { label: 'Billable', value: formatHours(timesheetData?.billable_total || 0), cls: 'text-primary' },
                  { label: 'Non-bill', value: formatHours(nonBillable),                         cls: 'text-slate-400' },
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

export default WeeklyTimesheet;