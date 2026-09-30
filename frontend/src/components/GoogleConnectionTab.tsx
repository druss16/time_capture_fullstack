/**
 * GoogleConnectionTab.tsx
 *
 * Per-user Gmail / Google Calendar connection card on Account → Connections.
 * The Google counterpart of MailConnectionTab / CalendarConnectionTab: same
 * status → health card → connect / disconnect shape, one component for both
 * Google products because only the endpoints and the copy differ.
 *
 * Backend: tracker/views_google.py. The OAuth callback lands back on this page
 * with ?gmail=connected|error or ?gcal=connected|error.
 *
 * Privacy (mirrors MailSignal's PRIVACY GUARANTEES for provider='google'):
 *   - Gmail uses the gmail.metadata scope: headers only, bodies and
 *     attachments are unreadable at the API level.
 *   - Sender/recipient addresses and subjects ARE stored for Gmail, and are
 *     shown only to you — managers and admins see the matched client and the
 *     counterparty domain, nothing more.
 */

import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Mail, Calendar, AlertCircle, Loader2, Unplug, Sparkles } from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import IntegrationHealthCard, { type IntegrationHealth } from '@/components/IntegrationHealthCard';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

type GoogleProduct = 'gmail' | 'calendar';

interface GoogleStatus {
  connected: boolean;
  configured?: boolean | undefined;
  org_disabled?: boolean | undefined;
  email?: string | undefined;
  last_synced_at?: string | null | undefined;
  last_sync_error?: string | undefined;
  health?: IntegrationHealth | undefined;
}

const COPY: Record<GoogleProduct, {
  title: string;
  pitch: string;
  queryKey: string;
  path: string;
  disconnectConfirm: string;
  bullets: { lead: string; text: string }[];
}> = {
  gmail: {
    title: 'Gmail',
    pitch: 'Connect Google Workspace mail so TimeTracker can match who you email to your clients.',
    queryKey: 'gmail',
    path: 'google/gmail',
    disconnectConfirm: 'Disconnect Gmail? This removes all stored Gmail signals.',
    bullets: [
      { lead: 'Headers only:', text: 'Google blocks message bodies and attachments at the API level for this permission — we never see them' },
      { lead: 'Only you see who:', text: 'sender, recipients and subject lines are shown to you alone; your manager and admins see only the matched client and domain' },
      { lead: 'Compose time:', text: 'when you send from Gmail, the time you spent writing is credited to the recipient\'s client' },
      { lead: 'Read-only:', text: 'we never send, modify, label or move messages' },
      { lead: 'Disconnect anytime:', text: 'all stored Gmail signals are removed immediately' },
    ],
  },
  calendar: {
    title: 'Google Calendar',
    pitch: 'Connect Google Calendar so meetings are attributed to the right client automatically.',
    queryKey: 'gcal',
    path: 'google/calendar',
    disconnectConfirm: 'Disconnect Google Calendar? This removes all synced calendar events.',
    bullets: [
      { lead: 'Read-only:', text: 'we only read events, never modify your calendar' },
      { lead: 'Privacy:', text: 'event titles are used for matching, never displayed to others' },
      { lead: 'Disconnect anytime:', text: 'all calendar data removed immediately' },
    ],
  },
};

