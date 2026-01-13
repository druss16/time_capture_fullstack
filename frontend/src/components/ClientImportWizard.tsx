// src/components/ClientImportWizard.tsx
/**
 * Client Import Wizard - Import clients from QuickBooks Online or Xero
 * Handles OAuth connection, customer fetching, selection, and import
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  Upload,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  Search,
  Users,
  ArrowRight,
  ArrowLeft,
  Link2,
  Unlink,
  FileSpreadsheet,
  CheckSquare,
  Square,
  MinusSquare,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// ============================================================================
// Types
// ============================================================================

interface TeamMember {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

interface IntegrationStatus {
  connected: boolean;
  realm_id?: string;
  tenant_id?: string;
  last_synced?: string;
}

interface ExternalCustomer {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  company_name?: string;
  balance?: number;
  already_imported: boolean;
}

interface ImportResult {
  imported: Array<{
    id: number;
    name: string;
    quickbooks_id?: string;
    xero_id?: string;
    linked_existing: boolean;
  }>;
  skipped: Array<{
    id: string;
    name: string;
    reason: string;
  }>;
  errors: Array<{
    id: string;
    name?: string;
    error: string;
  }>;
  summary: {
    imported_count: number;
    skipped_count: number;
    error_count: number;
  };
}

type Provider = 'quickbooks' | 'xero';
type Step = 'select-source' | 'connect' | 'select-customers' | 'importing' | 'complete';

interface Props {
  onClose: () => void;
  onSuccess: () => void;
  users: TeamMember[];
}

// ============================================================================
// Provider Config
// ============================================================================

const PROVIDERS = {
  quickbooks: {
    name: 'QuickBooks Online',
    shortName: 'QuickBooks',
    icon: '📗',
    color: 'emerald',
    bgColor: 'bg-emerald-50',
    borderColor: 'border-emerald-200',
    textColor: 'text-emerald-700',
    buttonColor: 'bg-emerald-600 hover:bg-emerald-700',
    description: 'Import customers from QuickBooks Online',
  },
  xero: {
    name: 'Xero',
    shortName: 'Xero',
    icon: '📘',
    color: 'blue',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
    textColor: 'text-blue-700',
    buttonColor: 'bg-blue-600 hover:bg-blue-700',
    description: 'Import contacts from Xero',
  },
};

// ============================================================================
// Component
// ============================================================================

export default function ClientImportWizard({ onClose, onSuccess, users }: Props) {
  // State
  const [step, setStep] = useState<Step>('select-source');
  const [provider, setProvider] = useState<Provider | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Integration status
  const [qbStatus, setQbStatus] = useState<IntegrationStatus>({ connected: false });
  const [xeroStatus, setXeroStatus] = useState<IntegrationStatus>({ connected: false });
  
  // Customers
  const [customers, setCustomers] = useState<ExternalCustomer[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  
  // Import results
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  // ============================================================================
  // Load Integration Status
  // ============================================================================

  const loadIntegrationStatus = useCallback(async () => {
    try {
      const [qbData, xeroData] = await Promise.all([
        safeFetchJson(`${API_BASE}/integrations/quickbooks/status/`).catch(() => ({ connected: false })),
        safeFetchJson(`${API_BASE}/integrations/xero/status/`).catch(() => ({ connected: false })),
      ]);
      
      setQbStatus(qbData);
      setXeroStatus(xeroData);
    } catch (err) {
      console.error('Failed to load integration status:', err);
    }
  }, []);

  useEffect(() => {
    loadIntegrationStatus();
  }, [loadIntegrationStatus]);

  // ============================================================================
  // OAuth Connection
  // ============================================================================

  const handleConnect = async (targetProvider: Provider) => {
    setLoading(true);
    setError(null);
    
    try {
      const endpoint = targetProvider === 'quickbooks' 
        ? '/integrations/quickbooks/connect/'
        : '/integrations/xero/connect/';
      
      const data = await safeFetchJson(`${API_BASE}${endpoint}`);
      
      if (!data.auth_url) {
        throw new Error('Failed to get authorization URL');
      }
      
      // Open OAuth popup
      const popup = window.open(
        data.auth_url,
        `${targetProvider}_oauth`,
        'width=600,height=700,scrollbars=yes'
      );
      
      // Listen for OAuth callback message
      const handleMessage = (event: MessageEvent) => {
        if (event.data?.type === 'oauth_callback' && event.data?.integration === targetProvider) {
          window.removeEventListener('message', handleMessage);
          
          if (event.data.success) {
            loadIntegrationStatus();
            // Auto-advance to customer selection
            setTimeout(() => {
              loadCustomers(targetProvider);
            }, 500);
          } else {
            setError('OAuth connection failed. Please try again.');
          }
          
          setLoading(false);
        }
      };
      
      window.addEventListener('message', handleMessage);
      
      // Cleanup if popup is closed without completing
      const checkClosed = setInterval(() => {
        if (popup?.closed) {
          clearInterval(checkClosed);
          window.removeEventListener('message', handleMessage);
          setLoading(false);
        }
      }, 1000);
      
    } catch (err: any) {
      setError(err.message || 'Failed to connect');
      setLoading(false);
    }
  };

  const handleDisconnect = async (targetProvider: Provider) => {
    if (!confirm(`Disconnect from ${PROVIDERS[targetProvider].name}? You can reconnect anytime.`)) {
      return;
    }
    
    setLoading(true);
    
    try {
      const endpoint = targetProvider === 'quickbooks'
        ? '/integrations/quickbooks/disconnect/'
        : '/integrations/xero/disconnect/';
      
      await safeFetchJson(`${API_BASE}${endpoint}`, { method: 'POST' });
      await loadIntegrationStatus();
    } catch (err: any) {
      setError(err.message || 'Failed to disconnect');
    } finally {
      setLoading(false);
    }
  };

  // ============================================================================
  // Load Customers
  // ============================================================================

  const loadCustomers = async (targetProvider: Provider) => {
    setLoading(true);
    setError(null);
    setCustomers([]);
    setSelectedIds(new Set());
    
    try {
      const endpoint = targetProvider === 'quickbooks'
        ? '/integrations/quickbooks/customers/'
        : '/integrations/xero/contacts/';
      
      const data = await safeFetchJson(`${API_BASE}${endpoint}`);
      const customerList = data.customers || data.contacts || [];
      
      setCustomers(customerList);
      setStep('select-customers');
      
      // Pre-select customers that haven't been imported yet
      const unimportedIds = new Set(
        customerList
          .filter((c: ExternalCustomer) => !c.already_imported)
          .map((c: ExternalCustomer) => c.id)
      );
      setSelectedIds(unimportedIds);
      
    } catch (err: any) {
      setError(err.message || 'Failed to load customers');
    } finally {
      setLoading(false);
    }
  };

  // ============================================================================
  // Import Customers
  // ============================================================================

  const handleImport = async () => {
    if (!provider || selectedIds.size === 0) return;
    
    setStep('importing');
    setLoading(true);
    setError(null);
    
    try {
      const endpoint = provider === 'quickbooks'
        ? '/integrations/quickbooks/import/'
        : '/integrations/xero/import/';
      
      const bodyKey = provider === 'quickbooks' ? 'customer_ids' : 'contact_ids';
      
      const result: ImportResult = await safeFetchJson(`${API_BASE}${endpoint}`, {
        method: 'POST',
        body: JSON.stringify({
          [bodyKey]: Array.from(selectedIds),
        }),
      });
      
      setImportResult(result);
      setStep('complete');
      
    } catch (err: any) {
      setError(err.message || 'Import failed');
      setStep('select-customers');
    } finally {
      setLoading(false);
    }
  };

  // ============================================================================
  // Selection Helpers
  // ============================================================================

  const filteredCustomers = customers.filter(c =>
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (c.email?.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (c.company_name?.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const importableCustomers = filteredCustomers.filter(c => !c.already_imported);
  const allImportableSelected = importableCustomers.length > 0 && 
    importableCustomers.every(c => selectedIds.has(c.id));
  const someImportableSelected = importableCustomers.some(c => selectedIds.has(c.id));

  const toggleSelectAll = () => {
    if (allImportableSelected) {
      // Deselect all importable
      const newSelected = new Set(selectedIds);
      importableCustomers.forEach(c => newSelected.delete(c.id));
      setSelectedIds(newSelected);
    } else {
      // Select all importable
      const newSelected = new Set(selectedIds);
      importableCustomers.forEach(c => newSelected.add(c.id));
      setSelectedIds(newSelected);
    }
  };

  const toggleCustomer = (id: string) => {
    const newSelected = new Set(selectedIds);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedIds(newSelected);
  };

  // ============================================================================
  // Render Steps
  // ============================================================================

  const renderSelectSource = () => (
    <div className="p-6">
      <h3 className="text-lg font-bold text-slate-900 mb-2">Import Clients</h3>
      <p className="text-slate-600 font-medium mb-6">
        Connect your accounting software to import your client list automatically.
      </p>

      <div className="grid grid-cols-2 gap-4">
        {/* QuickBooks Card */}
        <button
          onClick={() => {
            setProvider('quickbooks');
            if (qbStatus.connected) {
              loadCustomers('quickbooks');
            } else {
              setStep('connect');
            }
          }}
          className={cn(
            'p-5 rounded-xl border-2 text-left transition-all hover:shadow-md',
            'border-emerald-200 hover:border-emerald-400 bg-emerald-50/50'
          )}
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="text-3xl">📗</span>
            <div>
              <h4 className="font-bold text-slate-900">QuickBooks Online</h4>
              {qbStatus.connected ? (
                <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-bold">
                  ✓ Connected
                </span>
              ) : (
                <span className="text-xs text-slate-500 font-medium">Not connected</span>
              )}
            </div>
          </div>
          <p className="text-sm text-slate-600 font-medium">
            Import customers from QuickBooks Online
          </p>
        </button>

        {/* Xero Card */}
        <button
          onClick={() => {
            setProvider('xero');
            if (xeroStatus.connected) {
              loadCustomers('xero');
            } else {
              setStep('connect');
            }
          }}
          className={cn(
            'p-5 rounded-xl border-2 text-left transition-all hover:shadow-md',
            'border-blue-200 hover:border-blue-400 bg-blue-50/50'
          )}
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="text-3xl">📘</span>
            <div>
              <h4 className="font-bold text-slate-900">Xero</h4>
              {xeroStatus.connected ? (
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-bold">
                  ✓ Connected
                </span>
              ) : (
                <span className="text-xs text-slate-500 font-medium">Not connected</span>
              )}
            </div>
          </div>
          <p className="text-sm text-slate-600 font-medium">
            Import contacts from Xero
          </p>
        </button>
      </div>

      {/* CSV Import Option (future) */}
      <div className="mt-6 pt-6 border-t-2 border-slate-200">
        <button
          disabled
          className="w-full p-4 rounded-xl border-2 border-dashed border-slate-300 text-left opacity-50 cursor-not-allowed"
        >
          <div className="flex items-center gap-3">
            <FileSpreadsheet className="w-8 h-8 text-slate-400" />
            <div>
              <h4 className="font-bold text-slate-700">Import from CSV</h4>
              <p className="text-sm text-slate-500 font-medium">Coming soon</p>
            </div>
          </div>
        </button>
      </div>
    </div>
  );

  const renderConnect = () => {
    if (!provider) return null;
    const config = PROVIDERS[provider];
    const isConnected = provider === 'quickbooks' ? qbStatus.connected : xeroStatus.connected;

    return (
      <div className="p-6">
        <button
          onClick={() => {
            setProvider(null);
            setStep('select-source');
          }}
          className="flex items-center gap-2 text-slate-600 hover:text-slate-900 font-medium mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>

        <div className={cn('p-6 rounded-xl border-2', config.bgColor, config.borderColor)}>
          <div className="flex items-center gap-4 mb-4">
            <span className="text-4xl">{config.icon}</span>
            <div>
              <h3 className="text-xl font-bold text-slate-900">{config.name}</h3>
              <p className={cn('text-sm font-medium', config.textColor)}>
                {isConnected ? 'Connected' : 'Not connected'}
              </p>
            </div>
          </div>

          {isConnected ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-emerald-700 bg-emerald-100 px-4 py-3 rounded-xl">
                <CheckCircle2 className="w-5 h-5" />
                <span className="font-bold">Connected to {config.name}</span>
              </div>
              
              <div className="flex gap-3">
                <button
                  onClick={() => loadCustomers(provider)}
                  disabled={loading}
                  className={cn(
                    'flex-1 flex items-center justify-center gap-2 px-4 py-3 text-white rounded-xl font-bold transition-all',
                    config.buttonColor
                  )}
                >
                  {loading ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Users className="w-5 h-5" />
                  )}
                  Load Customers
                </button>
                
                <button
                  onClick={() => handleDisconnect(provider)}
                  disabled={loading}
                  className="px-4 py-3 border-2 border-red-200 text-red-600 rounded-xl font-bold hover:bg-red-50 transition-all"
                >
                  <Unlink className="w-5 h-5" />
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-slate-600 font-medium">
                Connect your {config.name} account to import your customer list.
                You'll be redirected to {config.shortName} to authorize access.
              </p>
              
              <button
                onClick={() => handleConnect(provider)}
                disabled={loading}
                className={cn(
                  'w-full flex items-center justify-center gap-2 px-4 py-3 text-white rounded-xl font-bold transition-all',
                  config.buttonColor
                )}
              >
                {loading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <>
                    <Link2 className="w-5 h-5" />
                    Connect to {config.name}
                  </>
                )}
              </button>
              
              <p className="text-xs text-slate-500 font-medium text-center">
                We only request read access to your customer/contact list.
                We never modify your {config.shortName} data.
              </p>
            </div>
          )}
        </div>

        {error && (
          <div className="mt-4 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
            <div>
              <p className="font-bold text-red-800">Connection Error</p>
              <p className="text-sm text-red-700 font-medium">{error}</p>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderSelectCustomers = () => {
    if (!provider) return null;
    const config = PROVIDERS[provider];

    return (
      <div className="flex flex-col h-full max-h-[70vh]">
        {/* Header */}
        <div className="p-4 border-b-2 border-slate-200">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{config.icon}</span>
              <div>
                <h3 className="font-bold text-slate-900">Select Customers to Import</h3>
                <p className="text-sm text-slate-500 font-medium">
                  {customers.length} customers found • {selectedIds.size} selected
                </p>
              </div>
            </div>
            <button
              onClick={() => loadCustomers(provider)}
              disabled={loading}
              className="p-2 text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
              title="Refresh list"
            >
              <RefreshCw className={cn('w-5 h-5', loading && 'animate-spin')} />
            </button>
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search customers..."
              className="w-full pl-10 pr-4 py-2.5 border-2 border-slate-200 rounded-xl text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
            />
          </div>
        </div>

        {/* Select All Row */}
        <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 flex items-center gap-3">
          <button
            onClick={toggleSelectAll}
            className="p-1 hover:bg-slate-200 rounded transition-colors"
          >
            {allImportableSelected ? (
              <CheckSquare className="w-5 h-5 text-primary" />
            ) : someImportableSelected ? (
              <MinusSquare className="w-5 h-5 text-primary" />
            ) : (
              <Square className="w-5 h-5 text-slate-400" />
            )}
          </button>
          <span className="text-sm font-bold text-slate-700">
            {allImportableSelected ? 'Deselect All' : 'Select All'} ({importableCustomers.length} importable)
          </span>
        </div>

        {/* Customer List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 text-primary animate-spin" />
            </div>
          ) : filteredCustomers.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Users className="w-12 h-12 mx-auto mb-3 text-slate-300" />
              <p className="font-bold">No customers found</p>
              <p className="text-sm">Try a different search term</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {filteredCustomers.map((customer) => (
                <div
                  key={customer.id}
                  className={cn(
                    'flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors',
                    customer.already_imported && 'opacity-50'
                  )}
                >
                  <button
                    onClick={() => !customer.already_imported && toggleCustomer(customer.id)}
                    disabled={customer.already_imported}
                    className="p-1"
                  >
                    {customer.already_imported ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                    ) : selectedIds.has(customer.id) ? (
                      <CheckSquare className="w-5 h-5 text-primary" />
                    ) : (
                      <Square className="w-5 h-5 text-slate-300" />
                    )}
                  </button>
                  
                  <div className="flex-1 min-w-0">
                    <p className="font-bold text-slate-900 truncate">{customer.name}</p>
                    <p className="text-sm text-slate-500 font-medium truncate">
                      {customer.email || customer.company_name || 'No email'}
                    </p>
                  </div>
                  
                  {customer.already_imported && (
                    <span className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full font-bold">
                      Already imported
                    </span>
                  )}
                  
                  {customer.balance !== undefined && customer.balance > 0 && (
                    <span className="text-sm font-bold text-amber-600">
                      ${customer.balance.toLocaleString()}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t-2 border-slate-200 bg-slate-50">
          {error && (
            <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-red-500" />
              <span className="text-sm text-red-700 font-medium">{error}</span>
            </div>
          )}
          
          <div className="flex items-center justify-between">
            <button
              onClick={() => {
                setStep('select-source');
                setProvider(null);
              }}
              className="px-4 py-2.5 text-slate-600 font-bold hover:bg-slate-200 rounded-xl transition-colors"
            >
              ← Back
            </button>
            
            <button
              onClick={handleImport}
              disabled={selectedIds.size === 0 || loading}
              className={cn(
                'flex items-center gap-2 px-6 py-2.5 text-white rounded-xl font-bold transition-all',
                'bg-primary hover:opacity-90 shadow-lg shadow-primary/25',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              <Upload className="w-5 h-5" />
              Import {selectedIds.size} Client{selectedIds.size !== 1 ? 's' : ''}
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderImporting = () => (
    <div className="p-12 text-center">
      <Loader2 className="w-12 h-12 text-primary animate-spin mx-auto mb-4" />
      <h3 className="text-xl font-bold text-slate-900 mb-2">Importing Clients...</h3>
      <p className="text-slate-600 font-medium">
        This may take a moment. Please don't close this window.
      </p>
    </div>
  );

  const renderComplete = () => {
    if (!importResult) return null;
    
    const { summary, imported, skipped, errors } = importResult;
    const hasErrors = errors.length > 0;
    const hasSkipped = skipped.length > 0;

    return (
      <div className="p-6">
        {/* Success Header */}
        <div className="text-center mb-6">
          <div className={cn(
            'w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4',
            hasErrors ? 'bg-amber-100' : 'bg-emerald-100'
          )}>
            {hasErrors ? (
              <AlertCircle className="w-8 h-8 text-amber-600" />
            ) : (
              <CheckCircle2 className="w-8 h-8 text-emerald-600" />
            )}
          </div>
          <h3 className="text-xl font-bold text-slate-900">
            {hasErrors ? 'Import Completed with Issues' : 'Import Complete!'}
          </h3>
          <p className="text-slate-600 font-medium">
            {summary.imported_count} client{summary.imported_count !== 1 ? 's' : ''} imported successfully
          </p>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-4 text-center">
            <p className="text-3xl font-extrabold text-emerald-600">{summary.imported_count}</p>
            <p className="text-sm font-bold text-emerald-700">Imported</p>
          </div>
          <div className="bg-slate-50 border-2 border-slate-200 rounded-xl p-4 text-center">
            <p className="text-3xl font-extrabold text-slate-600">{summary.skipped_count}</p>
            <p className="text-sm font-bold text-slate-700">Skipped</p>
          </div>
          <div className={cn(
            'rounded-xl p-4 text-center border-2',
            summary.error_count > 0 
              ? 'bg-red-50 border-red-200' 
              : 'bg-slate-50 border-slate-200'
          )}>
            <p className={cn(
              'text-3xl font-extrabold',
              summary.error_count > 0 ? 'text-red-600' : 'text-slate-600'
            )}>
              {summary.error_count}
            </p>
            <p className={cn(
              'text-sm font-bold',
              summary.error_count > 0 ? 'text-red-700' : 'text-slate-700'
            )}>
              Errors
            </p>
          </div>
        </div>

        {/* Imported List */}
        {imported.length > 0 && (
          <div className="mb-4">
            <h4 className="font-bold text-slate-900 mb-2 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500" />
              Successfully Imported
            </h4>
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl max-h-32 overflow-y-auto">
              {imported.map((item, idx) => (
                <div key={idx} className="px-3 py-2 text-sm border-b border-emerald-100 last:border-0">
                  <span className="font-bold text-emerald-800">{item.name}</span>
                  {item.linked_existing && (
                    <span className="ml-2 text-xs text-emerald-600">(linked to existing)</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Skipped List */}
        {hasSkipped && (
          <div className="mb-4">
            <h4 className="font-bold text-slate-900 mb-2 flex items-center gap-2">
              <ArrowRight className="w-4 h-4 text-slate-500" />
              Skipped
            </h4>
            <div className="bg-slate-50 border border-slate-200 rounded-xl max-h-32 overflow-y-auto">
              {skipped.map((item, idx) => (
                <div key={idx} className="px-3 py-2 text-sm border-b border-slate-100 last:border-0">
                  <span className="font-medium text-slate-700">{item.name}</span>
                  <span className="text-slate-500 ml-2">— {item.reason}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Errors List */}
        {hasErrors && (
          <div className="mb-4">
            <h4 className="font-bold text-slate-900 mb-2 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-red-500" />
              Errors
            </h4>
            <div className="bg-red-50 border border-red-200 rounded-xl max-h-32 overflow-y-auto">
              {errors.map((item, idx) => (
                <div key={idx} className="px-3 py-2 text-sm border-b border-red-100 last:border-0">
                  <span className="font-medium text-red-700">{item.name || item.id}</span>
                  <span className="text-red-600 ml-2">— {item.error}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 mt-6">
          <button
            onClick={() => {
              setStep('select-source');
              setProvider(null);
              setImportResult(null);
            }}
            className="flex-1 px-4 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-colors"
          >
            Import More
          </button>
          <button
            onClick={() => {
              onSuccess();
              onClose();
            }}
            className="flex-1 px-4 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 transition-all shadow-lg shadow-primary/25"
          >
            Done
          </button>
        </div>
      </div>
    );
  };

  // ============================================================================
  // Main Render
  // ============================================================================

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center">
              <Upload className="w-5 h-5 text-primary" />
            </div>
            <h2 className="text-lg font-bold text-slate-900">Import Clients</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="max-h-[70vh] overflow-hidden">
          {step === 'select-source' && renderSelectSource()}
          {step === 'connect' && renderConnect()}
          {step === 'select-customers' && renderSelectCustomers()}
          {step === 'importing' && renderImporting()}
          {step === 'complete' && renderComplete()}
        </div>
      </div>
    </div>
  );
}