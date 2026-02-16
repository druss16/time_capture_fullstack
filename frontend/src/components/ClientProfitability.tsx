// src/components/ClientProfitability.tsx
// Realization Dashboard: Budget (Billed) vs Actual (Worked)
// With QuickBooks/Xero Integration + Inline Editing + Export

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { safeFetchJson, safeUploadFile, API_BASE } from '@/lib/api';
import {
  TrendingUp,
  TrendingDown,
  Clock,
  DollarSign,
  Calendar,
  RefreshCw,
  Upload,
  AlertCircle,
  CheckCircle2,
  Target,
  FileSpreadsheet,
  Link2,
  X,
  Download,
  ExternalLink,
  Check,
  Square,
  CheckSquare,
  Loader2,
  Pencil,
  Save,
  FileDown,
  Send,
} from 'lucide-react';

import IntegrationStatusBanner from '@/components/IntegrationStatusBanner';


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

interface QBInvoice {
  id: string;
  doc_number: string;
  date: string;
  customer_name: string;
  customer_id: string;
  amount: number;
  hours: number | null;
  status: string;
  already_imported: boolean;
  client_matched: boolean;
  client_name: string | null;
}

interface DateRange {
  start: string;
  end: string;
}

interface Integration {
  id: number;
  provider: string;
  is_connected: boolean;
  company_name?: string;
}

interface EditingBilled {
  clientId: number;
  hours: string;
  amount: string;
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

// Calculate realization and status from hours
const calculateRealization = (billedHours: number, workedHours: number) => {
  if (workedHours <= 0 || billedHours <= 0) {
    return { realization: null, variance: null, status: 'no_data' };
  }
  
  const realization = (billedHours / workedHours) * 100;
  const variance = billedHours - workedHours;
  
  let status: string;
  if (realization >= 125) status = 'excellent';
  else if (realization >= 100) status = 'good';
  else if (realization >= 85) status = 'warning';
  else status = 'critical';
  
  return { realization, variance, status };
};

// ===============================
// EXPORT MODAL
// ===============================

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: RealizationSummary | null;
  dateRange: DateRange;
}

