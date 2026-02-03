// src/components/ClientProfitability.tsx
// Realization Dashboard: Budget (Billed) vs Actual (Worked)

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  TrendingUp,
  TrendingDown,
  Clock,
  DollarSign,
  Users,
  Calendar,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Upload,
  AlertCircle,
  CheckCircle2,
  Target,
  FileSpreadsheet,
  Link2,
  X,
} from 'lucide-react';

// ===============================
// TYPES
// ===============================

interface ClientRealization {
  client_id: number;
  client_name: string;
  client_code: string;
  billed_hours: number;
  billed_amount: number;
  worked_hours: number;
  variance_hours: number | null;
  realization: number | null;
  status: 'excellent' | 'good' | 'warning' | 'critical' | 'no_data';
}

interface RealizationSummary {
  period_start: string;
  period_end: string;
  clients: ClientRealization[];
  totals: {
    billed_hours: number;
    billed_amount: number;
    worked_hours: number;
    variance_hours: number;
    realization: number | null;
    status: string;
  };
}

interface Invoice {
  id: number;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  hours_billed: number | null;
  client_id: number | null;
  client_name: string;
  client_code: string;
  matched: boolean;
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

const formatHours = (hours: number): string => {
  return hours.toFixed(1);
};

const formatPercent = (value: number | null): string => {
  if (value === null) return '—';
  return `${value.toFixed(0)}%`;
};

const getStatusColor = (status: string): string => {
  switch (status) {
    case 'excellent': return 'text-emerald-600';
    case 'good': return 'text-green-600';
    case 'warning': return 'text-amber-600';
    case 'critical': return 'text-red-600';
    default: return 'text-slate-400';
  }
};

const getStatusBg = (status: string): string => {
  switch (status) {
    case 'excellent': return 'bg-emerald-50 border-emerald-200';
    case 'good': return 'bg-green-50 border-green-200';
    case 'warning': return 'bg-amber-50 border-amber-200';
    case 'critical': return 'bg-red-50 border-red-200';
    default: return 'bg-slate-50 border-slate-200';
  }
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'excellent':
    case 'good':
      return <TrendingUp className="w-4 h-4" />;
    case 'warning':
    case 'critical':
      return <TrendingDown className="w-4 h-4" />;
    default:
      return <Target className="w-4 h-4" />;
  }
};

const getStatusLabel = (status: string): string => {
  switch (status) {
    case 'excellent': return 'Excellent';
    case 'good': return 'On Target';
    case 'warning': return 'Over Budget';
    case 'critical': return 'Needs Review';
    default: return 'No Data';
  }
};