export default function GoogleConnectionTab({ product }: { product: GoogleProduct }) {
  const copy = COPY[product];
  const Icon = product === 'gmail' ? Mail : Calendar;

  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await safeFetchJson<GoogleStatus>(`${API_BASE}/${copy.path}/status/`));
    } catch (err: any) {
      console.error(`[${copy.title}] status fetch failed:`, err);
      setStatus({ connected: false });
    } finally {
      setLoading(false);
    }
  }, [copy.path, copy.title]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    const result = searchParams.get(copy.queryKey);
    if (!result) return;

    if (result === 'connected') {
      setToast({ type: 'success', message: `${copy.title} connected successfully` });
      loadStatus();
      // The first sync is enqueued on connect; refresh so last_synced_at fills in.
      setTimeout(loadStatus, 3000);
    } else if (result === 'error') {
      const reason = searchParams.get('reason') || 'unknown';
      setToast({
        type: 'error',
        message: reason === 'permission_not_granted'
          ? `Connection failed: Google access was not granted. Connect again and leave the ${copy.title} permission ticked.`
          : `Connection failed: ${reason.replace(/_/g, ' ')}`,
      });
    }

    searchParams.delete(copy.queryKey);
    searchParams.delete('reason');
    setSearchParams(searchParams, { replace: true });

    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [searchParams, setSearchParams, loadStatus, copy.queryKey, copy.title]);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const data = await safeFetchJson<{ auth_url: string }>(`${API_BASE}/${copy.path}/auth/start/`);
      window.location.href = data.auth_url;
    } catch (err: any) {
      setToast({ type: 'error', message: err?.message || 'Failed to start connection' });
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm(copy.disconnectConfirm)) return;
    setDisconnecting(true);
    try {
      await safeFetchJson(`${API_BASE}/${copy.path}/disconnect/`, { method: 'POST' });
      setToast({ type: 'success', message: `${copy.title} disconnected` });
      loadStatus();
    } catch (err: any) {
      setToast({ type: 'error', message: err?.message || 'Disconnect failed' });
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

  const header = (muted: boolean, subtitle: string) => (
    <div className="flex items-start gap-3">
      <div className={cn(
        'w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
        muted ? 'bg-slate-100' : 'bg-primary/10',
      )}>
        <Icon className={cn('w-5 h-5', muted ? 'text-slate-400' : 'text-primary')} />
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="text-base font-bold text-slate-900">{copy.title}</h3>
        <p className="text-sm text-slate-500 mt-0.5">{subtitle}</p>
      </div>
    </div>
  );

  if (status?.org_disabled) {
    return <div className="space-y-4">{header(true, 'Mail integration has been disabled by your administrator.')}</div>;
  }

  const health: IntegrationHealth = status?.health ?? {
    state: status?.connected ? 'ok' : 'disconnected',
    label: status?.connected ? 'Connected' : 'Not connected',
    guidance: '',
    detail: status?.last_sync_error || '',
    needs_action: false,
    syncing: !!status?.connected,
  };
  const showCard = !!status?.connected || health.needs_action;
  const notConfigured = status?.configured === false;

  return (
    <div className="space-y-4">
      {toast && (
        <div className={cn(
          'px-4 py-3 rounded-lg border text-sm font-medium',
          toast.type === 'success'
            ? 'bg-primary/5 border-primary/20 text-primary'
            : 'bg-rose-50 border-rose-200 text-rose-900',
        )}>
          {toast.message}
        </div>
      )}

      {header(false, copy.pitch)}

      {showCard ? (
        <div className="space-y-4 pt-2">
          <IntegrationHealthCard
            health={health}
            email={status?.email}
            lastSyncedAt={status?.last_synced_at}
            onReconnect={handleConnect}
            reconnecting={connecting}
            reconnectLabel={`Reconnect ${copy.title}`}
          />
          {health.state !== 'never_connected' && (
            <button
              onClick={handleDisconnect}
              disabled={disconnecting}
              className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-rose-600 hover:bg-rose-50 rounded-lg disabled:opacity-50 transition-all"
            >
              {disconnecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Unplug className="w-4 h-4" />}
              Disconnect
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-4 pt-2">
          <div className="flex items-start gap-3 px-4 py-3 bg-slate-50 border border-slate-200 rounded-lg">
            <AlertCircle className="w-5 h-5 text-slate-400 mt-0.5 shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-slate-900">Not connected</p>
              <p className="text-sm text-slate-500 mt-0.5">
                {notConfigured
                  ? 'Google sign-in is not set up on this server yet. Ask your TimeTracker administrator.'
                  : 'Uses your Google Workspace account. You can disconnect at any time.'}
              </p>
            </div>
          </div>

          <div className="bg-primary/5 border border-primary/20 rounded-lg p-3 text-xs text-slate-700 space-y-1.5">
            {copy.bullets.map((b) => (
              <p key={b.lead} className="flex items-start gap-1.5">
                <Sparkles className="w-3 h-3 text-primary mt-0.5 shrink-0" />
                <span><strong>{b.lead}</strong> {b.text}</span>
              </p>
            ))}
          </div>

          <button
            onClick={handleConnect}
            disabled={connecting || notConfigured}
            className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-all"
          >
            {connecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Icon className="w-4 h-4" />}
            Connect {copy.title}
          </button>
        </div>
      )}
    </div>
  );
}
