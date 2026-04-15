// src/components/TimesheetHistory.tsx
// Timesheet history — restyled to match WeeklyTimesheet design system

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ChevronDown, ChevronRight, RefreshCw, Clock, CheckCircle2,
  AlertTriangle, Search, X, Filter, ChevronDown as ChevronDownIcon,
  ArrowRight, User, Calendar,
} from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { cn } from '@/lib/design-system';
import { TimesheetDetailDrawer } from './TimesheetDetailDrawer';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Timesheet {
  id: number;
  user_id: number;
  user_username: string;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  week_start: string;
  week_end: string;
  status: string;
  total_hours: number;
  billable_hours: number;
  total_amount: string;
  auto_submitted: boolean;
  submitted_at: string | null;
  approved_at: string | null;
  approved_by_id: number | null;
  approved_by_username: string | null;
}

interface HistoryData {
  timesheets: Timesheet[];
  summary: {
    total_timesheets: number;
    total_hours: number;
    billable_hours: number;
    total_amount: string;
    auto_submitted_count: number;
  };
}

interface DateRange { start: string; end: string }

const getDefaultDates = (): DateRange => {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth() - 2, 1);
  return {
    start: start.toISOString().split('T')[0],
    end:   today.toISOString().split('T')[0],
  };
};

// ── Utilities ─────────────────────────────────────────────────────────────────

const fmtHours = (h: number | string): string => {
  const n = parseFloat(String(h)) || 0;
  if (n === 0) return '—';
  const hrs = Math.floor(n);
  const min = Math.round((n - hrs) * 60);
  if (hrs === 0) return `${min}m`;
  if (min === 0) return `${hrs}h`;
  return `${hrs}h ${min}m`;
};

const fmtMoney = (a: number | string): string => {
  const n = parseFloat(String(a)) || 0;
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
};

