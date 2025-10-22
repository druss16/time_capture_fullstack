import { useEffect, useMemo, useState } from "react";
import { BlockDto } from "../types";
import { downloadTodayCsv, fetchBlocksToday, fetchSuggestionsToday } from "../api/blocks";
import BlockCard from "../components/BlockCard";
import { useAuth } from "../auth/AuthProvider";

export default function DailyReview() {
  const [blocks, setBlocks] = useState<BlockDto[] | null>(null);
  const [busy, setBusy] = useState(false);
  const { logout } = useAuth();

  const load = async () => {
    setBusy(true);
    try {
      // pull blocks first
      const b = await fetchBlocksToday();
      // trigger (re)compute + get top-3 suggestions
      const withSug = await fetchSuggestionsToday();
      // merge suggestions into the already-fetched blocks by id
      const sugMap = new Map(withSug.map((x) => [x.id, x.suggestions || []]));
      setBlocks(b.map((x) => ({ ...x, suggestions: sugMap.get(x.id) || [] })));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); }, []);

  const totalMinutes = useMemo(() => (blocks?.reduce((acc, b) => acc + b.minutes, 0) ?? 0), [blocks]);

  const downloadCsv = async () => {
    const blob = await downloadTodayCsv();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "blocks_today.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Daily Review</h1>
        <div className="flex items-center gap-3">
          <button onClick={downloadCsv} className="border rounded-lg px-3 py-2">Export CSV</button>
          <button onClick={logout} className="border rounded-lg px-3 py-2">Logout</button>
        </div>
      </header>

      <div className="opacity-70 text-sm">
        {busy ? "Refreshing…" : `Total: ${totalMinutes} minutes across ${blocks?.length ?? 0} blocks`}
      </div>

      <div className="space-y-4">
        {blocks?.map((b) => (
          <BlockCard key={b.id} block={b} onLabeled={load} />
        ))}

        {!blocks?.length && !busy && <div className="opacity-70">No blocks yet today.</div>}
      </div>
    </div>
  );
}
