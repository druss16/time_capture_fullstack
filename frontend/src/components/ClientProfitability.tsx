// src/components/ClientProfitability.tsx
// Shows profit margins per client - Revenue vs Cost analysis

import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Users,
  Calendar,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Download,
  AlertCircle,
} from 'lucide-react';

// ===============================
// TYPES
// ===============================

interface StaffDetail {
  user_id: number;
  user_name: string;
  hours: number;
  billing_rate: number;
  cost_rate: number;
  revenue: number;
  cost: number;
  margin: number;
  margin_percent: number;
}

interface ClientProfitability {
  client_id: number;
  client_name: string;
  client_code: string;
  total_hours: number;
  billable_hours: number;
  total_revenue: number;
  total_cost: number;
  gross_margin: number;
  margin_percent: number;
  staff_details: StaffDetail[];
}

interface ProfitabilitySummary {
  period_start: string;
  period_end: string;
  clients: ClientProfitability[];
  totals: {
    total_hours: number;
    billable_hours: number;
    total_revenue: number;
    total_cost: number;
    gross_margin: number;
    margin_percent: number;
  };
}

interface DateRange {
  start: string;
  end: string;
}

// ===============================
// HELPER FUNCTIONS
// ===============================

const formatCurrency = (amount: number): string => {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
};

const formatPercent = (value: number): string => {
  return `${value.toFixed(1)}%`;
};

const formatHours = (hours: number): string => {
  return hours.toFixed(1);
};

const getMarginColor = (percent: number): string => {
  if (percent >= 50) return 'text-green-600';
  if (percent >= 30) return 'text-emerald-600';
  if (percent >= 15) return 'text-amber-600';
  if (percent >= 0) return 'text-orange-600';
  return 'text-red-600';
};

const getMarginBg = (percent: number): string => {
  if (percent >= 50) return 'bg-green-100';
  if (percent >= 30) return 'bg-emerald-100';
  if (percent >= 15) return 'bg-amber-100';
  if (percent >= 0) return 'bg-orange-100';
  return 'bg-red-100';
};

// ===============================
// MAIN COMPONENT
// ===============================

