/**
 * IntegrationPushPanel.tsx
 * Push approved time entries to QuickBooks or Xero
 * Lives inside the Client Billing tab
 */
import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  Upload,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  Loader2,
  Calendar,
  Eye,
  Send,
  XCircle,
  CloudOff,
  Plug,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

interface IntegrationStatus {
  quickbooks: { connected: boolean; realm_id?: string };
  xero: { connected: boolean; tenant_id?: string };
}

interface PushPreviewEntry {
  block_id: number;
  client: string;
  client_id: number;
  date: string;
  hours: number;
  category: string;
  notes: string;
}

interface PushResult {
  dry_run?: boolean;
  entries?: PushPreviewEntry[];
  pushed?: Array<{ block_id: number; client: string; hours: number; qb_time_activity_id?: string }>;
  errors?: Array<{ block_id: number; error: string }>;
  summary: {
    total_entries?: number;
    pushed_count?: number;
    total_hours: number;
    clients?: string[];
    invoices_created?: number;
    total_amount?: number;
  };
}

type Provider = 'quickbooks' | 'xero';

const IntegrationPushPanel: React.FC = () => {
  // State
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeProvider, setActiveProvider] = useState<Provider | null>(null);

  // Date range (default to current week Mon-Fri)
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    return new Date(d.setDate(diff)).toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => {
    const d = new Date();
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1) + 4;
    return new Date(d.setDate(diff)).toISOString().split('T')[0];
  });

  // Push flow
  const [preview, setPreview] = useState<PushResult | null>(null);
  const [pushResult, setPushResult] = useState<PushResult | null>(null);
  const [pushing, setPushing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch integration status
  const fetchStatus = useCallback(async () => {
    try {
      const resp = await safeFetchJson<any>(`${API_BASE}/integrations/status/`);
      const integrations = resp.integrations || resp;
      setStatus(integrations);

      if (integrations.quickbooks?.connected) setActiveProvider('quickbooks');
      else if (integrations.xero?.connected) setActiveProvider('xero');
    } catch (err) {
      console.error('Failed to fetch integration status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const isConnected = (provider: Provider): boolean => {
    if (!status) return false;
    return provider === 'quickbooks' ? status.quickbooks?.connected : status.xero?.connected;
  };

  const hasAnyConnection = status?.quickbooks?.connected || status?.xero?.connected;

  // Preview (dry run)
  const handlePreview = async () => {
    if (!activeProvider) return;
    setError(null);
    setPreview(null);
    setPushResult(null);
    setPreviewing(true);

    try {
      const endpoint =
        activeProvider === 'quickbooks'
          ? `${API_BASE}/integrations/quickbooks/push-time/`
          : `${API_BASE}/integrations/xero/push-time/`;

      const data = await safeFetchJson<PushResult>(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          dry_run: true,
        }),
      });
      setPreview(data);
    } catch (err: any) {
      setError(err?.message || 'Failed to preview. Check your connection.');
    } finally {
      setPreviewing(false);
    }
  };

  // Actual push
  const handlePush = async () => {
    if (!activeProvider) return;
    setError(null);
    setPushing(true);

    try {
      const endpoint =
        activeProvider === 'quickbooks'
          ? `${API_BASE}/integrations/quickbooks/push-time/`
          : `${API_BASE}/integrations/xero/push-time/`;

      const data = await safeFetchJson<PushResult>(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          dry_run: false,
        }),
      });
      setPushResult(data);
      setPreview(null);
    } catch (err: any) {
      setError(err?.message || 'Push failed. Please try again.');
    } finally {
      setPushing(false);
    }
  };

  const reset = () => {
    setPreview(null);
    setPushResult(null);
    setError(null);
  };

  // ── Not connected state ──
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
            Connect QuickBooks Online or Xero to push approved time entries directly to your billing
            system.
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
          <div className="w-10 h-10 rounded-xl bg-emerald-100 flex items-center justify-center">
            <Upload className="w-5 h-5 text-emerald-600" />
          </div>
          <div>
            <h3 className="text-base font-extrabold text-slate-900">Push Time to Billing</h3>
            <p className="text-sm text-slate-500 font-medium">
              Send approved time entries to your billing system
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
                    reset();
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
                {!connected && (
                  <span className="ml-1 text-xs text-slate-400">(off)</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Date Range + Preview */}
      <div className="p-6">
        <div className="flex items-end gap-4 mb-6">
          <div className="flex-1">
            <label className="block text-sm font-bold text-slate-700 mb-1.5">Start Date</label>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="date"
                value={startDate}
                onChange={(e) => {
                  setStartDate(e.target.value);
                  reset();
                }}
                className="w-full pl-10 pr-3 py-2.5 border-2 border-slate-200 rounded-xl text-sm font-medium text-slate-900 focus:border-primary focus:ring-0 outline-none"
              />
            </div>
          </div>
          <div className="flex-1">
            <label className="block text-sm font-bold text-slate-700 mb-1.5">End Date</label>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="date"
                value={endDate}
                onChange={(e) => {
                  setEndDate(e.target.value);
                  reset();
                }}
                className="w-full pl-10 pr-3 py-2.5 border-2 border-slate-200 rounded-xl text-sm font-medium text-slate-900 focus:border-primary focus:ring-0 outline-none"
              />
            </div>
          </div>
          <button
            onClick={handlePreview}
            disabled={previewing || !activeProvider}
            className={cn(
              'flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all',
              'bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {previewing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Eye className="w-4 h-4" />
            )}
            Preview
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-start gap-3 p-4 bg-red-50 border-2 border-red-200 rounded-xl mb-6">
            <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-bold text-red-800">{error}</p>
              <button
                onClick={reset}
                className="text-sm text-red-600 font-medium hover:underline mt-1"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Preview Table */}
        {preview && preview.entries && preview.entries.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-extrabold text-slate-900">
                Preview — {preview.summary.total_entries} entries, {preview.summary.total_hours?.toFixed(1)}h
              </h4>
              <span className="text-xs font-bold text-amber-600 bg-amber-50 px-2.5 py-1 rounded-lg border border-amber-200">
                DRY RUN — Nothing sent yet
              </span>
            </div>

            <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b-2 border-slate-200">
                    <th className="text-left px-4 py-2.5 font-bold text-slate-600">Date</th>
                    <th className="text-left px-4 py-2.5 font-bold text-slate-600">Client</th>
                    <th className="text-left px-4 py-2.5 font-bold text-slate-600">Category</th>
                    <th className="text-right px-4 py-2.5 font-bold text-slate-600">Hours</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.entries.slice(0, 20).map((entry, i) => (
                    <tr
                      key={entry.block_id}
                      className={cn(
                        'border-b border-slate-100 last:border-0',
                        i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'
                      )}
                    >
                      <td className="px-4 py-2.5 font-medium text-slate-700">{entry.date}</td>
                      <td className="px-4 py-2.5 font-bold text-slate-900">{entry.client}</td>
                      <td className="px-4 py-2.5 text-slate-600">{entry.category}</td>
                      <td className="px-4 py-2.5 text-right font-bold text-slate-900">
                        {entry.hours.toFixed(1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                {preview.entries.length > 20 && (
                  <tfoot>
                    <tr className="bg-slate-50">
                      <td colSpan={4} className="px-4 py-2 text-center text-sm text-slate-500 font-medium">
                        + {preview.entries.length - 20} more entries
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>

            {/* Summary + Push button */}
            <div className="flex items-center justify-between mt-4 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
              <div>
                <p className="text-sm font-bold text-emerald-800">
                  Ready to push {preview.summary.total_entries} entries ({preview.summary.total_hours?.toFixed(1)} hours)
                </p>
                {preview.summary.clients && (
                  <p className="text-xs text-emerald-600 font-medium mt-0.5">
                    Clients: {preview.summary.clients.join(', ')}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={reset}
                  className="px-4 py-2 text-sm font-bold text-slate-600 hover:text-slate-900 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handlePush}
                  disabled={pushing}
                  className="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 text-white font-bold rounded-xl hover:bg-emerald-700 transition-all shadow-lg shadow-emerald-600/25 disabled:opacity-50"
                >
                  {pushing ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  Push to {activeProvider === 'quickbooks' ? 'QuickBooks' : 'Xero'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Empty preview */}
        {preview && (!preview.entries || preview.entries.length === 0) && (
          <div className="flex items-center gap-3 p-4 bg-amber-50 border-2 border-amber-200 rounded-xl mb-6">
            <AlertCircle className="w-5 h-5 text-amber-500" />
            <p className="text-sm font-bold text-amber-800">
              No unpushed entries found for this date range. Entries may already be pushed, or there
              are no approved blocks with linked clients.
            </p>
          </div>
        )}

        {/* Push Result */}
        {pushResult && (
          <div className="space-y-4">
            {/* Success banner */}
            {pushResult.pushed && pushResult.pushed.length > 0 && (
              <div className="flex items-start gap-3 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
                <CheckCircle2 className="w-5 h-5 text-emerald-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-bold text-emerald-800">
                    Successfully pushed {pushResult.summary.pushed_count} entries (
                    {pushResult.summary.total_hours?.toFixed(1)} hours) to{' '}
                    {activeProvider === 'quickbooks' ? 'QuickBooks' : 'Xero'}
                  </p>
                  {activeProvider === 'xero' && pushResult.summary.invoices_created && (
                    <p className="text-xs text-emerald-600 font-medium mt-1">
                      {pushResult.summary.invoices_created} draft invoice(s) created •{' '}
                      ${pushResult.summary.total_amount?.toLocaleString()}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Errors */}
            {pushResult.errors && pushResult.errors.length > 0 && (
              <div className="flex items-start gap-3 p-4 bg-red-50 border-2 border-red-200 rounded-xl">
                <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-bold text-red-800">
                    {pushResult.errors.length} entry/entries failed
                  </p>
                  <ul className="mt-2 space-y-1">
                    {pushResult.errors.slice(0, 5).map((e, i) => (
                      <li key={i} className="text-xs text-red-600 font-medium">
                        Block #{e.block_id}: {e.error}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <button
              onClick={reset}
              className="flex items-center gap-2 text-sm font-bold text-primary hover:underline"
            >
              <RefreshCw className="w-4 h-4" />
              Push another batch
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default IntegrationPushPanel;