const ExportModal: React.FC<ExportModalProps> = ({ isOpen, onClose, data, dateRange }) => {
  const [exporting, setExporting] = useState(false);
  const [exportType, setExportType] = useState<'csv' | 'quickbooks'>('csv');
  const [qbConnected, setQbConnected] = useState(false);

  useEffect(() => {
    if (isOpen) {
      safeFetchJson<any>(`${API_BASE}/integrations/status/`)
        .then(res => {
          setQbConnected(res.integrations?.quickbooks?.connected || false);
        })
        .catch(() => {});
    }
  }, [isOpen]);

  const handleExportCSV = () => {
    if (!data) return;
    
    // Build CSV content
    const headers = ['Client Code', 'Client Name', 'Worked Hours', 'Billed Hours', 'Billed Amount', 'Variance Hours', 'Realization %', 'Status'];
    const rows = data.clients.map(c => [
      c.client_code || '',
      c.client_name,
      c.worked_hours.toFixed(2),
      c.billed_hours.toFixed(2),
      c.billed_amount.toFixed(2),
      c.variance_hours?.toFixed(2) || '',
      c.realization?.toFixed(1) || '',
      c.status,
    ]);
    
    // Add totals row
    rows.push([
      '',
      'TOTALS',
      data.totals.worked_hours.toFixed(2),
      data.totals.billed_hours.toFixed(2),
      data.totals.billed_amount.toFixed(2),
      data.totals.variance_hours.toFixed(2),
      data.totals.realization?.toFixed(1) || '',
      data.totals.status,
    ]);
    
    const csvContent = [
      `# Realization Report: ${dateRange.start} to ${dateRange.end}`,
      headers.join(','),
      ...rows.map(r => r.map(cell => `"${cell}"`).join(',')),
    ].join('\n');
    
    // Download
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `realization-${dateRange.start}-to-${dateRange.end}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    
    onClose();
  };

  const handleExportWorkedHoursCSV = () => {
    if (!data) return;
    
    // Export just worked hours for import into other systems
    const headers = ['client_code', 'client_name', 'period_start', 'period_end', 'worked_hours'];
    const rows = data.clients.map(c => [
      c.client_code || '',
      c.client_name,
      dateRange.start,
      dateRange.end,
      c.worked_hours.toFixed(2),
    ]);
    
    const csvContent = [
      headers.join(','),
      ...rows.map(r => r.map(cell => `"${cell}"`).join(',')),
    ].join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `worked-hours-${dateRange.start}-to-${dateRange.end}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    
    onClose();
  };

  const handleSyncToQB = async () => {
    setExporting(true);
    try {
      // This would sync time entries to QuickBooks
      await safeFetchJson(`${API_BASE}/integrations/quickbooks/push-time/`, {
        method: 'POST',
        body: JSON.stringify({
          start_date: dateRange.start,
          end_date: dateRange.end,
        }),
      });
      onClose();
    } catch (err) {
      console.error('Failed to sync to QuickBooks:', err);
    } finally {
      setExporting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full">
        <div className="flex items-center justify-between p-5 border-b border-slate-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center">
              <FileDown className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-800">Export Data</h3>
              <p className="text-sm text-slate-500">Download or sync your data</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg">
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        <div className="p-5 space-y-3">
          {/* Export Worked Hours CSV */}
          <button
            onClick={handleExportWorkedHoursCSV}
            className="w-full p-4 border-2 border-slate-200 rounded-xl hover:border-emerald-300 hover:bg-emerald-50 transition-all text-left group"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-emerald-100 rounded-lg flex items-center justify-center group-hover:bg-emerald-200 transition-colors">
                <Clock className="w-5 h-5 text-emerald-600" />
              </div>
              <div>
                <div className="font-semibold text-slate-800">Export Worked Hours</div>
                <div className="text-sm text-slate-500">CSV for import into QB/Xero</div>
              </div>
            </div>
          </button>

          {/* Export Full Report CSV */}
          <button
            onClick={handleExportCSV}
            className="w-full p-4 border-2 border-slate-200 rounded-xl hover:border-blue-300 hover:bg-blue-50 transition-all text-left group"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center group-hover:bg-blue-200 transition-colors">
                <FileSpreadsheet className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <div className="font-semibold text-slate-800">Export Full Report</div>
                <div className="text-sm text-slate-500">Billed vs Worked comparison</div>
              </div>
            </div>
          </button>

          {/* Sync to QuickBooks */}
          <button
            onClick={handleSyncToQB}
            disabled={!qbConnected || exporting}
            className={`w-full p-4 border-2 rounded-xl text-left group transition-all ${
              qbConnected 
                ? 'border-slate-200 hover:border-green-300 hover:bg-green-50' 
                : 'border-slate-200 opacity-50 cursor-not-allowed'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-xl ${
                qbConnected ? 'bg-green-100 group-hover:bg-green-200' : 'bg-slate-100'
              }`}>
                📗
              </div>
              <div className="flex-1">
                <div className="font-semibold text-slate-800">Sync to QuickBooks</div>
                <div className="text-sm text-slate-500">
                  {qbConnected ? 'Push time entries to QB' : 'Not connected'}
                </div>
              </div>
              {exporting && <Loader2 className="w-5 h-5 animate-spin text-green-600" />}
            </div>
          </button>

          {/* Xero Coming Soon */}
          <button
            disabled
            className="w-full p-4 border-2 border-slate-200 rounded-xl text-left opacity-50 cursor-not-allowed"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center text-xl">
                📘
              </div>
              <div>
                <div className="font-semibold text-slate-800">Sync to Xero</div>
                <div className="text-sm text-slate-400">Coming Soon</div>
              </div>
            </div>
          </button>
        </div>

        <div className="p-5 border-t border-slate-200">
          <button
            onClick={onClose}
            className="w-full py-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

// ===============================
// IMPORT MODAL (CSV + QuickBooks + Xero)
// ===============================

interface ImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  dateRange: DateRange;
}

type ImportSource = 'csv' | 'quickbooks' | 'xero' | 'manual';

const ImportModal: React.FC<ImportModalProps> = ({ isOpen, onClose, onSuccess, dateRange }) => {
  const [source, setSource] = useState<ImportSource>('csv');
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  
  // QuickBooks state
  const [qbConnected, setQbConnected] = useState(false);
  const [qbCompanyName, setQbCompanyName] = useState<string | null>(null);
  const [qbInvoices, setQbInvoices] = useState<QBInvoice[]>([]);
  const [qbLoading, setQbLoading] = useState(false);
  const [selectedQbInvoices, setSelectedQbInvoices] = useState<Set<string>>(new Set());
  
  useEffect(() => {
    if (isOpen) {
      checkIntegrations();
    }
  }, [isOpen]);

  const checkIntegrations = async () => {
    try {
      const data = await safeFetchJson<{ integrations: Integration[] }>(
        `${API_BASE}/integrations/status/`
      );
      const qb = data.integrations?.find(i => i.provider === 'quickbooks');
      if (qb?.is_connected) {
        setQbConnected(true);
        setQbCompanyName(qb.company_name || 'QuickBooks');
      }
    } catch (err) {
      console.error('Failed to check integrations:', err);
    }
  };

  const handleCSVUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    setResult(null);

    try {
      const data = await safeUploadFile<any>(
        `${API_BASE}/billing/invoices/import-csv/`,
        file,
        'file'
      );
      
      setResult(data);
      if (data.summary?.imported > 0) {
        onSuccess();
      }
    } catch (err: any) {
      let errorMessage = 'Upload failed';
      if (err.message) {
        try {
          const match = err.message.match(/HTTP \d+: (.+)/);
          if (match) {
            const parsed = JSON.parse(match[1]);
            errorMessage = parsed.error || parsed.message || errorMessage;
          } else {
            errorMessage = err.message;
          }
        } catch {
          errorMessage = err.message;
        }
      }
      setError(errorMessage);
    } finally {
      setUploading(false);
    }
  };

  const fetchQBInvoices = async () => {
    setQbLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        start_date: dateRange.start,
        end_date: dateRange.end,
      });
      const data = await safeFetchJson<{ invoices: QBInvoice[]; total: number }>(
        `${API_BASE}/integrations/quickbooks/invoices/?${params}`
      );
      setQbInvoices(data.invoices || []);
      
      const notImported = data.invoices?.filter(i => !i.already_imported).map(i => i.id) || [];
      setSelectedQbInvoices(new Set(notImported));
    } catch (err: any) {
      setError(err.message || 'Failed to fetch QuickBooks invoices');
    } finally {
      setQbLoading(false);
    }
  };

  const handleQBImport = async () => {
    if (selectedQbInvoices.size === 0) return;
    
    setUploading(true);
    setError(null);
    
    try {
      const data = await safeFetchJson<any>(`${API_BASE}/integrations/quickbooks/import/`, {
        method: 'POST',
        body: JSON.stringify({
          invoice_ids: Array.from(selectedQbInvoices),
        }),
      });
      
      setResult({
        source: 'quickbooks',
        summary: {
          imported: data.imported?.length || 0,
          skipped: data.skipped?.length || 0,
          errors: data.errors?.length || 0,
        }
      });
      
      if (data.imported?.length > 0) {
        onSuccess();
      }
    } catch (err: any) {
      setError(err.message || 'Failed to import from QuickBooks');
    } finally {
      setUploading(false);
    }
  };

  const toggleQBInvoice = (id: string) => {
    const newSelected = new Set(selectedQbInvoices);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedQbInvoices(newSelected);
  };

  const toggleAllQB = () => {
    const importable = qbInvoices.filter(i => !i.already_imported);
    if (selectedQbInvoices.size === importable.length) {
      setSelectedQbInvoices(new Set());
    } else {
      setSelectedQbInvoices(new Set(importable.map(i => i.id)));
    }
  };

  useEffect(() => {
    if (!isOpen) {
      setResult(null);
      setError(null);
      setUploading(false);
      setQbInvoices([]);
      setSelectedQbInvoices(new Set());
      setSource('csv');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between p-5 border-b border-slate-200 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center">
              <Upload className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-800">Import Billed Data</h3>
              <p className="text-sm text-slate-500">CSV, QuickBooks, or enter manually</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto flex-1">
          {!result && (
            <div className="grid grid-cols-3 gap-3 mb-6">
              <button
                onClick={() => setSource('csv')}
                className={`p-4 rounded-xl border-2 text-left transition-all ${
                  source === 'csv'
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center mb-3">
                  <FileSpreadsheet className="w-5 h-5 text-slate-600" />
                </div>
                <div className="font-semibold text-slate-800">CSV File</div>
                <div className="text-xs text-slate-500 mt-1">Upload from Excel</div>
              </button>

              <button
                onClick={() => {
                  setSource('quickbooks');
                  if (qbConnected && qbInvoices.length === 0) {
                    fetchQBInvoices();
                  }
                }}
                className={`p-4 rounded-xl border-2 text-left transition-all ${
                  source === 'quickbooks'
                    ? 'border-green-500 bg-green-50'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center mb-3 text-xl">
                  📗
                </div>
                <div className="font-semibold text-slate-800">QuickBooks</div>
                <div className="text-xs mt-1">
                  {qbConnected ? (
                    <span className="text-green-600 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      Connected
                    </span>
                  ) : (
                    <span className="text-slate-500">Not connected</span>
                  )}
                </div>
              </button>

              <button
                onClick={() => setSource('manual')}
                className={`p-4 rounded-xl border-2 text-left transition-all ${
                  source === 'manual'
                    ? 'border-purple-500 bg-purple-50'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center mb-3">
                  <Pencil className="w-5 h-5 text-purple-600" />
                </div>
                <div className="font-semibold text-slate-800">Manual Entry</div>
                <div className="text-xs text-slate-500 mt-1">Edit in table</div>
              </button>
            </div>
          )}

          {/* Manual Entry Instructions */}
          {source === 'manual' && !result && (
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-purple-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Pencil className="w-8 h-8 text-purple-600" />
              </div>
              <h4 className="font-semibold text-slate-800 mb-2">Manual Entry Mode</h4>
              <p className="text-slate-500 text-sm mb-4">
                Close this modal and click the <Pencil className="w-4 h-4 inline" /> icon next to any client's billed hours to edit directly in the table.
              </p>
              <button
                onClick={onClose}
                className="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
              >
                Got it, let me edit
              </button>
            </div>
          )}

          {/* CSV Upload */}
          {source === 'csv' && !result && (
            <>
              <div className="bg-slate-50 rounded-xl p-4 mb-4">
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

              <div
                className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                  uploading ? 'bg-blue-50 border-blue-300' : 'hover:bg-slate-50 border-slate-300'
                }`}
                onClick={() => fileRef.current?.click()}
              >
                {uploading ? (
                  <Loader2 className="w-8 h-8 text-blue-500 animate-spin mx-auto mb-3" />
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
                  onChange={handleCSVUpload}
                  className="hidden"
                />
              </div>
            </>
          )}

          {/* QuickBooks */}
          {source === 'quickbooks' && !result && (
            <>
              {!qbConnected ? (
                <div className="text-center py-8">
                  <div className="w-16 h-16 bg-green-100 rounded-2xl flex items-center justify-center mx-auto mb-4 text-3xl">
                    📗
                  </div>
                  <h4 className="font-semibold text-slate-800 mb-2">Connect QuickBooks</h4>
                  <p className="text-slate-500 text-sm mb-4">
                    Connect your QuickBooks account to import invoices automatically
                  </p>
                  <a
                    href="/settings?tab=integrations"
                    className="inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                  >
                    <ExternalLink className="w-4 h-4" />
                    Go to Settings
                  </a>
                </div>
              ) : qbLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-8 h-8 text-green-500 animate-spin" />
                </div>
              ) : qbInvoices.length === 0 ? (
                <div className="text-center py-8">
                  <FileSpreadsheet className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                  <p className="text-slate-500 font-medium">No invoices found</p>
                  <p className="text-slate-400 text-sm mt-1">
                    No invoices in QuickBooks for {dateRange.start} to {dateRange.end}
                  </p>
                  <button
                    onClick={fetchQBInvoices}
                    className="mt-4 px-4 py-2 text-green-600 hover:bg-green-50 rounded-lg transition-colors"
                  >
                    <RefreshCw className="w-4 h-4 inline mr-2" />
                    Refresh
                  </button>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-700">
                        {qbInvoices.length} invoice{qbInvoices.length !== 1 ? 's' : ''} from {qbCompanyName}
                      </span>
                      <button
                        onClick={fetchQBInvoices}
                        className="p-1 hover:bg-slate-100 rounded transition-colors"
                      >
                        <RefreshCw className="w-4 h-4 text-slate-400" />
                      </button>
                    </div>
                    <button
                      onClick={toggleAllQB}
                      className="text-sm text-blue-600 hover:text-blue-700"
                    >
                      {selectedQbInvoices.size === qbInvoices.filter(i => !i.already_imported).length
                        ? 'Deselect All'
                        : 'Select All'}
                    </button>
                  </div>

                  <div className="border border-slate-200 rounded-xl max-h-64 overflow-y-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-50 sticky top-0">
                        <tr>
                          <th className="w-10 px-3 py-2"></th>
                          <th className="text-left px-3 py-2 font-medium text-slate-700">Invoice</th>
                          <th className="text-left px-3 py-2 font-medium text-slate-700">Customer</th>
                          <th className="text-right px-3 py-2 font-medium text-slate-700">Amount</th>
                          <th className="text-center px-3 py-2 font-medium text-slate-700">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {qbInvoices.map((inv) => (
                          <tr
                            key={inv.id}
                            className={`${inv.already_imported ? 'bg-slate-50 opacity-60' : 'hover:bg-slate-50'}`}
                          >
                            <td className="px-3 py-2">
                              {inv.already_imported ? (
                                <CheckCircle2 className="w-5 h-5 text-green-500" />
                              ) : (
                                <button
                                  onClick={() => toggleQBInvoice(inv.id)}
                                  className="focus:outline-none"
                                >
                                  {selectedQbInvoices.has(inv.id) ? (
                                    <CheckSquare className="w-5 h-5 text-blue-600" />
                                  ) : (
                                    <Square className="w-5 h-5 text-slate-400" />
                                  )}
                                </button>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              <div className="font-medium text-slate-800">{inv.doc_number}</div>
                              <div className="text-xs text-slate-500">{inv.date}</div>
                            </td>
                            <td className="px-3 py-2">
                              <div className="text-slate-700">{inv.customer_name}</div>
                              {inv.client_matched && (
                                <div className="text-xs text-green-600 flex items-center gap-1">
                                  <Check className="w-3 h-3" />
                                  Matched
                                </div>
                              )}
                            </td>
                            <td className="px-3 py-2 text-right font-medium text-slate-800">
                              {formatCurrency(inv.amount)}
                            </td>
                            <td className="px-3 py-2 text-center">
                              {inv.already_imported ? (
                                <span className="text-xs text-slate-500">Imported</span>
                              ) : (
                                <span className={`text-xs px-2 py-1 rounded-full ${
                                  inv.status === 'Paid'
                                    ? 'bg-green-100 text-green-700'
                                    : 'bg-amber-100 text-amber-700'
                                }`}>
                                  {inv.status}
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {selectedQbInvoices.size > 0 && (
                    <button
                      onClick={handleQBImport}
                      disabled={uploading}
                      className="mt-4 w-full py-3 bg-green-600 text-white rounded-xl font-medium hover:bg-green-700 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                      {uploading ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Importing...
                        </>
                      ) : (
                        <>
                          <Download className="w-4 h-4" />
                          Import {selectedQbInvoices.size} Invoice{selectedQbInvoices.size !== 1 ? 's' : ''}
                        </>
                      )}
                    </button>
                  )}
                </>
              )}
            </>
          )}

          {error && (
            <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-red-700 font-medium">Import Failed</p>
                <p className="text-red-600 text-sm mt-1">{error}</p>
              </div>
            </div>
          )}

          {result && (
            <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-5 h-5 text-green-600" />
                <span className="font-medium text-green-800">Import Complete</span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-green-600">{result.summary?.imported || 0}</div>
                  <div className="text-xs text-slate-500">Imported</div>
                </div>
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-amber-600">{result.summary?.skipped || 0}</div>
                  <div className="text-xs text-slate-500">Skipped</div>
                </div>
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-slate-600">{result.summary?.unmatched_clients || result.summary?.errors || 0}</div>
                  <div className="text-xs text-slate-500">{result.source === 'quickbooks' ? 'Errors' : 'Unmatched'}</div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="p-5 border-t border-slate-200 flex justify-end gap-3 flex-shrink-0">
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
// EDITABLE BILLED CELL
// ===============================

interface EditableBilledCellProps {
  clientId: number;
  clientCode: string;
  billedHours: number;
  billedAmount: number;
  onSave: (clientId: number, hours: number, amount: number) => Promise<void>;
}

const EditableBilledCell: React.FC<EditableBilledCellProps> = ({
  clientId,
  clientCode,
  billedHours,
  billedAmount,
  onSave,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [hours, setHours] = useState(billedHours.toString());
  const [amount, setAmount] = useState(billedAmount.toString());
  const [saving, setSaving] = useState(false);
  const hoursRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing && hoursRef.current) {
      hoursRef.current.focus();
      hoursRef.current.select();
    }
  }, [isEditing]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(
        clientId,
        parseFloat(hours) || 0,
        parseFloat(amount) || 0
      );
      setIsEditing(false);
    } catch (err) {
      console.error('Failed to save:', err);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setHours(billedHours.toString());
    setAmount(billedAmount.toString());
    setIsEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave();
    } else if (e.key === 'Escape') {
      handleCancel();
    }
  };

  if (isEditing) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1">
            <input
              ref={hoursRef}
              type="number"
              value={hours}
              onChange={(e) => setHours(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-16 px-2 py-1 text-sm border border-blue-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-right"
              step="0.1"
              min="0"
              placeholder="0"
            />
            <span className="text-xs text-slate-500">h</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-slate-400">$</span>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-20 px-2 py-1 text-sm border border-slate-200 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-right"
              step="1"
              min="0"
              placeholder="0"
            />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="p-1 text-green-600 hover:bg-green-50 rounded transition-colors"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
          </button>
          <button
            onClick={handleCancel}
            className="p-1 text-slate-400 hover:bg-slate-100 rounded transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-end gap-2 group">
      <div className="text-right">
        <div className="font-medium text-slate-800">{formatHours(billedHours)}h</div>
        <div className="text-xs text-slate-500">{formatCurrency(billedAmount)}</div>
      </div>
      <button
        onClick={() => setIsEditing(true)}
        className="p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded opacity-0 group-hover:opacity-100 transition-all"
        title="Edit billed hours/amount"
      >
        <Pencil className="w-4 h-4" />
      </button>
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
  const [showImportModal, setShowImportModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [activeTab, setActiveTab] = useState<'realization' | 'invoices'>('realization');
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  
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
      setInvoices(result.invoices || []);
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

  const handleImportSuccess = () => {
    fetchData();
    fetchInvoices();
  };

  // Save edited billed hours/amount
  const handleSaveBilled = async (clientId: number, hours: number, amount: number) => {
    try {
      await safeFetchJson(`${API_BASE}/billing/clients/update-billed/`, {
        method: 'POST',
        body: JSON.stringify({
          client_id: clientId,
          period_start: dateRange.start,
          period_end: dateRange.end,
          billed_hours: hours,
          billed_amount: amount,
        }),
      });
      
      // Update local state immediately
      if (data) {
        const updatedClients = data.clients.map(client => {
          if (client.client_id === clientId) {
            const calc = calculateRealization(hours, client.worked_hours);
            return {
              ...client,
              billed_hours: hours,
              billed_amount: amount,
              variance_hours: calc.variance,
              realization: calc.realization,
              status: calc.status as any,
            };
          }
          return client;
        });
        
        // Recalculate totals
        const totals = {
          billed_hours: updatedClients.reduce((sum, c) => sum + c.billed_hours, 0),
          billed_amount: updatedClients.reduce((sum, c) => sum + c.billed_amount, 0),
          worked_hours: updatedClients.reduce((sum, c) => sum + c.worked_hours, 0),
          variance_hours: 0,
          realization: null as number | null,
          status: 'no_data',
        };
        const totalCalc = calculateRealization(totals.billed_hours, totals.worked_hours);
        totals.variance_hours = totalCalc.variance || 0;
        totals.realization = totalCalc.realization;
        totals.status = totalCalc.status;
        
        setData({
          ...data,
          clients: updatedClients,
          totals,
        });
      }
    } catch (err) {
      console.error('Failed to save billed data:', err);
      throw err;
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
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
            onClick={() => setShowExportModal(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            <FileDown className="w-4 h-4" />
            Export
          </button>
          <button
            onClick={() => setShowImportModal(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Upload className="w-4 h-4" />
            Import Billed
          </button>
          <button
            onClick={() => { fetchData(); fetchInvoices(); }}
            className="flex items-center gap-2 px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
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

      {/* Integration Status */}
      <IntegrationStatusBanner
        context="profitability"
        onDataRefresh={() => { fetchData(); fetchInvoices(); }}
      />

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

          {/* Inline Edit Hint */}
          <div className="bg-purple-50 border border-purple-200 rounded-xl p-4 flex items-center gap-3">
            <Pencil className="w-5 h-5 text-purple-600" />
            <p className="text-sm text-purple-700">
              <strong>Tip:</strong> Hover over any client's "Billed" column and click the <Pencil className="w-3 h-3 inline" /> icon to edit hours and amounts directly.
            </p>
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
                      <Pencil className="w-3 h-3 text-slate-400" />
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
                        Import invoices or enter billed hours manually
                      </p>
                      <button
                        onClick={() => setShowImportModal(true)}
                        className="mt-4 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
                      >
                        Import Billed Data
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
                      <td className="px-4 py-4">
                        <EditableBilledCell
                          clientId={client.client_id}
                          clientCode={client.client_code}
                          billedHours={client.billed_hours}
                          billedAmount={client.billed_amount}
                          onSave={handleSaveBilled}
                        />
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
                      Import from CSV, QuickBooks, or enter manually
                    </p>
                    <button
                      onClick={() => setShowImportModal(true)}
                      className="mt-4 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      Import Invoices
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

      {/* Import Modal */}
      <ImportModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
        onSuccess={handleImportSuccess}
        dateRange={dateRange}
      />

      {/* Export Modal */}
      <ExportModal
        isOpen={showExportModal}
        onClose={() => setShowExportModal(false)}
        data={data}
        dateRange={dateRange}
      />
    </div>
  );
};

export default ClientProfitability;