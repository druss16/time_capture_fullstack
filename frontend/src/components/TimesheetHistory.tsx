// src/components/TimesheetHistory.tsx
// View approved and locked timesheets - archive/history view

import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  CheckCircle,
  Lock,
  Calendar,
  Clock,
  DollarSign,
  RefreshCw,
  Filter,
  ChevronDown,
  ChevronUp,
  FileText,
  AlertCircle,
} from 'lucide-react';

// ===============================
// TYPES - Match backend response
// ===============================

interface TimesheetHistoryItem {
  id: number;
  user_id: number;
  user_username: string;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  week_start: string;
  week_end: string;
  status: 'approved' | 'locked';
  total_hours: number;
  billable_hours: number;
  total_amount: string;  // Backend sends as string
  auto_submitted: boolean;
  submitted_at: string | null;
  approved_at: string | null;
  approved_by_id: number | null;
  approved_by_username: string | null;
  locked_at?: string | null;
}

interface HistorySummary {
  total_timesheets: number;
  total_hours: number;
  billable_hours: number;
  total_amount: string;
  auto_submitted_count: number;
}

interface HistoryResponse {
  timesheets: TimesheetHistoryItem[];
  summary: HistorySummary;
}

interface TeamMember {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
}

// ===============================
// HELPER FUNCTIONS
// ===============================

const formatDateRange = (start: string, end: string): string => {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const startMonth = startDate.toLocaleDateString('en-US', { month: 'short' });
  const endMonth = endDate.toLocaleDateString('en-US', { month: 'short' });
  
  if (startMonth === endMonth) {
    return `${startMonth} ${startDate.getDate()} - ${endDate.getDate()}, ${startDate.getFullYear()}`;
  }
  return `${startMonth} ${startDate.getDate()} - ${endMonth} ${endDate.getDate()}, ${startDate.getFullYear()}`;
};

const formatCurrency = (amount: string | number): string => {
  const num = typeof amount === 'string' ? parseFloat(amount) : amount;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(num || 0);
};

const formatDateTime = (dateStr: string | null): string => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
};

const getUserDisplayName = (ts: TimesheetHistoryItem): string => {
  if (ts.user_first_name && ts.user_last_name) {
    return `${ts.user_first_name} ${ts.user_last_name}`;
  }
  return ts.user_username;
};

// ===============================
// MAIN COMPONENT
// ===============================

