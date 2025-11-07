import PairDeviceCard from "@/components/PairDeviceCard";
import { useEffect, useState } from "react";

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
      const res = await fetch("/api/devices/", {
        credentials: "include",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load devices");
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

  return (
    <div className="max-w-3xl mx-auto p-8 space-y-8">
      <h1 className="text-2xl font-bold text-blue-900">My Devices</h1>
      <p className="text-blue-700 text-sm">
        Manage and link your Time Capture desktop apps.
      </p>

      {/* Pair new device */}
      <PairDeviceCard />

      {/* Existing devices */}
      <div className="mt-8">
        <h2 className="text-lg font-semibold text-blue-900 mb-3">Linked Devices</h2>
        {loading && <div className="text-blue-700 text-sm">Loading...</div>}
        {error && <div className="text-red-600 text-sm">{error}</div>}

        {devices.length === 0 && !loading && (
          <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-800">
            No devices linked yet.
          </div>
        )}

        {devices.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full border border-blue-100 bg-white shadow-sm rounded-xl text-sm">
              <thead className="bg-blue-50 text-blue-900">
                <tr>
                  <th className="px-4 py-2 text-left">Hostname</th>
                  <th className="px-4 py-2 text-left">Platform</th>
                  <th className="px-4 py-2 text-left">Version</th>
                  <th className="px-4 py-2 text-left">Last Seen</th>
                  <th className="px-4 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {devices.map((d) => (
                  <tr key={d.device_id} className="border-t border-blue-100">
                    <td className="px-4 py-2">{d.hostname || "—"}</td>
                    <td className="px-4 py-2">{d.platform || "—"}</td>
                    <td className="px-4 py-2">{d.app_version || "—"}</td>
                    <td className="px-4 py-2 text-blue-700">
                      {d.last_seen_at
                        ? new Date(d.last_seen_at).toLocaleString()
                        : "Never"}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          d.is_active
                            ? "bg-green-100 text-green-700"
                            : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {d.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}