const ClientProfitability: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ProfitabilitySummary | null>(null);
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
  const [onlyApproved, setOnlyApproved] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        start_date: dateRange.start,
        end_date: dateRange.end,
        only_approved: String(onlyApproved),
      });
      
      const result = await safeFetchJson<ProfitabilitySummary>(
        `${API_BASE}/billing/profitability/?${params}`
      );
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load profitability data');
    } finally {
      setLoading(false);
    }
  }, [dateRange, onlyApproved]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const setPreset = (preset: string) => {
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
    
    setDateRange({
      start: start.toISOString().split('T')[0],
      end: end.toISOString().split('T')[0],
    });
  };

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Client Profitability</h1>
          <p className="text-slate-500 mt-1">Analyze margins by client and staff member</p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-2 px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-slate-400" />
            <input
              type="date"
              value={dateRange.start}
              onChange={(e) => setDateRange({ ...dateRange, start: e.target.value })}
              className="px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            />
            <span className="text-slate-400">to</span>
            <input
              type="date"
              value={dateRange.end}
              onChange={(e) => setDateRange({ ...dateRange, end: e.target.value })}
              className="px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
            />
          </div>
          
          <div className="flex items-center gap-1">
            {['thisMonth', 'lastMonth', 'thisQuarter', 'thisYear'].map((preset) => (
              <button
                key={preset}
                onClick={() => setPreset(preset)}
                className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded transition-colors"
              >
                {preset === 'thisMonth' ? 'This Month' :
                 preset === 'lastMonth' ? 'Last Month' :
                 preset === 'thisQuarter' ? 'This Quarter' : 'This Year'}
              </button>
            ))}
          </div>
          
          <label className="flex items-center gap-2 ml-auto cursor-pointer">
            <input
              type="checkbox"
              checked={onlyApproved}
              onChange={(e) => setOnlyApproved(e.target.checked)}
              className="w-4 h-4 text-blue-600 border-slate-300 rounded"
            />
            <span className="text-sm text-slate-600">Approved time only</span>
          </label>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500" />
          <span className="text-red-700">{error}</span>
        </div>
      )}

      {/* Summary Cards */}
      {data && (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
              <DollarSign className="w-4 h-4" />
              Total Revenue
            </div>
            <div className="text-2xl font-bold text-slate-800">
              {formatCurrency(data.totals.total_revenue)}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {formatHours(data.totals.billable_hours)} billable hours
            </div>
          </div>
          
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
              <Users className="w-4 h-4" />
              Total Cost
            </div>
            <div className="text-2xl font-bold text-slate-800">
              {formatCurrency(data.totals.total_cost)}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Employee labor cost
            </div>
          </div>
          
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
              <TrendingUp className="w-4 h-4" />
              Gross Margin
            </div>
            <div className={`text-2xl font-bold ${getMarginColor(data.totals.margin_percent)}`}>
              {formatCurrency(data.totals.gross_margin)}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Revenue minus cost
            </div>
          </div>
          
          <div className={`rounded-xl p-5 ${getMarginBg(data.totals.margin_percent)}`}>
            <div className="flex items-center gap-2 text-slate-600 text-sm mb-1">
              {data.totals.margin_percent >= 0 ? (
                <TrendingUp className="w-4 h-4" />
              ) : (
                <TrendingDown className="w-4 h-4" />
              )}
              Margin %
            </div>
            <div className={`text-2xl font-bold ${getMarginColor(data.totals.margin_percent)}`}>
              {formatPercent(data.totals.margin_percent)}
            </div>
            <div className="text-xs text-slate-600 mt-1">
              {data.totals.margin_percent >= 30 ? 'Healthy margin' : 
               data.totals.margin_percent >= 15 ? 'Watch closely' : 'Needs attention'}
            </div>
          </div>
        </div>
      )}

      {/* Client List */}
      {data && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Client</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Hours</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Revenue</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Cost</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Margin</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Margin %</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.clients.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-500">
                    No data for this period. Try adjusting the date range.
                  </td>
                </tr>
              ) : (
                data.clients.map((client) => (
                  <React.Fragment key={client.client_id}>
                    {/* Client Row */}
                    <tr 
                      className="hover:bg-slate-50 cursor-pointer transition-colors"
                      onClick={() => setExpandedClient(
                        expandedClient === client.client_id ? null : client.client_id
                      )}
                    >
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">
                            {client.client_code?.slice(0, 2) || client.client_name?.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <div className="font-medium text-slate-800">{client.client_name}</div>
                            {client.client_code && (
                              <div className="text-xs text-slate-500">{client.client_code}</div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right text-slate-700">
                        {formatHours(client.billable_hours)}h
                      </td>
                      <td className="px-4 py-4 text-right font-medium text-slate-800">
                        {formatCurrency(client.total_revenue)}
                      </td>
                      <td className="px-4 py-4 text-right text-slate-600">
                        {formatCurrency(client.total_cost)}
                      </td>
                      <td className={`px-4 py-4 text-right font-semibold ${getMarginColor(client.margin_percent)}`}>
                        {formatCurrency(client.gross_margin)}
                      </td>
                      <td className="px-4 py-4 text-right">
                        <span className={`inline-flex px-2 py-1 rounded-full text-sm font-medium ${getMarginBg(client.margin_percent)} ${getMarginColor(client.margin_percent)}`}>
                          {formatPercent(client.margin_percent)}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        {expandedClient === client.client_id ? (
                          <ChevronUp className="w-5 h-5 text-slate-400" />
                        ) : (
                          <ChevronDown className="w-5 h-5 text-slate-400" />
                        )}
                      </td>
                    </tr>
                    
                    {/* Expanded Staff Details */}
                    {expandedClient === client.client_id && client.staff_details && (
                      <tr>
                        <td colSpan={7} className="bg-slate-50 px-4 py-4">
                          <div className="ml-12">
                            <h4 className="font-medium text-slate-700 mb-3 flex items-center gap-2">
                              <Users className="w-4 h-4" />
                              Staff Breakdown
                            </h4>
                            <table className="w-full">
                              <thead>
                                <tr className="text-xs text-slate-500 uppercase tracking-wide">
                                  <th className="text-left pb-2">Staff Member</th>
                                  <th className="text-right pb-2">Hours</th>
                                  <th className="text-right pb-2">Bill Rate</th>
                                  <th className="text-right pb-2">Cost Rate</th>
                                  <th className="text-right pb-2">Revenue</th>
                                  <th className="text-right pb-2">Cost</th>
                                  <th className="text-right pb-2">Margin</th>
                                  <th className="text-right pb-2">Margin %</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-200">
                                {client.staff_details.map((staff) => (
                                  <tr key={staff.user_id} className="text-sm">
                                    <td className="py-2 text-slate-700">{staff.user_name}</td>
                                    <td className="py-2 text-right text-slate-600">{formatHours(staff.hours)}h</td>
                                    <td className="py-2 text-right text-slate-600">${staff.billing_rate}/hr</td>
                                    <td className="py-2 text-right text-slate-600">${staff.cost_rate}/hr</td>
                                    <td className="py-2 text-right text-slate-700">{formatCurrency(staff.revenue)}</td>
                                    <td className="py-2 text-right text-slate-600">{formatCurrency(staff.cost)}</td>
                                    <td className={`py-2 text-right font-medium ${getMarginColor(staff.margin_percent)}`}>
                                      {formatCurrency(staff.margin)}
                                    </td>
                                    <td className="py-2 text-right">
                                      <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${getMarginBg(staff.margin_percent)} ${getMarginColor(staff.margin_percent)}`}>
                                        {formatPercent(staff.margin_percent)}
                                      </span>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Margin Guide */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
        <h4 className="font-medium text-slate-700 mb-3">Margin Guidelines</h4>
        <div className="grid grid-cols-4 gap-4 text-sm">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-green-500"></div>
            <span className="text-slate-600">50%+ Excellent</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-emerald-500"></div>
            <span className="text-slate-600">30-50% Good</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-amber-500"></div>
            <span className="text-slate-600">15-30% Fair</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-500"></div>
            <span className="text-slate-600">&lt;15% Needs Review</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ClientProfitability;