// ===============================
// CSV UPLOAD MODAL
// ===============================

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const UploadModal: React.FC<UploadModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    setResult(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_BASE}/billing/invoices/import-csv/`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || 'Upload failed');
      } else {
        setResult(data);
        if (data.summary.imported > 0) {
          onSuccess();
        }
      }
    } catch (err) {
      setError('Failed to upload file');
    } finally {
      setUploading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center">
              <Upload className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-800">Import Invoices</h3>
              <p className="text-sm text-slate-500">Upload CSV from QuickBooks/Xero</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 space-y-5">
          {/* Format Guide */}
          <div className="bg-slate-50 rounded-xl p-4">
            <h4 className="font-medium text-slate-700 mb-2 flex items-center gap-2">
              <FileSpreadsheet className="w-4 h-4" />
              Expected CSV Format
            </h4>
            <code className="text-xs text-slate-600 block bg-white p-3 rounded-lg border border-slate-200 font-mono">
              client_code,invoice_number,invoice_date,amount,hours_billed<br/>
              MAVOPS,INV-001,2026-02-01,1500.00,10<br/>
              DAUPH,INV-002,2026-02-01,2000.00,15
            </code>
            <p className="text-xs text-slate-500 mt-2">
              <strong>Required:</strong> client_code, invoice_number, invoice_date, amount<br/>
              <strong>Optional:</strong> hours_billed
            </p>
          </div>

          {/* Upload Area */}
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
              uploading ? 'bg-blue-50 border-blue-300' : 'hover:bg-slate-50 border-slate-300'
            }`}
            onClick={() => fileRef.current?.click()}
          >
            {uploading ? (
              <RefreshCw className="w-8 h-8 text-blue-500 animate-spin mx-auto mb-3" />
            ) : (
              <Upload className="w-8 h-8 text-slate-400 mx-auto mb-3" />
            )}
            <p className="text-slate-600 font-medium">
              {uploading ? 'Uploading...' : 'Click to select CSV file'}
            </p>
            <p className="text-sm text-slate-400 mt-1">or drag and drop</p>
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              onChange={handleUpload}
              className="hidden"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-red-700 font-medium">Import Failed</p>
                <p className="text-red-600 text-sm mt-1">{error}</p>
              </div>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-5 h-5 text-green-600" />
                <span className="font-medium text-green-800">Import Complete</span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-green-600">{result.summary.imported}</div>
                  <div className="text-xs text-slate-500">Imported</div>
                </div>
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-amber-600">{result.summary.skipped}</div>
                  <div className="text-xs text-slate-500">Skipped</div>
                </div>
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-slate-600">{result.summary.unmatched_clients}</div>
                  <div className="text-xs text-slate-500">Unmatched</div>
                </div>
              </div>
              {result.summary.unmatched_clients > 0 && (
                <p className="text-xs text-amber-700 mt-3">
                  ⚠️ Some invoices have unmatched client codes. You can match them manually in the Invoices tab.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-5 border-t border-slate-200 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            {result ? 'Done' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ===============================
// MAIN COMPONENT
// ===============================

const ClientProfitability: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<RealizationSummary | null>(null);
  const [expandedClient, setExpandedClient] = useState<number | null>(null);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [activeTab, setActiveTab] = useState<'realization' | 'invoices'>('realization');
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  
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

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        start_date: dateRange.start,
        end_date: dateRange.end,
      });
      
      const result = await safeFetchJson<RealizationSummary>(
        `${API_BASE}/billing/realization/?${params}`
      );
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [dateRange]);

  const fetchInvoices = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        start_date: dateRange.start,
        end_date: dateRange.end,
      });
      const result = await safeFetchJson<{ invoices: Invoice[] }>(
        `${API_BASE}/billing/invoices/?${params}`
      );
      setInvoices(result.invoices);
    } catch (err) {
      console.error('Failed to load invoices:', err);
    }
  }, [dateRange]);

  useEffect(() => {
    fetchData();
    fetchInvoices();
  }, [fetchData, fetchInvoices]);

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
  if (loading && !data) {
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
          <h1 className="text-2xl font-bold text-slate-800">Realization</h1>
          <p className="text-slate-500 mt-1">Budget (Billed) vs Actual (Worked) Analysis</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowUploadModal(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Upload className="w-4 h-4" />
            Import Invoices
          </button>
          <button
            onClick={() => { fetchData(); fetchInvoices(); }}
            className="flex items-center gap-2 px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
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
              className="px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <span className="text-slate-400">to</span>
            <input
              type="date"
              value={dateRange.end}
              onChange={(e) => setDateRange({ ...dateRange, end: e.target.value })}
              className="px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
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
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-100 rounded-lg w-fit">
        <button
          onClick={() => setActiveTab('realization')}
          className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
            activeTab === 'realization'
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-600 hover:text-slate-800'
          }`}
        >
          <Target className="w-4 h-4 inline mr-2" />
          Realization
        </button>
        <button
          onClick={() => setActiveTab('invoices')}
          className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
            activeTab === 'invoices'
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-600 hover:text-slate-800'
          }`}
        >
          <FileSpreadsheet className="w-4 h-4 inline mr-2" />
          Invoices ({invoices.length})
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500" />
          <span className="text-red-700">{error}</span>
        </div>
      )}

      {/* Realization Tab */}
      {activeTab === 'realization' && data && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
                <DollarSign className="w-4 h-4" />
                Billed (Budget)
              </div>
              <div className="text-2xl font-bold text-slate-800">
                {formatHours(data.totals.billed_hours)}h
              </div>
              <div className="text-sm text-slate-500 mt-1">
                {formatCurrency(data.totals.billed_amount)} invoiced
              </div>
            </div>
            
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
                <Clock className="w-4 h-4" />
                Worked (Actual)
              </div>
              <div className="text-2xl font-bold text-slate-800">
                {formatHours(data.totals.worked_hours)}h
              </div>
              <div className="text-sm text-slate-500 mt-1">
                Billable time tracked
              </div>
            </div>
            
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex items-center gap-2 text-slate-500 text-sm mb-1">
                {data.totals.variance_hours >= 0 ? (
                  <TrendingUp className="w-4 h-4 text-green-500" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-red-500" />
                )}
                Variance
              </div>
              <div className={`text-2xl font-bold ${
                data.totals.variance_hours >= 0 ? 'text-green-600' : 'text-red-600'
              }`}>
                {data.totals.variance_hours >= 0 ? '+' : ''}{formatHours(data.totals.variance_hours)}h
              </div>
              <div className="text-sm text-slate-500 mt-1">
                {data.totals.variance_hours >= 0 ? 'Under budget' : 'Over budget'}
              </div>
            </div>
            
            <div className={`rounded-xl p-5 border ${getStatusBg(data.totals.status)}`}>
              <div className="flex items-center gap-2 text-slate-600 text-sm mb-1">
                <Target className="w-4 h-4" />
                Realization
              </div>
              <div className={`text-2xl font-bold ${getStatusColor(data.totals.status)}`}>
                {formatPercent(data.totals.realization)}
              </div>
              <div className={`text-sm mt-1 ${getStatusColor(data.totals.status)}`}>
                {getStatusLabel(data.totals.status)}
              </div>
            </div>
          </div>

          {/* Client List */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Client</th>
                  <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">
                    <span className="flex items-center justify-end gap-1">
                      <DollarSign className="w-3.5 h-3.5" />
                      Billed
                    </span>
                  </th>
                  <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">
                    <span className="flex items-center justify-end gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      Worked
                    </span>
                  </th>
                  <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Variance</th>
                  <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Realization</th>
                  <th className="text-center px-4 py-3 text-sm font-semibold text-slate-700">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.clients.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center py-12">
                      <Target className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                      <p className="text-slate-500 font-medium">No data for this period</p>
                      <p className="text-slate-400 text-sm mt-1">
                        Import invoices or adjust the date range
                      </p>
                      <button
                        onClick={() => setShowUploadModal(true)}
                        className="mt-4 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
                      >
                        Import Invoices
                      </button>
                    </td>
                  </tr>
                ) : (
                  data.clients.map((client) => (
                    <tr 
                      key={client.client_id}
                      className="hover:bg-slate-50 transition-colors"
                    >
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-3">
                          <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold text-sm ${
                            client.status === 'critical' ? 'bg-gradient-to-br from-red-500 to-red-600' :
                            client.status === 'warning' ? 'bg-gradient-to-br from-amber-500 to-amber-600' :
                            client.status === 'excellent' ? 'bg-gradient-to-br from-emerald-500 to-emerald-600' :
                            'bg-gradient-to-br from-blue-500 to-blue-600'
                          }`}>
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
                      <td className="px-4 py-4 text-right">
                        <div className="font-medium text-slate-800">{formatHours(client.billed_hours)}h</div>
                        <div className="text-xs text-slate-500">{formatCurrency(client.billed_amount)}</div>
                      </td>
                      <td className="px-4 py-4 text-right text-slate-700">
                        {formatHours(client.worked_hours)}h
                      </td>
                      <td className="px-4 py-4 text-right">
                        {client.variance_hours !== null ? (
                          <span className={client.variance_hours >= 0 ? 'text-green-600' : 'text-red-600'}>
                            {client.variance_hours >= 0 ? '+' : ''}{formatHours(client.variance_hours)}h
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-4 text-right">
                        <span className={`text-lg font-bold ${getStatusColor(client.status)}`}>
                          {formatPercent(client.realization)}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex justify-center">
                          <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ${getStatusBg(client.status)} ${getStatusColor(client.status)}`}>
                            {getStatusIcon(client.status)}
                            {getStatusLabel(client.status)}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Realization Guide */}
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-5">
            <h4 className="font-medium text-slate-700 mb-3">Understanding Realization</h4>
            <div className="grid grid-cols-2 gap-6 text-sm">
              <div>
                <p className="text-slate-600 mb-2">
                  <strong>Realization</strong> = Billed Hours ÷ Worked Hours × 100
                </p>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-emerald-500"></div>
                    <span className="text-slate-600"><strong>125%+</strong> — Excellent! Very efficient</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-green-500"></div>
                    <span className="text-slate-600"><strong>100-125%</strong> — On target or under budget</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-amber-500"></div>
                    <span className="text-slate-600"><strong>85-100%</strong> — Slightly over budget</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-red-500"></div>
                    <span className="text-slate-600"><strong>&lt;85%</strong> — Significantly over, needs review</span>
                  </div>
                </div>
              </div>
              <div className="border-l border-slate-200 pl-6">
                <p className="text-slate-600 mb-2"><strong>Example:</strong></p>
                <div className="space-y-2 text-slate-600">
                  <p>• Billed 10h, Worked 8h → <span className="text-emerald-600 font-medium">125% ✓</span> (efficient!)</p>
                  <p>• Billed 10h, Worked 10h → <span className="text-green-600 font-medium">100%</span> (break even)</p>
                  <p>• Billed 10h, Worked 12h → <span className="text-red-600 font-medium">83%</span> (over budget)</p>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Invoices Tab */}
      {activeTab === 'invoices' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Invoice #</th>
                <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Date</th>
                <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Client</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Amount</th>
                <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Hours</th>
                <th className="text-center px-4 py-3 text-sm font-semibold text-slate-700">Matched</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {invoices.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-12">
                    <FileSpreadsheet className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                    <p className="text-slate-500 font-medium">No invoices imported yet</p>
                    <p className="text-slate-400 text-sm mt-1">
                      Import from CSV or connect QuickBooks/Xero
                    </p>
                    <button
                      onClick={() => setShowUploadModal(true)}
                      className="mt-4 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      Import CSV
                    </button>
                  </td>
                </tr>
              ) : (
                invoices.map((inv) => (
                  <tr key={inv.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-mono text-sm text-slate-800">{inv.invoice_number}</td>
                    <td className="px-4 py-3 text-slate-600">{inv.invoice_date}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{inv.client_name}</div>
                      {inv.client_code && (
                        <div className="text-xs text-slate-500">{inv.client_code}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-slate-800">
                      {formatCurrency(inv.amount)}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-600">
                      {inv.hours_billed ? `${inv.hours_billed}h` : '—'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {inv.matched ? (
                        <span className="inline-flex items-center gap-1 text-green-600">
                          <CheckCircle2 className="w-4 h-4" />
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-amber-600">
                          <Link2 className="w-4 h-4" />
                          <span className="text-xs">Match</span>
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Upload Modal */}
      <UploadModal
        isOpen={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        onSuccess={() => {
          fetchData();
          fetchInvoices();
        }}
      />
    </div>
  );
};

export default ClientProfitability;