/**
 * IntegrationInvoicePanel.tsx
 * Pull invoices from QuickBooks/Xero.
 * Lives in the Invoices tab. What it imports is what Set Fees reads back as
 * "billed last year" — the anchor a partner sets this period's fee against —
 * so this is the way that history gets into the product.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  Download,
  Calendar,
  Loader2,
  AlertCircle,
  CheckCircle2,
  TrendingUp,
  TrendingDown,
  Minus,
  CloudOff,
  Plug,
  ExternalLink,
  RefreshCw,
  ArrowDownToLine,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

interface IntegrationStatus {
  quickbooks: { connected: boolean };
  xero: { connected: boolean };
}

interface InvoiceCustomer {
  customer_name: string;
  matched: boolean;
  timetracker_client_id: number | null;
  quickbooks_id?: string;
  xero_id?: string;
  total_billed: number;
  total_paid: number;
  total_balance?: number;
  total_due?: number;
  invoice_count: number;
}

interface InvoicePullResult {
  period: { start: string; end: string };
  customers: InvoiceCustomer[];
  totals: {
    total_billed: number;
    total_paid: number;
    total_balance?: number;
    total_due?: number;
    invoice_count: number;
  };
}

type Provider = 'quickbooks' | 'xero';

const IntegrationInvoicePanel: React.FC = () => {
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeProvider, setActiveProvider] = useState<Provider | null>(null);

  // Default to current month
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
  });
  const [endDate, setEndDate] = useState(() => {
    const d = new Date();
    const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${lastDay}`;
  });

  const [result, setResult] = useState<InvoicePullResult | null>(null);
  const [pulling, setPulling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeFetchJson<IntegrationStatus>(`${API_BASE}/integrations/status/`);
      setStatus(data);
      if (data.quickbooks?.connected) setActiveProvider('quickbooks');
      else if (data.xero?.connected) setActiveProvider('xero');
    } catch (err) {
      console.error('Failed to fetch integration status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const isConnected = (p: Provider) =>
    status ? (p === 'quickbooks' ? status.quickbooks?.connected : status.xero?.connected) : false;
  const hasAnyConnection = status?.quickbooks?.connected || status?.xero?.connected;

  const handlePull = async () => {
    if (!activeProvider) return;
    setError(null);
    setResult(null);
    setPulling(true);

    try {
      const endpoint =
        activeProvider === 'quickbooks'
          ? `${API_BASE}/integrations/quickbooks/invoices/`
          : `${API_BASE}/integrations/xero/invoices/`;

      const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
      const data = await safeFetchJson<InvoicePullResult>(`${endpoint}?${params}`);
      setResult(data);
    } catch (err: any) {
      setError(err?.message || 'Failed to pull invoices.');
    } finally {
      setPulling(false);
    }
  };

  const formatCurrency = (n: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);

  const getCollectionRate = (paid: number, billed: number) => {
    if (billed <= 0) return 0;
    return Math.round((paid / billed) * 100);
  };

  const CollectionBadge: React.FC<{ rate: number }> = ({ rate }) => {
    if (rate >= 90) {
      return (
        <span className="inline-flex items-center gap-1 text-xs font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-lg">
          <TrendingUp className="w-3 h-3" />
          {rate}%
        </span>
      );
    }
    if (rate >= 70) {
      return (
        <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-lg">
          <Minus className="w-3 h-3" />
          {rate}%
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 text-xs font-bold text-red-700 bg-red-50 px-2 py-0.5 rounded-lg">
        <TrendingDown className="w-3 h-3" />
        {rate}%
      </span>
    );
  };

  // Not connected
  if (!loading && !hasAnyConnection) {
    return (
      <div className="bg-white rounded-2xl border-2 border-slate-200 p-8">
        <div className="flex flex-col items-center text-center py-8">
          <div className="w-14 h-14 rounded-2xl bg-slate-100 flex items-center justify-center mb-4">
            <CloudOff className="w-7 h-7 text-slate-400" />
          </div>
          <h3 className="text-lg font-extrabold text-slate-900 mb-2">
            No Billing System Connected
          </h3>
          <p className="text-slate-600 font-medium mb-6 max-w-sm">
            Connect QuickBooks Online or Xero to pull in what you've actually billed.
          </p>
          <a
            href="/account"
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-bold rounded-xl hover:opacity-90 transition-all shadow-lg shadow-primary/25"
          >
            <Plug className="w-4 h-4" />
            Connect in Settings
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="bg-white rounded-2xl border-2 border-slate-200 p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
          <span className="ml-3 text-slate-600 font-medium">Checking integrations...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl border-2 border-slate-200 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b-2 border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-100 flex items-center justify-center">
            <ArrowDownToLine className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <h3 className="text-base font-extrabold text-slate-900">Invoice Data</h3>
            <p className="text-sm text-slate-500 font-medium">
              Pull invoices so past fees show up alongside tracked time
            </p>
          </div>
        </div>

        {/* Provider toggle */}
        <div className="flex items-center gap-1 bg-slate-100 rounded-xl p-1">
          {(['quickbooks', 'xero'] as Provider[]).map((p) => {
            const connected = isConnected(p);
            const label = p === 'quickbooks' ? 'QuickBooks' : 'Xero';
            return (
              <button
                key={p}
                onClick={() => {
                  if (connected) {
                    setActiveProvider(p);
                    setResult(null);
                    setError(null);
                  }
                }}
                disabled={!connected}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-sm font-bold transition-all',
                  activeProvider === p
                    ? 'bg-white text-slate-900 shadow-sm'
                    : connected
                      ? 'text-slate-600 hover:text-slate-900'
                      : 'text-slate-400 cursor-not-allowed'
                )}
              >
                {label}
                {!connected && <span className="ml-1 text-xs text-slate-400">(off)</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* Controls */}
      <div className="p-6">
        <div className="flex items-end gap-4 mb-6">
          <div className="flex-1">
            <label className="block text-sm font-bold text-slate-700 mb-1.5">From</label>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full pl-10 pr-3 py-2.5 border-2 border-slate-200 rounded-xl text-sm font-medium text-slate-900 focus:border-primary focus:ring-0 outline-none"
              />
            </div>
          </div>
          <div className="flex-1">
            <label className="block text-sm font-bold text-slate-700 mb-1.5">To</label>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full pl-10 pr-3 py-2.5 border-2 border-slate-200 rounded-xl text-sm font-medium text-slate-900 focus:border-primary focus:ring-0 outline-none"
              />
            </div>
          </div>
          <button
            onClick={handlePull}
            disabled={pulling || !activeProvider}
            className={cn(
              'flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all',
              'bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {pulling ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            Pull Invoices
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-start gap-3 p-4 bg-red-50 border-2 border-red-200 rounded-xl mb-6">
            <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
            <p className="text-sm font-bold text-red-800">{error}</p>
          </div>
        )}

        {/* Results */}
        {result && (
          <div>
            {/* Summary Cards */}
            <div className="grid grid-cols-4 gap-4 mb-6">
              <div className="p-4 bg-slate-50 rounded-xl border-2 border-slate-200">
                <p className="text-xs font-bold text-slate-500 uppercase tracking-wide">
                  Total Billed
                </p>
                <p className="text-xl font-extrabold text-slate-900 mt-1">
                  {formatCurrency(result.totals.total_billed)}
                </p>
              </div>
              <div className="p-4 bg-emerald-50 rounded-xl border-2 border-emerald-200">
                <p className="text-xs font-bold text-emerald-600 uppercase tracking-wide">
                  Total Paid
                </p>
                <p className="text-xl font-extrabold text-emerald-700 mt-1">
                  {formatCurrency(result.totals.total_paid)}
                </p>
              </div>
              <div className="p-4 bg-amber-50 rounded-xl border-2 border-amber-200">
                <p className="text-xs font-bold text-amber-600 uppercase tracking-wide">
                  Outstanding
                </p>
                <p className="text-xl font-extrabold text-amber-700 mt-1">
                  {formatCurrency(
                    (result.totals.total_balance ?? result.totals.total_due) || 0
                  )}
                </p>
              </div>
              <div className="p-4 bg-blue-50 rounded-xl border-2 border-blue-200">
                <p className="text-xs font-bold text-blue-600 uppercase tracking-wide">
                  Collection Rate
                </p>
                <p className="text-xl font-extrabold text-blue-700 mt-1">
                  {getCollectionRate(result.totals.total_paid, result.totals.total_billed)}%
                </p>
              </div>
            </div>

            {/* Client breakdown table */}
            {result.customers.length > 0 ? (
              <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 border-b-2 border-slate-200">
                      <th className="text-left px-4 py-2.5 font-bold text-slate-600">Client</th>
                      <th className="text-center px-4 py-2.5 font-bold text-slate-600">Linked</th>
                      <th className="text-right px-4 py-2.5 font-bold text-slate-600">Invoices</th>
                      <th className="text-right px-4 py-2.5 font-bold text-slate-600">Billed</th>
                      <th className="text-right px-4 py-2.5 font-bold text-slate-600">Paid</th>
                      <th className="text-right px-4 py-2.5 font-bold text-slate-600">Collection</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.customers.map((c, i) => {
                      const collRate = getCollectionRate(c.total_paid, c.total_billed);
                      return (
                        <tr
                          key={i}
                          className={cn(
                            'border-b border-slate-100 last:border-0',
                            i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'
                          )}
                        >
                          <td className="px-4 py-2.5 font-bold text-slate-900">
                            {c.customer_name}
                          </td>
                          <td className="px-4 py-2.5 text-center">
                            {c.matched ? (
                              <CheckCircle2 className="w-4 h-4 text-emerald-500 mx-auto" />
                            ) : (
                              <span className="text-xs text-slate-400 font-medium">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right font-medium text-slate-700">
                            {c.invoice_count}
                          </td>
                          <td className="px-4 py-2.5 text-right font-bold text-slate-900">
                            {formatCurrency(c.total_billed)}
                          </td>
                          <td className="px-4 py-2.5 text-right font-medium text-emerald-700">
                            {formatCurrency(c.total_paid)}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <CollectionBadge rate={collRate} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex items-center gap-3 p-4 bg-amber-50 border-2 border-amber-200 rounded-xl">
                <AlertCircle className="w-5 h-5 text-amber-500" />
                <p className="text-sm font-bold text-amber-800">
                  No invoices found for this date range.
                </p>
              </div>
            )}

            {/* Refresh */}
            <div className="mt-4 flex justify-end">
              <button
                onClick={handlePull}
                disabled={pulling}
                className="flex items-center gap-2 text-sm font-bold text-primary hover:underline"
              >
                <RefreshCw className={cn('w-4 h-4', pulling && 'animate-spin')} />
                Refresh
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default IntegrationInvoicePanel;