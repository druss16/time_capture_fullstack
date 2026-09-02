// src/components/TimesheetDetailDrawer.tsx
// Slide-in drawer for manager timesheet review — week grid + daily block timeline

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  X, CheckCircle2, XCircle, RefreshCw, AlertTriangle,
  Clock, ChevronDown, ChevronRight, Monitor, Cpu, Tag,
  Calendar, DollarSign, Info, Sparkles,
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

interface Block {
  id: number;
  started_at: string;
  ended_at: string;
  duration_minutes: number;
  client_name: string | null;
  task_type_name: string | null;
  is_billable: boolean;
  window_title: string | null;
  application: string | null;
  classification_source: 'manual' | 'ai' | 'rule' | 'idle' | null;
  ai_confidence: number | null;
  taxpayer_name: string | null;
}

interface DayBlocks {
  date: string;
  blocks: Block[];
  total_minutes: number;
}

interface TimesheetDetail {
  timesheet_id: number;
  user_name: string;
  user_email: string;
  week_start: string;
  week_end: string;
  status: string;
  auto_submitted?: boolean;
  submitted_at: string | null;
  submitted_notes: string;
  rejection_reason?: string;
  entries: TimesheetEntry[];
  daily_totals: Record<string, number>;
  grand_total: number;
  billable_total: number;
  days: DayBlocks[];
}