const fmtWeek = (start: string, end: string): string => {
  const s = new Date(start + 'T00:00:00');
  const e = new Date(end   + 'T00:00:00');
  return `${s.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${e.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
};

const fmtDateTime = (iso: string | null): string => {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
};

const userName = (ts: Timesheet): string =>
  `${ts.user_first_name} ${ts.user_last_name}`.trim() || ts.user_username;

const userInitials = (ts: Timesheet): string => {
  const name = userName(ts);
  return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
};

const AVATAR_COLORS = [
  'bg-blue-500','bg-emerald-500','bg-amber-500','bg-rose-500',
  'bg-violet-500','bg-cyan-500','bg-orange-500','bg-indigo-500',
];

// ── Main Component ────────────────────────────────────────────────────────────

export default function TimesheetHistory() {
  const [data,               setData]               = useState<HistoryData | null>(null);
  const [loading,            setLoading]            = useState(true);
  const [err,                setErr]                = useState<string | null>(null);
  const [search,             setSearch]             = useState('');
  const [filterUser,         setFilterUser]         = useState('');
  const [showFilter,         setShowFilter]         = useState(false);
  const [drawerTimesheetId,  setDrawerTimesheetId]  = useState<number | null>(null);
  const [dateRange,          setDateRange]          = useState<DateRange>(getDefaultDates);
  const [localStart,         setLocalStart]         = useState(getDefaultDates().start);
  const [localEnd,           setLocalEnd]           = useState(getDefaultDates().end);
  const filterRef  = useRef<HTMLDivElement>(null);
  const searchRef  = useRef<HTMLInputElement>(null);

  // Close filter menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) setShowFilter(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const params = new URLSearchParams({ start_date: dateRange.start, end_date: dateRange.end });
      setData(await safeFetchJson<HistoryData>(`${API_BASE}/billing/timesheet-history/?${params}`));
    } catch (e: any) {
      setErr(e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [dateRange]);

  useEffect(() => { load(); }, [load]);

  const applyDates = () => setDateRange({ start: localStart, end: localEnd });

  const setPreset = (p: string) => {
    const today = new Date();
    let s: Date, e: Date = today;
    switch (p) {
      case 'thisMonth':  s = new Date(today.getFullYear(), today.getMonth(), 1);   e = new Date(today.getFullYear(), today.getMonth() + 1, 0); break;
      case 'lastMonth':  s = new Date(today.getFullYear(), today.getMonth() - 1, 1); e = new Date(today.getFullYear(), today.getMonth(), 0); break;
      case 'last3':      s = new Date(today.getFullYear(), today.getMonth() - 2, 1); break;
      case 'thisYear':   s = new Date(today.getFullYear(), 0, 1); break;
      default:           s = new Date(today.getFullYear(), today.getMonth() - 2, 1);
    }
    const start = s.toISOString().split('T')[0];
    const end   = e.toISOString().split('T')[0];
    setLocalStart(start); setLocalEnd(end); setDateRange({ start, end });
  };

  const timesheets = data?.timesheets || [];
  const summary    = data?.summary;
  const users      = Array.from(new Set(timesheets.map(t => userName(t)))).sort();

  const filtered = timesheets.filter(ts => {
    if (filterUser && userName(ts) !== filterUser) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!userName(ts).toLowerCase().includes(q) && !fmtWeek(ts.week_start, ts.week_end).toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const hasFilter = search || filterUser || dateRange.start !== getDefaultDates().start || dateRange.end !== getDefaultDates().end;
  const nonBillableTotal = parseFloat(String(summary?.total_hours || 0)) - parseFloat(String(summary?.billable_hours || 0));

  if (loading && !data) return (
    <div className="flex items-center justify-center min-h-[300px]">
      <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
    </div>
  );

  return (
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2">

      {/* ── ROW 1: Title / Stats ───────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 h-14 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3 shrink-0">
          <h2 className="text-base font-bold text-slate-800">History</h2>
          {summary && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-slate-50 text-slate-600 border-border/50">
              {summary.total_timesheets} timesheet{summary.total_timesheets !== 1 ? 's' : ''}
            </span>
          )}
          {summary && summary.auto_submitted_count > 0 && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-amber-50 text-amber-700 border-amber-200">
              <Clock className="w-3 h-3" /> {summary.auto_submitted_count} auto-sub
            </span>
          )}
        </div>

        <div className="flex items-center gap-4">
          {summary && (
            <div className="flex items-center gap-5 pr-4 border-r border-border/50">
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-primary leading-none">{fmtHours(summary.billable_hours)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Billable</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-slate-400 leading-none">{fmtHours(nonBillableTotal)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Non-bill</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-slate-700 leading-none">{fmtHours(summary.total_hours)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Total</p>
              </div>
              <div className="text-right border-l border-border/40 pl-5">
                <p className="text-sm font-bold tabular-nums text-emerald-600 leading-none">{fmtMoney(summary.total_amount)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Value</p>
              </div>
            </div>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* ── ROW 2: Search / Date / Filter ─────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-4 h-11 flex items-center gap-3 shrink-0">
        <div className="relative w-48">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by name or week…"
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

        {/* Date range */}
        <div className="flex items-center gap-2 pl-3 border-l border-border/40">
          <Calendar className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <input
            type="date" value={localStart} onChange={e => setLocalStart(e.target.value)}
            className="text-xs px-2 py-1 bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 tabular-nums"
          />
          <span className="text-slate-300 text-xs">–</span>
          <input
            type="date" value={localEnd} onChange={e => setLocalEnd(e.target.value)}
            className="text-xs px-2 py-1 bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 tabular-nums"
          />
          <button onClick={applyDates} className="px-2.5 py-1 text-xs font-semibold bg-primary text-white rounded-lg hover:opacity-90 transition-all">Apply</button>
        </div>

        {/* Date presets */}
        <div className="flex items-center gap-1 pl-1 border-l border-border/40">
          {[['thisMonth','This Mo.'],['lastMonth','Last Mo.'],['last3','Last 3 Mo.'],['thisYear','Year']].map(([p, l]) => (
            <button key={p} onClick={() => setPreset(p)} className="px-2.5 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100 rounded-lg transition-colors">{l}</button>
          ))}
        </div>

        {/* Employee filter */}
        {users.length > 1 && (
          <div className="relative shrink-0" ref={filterRef}>
            <button
              onClick={() => setShowFilter(v => !v)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all',
                filterUser
                  ? 'bg-primary/8 text-primary border-primary/25'
                  : 'bg-slate-50 text-slate-600 border-border/50 hover:bg-slate-100'
              )}
            >
              <User className="w-3.5 h-3.5" />
              {filterUser || 'All employees'}
              <ChevronDownIcon className="w-3 h-3" />
            </button>
            {showFilter && (
              <div className="absolute top-full mt-1 left-0 bg-white rounded-xl border border-border/60 shadow-lg z-20 py-1 min-w-[180px]">
                {['', ...users].map(u => (
                  <button
                    key={u}
                    onClick={() => { setFilterUser(u); setShowFilter(false); }}
                    className={cn('w-full text-left px-4 py-2 text-sm transition-colors', filterUser === u ? 'text-primary font-semibold bg-primary/5' : 'text-slate-600 hover:bg-slate-50')}
                  >
                    {u || 'All employees'}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Count + clear */}
        <span className="text-xs text-slate-400 ml-1">
          {filtered.length === timesheets.length
            ? `${timesheets.length} timesheet${timesheets.length !== 1 ? 's' : ''}`
            : <><span className="font-semibold text-slate-600">{filtered.length}</span> of {timesheets.length}</>
          }
          {hasFilter && filtered.length < timesheets.length && (
            <button onClick={() => { setSearch(''); setFilterUser(''); }} className="ml-2 text-primary hover:underline font-medium">Clear</button>
          )}
        </span>
      </div>

      {/* ── Error ─────────────────────────────────────────────────────── */}
      {err && (
        <div className="flex items-start gap-3 px-4 py-3 rounded-lg border bg-red-50 border-red-200 text-sm shrink-0">
          <AlertTriangle className="w-4 h-4 mt-0.5 text-red-500 shrink-0" />
          <span className="text-red-700">{err}</span>
        </div>
      )}

      {/* ── Table ──────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-sm" style={{ minWidth: 760 }}>

            <thead className="sticky top-0 z-20">
              <tr className="border-b border-border/60 bg-white">
                <th className="sticky left-0 z-20 text-left px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 min-w-[200px] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  Employee
                </th>
                <th className="text-left px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Week</th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Billable</th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Non-bill</th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Total</th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Amount</th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Approved</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-border/30">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-16 text-slate-400">
                    <CheckCircle2 className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                    <p className="font-medium text-slate-500">
                      {timesheets.length === 0 ? 'No approved timesheets yet' : 'No timesheets match your filters'}
                    </p>
                    <p className="text-sm mt-1">
                      {timesheets.length === 0
                        ? 'Approved timesheets will appear here'
                        : (
                          <button
                            onClick={() => {
                              setSearch(''); setFilterUser('');
                              const d = getDefaultDates();
                              setLocalStart(d.start); setLocalEnd(d.end); setDateRange(d);
                            }}
                            className="text-primary hover:underline"
                          >
                            Clear filters
                          </button>
                        )
                      }
                    </p>
                  </td>
                </tr>
              ) : (
                filtered.map((ts) => {
                  const color   = AVATAR_COLORS[ts.user_id % AVATAR_COLORS.length];
                  const nonBill = ts.total_hours - ts.billable_hours;

                  return (
                    <tr
                      key={ts.id}
                      onClick={() => setDrawerTimesheetId(ts.id)}
                      className="cursor-pointer hover:bg-slate-50/60 transition-colors"
                    >
                      {/* Employee */}
                      <td className="sticky left-0 z-10 px-4 py-2.5 bg-white shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                        <div className="flex items-center gap-2.5">
                          <div className={cn('w-7 h-7 rounded-full flex items-center justify-center text-white text-[10px] font-bold shrink-0', color)}>
                            {userInitials(ts)}
                          </div>
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-800 text-sm leading-tight truncate">{userName(ts)}</p>
                            <p className="text-xs text-slate-400 truncate">{ts.user_email}</p>
                          </div>
                        </div>
                      </td>

                      {/* Week */}
                      <td className="px-4 py-2.5 text-sm text-slate-600 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          {fmtWeek(ts.week_start, ts.week_end)}
                          {ts.auto_submitted && (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 whitespace-nowrap">
                              <Clock className="w-2.5 h-2.5" /> Auto
                            </span>
                          )}
                          <ChevronRight className="w-3.5 h-3.5 text-slate-300 ml-1" />
                        </div>
                      </td>

                      {/* Billable */}
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        <p className="text-sm font-bold text-primary leading-none">{fmtHours(ts.billable_hours)}</p>
                      </td>

                      {/* Non-bill */}
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        <p className="text-sm font-bold text-slate-400 leading-none">{fmtHours(nonBill)}</p>
                      </td>

                      {/* Total */}
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        <p className="text-sm font-bold text-slate-700 leading-none">{fmtHours(ts.total_hours)}</p>
                      </td>

                      {/* Amount */}
                      <td className="px-4 py-2.5 text-right tabular-nums whitespace-nowrap">
                        <span className="text-sm font-semibold text-emerald-600">{fmtMoney(ts.total_amount)}</span>
                      </td>

                      {/* Approved */}
                      <td className="px-4 py-2.5 text-right">
                        <p className="text-xs text-slate-500 tabular-nums">{fmtDateTime(ts.approved_at)}</p>
                        {ts.approved_by_username && (
                          <p className="text-[10px] text-slate-400">by {ts.approved_by_username}</p>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between bg-slate-50/40 shrink-0">
          <p className="text-xs text-slate-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
            Click any row to view timesheet detail
          </p>
          {summary && (
            <p className="text-xs font-semibold text-emerald-600 tabular-nums">{fmtMoney(summary.total_amount)} total value</p>
          )}
        </div>
      </div>

      {/* ── Detail Drawer ─────────────────────────────────────────────── */}
      <TimesheetDetailDrawer
        timesheetId={drawerTimesheetId}
        onClose={() => setDrawerTimesheetId(null)}
        onApprove={async (id) => {
          await safeFetchJson(`${API_BASE}/billing/timesheets/${id}/approve/`, {
            method: 'POST',
            body: JSON.stringify({ notes: '' }),
          });
          load();
        }}
        onReject={async (id, reason) => {
          await safeFetchJson(`${API_BASE}/billing/timesheets/${id}/reject/`, {
            method: 'POST',
            body: JSON.stringify({ reason }),
          });
          load();
        }}
      />
    </div>
  );
}