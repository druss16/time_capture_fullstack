// src/pages/Devices.tsx
/**
 * Devices.tsx - My Devices page
 * Updated to match design system
 */

import PairDeviceCard from "@/components/PairDeviceCard";
import { useEffect, useState } from "react";
import { safeFetchJson, API_BASE } from '@/lib/api';
import { Monitor, RefreshCw, Laptop, AlertCircle } from 'lucide-react';
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
      const data = await safeFetchJson<{ devices: Device[] }>(`${API_BASE}/devices/`);
      setDevices(data.devices || []);
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
    if (diffHours < 1) return 'bg-emerald-500';
    if (diffHours < 24) return 'bg-amber-500';
    return 'bg-slate-400';
  };

  return (
    <div className="space-y-6">
      {/* Header Card */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 bg-primary/10 rounded-2xl flex items-center justify-center">
            <Monitor className="w-7 h-7 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">My Devices</h2>
            <p className="text-slate-500 font-medium">Manage and link your Time Capture desktop apps</p>
          </div>
        </div>

        {/* Pair new device */}
        <PairDeviceCard />
      </div>

      {/* Linked Devices Card */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 overflow-hidden">
        <div className="px-8 py-5 border-b-2 border-slate-200 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Linked Devices</h3>
            <p className="text-sm text-slate-500 font-medium">{devices.length} device{devices.length !== 1 ? 's' : ''} connected</p>
          </div>
          <button
            onClick={fetchDevices}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-50 transition-all disabled:opacity-50"
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
            Refresh
          </button>
        </div>

        <div className="p-8">
          {loading && devices.length === 0 && (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="w-6 h-6 text-primary animate-spin" />
            </div>
          )}

          {error && (
            <div className="bg-red-50 border-2 border-red-200 rounded-xl p-4 flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
              <p className="text-red-700 font-medium">{error}</p>
            </div>
          )}

          {!loading && !error && devices.length === 0 && (
            <div className="text-center py-12">
              <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-4">
                <Laptop className="w-8 h-8 text-slate-400" />
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
                    <th className="text-left px-4 py-3 text-sm font-bold text-slate-500">Status</th>
                    <th className="text-left px-4 py-3 text-sm font-bold text-slate-500">Hostname</th>
                    <th className="text-left px-4 py-3 text-sm font-bold text-slate-500">Platform</th>
                    <th className="text-left px-4 py-3 text-sm font-bold text-slate-500">Version</th>
                    <th className="text-left px-4 py-3 text-sm font-bold text-slate-500">Last Seen</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {devices.map((d) => (
                    <tr key={d.device_id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          <div className={cn('w-3 h-3 rounded-full', d.is_active ? getStatusColor(d.last_seen_at) : 'bg-slate-300')} />
                          <span className={cn(
                            'text-xs px-2 py-1 rounded-full font-bold',
                            d.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
                          )}>
                            {d.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-4 font-bold text-slate-900">{d.hostname || '—'}</td>
                      <td className="px-4 py-4 text-sm text-slate-600 font-medium capitalize">{d.platform || '—'}</td>
                      <td className="px-4 py-4 text-sm text-slate-500 font-mono font-semibold">{d.app_version || '—'}</td>
                      <td className="px-4 py-4 text-sm text-slate-500 font-medium">
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
        <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-6">
          <div className="flex items-center gap-6 text-sm text-slate-500">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-emerald-500" />
              <span className="font-medium">Active now</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-amber-500" />
              <span className="font-medium">Active today</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-slate-400" />
              <span className="font-medium">Inactive</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}