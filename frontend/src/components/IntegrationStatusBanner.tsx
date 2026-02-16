// src/components/IntegrationStatusBanner.tsx
// Lightweight banner for any billing/profitability page
// Shows connection status + quick actions (connect, import, sync)
//
// PATH FIXES (v2):
// - GET /integrations/ → GET /integrations/status/
// - POST pull-invoices → GET invoices (correct method + path)

import React, { useState, useEffect } from 'react';
import { safeFetchJson } from '@/lib/api';
import {
  Link2,
  Unlink,
  ExternalLink,
  CheckCircle2,
  RefreshCw,
  Upload,
  ArrowRight,
  Loader2,
  X,
  Zap,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

// ===============================
// TYPES — match backend integrations_status() response shape
// ===============================

interface IntegrationProvider {
  connected: boolean;
  last_synced?: string | null;
  realm_id?: string | null;
  tenant_id?: string | null;
}

interface IntegrationStatusResponse {
  integrations: {
    quickbooks: IntegrationProvider;
    xero: IntegrationProvider;
  };
  client_stats: {
    from_quickbooks: number;
    from_xero: number;
    manual: number;
  };
}

interface IntegrationStatusBannerProps {
  /** Which context this banner is in — adjusts the CTA language */
  context?: 'profitability' | 'billing' | 'general';
  /** Callback after a successful sync/import action */
  onDataRefresh?: () => void;
  /** Compact mode (single line) */
  compact?: boolean;
}

const PROVIDER_CONFIG = {
  quickbooks: { name: 'QuickBooks', short: 'QBO', icon: '📗', color: 'green' },
  xero: { name: 'Xero', short: 'Xero', icon: '📘', color: 'blue' },
};

const IntegrationStatusBanner: React.FC<IntegrationStatusBannerProps> = ({
  context = 'general',
  onDataRefresh,
  compact = false,
}) => {
  const [loading, setLoading] = useState(true);
  const [connectedProviders, setConnectedProviders] = useState<
    Array<{ provider: 'quickbooks' | 'xero'; last_synced: string | null }>
  >([]);
  const [syncing, setSyncing] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        // FIX: was /integrations/ → now /integrations/status/
        const data = await safeFetchJson<IntegrationStatusResponse>(
          `${API_BASE}/integrations/status/`
        );

        const providers: typeof connectedProviders = [];
        if (data.integrations?.quickbooks?.connected) {
          providers.push({
            provider: 'quickbooks',
            last_synced: data.integrations.quickbooks.last_synced || null,
          });
        }
        if (data.integrations?.xero?.connected) {
          providers.push({
            provider: 'xero',
            last_synced: data.integrations.xero.last_synced || null,
          });
        }
        setConnectedProviders(providers);
      } catch (err) {
        // Silently fail — this is a non-critical banner
        console.error('Integration status check failed:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  // Clear sync result after 4s
  useEffect(() => {
    if (syncResult) {
      const timer = setTimeout(() => setSyncResult(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [syncResult]);

  const hasConnection = connectedProviders.length > 0;

  const handleQuickSync = async (provider: string) => {
    setSyncing(true);
    setSyncResult(null);
    try {
      // FIX: Use correct backend endpoints
      // For profitability context → pull invoices (GET, not POST)
      // For billing context → push time (POST)
      if (context === 'profitability') {
        const params = new URLSearchParams({
          start_date: new Date(new Date().getFullYear(), new Date().getMonth(), 1)
            .toISOString().split('T')[0],
          end_date: new Date().toISOString().split('T')[0],
        });
        const result = await safeFetchJson<{ totals?: { invoice_count?: number } }>(
          `${API_BASE}/integrations/${provider}/invoices/?${params}`
        );
        const count = result.totals?.invoice_count || 0;
        setSyncResult(`Pulled ${count} invoice${count !== 1 ? 's' : ''}`);
      } else {
        // For billing, just trigger a data refresh — actual push is done via IntegrationPushPanel
        setSyncResult('Data refreshed');
      }
      onDataRefresh?.();
    } catch (err: any) {
      setSyncResult('Sync failed — check Settings');
    } finally {
      setSyncing(false);
    }
  };

  if (loading || dismissed) return null;

  // ── Not Connected State ──
  if (!hasConnection) {
    if (compact) {
      return (
        <div className="flex items-center justify-between p-3 bg-amber-50 border-2 border-amber-200 rounded-xl">
          <div className="flex items-center gap-2">
            <Unlink className="w-4 h-4 text-amber-600" />
            <span className="text-sm text-amber-700 font-bold">
              No billing system connected
            </span>
          </div>
          <div className="flex items-center gap-2">
            <a
              href="/settings?tab=integrations"
              className="flex items-center gap-1 px-3 py-1.5 bg-amber-600 text-white rounded-lg font-bold text-xs hover:bg-amber-700 transition-colors"
            >
              Connect
              <ExternalLink className="w-3 h-3" />
            </a>
            <button
              onClick={() => setDismissed(true)}
              className="p-1 text-amber-400 hover:text-amber-600 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      );
    }

    return (
      <div className="bg-gradient-to-r from-amber-50 to-orange-50 border-2 border-amber-200 rounded-2xl p-5">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 bg-amber-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <Link2 className="w-6 h-6 text-amber-600" />
            </div>
            <div>
              <h3 className="font-extrabold text-slate-900 text-lg">
                Connect Your Billing System
              </h3>
              <p className="text-slate-600 font-medium mt-1 text-sm">
                {context === 'profitability'
                  ? 'Link QuickBooks or Xero to automatically pull invoices and compare billed vs worked hours.'
                  : context === 'billing'
                  ? 'Link QuickBooks or Xero to push approved time entries and sync client invoices.'
                  : 'Connect QuickBooks or Xero to sync invoices, time entries, and client data.'}
              </p>

              <div className="flex items-center gap-3 mt-4">
                <a
                  href="/settings?tab=integrations"
                  className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
                >
                  <Zap className="w-4 h-4" />
                  Set Up Integration
                  <ArrowRight className="w-4 h-4" />
                </a>

                {/* Quick connect shortcuts */}
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <span>or connect directly:</span>
                  <span className="text-xl cursor-pointer hover:scale-110 transition-transform" title="QuickBooks">
                    📗
                  </span>
                  <span className="text-xl cursor-pointer hover:scale-110 transition-transform" title="Xero">
                    📘
                  </span>
                </div>
              </div>
            </div>
          </div>
          <button
            onClick={() => setDismissed(true)}
            className="p-1.5 text-amber-400 hover:text-amber-600 hover:bg-amber-100 rounded-lg transition-colors flex-shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>
    );
  }

  // ── Connected State ──
  return (
    <div className="flex items-center justify-between p-3 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
      <div className="flex items-center gap-3">
        {connectedProviders.map((integration) => {
          const config = PROVIDER_CONFIG[integration.provider];
          return (
            <div key={integration.provider} className="flex items-center gap-2">
              <span className="text-lg">{config.icon}</span>
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                <span className="text-sm font-bold text-emerald-800">
                  {config.name}
                </span>
                {integration.last_synced && (
                  <span className="text-xs text-emerald-600 ml-1">
                    · Synced {new Date(integration.last_synced).toLocaleDateString()}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        {/* Sync result flash */}
        {syncResult && (
          <span className="text-xs font-bold text-emerald-700 animate-in fade-in">{syncResult}</span>
        )}

        {/* Quick sync button */}
        {connectedProviders.map((integration) => (
          <button
            key={integration.provider}
            onClick={() => handleQuickSync(integration.provider)}
            disabled={syncing}
            className="flex items-center gap-1.5 px-3 py-1.5 border-2 border-emerald-200 rounded-lg text-emerald-700 font-bold text-xs hover:bg-emerald-100 transition-all disabled:opacity-50"
          >
            {syncing ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            {context === 'profitability' ? 'Pull Invoices' : 'Sync'}
          </button>
        ))}

        {/* Settings link */}
        <a
          href="/settings?tab=integrations"
          className="p-1.5 text-emerald-500 hover:text-emerald-700 hover:bg-emerald-100 rounded-lg transition-colors"
          title="Integration Settings"
        >
          <ExternalLink className="w-4 h-4" />
        </a>
      </div>
    </div>
  );
};

export default IntegrationStatusBanner;