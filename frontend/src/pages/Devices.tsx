// src/pages/Devices.tsx
/**
 * Devices.tsx - My Devices page
 * Updated to match design system with teal colors
 */

import PairDeviceCard from "@/components/PairDeviceCard";
import { useEffect, useState } from "react";
import { safeFetchJson, API_BASE } from '@/lib/api';
import { Monitor, RefreshCw, Laptop, AlertCircle, Trash2 } from 'lucide-react';
import { cn } from '@/lib/design-system';

type Device = {
  device_id: string;
  hostname: string;
  platform: string;
  app_version: string;
  is_active: boolean;
  last_seen_at: string | null;
};

export default function Devices() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  async function fetchDevices() {
    setLoading(true);
    setError("");
    try {
      // The endpoint returns a bare array; tolerate a wrapped shape too so this
      // does not silently render "no devices" if that ever changes.
      const data = await safeFetchJson<Device[] | { devices: Device[] }>(`${API_BASE}/devices/`);
      setDevices(Array.isArray(data) ? data : data?.devices || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchDevices();
  }, []);

  const formatLastSeen = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
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

  const getStatusColor = (lastSeen: string | null) => {
    if (!lastSeen) return 'bg-slate-400';
    const date = new Date(lastSeen);
    const now = new Date();
    const diffHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);
    if (diffHours < 1) return 'bg-teal-500';
    if (diffHours < 24) return 'bg-amber-500';
    return 'bg-slate-400';
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-teal-500 flex items-center justify-center shadow-lg shadow-teal-500/25">
            <Monitor className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">My Devices</h1>
            <p className="text-slate-600 font-medium">Manage and link your TimeTracker desktop apps</p>
          </div>
        </div>

        {/* Pair new device */}
        <PairDeviceCard />

        {/* Linked Devices */}
        <div className="bg-white rounded-2xl border-2 border-slate-200 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b-2 border-slate-200 bg-slate-50 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-extrabold text-slate-900">Linked Devices</h2>
              <p className="text-sm text-slate-600 font-medium">{devices.length} device{devices.length !== 1 ? 's' : ''} connected</p>
            </div>
            <button
              onClick={fetchDevices}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all disabled:opacity-50"
            >
              <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
              Refresh
            </button>
          </div>

          <div className="p-6">
            {loading && devices.length === 0 && (
              <div className="flex items-center justify-center py-8">
                <RefreshCw className="w-6 h-6 text-teal-500 animate-spin" />
              </div>
            )}

            {error && (
              <div className="bg-red-50 border-2 border-red-200 rounded-xl p-4 flex items-center gap-3 text-red-700 font-semibold">
                <AlertCircle className="w-5 h-5 flex-shrink-0" />
                {error}
              </div>
            )}

            {!loading && !error && devices.length === 0 && (
              <div className="text-center py-12">
                <div className="w-16 h-16 rounded-full bg-teal-100 flex items-center justify-center mx-auto mb-4">
                  <Laptop className="w-8 h-8 text-teal-500" />
                </div>
                <p className="text-slate-900 font-bold">No devices linked yet</p>
                <p className="text-sm text-slate-500 font-medium mt-1">
                  Use the pairing code above to connect your first device
                </p>
              </div>
            )}

            {devices.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b-2 border-slate-200">
                      <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Status</th>
                      <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Hostname</th>
                      <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Platform</th>
                      <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Version</th>
                      <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Last Seen</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {devices.map((d) => (
                      <tr key={d.device_id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className={cn('w-3 h-3 rounded-full', d.is_active ? getStatusColor(d.last_seen_at) : 'bg-slate-300')} />
                            <span className={cn(
                              'text-xs px-2 py-1 rounded-full font-bold',
                              d.is_active ? 'bg-teal-100 text-teal-700' : 'bg-slate-100 text-slate-500'
                            )}>
                              {d.is_active ? 'Active' : 'Inactive'}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 font-bold text-slate-900">{d.hostname || '—'}</td>
                        <td className="px-4 py-3 text-sm text-slate-700 font-medium capitalize">{d.platform || '—'}</td>
                        <td className="px-4 py-3 text-sm text-slate-500 font-mono font-semibold">{d.app_version || '—'}</td>
                        <td className="px-4 py-3 text-sm text-slate-500 font-medium">
                          {formatLastSeen(d.last_seen_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Status Legend */}
        {devices.length > 0 && (
          <div className="flex items-center gap-6 text-sm text-slate-600 font-medium">
            <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-teal-500" />Active now</div>
            <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-amber-500" />Active today</div>
            <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-slate-400" />Inactive</div>
          </div>
        )}
      </div>
    </div>
  );
}