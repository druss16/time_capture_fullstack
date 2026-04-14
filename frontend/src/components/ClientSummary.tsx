// src/components/ClientSummary.tsx
// Manager/billing view — restyled to match WeeklyTimesheet design system

import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import IntegrationStatusBanner from '@/components/IntegrationStatusBanner';
import IntegrationPushPanel from '@/components/IntegrationPushPanel';
import {
  RefreshCw, AlertTriangle, ChevronDown, ChevronRight,
  FileText, Calendar, Users, Tag, DollarSign, Clock,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

// ── Types ─────────────────────────────────────────────────────────────────────

interface StaffBreakdown {
  user_id: number;
  username: string;
  hours: number;
  amount: number;
}

interface TaskBreakdown {
  task_type_id: number | null;
  task_type: string;
  hours: number;
  amount: number;
}

interface ClientData {
  client_id: number | null;
  client_name: string;
  client_code: string;
  total_hours: number;
  billable_hours: number;
  non_billable_hours: number;
  total_amount: number;
  staff_breakdown: StaffBreakdown[];
  task_breakdown: TaskBreakdown[];
}

interface SummaryData {
  period_start: string;
  period_end: string;
  clients: ClientData[];
  totals: { total_hours: number; billable_hours: number; total_amount: number };
}

// ── Utilities ─────────────────────────────────────────────────────────────────

const formatHours = (h: number | string): string => {
  const num = parseFloat(String(h)) || 0;
  if (num === 0) return '—';
  const hrs = Math.floor(num);
  const min = Math.round((num - hrs) * 60);
  if (hrs === 0) return `${min}m`;
  if (min === 0) return `${hrs}h`;
  return `${hrs}h ${min}m`;
};

const formatCurrency = (amount: number | string): string => {
  const num = parseFloat(String(amount)) || 0;
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
};

const getDefaultDates = () => {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), 1);
  const end   = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  return {
    start: start.toISOString().split('T')[0],
    end:   end.toISOString().split('T')[0],
  };
};

// ── Client initials avatar ────────────────────────────────────────────────────

const ClientAvatar: React.FC<{ name: string; code: string }> = ({ name, code }) => {
  const label = (code || name || '??').slice(0, 2).toUpperCase();
  const COLORS = [
    'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500',
    'bg-violet-500', 'bg-cyan-500', 'bg-orange-500', 'bg-indigo-500',
  ];
  const color = COLORS[(name?.length ?? 0) % COLORS.length];
  return (
    <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center text-white text-[10px] font-bold shrink-0', color)}>
      {label}
    </div>
  );
};

// ── Expanded breakdown panel ──────────────────────────────────────────────────

