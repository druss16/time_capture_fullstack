// src/components/IntegrationsTab.tsx
// Manage QuickBooks & Xero connections from Settings
// Connect / Disconnect / Import Clients / View Status
//
// PATH FIXES (v2):
// - GET /integrations/ → GET /integrations/status/ (matches backend)
// - Adapted types to match actual integrations_status() response shape
// - GET /integrations/{provider}/customers/ → correct per-provider paths
// - Removed references to endpoints that don't exist yet (sync-history, client-mappings, auto-match)
//   These are stubbed with TODO comments for when backend is ready

import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson } from '@/lib/api';
import {
  Link2,
  Unlink,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  ArrowRight,
  Loader2,
  X,
  Check,
  Clock,
  Building2,
  Users,
  ChevronDown,
  ChevronUp,
  Search,
  Zap,
  ShieldCheck,
  Download,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;
const [conflictCount, setConflictCount] = useState(0);


// ===============================
// TYPES — match actual backend response from integrations_status()
// ===============================

interface ProviderStatus {
  connected: boolean;
  last_synced?: string | null;
  realm_id?: string | null;   // QuickBooks
  tenant_id?: string | null;  // Xero
}

interface IntegrationStatusResponse {
  integrations: {
    quickbooks: ProviderStatus;
    xero: ProviderStatus;
  };
  client_stats: {
    from_quickbooks: number;
    from_xero: number;
    manual: number;
  };
}

// Normalized integration for UI
interface Integration {
  provider: 'quickbooks' | 'xero';
  is_connected: boolean;
  last_synced: string | null;
  company_id: string | null;  // realm_id or tenant_id
}

interface ExternalCustomer {
  id: string;
  name: string;
  company_name?: string;
  email?: string;
  already_imported: boolean;
}

interface IntegrationsTabProps {
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

// ===============================
// PROVIDER CONFIGS
// ===============================

const PROVIDERS = {
  quickbooks: {
    name: 'QuickBooks Online',
    short: 'QBO',
    icon: '📗',
    color: 'green',
    description: 'Sync invoices, push time entries, and pull client data from Intuit QuickBooks Online.',
    features: ['Pull invoices for realization', 'Push approved time entries', 'Import clients/customers', 'Sync payment status'],
    bgClass: 'bg-green-50 border-green-200',
    accentClass: 'text-green-700',
    btnClass: 'bg-green-600 hover:bg-green-700',
    badgeClass: 'bg-green-100 text-green-800',
    iconBgClass: 'bg-green-100',
    customersEndpoint: 'customers',  // /integrations/quickbooks/customers/
    importEndpoint: 'import',        // /integrations/quickbooks/import/
  },
  xero: {
    name: 'Xero',
    short: 'Xero',
    icon: '📘',
    color: 'blue',
    description: 'Sync invoices, push time entries, and pull client data from Xero accounting.',
    features: ['Pull invoices for realization', 'Push approved time entries', 'Import contacts', 'Sync payment status'],
    bgClass: 'bg-blue-50 border-blue-200',
    accentClass: 'text-blue-700',
    btnClass: 'bg-blue-600 hover:bg-blue-700',
    badgeClass: 'bg-blue-100 text-blue-800',
    iconBgClass: 'bg-blue-100',
    customersEndpoint: 'contacts',   // /integrations/xero/contacts/
    importEndpoint: 'import',        // /integrations/xero/import/
  },
} as const;

// ===============================
// IMPORT CLIENTS MODAL
// ===============================

interface ImportClientsModalProps {
  isOpen: boolean;
  onClose: () => void;
  provider: 'quickbooks' | 'xero';
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

const ImportClientsModal: React.FC<ImportClientsModalProps> = ({ isOpen, onClose, provider, onSuccess, onError }) => {
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [customers, setCustomers] = useState<ExternalCustomer[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [result, setResult] = useState<any>(null);

  const config = PROVIDERS[provider];

  useEffect(() => {
    if (isOpen) {
      loadCustomers();
    }
  }, [isOpen]);

  const loadCustomers = async () => {
    setLoading(true);
    try {
      // FIX: Use correct per-provider endpoint
      const endpoint = `${API_BASE}/integrations/${provider}/${config.customersEndpoint}/`;
      const data = await safeFetchJson<{ customers?: ExternalCustomer[]; contacts?: ExternalCustomer[] }>(endpoint);
      
      // QBO returns 'customers', Xero returns 'contacts'
      const list = data.customers || data.contacts || [];
      setCustomers(list);
      
      // Auto-select non-imported ones
      const importable = list.filter(c => !c.already_imported).map(c => c.id);
      setSelected(new Set(importable));
    } catch (err: any) {
      onError(err?.message || `Failed to load ${config.short} customers`);
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    if (selected.size === 0) return;
    setImporting(true);
    try {
      const endpoint = `${API_BASE}/integrations/${provider}/${config.importEndpoint}/`;
      const bodyKey = provider === 'quickbooks' ? 'customer_ids' : 'contact_ids';
      
      const data = await safeFetchJson<any>(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [bodyKey]: Array.from(selected) }),
      });
      
      setResult(data);
      const count = data.summary?.imported_count || data.imported?.length || 0;
      if (count > 0) {
        onSuccess(`Imported ${count} client${count !== 1 ? 's' : ''} from ${config.short}`);
      }
    } catch (err: any) {
      onError(err?.message || 'Import failed');
    } finally {
      setImporting(false);
    }
  };

  const toggleCustomer = (id: string) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };

  const toggleAll = () => {
    const importable = customers.filter(c => !c.already_imported);
    if (selected.size === importable.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(importable.map(c => c.id)));
    }
  };

  const filtered = customers.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase()) ||
    (c.email || '').toLowerCase().includes(search.toLowerCase())
  );

  useEffect(() => {
    if (!isOpen) {
      setResult(null);
      setSearch('');
      setCustomers([]);
      setSelected(new Set());
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b-2 border-slate-200 bg-slate-50 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center text-xl', config.iconBgClass)}>
              {config.icon}
            </div>
            <div>
              <h3 className="font-bold text-slate-900">Import Clients from {config.name}</h3>
              <p className="text-sm text-slate-500 font-medium">
                {customers.length} found · {customers.filter(c => c.already_imported).length} already imported
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-lg transition-colors">
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto flex-1">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 text-slate-400 animate-spin" />
            </div>
          ) : result ? (
            <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-5 h-5 text-green-600" />
                <span className="font-medium text-green-800">Import Complete</span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-green-600">{result.summary?.imported_count || 0}</div>
                  <div className="text-xs text-slate-500">Imported</div>
                </div>
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-amber-600">{result.summary?.skipped_count || 0}</div>
                  <div className="text-xs text-slate-500">Skipped</div>
                </div>
                <div className="bg-white rounded-lg p-3">
                  <div className="text-2xl font-bold text-red-600">{result.summary?.error_count || 0}</div>
                  <div className="text-xs text-slate-500">Errors</div>
                </div>
              </div>
            </div>
          ) : (
            <>
              {/* Search + Select All */}
              <div className="flex items-center gap-3 mb-4">
                <div className="relative flex-1">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search customers..."
                    className="w-full pl-10 pr-4 py-2.5 border-2 border-slate-200 rounded-xl text-slate-900 font-medium focus:border-primary focus:outline-none transition-all"
                  />
                </div>
                <button
                  onClick={toggleAll}
                  className="text-sm text-blue-600 hover:text-blue-700 font-bold whitespace-nowrap"
                >
                  {selected.size === customers.filter(c => !c.already_imported).length
                    ? 'Deselect All'
                    : 'Select All'}
                </button>
              </div>

              {/* Customer list */}
              <div className="border-2 border-slate-200 rounded-xl max-h-96 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 sticky top-0">
                    <tr>
                      <th className="w-10 px-3 py-2"></th>
                      <th className="text-left px-3 py-2 font-bold text-slate-700">Name</th>
                      <th className="text-left px-3 py-2 font-bold text-slate-700">Email</th>
                      <th className="text-center px-3 py-2 font-bold text-slate-700">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filtered.map(c => (
                      <tr key={c.id} className={c.already_imported ? 'bg-slate-50 opacity-60' : 'hover:bg-slate-50'}>
                        <td className="px-3 py-2">
                          {c.already_imported ? (
                            <CheckCircle2 className="w-5 h-5 text-green-500" />
                          ) : (
                            <button onClick={() => toggleCustomer(c.id)}>
                              {selected.has(c.id) ? (
                                <div className="w-5 h-5 bg-blue-600 rounded flex items-center justify-center">
                                  <Check className="w-3 h-3 text-white" />
                                </div>
                              ) : (
                                <div className="w-5 h-5 border-2 border-slate-300 rounded" />
                              )}
                            </button>
                          )}
                        </td>
                        <td className="px-3 py-2 font-medium text-slate-800">{c.name}</td>
                        <td className="px-3 py-2 text-slate-600">{c.email || '—'}</td>
                        <td className="px-3 py-2 text-center">
                          {c.already_imported ? (
                            <span className="text-xs text-slate-500">Imported</span>
                          ) : (
                            <span className="text-xs text-blue-600">New</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={4} className="text-center py-8 text-slate-500">
                          {search ? 'No matches' : 'No customers found'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-5 border-t-2 border-slate-200 bg-slate-50 flex-shrink-0">
          <div>
            {!result && selected.size > 0 && (
              <span className="text-sm text-blue-600 font-bold">
                {selected.size} selected
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all"
            >
              {result ? 'Done' : 'Cancel'}
            </button>
            {!result && (
              <button
                onClick={handleImport}
                disabled={importing || selected.size === 0}
                className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all"
              >
                {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                Import {selected.size} Client{selected.size !== 1 ? 's' : ''}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// ===============================
// PROVIDER CARD
// ===============================

interface ProviderCardProps {
  provider: 'quickbooks' | 'xero';
  status: ProviderStatus;
  clientCount: number;
  onConnect: (provider: 'quickbooks' | 'xero') => void;
  onDisconnect: (provider: 'quickbooks' | 'xero') => void;
  onImportClients: (provider: 'quickbooks' | 'xero') => void;
}

const ProviderCard: React.FC<ProviderCardProps> = ({
  provider,
  status,
  clientCount,
  onConnect,
  onDisconnect,
  onImportClients,
}) => {
  const [showDetails, setShowDetails] = useState(false);
  const config = PROVIDERS[provider];
  const connected = status.connected;

  return (
    <div className={cn('border-2 rounded-2xl overflow-hidden transition-all', connected ? config.bgClass : 'border-slate-200 bg-white')}>
      {/* Card Header */}
      <div className="p-5">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className={cn('w-14 h-14 rounded-xl flex items-center justify-center text-3xl', config.iconBgClass)}>
              {config.icon}
            </div>
            <div>
              <h3 className="text-lg font-extrabold text-slate-900">{config.name}</h3>
              <p className="text-sm text-slate-500 font-medium mt-0.5">{config.description}</p>
            </div>
          </div>
          <div>
            {connected ? (
              <span className={cn('inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold', config.badgeClass)}>
                <CheckCircle2 className="w-3.5 h-3.5" />
                Connected
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold bg-slate-100 text-slate-500">
                <Unlink className="w-3.5 h-3.5" />
                Not Connected
              </span>
            )}
          </div>
        </div>

        {/* Features (when not connected) */}
        {!connected && (
          <div className="mt-4 grid grid-cols-2 gap-2">
            {config.features.map((feature, idx) => (
              <div key={idx} className="flex items-center gap-2 text-sm text-slate-600">
                <Check className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                <span>{feature}</span>
              </div>
            ))}
          </div>
        )}

        {/* Connected Info */}
        {connected && (
          <div className="mt-4 grid grid-cols-3 gap-4">
            <div className="bg-white/70 rounded-xl p-3 border border-slate-200/50">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold mb-1">
                <Building2 className="w-3.5 h-3.5" />
                {provider === 'quickbooks' ? 'Realm ID' : 'Tenant ID'}
              </div>
              <p className="font-bold text-slate-900 text-sm font-mono truncate">
                {(provider === 'quickbooks' ? status.realm_id : status.tenant_id) || '—'}
              </p>
            </div>
            <div className="bg-white/70 rounded-xl p-3 border border-slate-200/50">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold mb-1">
                <Users className="w-3.5 h-3.5" />
                Imported Clients
              </div>
              <p className="font-bold text-slate-900 text-sm">{clientCount}</p>
            </div>
            <div className="bg-white/70 rounded-xl p-3 border border-slate-200/50">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold mb-1">
                <Clock className="w-3.5 h-3.5" />
                Last Synced
              </div>
              <p className="font-bold text-slate-900 text-sm">
                {status.last_synced
                  ? (() => {
                      const diff = Math.floor((Date.now() - new Date(status.last_synced).getTime()) / 1000);
                      if (diff < 60) return `${diff}s ago`;
                      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
                      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
                      return new Date(status.last_synced).toLocaleDateString();
                    })()
                  : 'Never'}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="px-5 pb-5">
        {connected ? (
          <div className="flex items-center gap-3">
            <button
              onClick={() => onImportClients(provider)}
              className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
            >
              <Download className="w-4 h-4" />
              Import Clients
            </button>
            <div className="flex-1" />
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 font-medium transition-colors"
            >
              Details
              {showDetails ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            <button
              onClick={() => onDisconnect(provider)}
              className="flex items-center gap-2 px-4 py-2.5 border-2 border-red-200 text-red-600 rounded-xl font-bold text-sm hover:bg-red-50 transition-all"
            >
              <Unlink className="w-4 h-4" />
              Disconnect
            </button>
          </div>
        ) : (
          <button
            onClick={() => onConnect(provider)}
            className={cn(
              'flex items-center gap-2 px-5 py-3 text-white rounded-xl font-bold text-sm transition-all shadow-lg',
              config.btnClass
            )}
          >
            <Link2 className="w-4 h-4" />
            Connect {config.name}
            <ExternalLink className="w-4 h-4 ml-1" />
          </button>
        )}
      </div>

      {/* Expanded Details */}
      {connected && showDetails && (
        <div className="border-t-2 border-slate-200/50 bg-white/50 p-5">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-slate-500 font-semibold">Provider</p>
              <p className="text-slate-900 font-bold">{config.name}</p>
            </div>
            <div>
              <p className="text-slate-500 font-semibold">{provider === 'quickbooks' ? 'Realm ID' : 'Tenant ID'}</p>
              <p className="text-slate-900 font-mono font-bold">
                {(provider === 'quickbooks' ? status.realm_id : status.tenant_id) || '—'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ===============================
// MAIN COMPONENT
// ===============================

const IntegrationsTab: React.FC<IntegrationsTabProps> = ({ onSuccess, onError }) => {
  const [loading, setLoading] = useState(true);
  const [statusData, setStatusData] = useState<IntegrationStatusResponse | null>(null);
  const [importProvider, setImportProvider] = useState<'quickbooks' | 'xero' | null>(null);
  const [conflictCount, setConflictCount] = useState(0);

  const fetchIntegrations = useCallback(async () => {
    try {
      const data = await safeFetchJson<IntegrationStatusResponse>(
        `${API_BASE}/integrations/status/`
      );
      setStatusData(data);
      try {
        const conflicts = await safeFetchJson<{ count: number }>(
          `${API_BASE}/billing/invoices/conflicts/`
        );
        setConflictCount(conflicts.count || 0);
      } catch (_) {}
    } catch (err: any) {
      console.error('Failed to load integrations:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIntegrations();
  }, [fetchIntegrations]);

  // Listen for OAuth callback postMessage
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === 'oauth_callback' && event.data?.success) {
        onSuccess(`${event.data.integration === 'quickbooks' ? 'QuickBooks' : 'Xero'} connected successfully!`);
        fetchIntegrations();
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [fetchIntegrations, onSuccess]);

  // Check URL params for OAuth redirect results
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('quickbooks_connected') === 'true') {
      onSuccess('QuickBooks connected successfully!');
      fetchIntegrations();
    } else if (params.get('xero_connected') === 'true') {
      onSuccess('Xero connected successfully!');
      fetchIntegrations();
    } else if (params.get('integration_error')) {
      onError(`Connection failed: ${params.get('integration_error')}`);
    }
    // Clean URL
    if (params.has('quickbooks_connected') || params.has('xero_connected') || params.has('integration_error')) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  const handleConnect = async (provider: 'quickbooks' | 'xero') => {
    try {
      const data = await safeFetchJson<{ auth_url: string }>(
        `${API_BASE}/integrations/${provider}/connect/`
      );
      if (data.auth_url) {
        // Open in popup for OAuth flow
        const width = 600;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        // NEW: full-page redirect
        window.location.href = data.auth_url;
      }
    } catch (err: any) {
      onError(err?.message || `Failed to initiate ${provider} connection`);
    }
  };

  const handleDisconnect = async (provider: 'quickbooks' | 'xero') => {
    const name = PROVIDERS[provider].name;
    if (!confirm(`Disconnect ${name}? This will remove the connection but won't delete any imported data.`)) return;

    try {
      await safeFetchJson(`${API_BASE}/integrations/${provider}/disconnect/`, {
        method: 'POST',
      });
      onSuccess(`${name} disconnected`);
      await fetchIntegrations();
    } catch (err: any) {
      onError(err?.message || 'Failed to disconnect');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-6 h-6 text-primary animate-spin" />
      </div>
    );
  }

  const qbStatus = statusData?.integrations?.quickbooks || { connected: false };
  const xeroStatus = statusData?.integrations?.xero || { connected: false };
  const clientStats = statusData?.client_stats || { from_quickbooks: 0, from_xero: 0, manual: 0 };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Link2 className="w-5 h-5 text-primary" />
          Integrations
        </h2>
      </div>

      {/* Security note */}
      <div className="mb-6 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl flex items-start gap-3">
        <ShieldCheck className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-sm text-emerald-800 font-bold">Secure OAuth Connections</p>
          <p className="text-sm text-emerald-700 mt-0.5">
            TimeTracker uses official OAuth 2.0 to connect securely. We never store your accounting login credentials — only encrypted access tokens.
          </p>
        </div>
      </div>

      {/* Conflict Banner */}
      {conflictCount > 0 && (
        <div className="mb-4 p-4 bg-amber-50 border-2 border-amber-200 rounded-xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0" />
            <div>
              <p className="text-sm font-bold text-amber-800">
                {conflictCount} invoice{conflictCount !== 1 ? 's' : ''} need review
              </p>
              <p className="text-xs text-amber-600 mt-0.5">
                QuickBooks amounts differ from what's in TimeTracker
              </p>
            </div>
          </div>
          
            <a href="/billing?tab=invoices&filter=conflicts"
            className="flex items-center gap-1.5 px-3 py-2 bg-amber-600 text-white rounded-lg font-bold text-xs hover:bg-amber-700 transition-colors"
          >
            Review <ArrowRight className="w-3 h-3" />
          </a>
        </div>
      )}

      {/* Provider Cards */}
      <div className="space-y-4">
        <ProviderCard
          provider="quickbooks"
          status={qbStatus}
          clientCount={clientStats.from_quickbooks}
          onConnect={handleConnect}
          onDisconnect={handleDisconnect}
          onImportClients={setImportProvider}
        />
        <ProviderCard
          provider="xero"
          status={xeroStatus}
          clientCount={clientStats.from_xero}
          onConnect={handleConnect}
          onDisconnect={handleDisconnect}
          onImportClients={setImportProvider}
        />
      </div>

      {/* Import Clients Modal */}
      {importProvider && (
        <ImportClientsModal
          isOpen={!!importProvider}
          onClose={() => setImportProvider(null)}
          provider={importProvider}
          onSuccess={(msg) => {
            onSuccess(msg);
            fetchIntegrations(); // Refresh client counts
          }}
          onError={onError}
        />
      )}
    </div>
  );
};

export default IntegrationsTab;