// src/components/ClientSummary.tsx
// Manager/billing view - hours and amounts by client for invoicing

import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';

// ===============================
// TYPES
// ===============================

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

interface SummaryTotals {
  total_hours: number;
  billable_hours: number;
  total_amount: number;
}

interface SummaryData {
  period_start: string;
  period_end: string;
  clients: ClientData[];
  totals: SummaryTotals;
}

interface DateRange {
  start: string;
  end: string;
}

interface Filters {
  onlyApproved: boolean;
  onlyBillable: boolean;
}

interface ClientSummaryProps {
  // No props needed - uses API_BASE from lib/api
}

interface DateRangePickerProps {
  startDate: string;
  endDate: string;
  onChange: (start: string, end: string) => void;
}

interface ClientCardProps {
  client: ClientData;
  expanded: boolean;
  onToggle: () => void;
  onCreateInvoice: (client: ClientData) => void;
}

// ===============================
// UTILITY FUNCTIONS
// ===============================

const formatHours = (hours: number | string): string => {
  const num = parseFloat(String(hours)) || 0;
  return num.toFixed(1);
};

const formatCurrency = (amount: number | string): string => {
  const num = parseFloat(String(amount)) || 0;
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
};

// ===============================
// SUB-COMPONENTS
// ===============================

const DateRangePicker: React.FC<DateRangePickerProps> = ({ startDate, endDate, onChange }) => {
  const [localStart, setLocalStart] = useState<string>(startDate);
  const [localEnd, setLocalEnd] = useState<string>(endDate);

  const handleApply = (): void => {
    onChange(localStart, localEnd);
  };

  const setPreset = (preset: string): void => {
    const today = new Date();
    let start: Date;
    let end: Date;
    
    switch (preset) {
      case 'thisMonth':
        start = new Date(today.getFullYear(), today.getMonth(), 1);
        end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        break;
      case 'lastMonth':
        start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        end = new Date(today.getFullYear(), today.getMonth(), 0);
        break;
      case 'thisQuarter':
        const quarter = Math.floor(today.getMonth() / 3);
        start = new Date(today.getFullYear(), quarter * 3, 1);
        end = new Date(today.getFullYear(), quarter * 3 + 3, 0);
        break;
      case 'thisYear':
        start = new Date(today.getFullYear(), 0, 1);
        end = new Date(today.getFullYear(), 11, 31);
        break;
      default:
        return;
    }
    
    const startStr = start.toISOString().split('T')[0];
    const endStr = end.toISOString().split('T')[0];
    setLocalStart(startStr);
    setLocalEnd(endStr);
    onChange(startStr, endStr);
  };

  return (
    <div className="flex items-center gap-4 flex-wrap">
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-600">From:</label>
        <input
          type="date"
          value={localStart}
          onChange={(e) => setLocalStart(e.target.value)}
          className="px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-600">To:</label>
        <input
          type="date"
          value={localEnd}
          onChange={(e) => setLocalEnd(e.target.value)}
          className="px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
      <button
        onClick={handleApply}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
      >
        Apply
      </button>
      <div className="flex items-center gap-1 ml-2">
        <button
          onClick={() => setPreset('thisMonth')}
          className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded transition-colors"
        >
          This Month
        </button>
        <button
          onClick={() => setPreset('lastMonth')}
          className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded transition-colors"
        >
          Last Month
        </button>
        <button
          onClick={() => setPreset('thisQuarter')}
          className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded transition-colors"
        >
          This Quarter
        </button>
      </div>
    </div>
  );
};

