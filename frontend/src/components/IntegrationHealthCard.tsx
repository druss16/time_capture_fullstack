/**
 * IntegrationHealthCard.tsx
 *
 * The status card on the Connections page, for both Mail and Calendar.
 *
 * It exists because `connected` is one bit and it is wrong in both directions:
 * a row whose Microsoft consent was abandoned reads as plain "Not connected"
 * (indistinguishable from never having tried), and a row paused after 5 failed
 * syncs still reads as "Connected" while nothing has synced for weeks. Three TL
 * Wall calendars sat in that second state for 17 days with the page showing a
 * green check the whole time.
 *
 * The `health` object from the API is the source of truth — see
 * tracker/services/integration_health.py. Server and page share one assessor
 * so they cannot drift.
 */

import { CheckCircle2, AlertCircle, AlertTriangle, Loader2, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/design-system';

export interface IntegrationHealth {
  state: 'ok' | 'never_connected' | 'paused' | 'expired' | 'disconnected' | 'stale';
  label: string;
  guidance: string;
  detail: string;
  needs_action: boolean;
  syncing: boolean;
}

interface Props {
  health: IntegrationHealth;
  // Explicit `| undefined`: the project sets exactOptionalPropertyTypes, so an
  // optional prop does not implicitly accept undefined from a caller.
  email?: string | undefined;
  lastSyncedAt?: string | null | undefined;
  /** Re-runs the same OAuth flow as the initial connect. */
  onReconnect: () => void | Promise<void>;
  reconnecting?: boolean | undefined;
  reconnectLabel: string;
}

/** Healthy is the only green. Everything else earns amber or worse. */
function tone(health: IntegrationHealth) {
  if (health.state === 'ok') {
    return {
      box: 'bg-primary/5 border-primary/20',
      Icon: CheckCircle2,
      iconClass: 'text-primary',
    };
  }
  if (health.needs_action) {
    return {
      box: 'bg-amber-50 border-amber-300',
      Icon: AlertTriangle,
      iconClass: 'text-amber-600',
    };
  }
  return {
    box: 'bg-slate-50 border-slate-200',
    Icon: AlertCircle,
    iconClass: 'text-slate-400',
  };
}

export default function IntegrationHealthCard({
  health,
  email,
  lastSyncedAt,
  onReconnect,
  reconnecting,
  reconnectLabel,
}: Props) {
  const { box, Icon, iconClass } = tone(health);

  return (
    <div className="space-y-3">
      <div className={cn('flex items-start gap-3 px-4 py-3 border rounded-lg', box)}>
        <Icon className={cn('w-5 h-5 mt-0.5 shrink-0', iconClass)} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-900">{health.label}</p>

          {email && (
            <p className="text-sm text-slate-600 mt-0.5 truncate">{email}</p>
          )}

          {health.guidance && (
            <p className="text-sm text-slate-700 mt-1">{health.guidance}</p>
          )}

          {lastSyncedAt ? (
            <p className="text-xs text-slate-500 mt-1">
              Last synced {new Date(lastSyncedAt).toLocaleString()}
            </p>
          ) : (
            health.state === 'never_connected' && (
              <p className="text-xs text-slate-500 mt-1">Never synced</p>
            )
          )}
        </div>
      </div>

      {health.needs_action && (
        <button
          onClick={onReconnect}
          disabled={reconnecting}
          className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-all"
        >
          {reconnecting
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <RefreshCw className="w-4 h-4" />}
          {reconnectLabel}
        </button>
      )}
    </div>
  );
}