const BreakdownPanel: React.FC<{ client: ClientData; onCreateInvoice: () => void }> = ({
  client, onCreateInvoice,
}) => (
  <tr>
    <td colSpan={6} className="px-0 pb-0 pt-0">
      <div className="mx-4 mb-3 bg-slate-50 rounded-xl border border-border/40 overflow-hidden">
        <div className="grid grid-cols-2 divide-x divide-border/40">

          {/* Staff breakdown */}
          <div className="p-4">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
              <Users className="w-3 h-3" /> By Staff
            </p>
            {client.staff_breakdown?.length > 0 ? (
              <div className="space-y-1">
                {client.staff_breakdown.map((s, i) => (
                  <div key={i} className="flex items-center justify-between text-sm py-1 px-2 rounded-lg hover:bg-white transition-colors">
                    <span className="text-slate-600">{s.username}</span>
                    <div className="flex items-center gap-4 tabular-nums">
                      <span className="text-xs text-slate-400">{formatHours(s.hours)}</span>
                      <span className="text-xs font-medium text-slate-700 w-20 text-right">{formatCurrency(s.amount)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-300 italic">No staff data</p>
            )}
          </div>

          {/* Task breakdown */}
          <div className="p-4">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
              <Tag className="w-3 h-3" /> By Task
            </p>
            {client.task_breakdown?.length > 0 ? (
              <div className="space-y-1">
                {client.task_breakdown.map((t, i) => (
                  <div key={i} className="flex items-center justify-between text-sm py-1 px-2 rounded-lg hover:bg-white transition-colors">
                    <span className="text-slate-600">{t.task_type || 'General'}</span>
                    <div className="flex items-center gap-4 tabular-nums">
                      <span className="text-xs text-slate-400">{formatHours(t.hours)}</span>
                      <span className="text-xs font-medium text-slate-700 w-20 text-right">{formatCurrency(t.amount)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-300 italic">No task data</p>
            )}
          </div>
        </div>

        {/* Footer action */}
        <div className="px-4 py-3 border-t border-border/40 bg-white/60 flex justify-end">
          <button
            onClick={onCreateInvoice}
            className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-xs font-semibold rounded-lg hover:opacity-90 transition-all"
          >
            <FileText className="w-3.5 h-3.5" /> Create Invoice
          </button>
        </div>
      </div>
    </td>
  </tr>
);

// ── Main Component ────────────────────────────────────────────────────────────

const ClientSummary: React.FC = () => {
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState<string | null>(null);
  const [summaryData,  setSummaryData]  = useState<SummaryData | null>(null);
  const [expandedId,   setExpandedId]   = useState<number | null>(null);
  const [dateRange,    setDateRange]    = useState(getDefaultDates);
  const [localStart,   setLocalStart]   = useState(getDefaultDates().start);
  const [localEnd,     setLocalEnd]     = useState(getDefaultDates().end);
  const [onlyApproved, setOnlyApproved] = useState(false);
  const [onlyBillable, setOnlyBillable] = useState(false);

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        start_date:    dateRange.start,
        end_date:      dateRange.end,
        only_approved: String(onlyApproved),
        only_billable: String(onlyBillable),
      });
      const data = await safeFetchJson<SummaryData>(`${API_BASE}/billing/client-summary/?${params}`);
      setSummaryData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [dateRange, onlyApproved, onlyBillable]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);

  const applyDates = () => setDateRange({ start: localStart, end: localEnd });

  const setPreset = (preset: string) => {
    const today = new Date();
    let s: Date, e: Date;
    if (preset === 'thisMonth') {
      s = new Date(today.getFullYear(), today.getMonth(), 1);
      e = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    } else if (preset === 'lastMonth') {
      s = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      e = new Date(today.getFullYear(), today.getMonth(), 0);
    } else {
      const q = Math.floor(today.getMonth() / 3);
      s = new Date(today.getFullYear(), q * 3, 1);
      e = new Date(today.getFullYear(), q * 3 + 3, 0);
    }
    const start = s.toISOString().split('T')[0];
    const end   = e.toISOString().split('T')[0];
    setLocalStart(start);
    setLocalEnd(end);
    setDateRange({ start, end });
  };

  const handleCreateInvoice = (client: ClientData) => {
    const params = new URLSearchParams({
      client_id:  String(client.client_id),
      start_date: dateRange.start,
      end_date:   dateRange.end,
    });
    window.location.href = `/invoices/create?${params}`;
  };

  const totals = summaryData?.totals;
  const nonBillableTotal = (totals?.total_hours ?? 0) - (totals?.billable_hours ?? 0);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2">

      {/* ── ROW 1: Title / Stats ───────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 h-14 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3 shrink-0">
          <h2 className="text-base font-bold text-slate-800">Client Billing</h2>
          {summaryData && (
            <span className="text-xs text-slate-400 font-medium">
              {summaryData.period_start} – {summaryData.period_end}
            </span>
          )}
        </div>

        {totals && (
          <div className="flex items-center gap-5 pr-4 border-r border-border/50">
            <div className="text-right">
              <p className="text-sm font-bold tabular-nums text-primary leading-none">{formatHours(totals.billable_hours)}</p>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Billable</p>
            </div>
            <div className="text-right">
              <p className="text-sm font-bold tabular-nums text-slate-400 leading-none">{formatHours(nonBillableTotal)}</p>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Non-bill</p>
            </div>
            <div className="text-right">
              <p className="text-sm font-bold tabular-nums text-slate-700 leading-none">{formatHours(totals.total_hours)}</p>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Total</p>
            </div>
            <div className="text-right border-l border-border/40 pl-5">
              <p className="text-sm font-bold tabular-nums text-emerald-600 leading-none">{formatCurrency(totals.total_amount)}</p>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Billable $</p>
            </div>
          </div>
        )}

        <button
          onClick={fetchSummary}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* ── ROW 2: Filters ────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-4 h-11 flex items-center gap-3 shrink-0">
        {/* Date inputs */}
        <Calendar className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <input
          type="date"
          value={localStart}
          onChange={e => setLocalStart(e.target.value)}
          className="text-xs px-2 py-1 bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 tabular-nums"
        />
        <span className="text-slate-300 text-xs">–</span>
        <input
          type="date"
          value={localEnd}
          onChange={e => setLocalEnd(e.target.value)}
          className="text-xs px-2 py-1 bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 tabular-nums"
        />
        <button
          onClick={applyDates}
          className="px-2.5 py-1 text-xs font-semibold bg-primary text-white rounded-lg hover:opacity-90 transition-all"
        >
          Apply
        </button>

        {/* Presets */}
        <div className="flex items-center gap-1 pl-1 border-l border-border/40">
          {['thisMonth', 'lastMonth', 'thisQuarter'].map(p => (
            <button
              key={p}
              onClick={() => setPreset(p)}
              className="px-2.5 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
            >
              {p === 'thisMonth' ? 'This Mo.' : p === 'lastMonth' ? 'Last Mo.' : 'Quarter'}
            </button>
          ))}
        </div>

        {/* Toggles */}
        <div className="flex items-center gap-3 pl-1 border-l border-border/40 ml-auto">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={onlyApproved}
              onChange={e => setOnlyApproved(e.target.checked)}
              className="w-3.5 h-3.5 rounded accent-primary"
            />
            <span className="text-xs text-slate-500 font-medium">Approved only</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={onlyBillable}
              onChange={e => setOnlyBillable(e.target.checked)}
              className="w-3.5 h-3.5 rounded accent-primary"
            />
            <span className="text-xs text-slate-500 font-medium">Billable only</span>
          </label>
        </div>
      </div>

      {/* ── Error ─────────────────────────────────────────────────────── */}
      {error && (
        <div className="flex items-start gap-3 px-4 py-3 rounded-lg border bg-red-50 border-red-200 text-sm shrink-0">
          <AlertTriangle className="w-4 h-4 mt-0.5 text-red-500 shrink-0" />
          <div>
            <p className="font-semibold text-red-700">Error</p>
            <p className="mt-0.5 text-red-600">{error}</p>
          </div>
        </div>
      )}

      {/* ── Integration push panel ─────────────────────────────────────── */}
      <div className="shrink-0">
        <IntegrationPushPanel />
      </div>

      {/* ── Table ──────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-sm" style={{ minWidth: 640 }}>

            <thead className="sticky top-0 z-20">
              <tr className="border-b border-border/60 bg-white">
                <th className="sticky left-0 z-20 text-left px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 min-w-[200px] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  Client
                </th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                  Billable
                </th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                  Non-bill
                </th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                  Total
                </th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                  Amount
                </th>
                <th className="px-4 py-3 bg-slate-50 w-8" />
              </tr>
            </thead>

            <tbody className="divide-y divide-border/30">
              {!summaryData?.clients?.length ? (
                <tr>
                  <td colSpan={6} className="text-center py-16 text-slate-400">
                    <Clock className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                    <p className="font-medium text-slate-500">No data for this period</p>
                    <p className="text-sm mt-1">Try adjusting the date range or filters</p>
                  </td>
                </tr>
              ) : (
                summaryData.clients.map(client => {
                  const isExpanded = expandedId === client.client_id;
                  return (
                    <React.Fragment key={client.client_id}>
                      <tr
                        onClick={() => setExpandedId(isExpanded ? null : client.client_id)}
                        className="cursor-pointer hover:bg-slate-50/60 transition-colors"
                      >
                        {/* Client name */}
                        <td className="sticky left-0 z-10 px-4 py-3 bg-white shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                          <div className="flex items-center gap-2.5">
                            <ClientAvatar name={client.client_name} code={client.client_code} />
                            <div className="min-w-0">
                              <p className="font-semibold text-slate-800 text-sm leading-tight truncate">{client.client_name}</p>
                              {client.client_code && (
                                <p className="text-xs text-slate-400 truncate">{client.client_code}</p>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Billable */}
                        <td className="px-4 py-3 text-right tabular-nums">
                          <p className="text-sm font-bold text-primary leading-none">{formatHours(client.billable_hours)}</p>
                        </td>

                        {/* Non-bill */}
                        <td className="px-4 py-3 text-right tabular-nums">
                          <p className="text-sm font-bold text-slate-400 leading-none">{formatHours(client.non_billable_hours)}</p>
                        </td>

                        {/* Total */}
                        <td className="px-4 py-3 text-right tabular-nums">
                          <p className="text-sm font-bold text-slate-700 leading-none">{formatHours(client.total_hours)}</p>
                        </td>

                        {/* Amount */}
                        <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap">
                          <span className="text-sm font-semibold text-emerald-600">{formatCurrency(client.total_amount)}</span>
                        </td>

                        {/* Expand chevron */}
                        <td className="px-4 py-3 text-slate-300">
                          {isExpanded
                            ? <ChevronDown className="w-4 h-4" />
                            : <ChevronRight className="w-4 h-4" />
                          }
                        </td>
                      </tr>

                      {/* Expanded breakdown */}
                      {isExpanded && (
                        <BreakdownPanel
                          client={client}
                          onCreateInvoice={() => handleCreateInvoice(client)}
                        />
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between bg-slate-50/40 shrink-0">
          <p className="text-xs text-slate-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
            {summaryData?.clients?.length ?? 0} client{(summaryData?.clients?.length ?? 0) !== 1 ? 's' : ''} · click a row to see staff & task breakdown
          </p>
          {totals && (
            <p className="text-xs font-semibold text-emerald-600 tabular-nums">
              {formatCurrency(totals.total_amount)} total billable
            </p>
          )}
        </div>
      </div>

    </div>
  );
};

export default ClientSummary;