interface Props {
  timesheetId: number | null;
  onClose: () => void;
  // May be sync: the approvals queue hides the row and fires the request without
  // waiting, so this returns immediately. `await` below handles both.
  onApprove: (id: number) => void | Promise<void>;
  onReject:  (id: number, reason: string) => void | Promise<void>;
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

const formatMins = (mins: number): string => {
  if (mins === 0) return '—';
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
};

const formatCurrency = (amount: number): string =>
  amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

const formatWeekRange = (weekStart: string, weekEnd: string): string => {
  const s = new Date(weekStart + 'T00:00:00');
  const e = new Date(weekEnd   + 'T00:00:00');
  return `${s.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${e.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
};

const formatTime = (iso: string): string => {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
};

const formatDayHeader = (date: string): { weekday: string; dayNum: number; isToday: boolean; isWeekend: boolean } => {
  const d = new Date(date + 'T00:00:00');
  const today = new Date().toISOString().split('T')[0];
  const dow = d.getDay();
  return {
    weekday: d.toLocaleDateString('en-US', { weekday: 'short' }),
    dayNum: d.getDate(),
    isToday: date === today,
    isWeekend: dow === 0 || dow === 6,
  };
};

const AVATAR_COLORS = [
  'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500',
  'bg-violet-500', 'bg-cyan-500', 'bg-orange-500', 'bg-indigo-500',
];

// ── Sub-components ────────────────────────────────────────────────────────────

const Avatar: React.FC<{ name: string; size?: 'sm' | 'md' }> = ({ name, size = 'md' }) => {
  const initials = name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  const colorCls = AVATAR_COLORS[name.length % AVATAR_COLORS.length];
  return (
    <div className={cn(
      'rounded-full flex items-center justify-center text-white font-bold shrink-0',
      colorCls,
      size === 'sm' ? 'w-7 h-7 text-xs' : 'w-9 h-9 text-sm'
    )}>
      {initials}
    </div>
  );
};

// Confidence pill
const ConfidencePill: React.FC<{ source: Block['classification_source']; confidence: number | null }> = ({ source, confidence }) => {
  if (source === 'idle') return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-400">
      Idle
    </span>
  );
  if (source === 'manual') return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-500">
      Manual
    </span>
  );
  if (source === 'rule') return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-primary/8 text-primary/70">
      <Tag className="w-2.5 h-2.5" /> Rule
    </span>
  );
  if (source === 'ai' && confidence !== null) {
    const pct = Math.round(confidence * 100);
    const cls = pct >= 88
      ? 'bg-emerald-50 text-emerald-700'
      : pct >= 65
        ? 'bg-amber-50 text-amber-700'
        : 'bg-red-50 text-red-600';
    return (
      <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium', cls)}>
        <Sparkles className="w-2.5 h-2.5" /> {pct}%
      </span>
    );
  }
  return null;
};

// Single block row in the timeline
const BlockRow: React.FC<{ block: Block }> = ({ block }) => {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = block.window_title || block.application || block.taxpayer_name;

  return (
    <div className={cn(
      'border border-border/40 rounded-lg overflow-hidden transition-all',
      block.classification_source === 'idle' ? 'opacity-50' : '',
    )}>
      <div
        className={cn(
          'flex items-center gap-3 px-3 py-2 text-sm',
          hasDetail ? 'cursor-pointer hover:bg-slate-50/80' : '',
          block.is_billable ? 'border-l-2 border-l-primary' : 'border-l-2 border-l-slate-200',
        )}
        onClick={() => hasDetail && setExpanded(v => !v)}
      >
        {/* Time range */}
        <span className="text-xs text-slate-400 tabular-nums whitespace-nowrap w-[105px] shrink-0">
          {formatTime(block.started_at)} – {formatTime(block.ended_at)}
        </span>

        {/* Client + task */}
        <div className="flex-1 min-w-0">
          <span className="font-medium text-slate-700 truncate block">
            {block.client_name ?? <span className="text-slate-300 italic">Unclassified</span>}
          </span>
          {block.task_type_name && (
            <span className="text-xs text-slate-400 truncate block">{block.task_type_name}</span>
          )}
        </div>

        {/* Taxpayer if present */}
        {block.taxpayer_name && (
          <span className="text-xs text-slate-500 bg-slate-50 border border-border/50 rounded px-1.5 py-0.5 truncate max-w-[120px] shrink-0">
            {block.taxpayer_name}
          </span>
        )}

        {/* Confidence */}
        <ConfidencePill source={block.classification_source} confidence={block.ai_confidence} />

        {/* Duration */}
        <span className="text-xs font-semibold tabular-nums text-slate-600 w-10 text-right shrink-0">
          {formatMins(block.duration_minutes)}
        </span>

        {/* Expand chevron */}
        {hasDetail && (
          <span className="text-slate-300 shrink-0">
            {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          </span>
        )}
      </div>

      {/* Expanded detail */}
      {expanded && hasDetail && (
        <div className="px-3 pb-2.5 pt-1 bg-slate-50/60 border-t border-border/30 space-y-1">
          {block.application && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Monitor className="w-3 h-3 shrink-0 text-slate-300" />
              <span className="font-medium text-slate-400 w-16 shrink-0">App</span>
              <span className="text-slate-600">{block.application}</span>
            </div>
          )}
          {block.window_title && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Cpu className="w-3 h-3 shrink-0 text-slate-300" />
              <span className="font-medium text-slate-400 w-16 shrink-0">Window</span>
              <span className="text-slate-600 truncate">{block.window_title}</span>
            </div>
          )}
          {block.taxpayer_name && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Tag className="w-3 h-3 shrink-0 text-slate-300" />
              <span className="font-medium text-slate-400 w-16 shrink-0">Taxpayer</span>
              <span className="text-slate-600">{block.taxpayer_name}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Day section in timeline
const DaySection: React.FC<{ dayBlocks: DayBlocks }> = ({ dayBlocks }) => {
  const { weekday, dayNum, isToday, isWeekend } = formatDayHeader(dayBlocks.date);
  const [open, setOpen] = useState(!isWeekend && dayBlocks.total_minutes > 0);
  const billable = dayBlocks.blocks.filter(b => b.is_billable).reduce((s, b) => s + b.duration_minutes, 0);

  if (dayBlocks.blocks.length === 0) {
    return (
      <div className={cn('flex items-center gap-3 py-2', isWeekend ? 'opacity-40' : '')}>
        <div className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shrink-0',
          isToday ? 'bg-primary text-white' : 'bg-slate-100 text-slate-400'
        )}>
          {dayNum}
        </div>
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{weekday}</span>
        <span className="text-xs text-slate-300 italic">No activity</span>
      </div>
    );
  }

  return (
    <div>
      {/* Day header row */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-3 py-2 hover:bg-slate-50/60 rounded-lg px-1 -mx-1 transition-colors"
      >
        <div className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shrink-0',
          isToday ? 'bg-primary text-white' : isWeekend ? 'bg-slate-100 text-slate-400' : 'bg-slate-100 text-slate-600'
        )}>
          {dayNum}
        </div>
        <span className="text-xs font-bold text-slate-600 uppercase tracking-wider w-8">{weekday}</span>
        <div className="flex items-center gap-2 flex-1">
          <span className="text-xs font-semibold text-slate-700 tabular-nums">{formatMins(dayBlocks.total_minutes)}</span>
          {billable > 0 && (
            <span className="text-[10px] text-primary font-medium tabular-nums">{formatMins(billable)} billable</span>
          )}
          <span className="text-[10px] text-slate-300">{dayBlocks.blocks.length} block{dayBlocks.blocks.length !== 1 ? 's' : ''}</span>
        </div>
        <span className="text-slate-300 mr-1">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </span>
      </button>

      {/* Blocks */}
      {open && (
        <div className="ml-11 space-y-1 pb-3">
          {dayBlocks.blocks.map(block => (
            <BlockRow key={block.id} block={block} />
          ))}
        </div>
      )}
    </div>
  );
};

// ── Week Grid (read-only, matches WeeklyTimesheet style) ──────────────────────

const WeekGrid: React.FC<{ detail: TimesheetDetail }> = ({ detail }) => {
  const today = new Date().toISOString().split('T')[0];
  const start = new Date(detail.week_start + 'T00:00:00');

  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    const date = d.toISOString().split('T')[0];
    return {
      date,
      label: d.toLocaleDateString('en-US', { weekday: 'short' }),
      dayNum: d.getDate(),
      isWeekend: i >= 5,
      isToday: date === today,
    };
  });

  // Group entries by client
  const grouped: Record<string, TimesheetEntry[]> = {};
  detail.entries.forEach(e => {
    if (!grouped[e.client_name]) grouped[e.client_name] = [];
    grouped[e.client_name].push(e);
  });

  const nonBillable = detail.grand_total - detail.billable_total;

  return (
    <div className="border border-border/50 rounded-xl overflow-hidden">
      {/* Summary strip */}
      <div className="flex items-center gap-6 px-4 py-2.5 bg-slate-50 border-b border-border/50">
        <div>
          <p className="text-xs font-bold tabular-nums text-primary">{formatHours(detail.billable_total)}</p>
          <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-400">Billable</p>
        </div>
        <div>
          <p className="text-xs font-bold tabular-nums text-slate-400">{formatHours(nonBillable)}</p>
          <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-400">Non-bill</p>
        </div>
        <div>
          <p className="text-xs font-bold tabular-nums text-slate-700">{formatHours(detail.grand_total)}</p>
          <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-400">Total</p>
        </div>
      </div>

      {/* The grid scrolls inside itself rather than inside the drawer body.
          It has to: `position: sticky` measures against the nearest scrolling
          ancestor, and the old `overflow-x-auto` wrapper was one — with no
          height, so a sticky header stuck to a box that itself scrolled away.
          The day columns went off the top of a long week and the numbers below
          belonged to no nameable day. Same max-height idiom as the misfile
          ledger on the Approvals tab. */}
      <div className="overflow-auto max-h-[46vh]">
        <table className="w-full border-collapse text-xs" style={{ minWidth: 520 }}>
          <thead className="sticky top-0 z-20">
            <tr className="border-b border-border/40 bg-white">
              <th className="text-left px-3 py-2 font-semibold text-slate-500 text-[10px] uppercase tracking-wider bg-slate-50 min-w-[140px] border-b border-border/40">
                Client / Task
              </th>
              {days.map(day => (
                <th key={day.date} className={cn(
                  'text-center px-1 py-2 font-semibold min-w-[44px] border-b border-border/40',
                  day.isWeekend ? 'bg-slate-100 text-slate-400' : 'bg-slate-50 text-slate-500'
                )}>
                  <div className="text-[9px] uppercase tracking-wider">{day.label}</div>
                  <div className={cn(
                    'text-sm font-bold mt-0.5 w-6 h-6 flex items-center justify-center rounded-full mx-auto',
                    day.isToday ? 'bg-primary text-white' : ''
                  )}>
                    {day.dayNum}
                  </div>
                </th>
              ))}
              <th className="text-center px-2 py-2 bg-slate-50 font-semibold text-slate-500 text-[10px] uppercase tracking-wider min-w-[44px] border-b border-border/40">
                Total
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/20">
            {Object.entries(grouped).map(([clientName, entries]) => {
              const hasMultiple = entries.length > 1;
              const clientTotal = entries.reduce((s, e) => s + e.total, 0);

              return (
                <React.Fragment key={clientName}>
                  {hasMultiple && (
                    <tr className="bg-slate-50/60">
                      <td className="px-3 py-1.5">
                        <span className="font-semibold text-slate-600 text-[11px]">{clientName}</span>
                        <span className="text-[10px] text-slate-400 ml-1.5">{entries.length} tasks</span>
                      </td>
                      {days.map(day => {
                        const val = entries.reduce((s, e) => s + (e.days[day.date] || 0), 0);
                        return (
                          <td key={day.date} className={cn(
                            'text-center px-1 py-1.5 tabular-nums text-[11px]',
                            day.isWeekend ? 'bg-slate-50/60' : '',
                            val > 0 ? 'font-semibold text-slate-600' : 'text-slate-200'
                          )}>
                            {val > 0 ? formatHours(val) : '—'}
                          </td>
                        );
                      })}
                      <td className={cn('text-center px-2 py-1.5 tabular-nums text-[11px] font-bold', clientTotal > 0 ? 'text-slate-700' : 'text-slate-200')}>
                        {formatHours(clientTotal)}
                      </td>
                    </tr>
                  )}
                  {entries.map(entry => (
                    <tr key={`${entry.client_id}-${entry.task_type_id}`} className="hover:bg-slate-50/40">
                      <td className={cn('px-3 py-1.5', hasMultiple && 'pl-5')}>
                        <div className="flex items-center gap-2">
                          <div className={cn('w-1 h-4 rounded-full shrink-0', entry.is_billable ? 'bg-primary' : 'bg-slate-200')} />
                          <div>
                            <p className={cn('leading-tight', hasMultiple ? 'text-slate-500 text-[11px]' : 'font-semibold text-slate-700 text-[11px]')}>
                              {hasMultiple ? entry.task_type_name : entry.client_name}
                            </p>
                            {!hasMultiple && <p className="text-[10px] text-slate-400">{entry.task_type_name}</p>}
                          </div>
                        </div>
                      </td>
                      {days.map(day => {
                        const val = entry.days[day.date] || 0;
                        return (
                          <td key={day.date} className={cn(
                            'text-center px-1 py-1.5 tabular-nums text-[11px]',
                            day.isWeekend ? 'bg-slate-50/40' : '',
                            val > 0 ? 'font-medium text-slate-700' : 'text-slate-200'
                          )}>
                            {val > 0 ? formatHours(val) : '—'}
                          </td>
                        );
                      })}
                      <td className={cn('text-center px-2 py-1.5 tabular-nums text-[11px] font-bold', entry.total > 0 ? 'text-slate-700' : 'text-slate-200')}>
                        {formatHours(entry.total)}
                      </td>
                    </tr>
                  ))}
                </React.Fragment>
              );
            })}
          </tbody>
          <tfoot className="sticky bottom-0 z-20">
            <tr className="bg-slate-50 border-t-2 border-border/50">
              <td className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-50 border-t-2 border-border/50">
                Daily Totals
              </td>
              {days.map(day => (
                <td key={day.date} className={cn(
                  'text-center px-1 py-1.5 font-bold tabular-nums text-[11px] text-slate-700 border-t-2 border-border/50',
                  day.isWeekend ? 'bg-slate-100' : 'bg-slate-50'
                )}>
                  {formatHours(detail.daily_totals?.[day.date] || 0)}
                </td>
              ))}
              <td className="text-center px-2 py-1.5 font-bold text-primary tabular-nums text-[11px] bg-slate-50 border-t-2 border-border/50">
                {formatHours(detail.grand_total)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
};

// ── Main Drawer ───────────────────────────────────────────────────────────────

export const TimesheetDetailDrawer: React.FC<Props> = ({
  timesheetId, onClose, onApprove, onReject,
}) => {
  const [detail,          setDetail]          = useState<TimesheetDetail | null>(null);
  const [loading,         setLoading]         = useState(false);
  const [error,           setError]           = useState<string | null>(null);
  const [activeTab,       setActiveTab]       = useState<'grid' | 'timeline'>('grid');
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason,    setRejectReason]    = useState('');
  const [processing,      setProcessing]      = useState(false);
  const [visible,         setVisible]         = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  // Animate in
  useEffect(() => {
    if (timesheetId !== null) {
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
    }
  }, [timesheetId]);

  // Fetch detail
  useEffect(() => {
    if (!timesheetId) return;
    setLoading(true);
    setError(null);
    setDetail(null);
    setActiveTab('grid');
    safeFetchJson<TimesheetDetail>(`${API_BASE}/billing/timesheets/${timesheetId}/detail/`)
      .then(setDetail)
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [timesheetId]);

  // Esc to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') handleClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const handleClose = () => {
    setVisible(false);
    setTimeout(onClose, 280);
  };

  const handleApprove = async () => {
    if (!timesheetId) return;
    setProcessing(true);
    await onApprove(timesheetId);
    setProcessing(false);
    handleClose();
  };

  const handleReject = async () => {
    if (!timesheetId || !rejectReason.trim()) return;
    setProcessing(true);
    await onReject(timesheetId, rejectReason);
    setProcessing(false);
    setShowRejectModal(false);
    handleClose();
  };

  if (timesheetId === null) return null;

  const canAct = detail?.status === 'submitted';
  const nonBillable = (detail?.grand_total ?? 0) - (detail?.billable_total ?? 0);

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          'fixed inset-0 bg-black/25 backdrop-blur-[2px] z-40 transition-opacity duration-300',
          visible ? 'opacity-100' : 'opacity-0'
        )}
        onClick={handleClose}
      />

      {/* Drawer panel */}
      <div
        ref={drawerRef}
        className={cn(
          'fixed top-0 right-0 h-full w-[600px] max-w-[95vw] bg-white shadow-2xl z-50',
          'flex flex-col transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]',
          visible ? 'translate-x-0' : 'translate-x-full'
        )}
      >
        {/* ── Header ────────────────────────────────────────────────────── */}
        <div className="px-5 py-4 border-b border-border/50 shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              {detail && <Avatar name={detail.user_name} />}
              <div>
                <h2 className="text-base font-bold text-slate-800 leading-tight">
                  {detail?.user_name ?? 'Loading...'}
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  {detail ? formatWeekRange(detail.week_start, detail.week_end) : '—'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Status badge */}
              {detail?.auto_submitted && (
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                  <Clock className="w-3 h-3" /> Auto-submitted
                </span>
              )}
              <button
                onClick={handleClose}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Stat strip */}
          {detail && (
            <div className="flex items-center gap-5 mt-3 pt-3 border-t border-border/40">
              <div>
                <p className="text-sm font-bold tabular-nums text-primary leading-none">{formatHours(detail.billable_total)}</p>
                <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Billable</p>
              </div>
              <div>
                <p className="text-sm font-bold tabular-nums text-slate-400 leading-none">{formatHours(nonBillable)}</p>
                <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Non-bill</p>
              </div>
              <div>
                <p className="text-sm font-bold tabular-nums text-slate-700 leading-none">{formatHours(detail.grand_total)}</p>
                <p className="text-[9px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Total</p>
              </div>

              {/* Submitted notes */}
              {detail.submitted_notes && !detail.submitted_notes.startsWith('[Auto-submitted') && (
                <div className="ml-auto flex items-center gap-1.5 text-xs text-primary/70 max-w-[200px]">
                  <Info className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate italic">{detail.submitted_notes}</span>
                </div>
              )}
            </div>
          )}

          {/* Auto-submitted warning */}
          {detail?.auto_submitted && (
            <div className="mt-3 flex items-start gap-2 px-3 py-2 bg-amber-50 rounded-lg border border-amber-100 text-xs text-amber-700">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              Employee did not manually review before submission (Tuesday auto-submit deadline).
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1 mt-3">
            {(['grid', 'timeline'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  'px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors capitalize',
                  activeTab === tab
                    ? 'bg-primary text-white'
                    : 'text-slate-500 hover:bg-slate-100'
                )}
              >
                {tab === 'grid' ? 'Week Summary' : 'Daily Timeline'}
              </button>
            ))}
          </div>
        </div>

        {/* ── Body ──────────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading && (
            <div className="flex items-center justify-center h-48">
              <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
            </div>
          )}

          {error && (
            <div className="m-5 flex items-start gap-3 px-4 py-3 rounded-lg border bg-red-50 border-red-200 text-sm">
              <AlertTriangle className="w-4 h-4 mt-0.5 text-red-500 shrink-0" />
              <span className="text-red-700">{error}</span>
            </div>
          )}

          {detail && (
            <div className="p-5 space-y-4">
              {/* Week grid */}
              {activeTab === 'grid' && (
                <WeekGrid detail={detail} />
              )}

              {/* Daily timeline */}
              {activeTab === 'timeline' && (
                <div className="space-y-1">
                  {detail.days?.length > 0 ? (
                    detail.days.map(dayBlocks => (
                      <DaySection key={dayBlocks.date} dayBlocks={dayBlocks} />
                    ))
                  ) : (
                    <div className="text-center py-12 text-slate-400">
                      <Clock className="w-8 h-8 text-slate-200 mx-auto mb-3" />
                      <p className="font-medium text-slate-500">No block-level data available</p>
                      <p className="text-xs mt-1">Timeline data may not be available for this timesheet</p>
                    </div>
                  )}

                  {/* AI legend */}
                  {detail.days?.some(d => d.blocks.some(b => b.classification_source === 'ai')) && (
                    <div className="pt-3 border-t border-border/30 flex items-center gap-4 text-[10px] text-slate-400">
                      <span className="font-semibold uppercase tracking-wider">AI confidence:</span>
                      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-emerald-400 inline-block" /> ≥88% high</span>
                      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-amber-400 inline-block" /> 65–87% medium</span>
                      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-red-400 inline-block" /> &lt;65% low</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Footer actions ─────────────────────────────────────────────── */}
        {canAct && (
          <div className="px-5 py-4 border-t border-border/50 bg-slate-50/40 shrink-0 flex items-center justify-end gap-2">
            <button
              onClick={() => setShowRejectModal(true)}
              disabled={processing}
              className="px-4 py-2 text-sm font-semibold text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-colors disabled:opacity-50"
            >
              Reject
            </button>
            <button
              onClick={handleApprove}
              disabled={processing}
              className="px-5 py-2 bg-emerald-600 text-white text-sm font-semibold rounded-lg hover:bg-emerald-700 transition-all disabled:opacity-50 flex items-center gap-2"
            >
              {processing
                ? <><RefreshCw className="w-4 h-4 animate-spin" /> Processing...</>
                : <><CheckCircle2 className="w-4 h-4" /> Approve Timesheet</>
              }
            </button>
          </div>
        )}

        {/* Already actioned state */}
        {detail && !canAct && (
          <div className="px-5 py-3 border-t border-border/50 bg-slate-50/40 shrink-0">
            <p className="text-xs text-slate-400 text-center capitalize">
              This timesheet is <span className="font-semibold text-slate-600">{detail.status}</span>
            </p>
          </div>
        )}
      </div>

      {/* ── Reject Modal ──────────────────────────────────────────────────── */}
      {showRejectModal && detail && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[60]">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full mx-4 overflow-hidden">
            <div className="px-6 py-4 border-b border-border/50">
              <h3 className="text-base font-bold text-slate-800">Reject Timesheet</h3>
              <p className="text-sm text-slate-500 mt-0.5">
                {detail.user_name} · {formatWeekRange(detail.week_start, detail.week_end)}
              </p>
            </div>
            <div className="p-6 space-y-4">
              {detail.auto_submitted && (
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
      )}
    </>
  );
};

export default TimesheetDetailDrawer;