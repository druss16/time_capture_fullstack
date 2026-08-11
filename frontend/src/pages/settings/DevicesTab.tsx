// src/pages/settings/DevicesTab.tsx
import { Monitor, RefreshCw, Check, X } from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import type { Device } from './types';
import { SettingsPage, secondaryBtnClass } from './ui';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface Props {
  devices: Device[];
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

export default function DevicesTab({ devices, onRefresh, onSuccess, onError }: Props) {
  const handleDeactivate = async (deviceId: number, machineName: string) => {
    if (!confirm(`Deactivate device "${machineName}"?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/devices/${deviceId}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: false }),
      });
      onSuccess('Device deactivated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to deactivate');
    }
  };

  const handleActivate = async (deviceId: number) => {
    try {
      await safeFetchJson(`${API_BASE}/settings/devices/${deviceId}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: true }),
      });
      onSuccess('Device activated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to activate');
    }
  };

  const formatLastSeen = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getOSIcon = (os: string) => {
    const l = os.toLowerCase();
    if (l.includes('mac') || l.includes('darwin')) return '🍎';
    if (l.includes('win')) return '🪟';
    if (l.includes('linux')) return '🐧';
    return '💻';
  };

  return (
    <SettingsPage
      title="Devices"
      subtitle={`${devices.length} registered device${devices.length !== 1 ? 's' : ''}`}
      actions={
        <button onClick={onRefresh} className={secondaryBtnClass}>
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      }
    >
      <div className="rounded-2xl border border-slate-200/70 overflow-hidden">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border/60 bg-slate-50/80">
              {['Device', 'User', 'OS', 'Agent Version', 'Last Seen', 'Status', 'Actions'].map(h => (
                <th key={h} className={cn(
                  'px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500',
                  h === 'Actions' ? 'text-right' : 'text-left'
                )}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {devices.length === 0 ? (
              <tr>
                <td colSpan={7} className="text-center py-14">
                  <Monitor className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                  <p className="font-semibold text-slate-500">No devices registered</p>
                  <p className="text-xs text-slate-400 mt-1">Install the TimeTracker agent on your team's computers</p>
                </td>
              </tr>
            ) : devices.map(device => (
              <tr key={device.id} className="hover:bg-slate-50/60 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{getOSIcon(device.os)}</span>
                    <span className="font-semibold text-slate-800">{device.machine_name}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-600">{device.user}</td>
                <td className="px-4 py-3 text-slate-500 text-xs">{device.os} {device.os_version}</td>
                <td className="px-4 py-3 text-slate-500 font-mono text-xs">{device.agent_version || '—'}</td>
                <td className="px-4 py-3 text-slate-400 text-xs">{formatLastSeen(device.last_seen)}</td>
                <td className="px-4 py-3">
                  <span className={cn('text-xs px-2 py-0.5 rounded-full font-semibold border',
                    device.is_active
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : 'bg-slate-100 text-slate-400 border-slate-200'
                  )}>
                    {device.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {device.is_active ? (
                    <button onClick={() => handleDeactivate(device.id, device.machine_name)} className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  ) : (
                    <button onClick={() => handleActivate(device.id)} className="p-1.5 text-slate-400 hover:text-emerald-500 hover:bg-emerald-50 rounded-lg transition-colors">
                      <Check className="w-3.5 h-3.5" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SettingsPage>
  );
}