const TimesheetHistory: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TimesheetHistoryItem[]>([]);
  const [summary, setSummary] = useState<HistorySummary | null>(null);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [showFilters, setShowFilters] = useState(false);
  
  // Filters
  const [filters, setFilters] = useState({
    user_id: '',
    status: '',
    start_date: '',
    end_date: '',
  });

  // Fetch team members for filter dropdown
  useEffect(() => {
    const fetchTeam = async () => {
      try {
        const team = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`);
        setTeamMembers(team || []);
      } catch (err) {
        console.error('Failed to fetch team:', err);
      }
    };
    fetchTeam();
  }, []);

  // Fetch history data
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filters.user_id) params.append('user_id', filters.user_id);
      if (filters.status) params.append('status', filters.status);
      if (filters.start_date) params.append('start_date', filters.start_date);
      if (filters.end_date) params.append('end_date', filters.end_date);
      
      const queryString = params.toString();
      const url = `${API_BASE}/billing/timesheet-history/${queryString ? '?' + queryString : ''}`;
      
      const response = await safeFetchJson<HistoryResponse>(url);
      setData(response.timesheets || []);
      setSummary(response.summary || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Status badge component
  const StatusBadge: React.FC<{ status: string; autoSubmitted?: boolean }> = ({ status, autoSubmitted }) => {
    return (
      <div className="flex flex-col items-center gap-1">
        {status === 'approved' && (
          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full bg-green-100 text-green-700">
            <CheckCircle className="w-3 h-3" />
            Approved
          </span>
        )}
        {status === 'locked' && (
          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full bg-slate-100 text-slate-700">
            <Lock className="w-3 h-3" />
            Locked
          </span>
        )}
        {autoSubmitted && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-amber-100 text-amber-700" title="Auto-submitted by system">
            <Clock className="w-3 h-3" />
            Auto
          </span>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
            <FileText className="w-5 h-5 text-blue-600" />
            Timesheet History
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            View approved and locked timesheets
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-2 px-4 py-2 text-sm border rounded-lg transition-colors ${
              showFilters 
                ? 'bg-blue-50 border-blue-200 text-blue-700'
                : 'border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            <Filter className="w-4 h-4" />
            Filters
            {showFilters ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          <button
            onClick={fetchData}
            className="flex items-center gap-2 px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Filters Panel */}
      {showFilters && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
          <div className="grid grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Employee</label>
              <select
                value={filters.user_id}
                onChange={(e) => setFilters({ ...filters, user_id: e.target.value })}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              >
                <option value="">All Employees</option>
                {teamMembers.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.first_name} {member.last_name || member.username}
                  </option>
                ))}
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Status</label>
              <select
                value={filters.status}
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              >
                <option value="">All Statuses</option>
                <option value="approved">Approved</option>
                <option value="locked">Locked</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">From Week</label>
              <input
                type="date"
                value={filters.start_date}
                onChange={(e) => setFilters({ ...filters, start_date: e.target.value })}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">To Week</label>
              <input
                type="date"
                value={filters.end_date}
                onChange={(e) => setFilters({ ...filters, end_date: e.target.value })}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
          
          <div className="flex justify-end mt-4">
            <button
              onClick={() => setFilters({ user_id: '', status: '', start_date: '', end_date: '' })}
              className="text-sm text-slate-500 hover:text-slate-700"
            >
              Clear Filters
            </button>
          </div>
        </div>
      )}

      {/* Summary Cards - Use backend summary */}
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
            <FileText className="w-4 h-4" />
            Timesheets
          </div>
          <div className="text-2xl font-bold text-slate-800">
            {summary?.total_timesheets ?? data.length}
          </div>
        </div>
        
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
            <Clock className="w-4 h-4" />
            Total Hours
          </div>
          <div className="text-2xl font-bold text-slate-800">
            {(summary?.total_hours ?? 0).toFixed(1)}
          </div>
        </div>
        
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
            <Clock className="w-4 h-4" />
            Billable Hours
          </div>
          <div className="text-2xl font-bold text-blue-600">
            {(summary?.billable_hours ?? 0).toFixed(1)}
          </div>
        </div>
        
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
            <DollarSign className="w-4 h-4" />
            Total Value
          </div>
          <div className="text-2xl font-bold text-green-600">
            {formatCurrency(summary?.total_amount ?? '0')}
          </div>
        </div>
        
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
            <AlertCircle className="w-4 h-4" />
            Auto-Submitted
          </div>
          <div className="text-2xl font-bold text-amber-600">
            {summary?.auto_submitted_count ?? 0}
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          {error}
        </div>
      )}

      {/* Loading State */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-8 h-8 text-blue-500 animate-spin" />
        </div>
      ) : (
        /* Table */
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Employee</th>
                <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Week</th>
                <th className="text-center px-4 py-3 text-sm font-semibold text-slate-700">Status</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Total</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Billable</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Amount</th>
                <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Approved</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-500">
                    <FileText className="w-12 h-12 mx-auto mb-3 text-slate-300" />
                    <p>No approved timesheets found</p>
                    <p className="text-sm mt-1">Timesheets will appear here after they're approved</p>
                  </td>
                </tr>
              ) : (
                data.map((ts) => (
                  <tr 
                    key={ts.id} 
                    className={`hover:bg-slate-50 transition-colors ${
                      ts.auto_submitted ? 'bg-amber-50/30' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-blue-600 rounded-full flex items-center justify-center text-white font-medium text-sm">
                          {getUserDisplayName(ts).charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <div className="font-medium text-slate-800">{getUserDisplayName(ts)}</div>
                          <div className="text-xs text-slate-500">{ts.user_email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 text-slate-700">
                        <Calendar className="w-4 h-4 text-slate-400" />
                        {formatDateRange(ts.week_start, ts.week_end)}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <StatusBadge status={ts.status} autoSubmitted={ts.auto_submitted} />
                    </td>
                    <td className="px-4 py-3 text-right text-slate-700">
                      {ts.total_hours.toFixed(1)}h
                    </td>
                    <td className="px-4 py-3 text-right text-blue-600 font-medium">
                      {ts.billable_hours.toFixed(1)}h
                    </td>
                    <td className="px-4 py-3 text-right text-green-600 font-semibold">
                      {formatCurrency(ts.total_amount)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-sm text-slate-600">
                        {formatDateTime(ts.approved_at)}
                      </div>
                      {ts.approved_by_username && (
                        <div className="text-xs text-slate-400">
                          by {ts.approved_by_username}
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default TimesheetHistory;