const ClientCard: React.FC<ClientCardProps> = ({ client, expanded, onToggle, onCreateInvoice }) => {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full px-5 py-4 flex items-center justify-between hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-blue-600 rounded-lg flex items-center justify-center text-white font-bold">
            {client.client_code?.slice(0, 2) || client.client_name?.slice(0, 2).toUpperCase()}
          </div>
          <div className="text-left">
            <h3 className="font-semibold text-slate-800">{client.client_name}</h3>
            {client.client_code && (
              <span className="text-sm text-slate-500">{client.client_code}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="text-sm text-slate-500">Total Hours</div>
            <div className="font-semibold text-slate-800">{formatHours(client.total_hours)}h</div>
          </div>
          <div className="text-right">
            <div className="text-sm text-slate-500">Billable</div>
            <div className="font-semibold text-emerald-600">{formatHours(client.billable_hours)}h</div>
          </div>
          <div className="text-right min-w-[100px]">
            <div className="text-sm text-slate-500">Amount</div>
            <div className="font-bold text-blue-600">{formatCurrency(client.total_amount)}</div>
          </div>
          <svg
            className={`w-5 h-5 text-slate-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-slate-200 bg-slate-50 p-5">
          <div className="grid md:grid-cols-2 gap-6">
            {/* Staff Breakdown */}
            <div>
              <h4 className="font-medium text-slate-700 mb-3 flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                By Staff Member
              </h4>
              <div className="space-y-2">
                {client.staff_breakdown?.map((staff, idx) => (
                  <div key={idx} className="flex items-center justify-between py-2 px-3 bg-white rounded-lg">
                    <span className="text-slate-700">{staff.username}</span>
                    <div className="flex items-center gap-4 text-sm">
                      <span className="text-slate-500">{formatHours(staff.hours)}h</span>
                      <span className="font-medium text-slate-700">{formatCurrency(staff.amount)}</span>
                    </div>
                  </div>
                ))}
                {(!client.staff_breakdown || client.staff_breakdown.length === 0) && (
                  <div className="text-sm text-slate-500 italic">No staff data</div>
                )}
              </div>
            </div>

            {/* Task Breakdown */}
            <div>
              <h4 className="font-medium text-slate-700 mb-3 flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                By Task Type
              </h4>
              <div className="space-y-2">
                {client.task_breakdown?.map((task, idx) => (
                  <div key={idx} className="flex items-center justify-between py-2 px-3 bg-white rounded-lg">
                    <span className="text-slate-700">{task.task_type || 'General'}</span>
                    <div className="flex items-center gap-4 text-sm">
                      <span className="text-slate-500">{formatHours(task.hours)}h</span>
                      <span className="font-medium text-slate-700">{formatCurrency(task.amount)}</span>
                    </div>
                  </div>
                ))}
                {(!client.task_breakdown || client.task_breakdown.length === 0) && (
                  <div className="text-sm text-slate-500 italic">No task data</div>
                )}
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="mt-5 pt-4 border-t border-slate-200 flex items-center justify-end gap-3">
            <button
              onClick={() => onCreateInvoice(client)}
              className="px-5 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Create Invoice
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// ===============================
// MAIN COMPONENT
// ===============================

const ClientSummary: React.FC<ClientSummaryProps> = () => {
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [summaryData, setSummaryData] = useState<SummaryData | null>(null);
  const [expandedClient, setExpandedClient] = useState<number | null>(null);
  
  // Default to current month
  const getDefaultDates = (): DateRange => {
    const today = new Date();
    const start = new Date(today.getFullYear(), today.getMonth(), 1);
    const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    return {
      start: start.toISOString().split('T')[0],
      end: end.toISOString().split('T')[0],
    };
  };
  
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDates);
  const [filters, setFilters] = useState<Filters>({
    onlyApproved: false,
    onlyBillable: false,
  });

  const fetchSummary = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        start_date: dateRange.start,
        end_date: dateRange.end,
        only_approved: String(filters.onlyApproved),
        only_billable: String(filters.onlyBillable),
      });
      
      const data = await safeFetchJson<SummaryData>(
        `${API_BASE}/billing/client-summary/?${params}`
      );
      setSummaryData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [dateRange, filters]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  const handleDateChange = (start: string, end: string): void => {
    setDateRange({ start, end });
  };

  const handleCreateInvoice = (client: ClientData): void => {
    const params = new URLSearchParams({
      client_id: String(client.client_id),
      start_date: dateRange.start,
      end_date: dateRange.end,
    });
    window.location.href = `/invoices/create?${params}`;
  };

  if (loading) {
    return (
      <div className="min-h-[400px] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-500">Loading client summary...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Client Billing Summary</h1>
        <p className="text-slate-500 mt-1">Review hours and prepare invoices by client</p>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <DateRangePicker
          startDate={dateRange.start}
          endDate={dateRange.end}
          onChange={handleDateChange}
        />
        
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-slate-100">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={filters.onlyApproved}
              onChange={(e) => setFilters({ ...filters, onlyApproved: e.target.checked })}
              className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
            />
            <span className="text-sm text-slate-600">Approved time only</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={filters.onlyBillable}
              onChange={(e) => setFilters({ ...filters, onlyBillable: e.target.checked })}
              className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
            />
            <span className="text-sm text-slate-600">Billable time only</span>
          </label>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
          <svg className="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <span className="text-red-700">{error}</span>
        </div>
      )}

      {/* Totals Summary */}
      {summaryData && (
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-gradient-to-br from-slate-50 to-slate-100 rounded-xl p-5 border border-slate-200">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 bg-slate-500 rounded-lg flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <span className="text-sm font-medium text-slate-600">Total Hours</span>
            </div>
            <div className="text-3xl font-bold text-slate-800">
              {formatHours(summaryData.totals?.total_hours || 0)}
            </div>
          </div>
          
          <div className="bg-gradient-to-br from-emerald-50 to-emerald-100 rounded-xl p-5 border border-emerald-200">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 bg-emerald-500 rounded-lg flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <span className="text-sm font-medium text-emerald-700">Billable Hours</span>
            </div>
            <div className="text-3xl font-bold text-emerald-700">
              {formatHours(summaryData.totals?.billable_hours || 0)}
            </div>
          </div>
          
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl p-5 border border-blue-200">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <span className="text-sm font-medium text-blue-700">Total Billable</span>
            </div>
            <div className="text-3xl font-bold text-blue-700">
              {formatCurrency(summaryData.totals?.total_amount || 0)}
            </div>
          </div>
        </div>
      )}

      {/* Client List */}
      <div className="space-y-3">
        {summaryData?.clients?.length === 0 ? (
          <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
            <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-slate-800 mb-2">No data for this period</h3>
            <p className="text-slate-500">Try adjusting the date range or filters</p>
          </div>
        ) : (
          summaryData?.clients?.map((client) => (
            <ClientCard
              key={client.client_id}
              client={client}
              expanded={expandedClient === client.client_id}
              onToggle={() => setExpandedClient(
                expandedClient === client.client_id ? null : client.client_id
              )}
              onCreateInvoice={handleCreateInvoice}
            />
          ))
        )}
      </div>
    </div>
  );
};

export default ClientSummary;