import { useEffect, useState } from "react";
import { fetchRecentBlocks } from "../api/blocks";

type BlockRow = {
  id: number;
  user: number | string;
  hostname: string;
  start: string;
  end: string;
  window_title: string;
  url: string | null;
  file_path: string | null;
  ai_extracted_client: string;
  ai_category: string;
  ai_confidence: number;
  ai_processed_at: string;
};

export default function RecentClassifications() {
  const [rows, setRows] = useState<BlockRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const data = await fetchRecentBlocks(false, 50);
        setRows(data);
      } catch (e:any) {
        setErr(e?.message || "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="p-4 text-sm opacity-70">Loading…</div>;
  if (err) return <div className="p-4 text-sm text-red-600">{err}</div>;

  return (
    <div className="p-4">
      <h2 className="text-xl font-semibold mb-3">Recent AI Classifications</h2>
      <div className="overflow-x-auto rounded-2xl shadow">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left">When</th>
              <th className="px-3 py-2 text-left">Client</th>
              <th className="px-3 py-2 text-left">Category</th>
              <th className="px-3 py-2 text-left">Confidence</th>
              <th className="px-3 py-2 text-left">Window</th>
              <th className="px-3 py-2 text-left">Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-b last:border-0">
                <td className="px-3 py-2">{new Date(r.ai_processed_at).toLocaleString()}</td>
                <td className="px-3 py-2 font-medium">{r.ai_extracted_client || "—"}</td>
                <td className="px-3 py-2">{r.ai_category}</td>
                <td className="px-3 py-2">{(r.ai_confidence * 100).toFixed(1)}%</td>
                <td className="px-3 py-2">{r.window_title}</td>
                <td className="px-3 py-2">
                  {r.url ? <a className="underline" href={r.url} target="_blank">url</a> :
                   r.file_path ? <span title={r.file_path}>file</span> : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}