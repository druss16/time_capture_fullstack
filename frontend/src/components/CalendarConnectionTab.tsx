/**
 * CalendarConnectionTab.tsx
 * 
 * Settings tab for managing Microsoft Calendar connection.
 * - Shows connection status (connected/disconnected, email)
 * - "Connect" button → kicks off OAuth flow
 * - "Disconnect" button → clears tokens, deletes derived events
 * - Handles ?calendar=connected | ?calendar=error URL params from OAuth callback
 */

import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Calendar,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Unplug,
  Sparkles,
} from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';

interface CalendarStatus {
  connected: boolean;
  email?: string;
  last_synced_at?: string | null;
  last_sync_error?: string;
}

export default function CalendarConnectionTab() {
  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [toast, setToast] = useState<{
    type: 'success' | 'error';
    message: string;
  } | null>(null);

  // ── Load current status ──
  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await safeFetchJson<CalendarStatus>(
        `${API_BASE}/calendar/microsoft/status/`
      );
      setStatus(data);
    } catch (err: any) {
      console.error('[Calendar] status fetch failed:', err);
      setStatus({ connected: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // ── Handle OAuth callback redirect (?calendar=connected | error) ──
  useEffect(() => {
    const callbackResult = searchParams.get('calendar');
    if (!callbackResult) return;

    if (callbackResult === 'connected') {
      setToast({
        type: 'success',
        message: 'Microsoft Calendar connected successfully',
      });
      loadStatus(); // refresh
    } else if (callbackResult === 'error') {
      const reason = searchParams.get('reason') || 'unknown';
      setToast({
        type: 'error',
        message: `Connection failed: ${reason.replace(/_/g, ' ')}`,
      });
    }

    // Clear the URL params so refresh doesn't re-trigger toast
    searchParams.delete('calendar');
    searchParams.delete('reason');
    setSearchParams(searchParams, { replace: true });

    // Auto-clear toast after 5s
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [searchParams, setSearchParams, loadStatus]);

  // ── Connect ──
  const handleConnect = async () => {
    setConnecting(true);
    try {
      const data = await safeFetchJson<{ auth_url: string }>(
        `${API_BASE}/calendar/auth/microsoft/start/`
      );
      // Redirect to Microsoft sign-in
      window.location.href = data.auth_url;
    } catch (err: any) {
      console.error('[Calendar] connect failed:', err);
      setToast({
        type: 'error',
        message: err?.message || 'Failed to start connection',
      });
      setConnecting(false);
    }
  };

  // ── Disconnect ──
  const handleDisconnect = async () => {
    if (
      !confirm(
        'Disconnect Microsoft Calendar? This will remove all calendar event data.'
      )
    ) {
      return;
    }
    setDisconnecting(true);
    try {
      await safeFetchJson(`${API_BASE}/calendar/microsoft/disconnect/`, {
        method: 'POST',
      });
      setToast({ type: 'success', message: 'Calendar disconnected' });
      loadStatus();
    } catch (err: any) {
      setToast({
        type: 'error',
        message: err?.message || 'Disconnect failed',
      });
    } finally {
      setDisconnecting(false);
    }
  };

  // ── Render ──
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-2xl">
      {/* Toast */}
      {toast && (
        <div
          className={`px-4 py-3 rounded-lg border text-sm font-medium ${
            toast.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
              : 'bg-rose-50 border-rose-200 text-rose-900'
          }`}
        >
          {toast.message}
        </div>
      )}

      {/* Header */}
      <div className="flex items-start gap-3 mb-2">
        <div className="p-2 bg-blue-50 rounded-lg">
          <Calendar className="w-5 h-5 text-blue-600" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-bold text-slate-800">
            Microsoft Calendar
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Connect Outlook to attribute meeting time to clients automatically.
          </p>
        </div>
      </div>

      {/* Connection card */}
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        {status?.connected ? (
          // ── Connected state ──
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="w-5 h-5 text-emerald-500 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-slate-800">
                  Connected
                </p>
                <p className="text-sm text-slate-500 mt-0.5 truncate">
                  {status.email || '(account email unavailable)'}
                </p>
                {status.last_synced_at && (
                  <p className="text-xs text-slate-400 mt-1">
                    Last synced{' '}
                    {new Date(status.last_synced_at).toLocaleString()}
                  </p>
                )}
                {status.last_sync_error && (
                  <p className="text-xs text-rose-600 mt-1.5 italic">
                    {status.last_sync_error}
                  </p>
                )}
              </div>
            </div>

            <div className="flex gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-rose-600 hover:bg-rose-50 rounded-lg disabled:opacity-50 transition-all"
              >
                {disconnecting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Unplug className="w-4 h-4" />
                )}
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          // ── Not connected state ──
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-slate-400 mt-0.5 shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-slate-800">
                  Not connected
                </p>
                <p className="text-sm text-slate-500 mt-0.5">
                  TimeTracker will use your meeting times to better classify
                  what client you're working on.
                </p>
              </div>
            </div>

            <div className="bg-slate-50 rounded-lg p-3 text-xs text-slate-600 space-y-1">
              <p className="flex items-start gap-1.5">
                <Sparkles className="w-3 h-3 text-blue-500 mt-0.5 shrink-0" />
                <span>
                  <strong>Read-only:</strong> we only read events, never
                  modify your calendar
                </span>
              </p>
              <p className="flex items-start gap-1.5">
                <Sparkles className="w-3 h-3 text-blue-500 mt-0.5 shrink-0" />
                <span>
                  <strong>Privacy:</strong> event titles are used for
                  matching but never displayed to other users
                </span>
              </p>
              <p className="flex items-start gap-1.5">
                <Sparkles className="w-3 h-3 text-blue-500 mt-0.5 shrink-0" />
                <span>
                  <strong>Disconnect anytime:</strong> all calendar data
                  removed immediately
                </span>
              </p>
            </div>

            <button
              onClick={handleConnect}
              disabled={connecting}
              className="w-full sm:w-auto flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-all"
            >
              {connecting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Calendar className="w-4 h-4" />
              )}
              Connect Microsoft Calendar
            </button>
          </div>
        )}
      </div>
    </div>
  );
}