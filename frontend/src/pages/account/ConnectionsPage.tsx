/**
 * CalendarConnectionTab.tsx
 * 
 * Per-user component for managing Microsoft Calendar connection.
 * Renders inside ConnectionsPage. Handles OAuth flow start, status
 * display, and disconnect.
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
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

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

  useEffect(() => {
    const callbackResult = searchParams.get('calendar');
    if (!callbackResult) return;

    if (callbackResult === 'connected') {
      setToast({
        type: 'success',
        message: 'Microsoft Calendar connected successfully',
      });
      loadStatus();
    } else if (callbackResult === 'error') {
      const reason = searchParams.get('reason') || 'unknown';
      setToast({
        type: 'error',
        message: `Connection failed: ${reason.replace(/_/g, ' ')}`,
      });
    }

    searchParams.delete('calendar');
    searchParams.delete('reason');
    setSearchParams(searchParams, { replace: true });

    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [searchParams, setSearchParams, loadStatus]);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const data = await safeFetchJson<{ auth_url: string }>(
        `${API_BASE}/calendar/auth/microsoft/start/`
      );
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

  const handleDisconnect = async () => {
    if (!confirm('Disconnect Microsoft Calendar? This will remove all calendar event data.')) {
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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {toast && (
        <div className={cn(
          'px-4 py-3 rounded-lg border text-sm font-medium',
          toast.type === 'success'
            ? 'bg-primary/5 border-primary/20 text-primary'
            : 'bg-rose-50 border-rose-200 text-rose-900'
        )}>
          {toast.message}
        </div>
      )}

      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 bg-primary/10 rounded-lg flex items-center justify-center shrink-0">
          <Calendar className="w-5 h-5 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-bold text-slate-900">Microsoft Calendar</h3>
          <p className="text-sm text-slate-500 mt-0.5">
            Connect Outlook to attribute meeting time to clients automatically.
          </p>
        </div>
      </div>

      {status?.connected ? (
        <div className="space-y-4 pt-2">
          <div className="flex items-start gap-3 px-4 py-3 bg-primary/5 border border-primary/20 rounded-lg">
            <CheckCircle2 className="w-5 h-5 text-primary mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-slate-900">Connected</p>
              <p className="text-sm text-slate-600 mt-0.5 truncate">
                {status.email || '(account email unavailable)'}
              </p>
              {status.last_synced_at && (
                <p className="text-xs text-slate-500 mt-1">
                  Last synced {new Date(status.last_synced_at).toLocaleString()}
                </p>
              )}
              {status.last_sync_error && (
                <p className="text-xs text-rose-600 mt-1.5 italic">
                  {status.last_sync_error}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={handleDisconnect}
            disabled={disconnecting}
            className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-rose-600 hover:bg-rose-50 rounded-lg disabled:opacity-50 transition-all"
          >
            {disconnecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Unplug className="w-4 h-4" />}
            Disconnect
          </button>
        </div>
      ) : (
        <div className="space-y-4 pt-2">
          <div className="flex items-start gap-3 px-4 py-3 bg-slate-50 border border-slate-200 rounded-lg">
            <AlertCircle className="w-5 h-5 text-slate-400 mt-0.5 shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-slate-900">Not connected</p>
              <p className="text-sm text-slate-500 mt-0.5">
                Calendar events help TimeTracker understand which client you're meeting with.
              </p>
            </div>
          </div>

          <div className="bg-primary/5 border border-primary/20 rounded-lg p-3 text-xs text-slate-700 space-y-1.5">
            <p className="flex items-start gap-1.5">
              <Sparkles className="w-3 h-3 text-primary mt-0.5 shrink-0" />
              <span><strong>Read-only:</strong> we only read events, never modify your calendar</span>
            </p>
            <p className="flex items-start gap-1.5">
              <Sparkles className="w-3 h-3 text-primary mt-0.5 shrink-0" />
              <span><strong>Privacy:</strong> event titles are used for matching, never displayed to others</span>
            </p>
            <p className="flex items-start gap-1.5">
              <Sparkles className="w-3 h-3 text-primary mt-0.5 shrink-0" />
              <span><strong>Disconnect anytime:</strong> all calendar data removed immediately</span>
            </p>
          </div>

          <button
            onClick={handleConnect}
            disabled={connecting}
            className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-all"
          >
            {connecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Calendar className="w-4 h-4" />}
            Connect Microsoft Calendar
          </button>
        </div>
      )}
    </div>
  );
}