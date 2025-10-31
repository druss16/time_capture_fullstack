// src/pages/TimecardSummary.tsx
import { useEffect, useMemo, useState } from "react";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type TaskRow = { task_name: string; total_hours: number; categories: Record<string, number>; block_ids?: number[]; };
type ClientRow = { client_name: string; total_hours: number; categories: Record<string, number>; block_ids?: number[]; tasks?: TaskRow[]; };
type SummaryResp = { date: string; user: string; total_hours: number; clients: ClientRow[]; };

const fmtHours = (n: number) => (Math.round((n || 0) * 100) / 100).toFixed(2);
const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export default function TimecardSummary() {
  const [data, setData] = useState<SummaryResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [user, setUser] = useState<string>(""); // blank = all users
  const [date, setDate] = useState<string>(todayIso());
  const [err, setErr] = useState<string | null>(null);
  const [whoami, setWhoami] = useState<string>("");

  // Prefill user once per page load
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/whoami/`, { credentials: "include" });
        if (r.ok) {
          const j = (await r.json()) as { username?: string };
          if (j?.username) {
            setWhoami(j.username);
            // only auto-fill if the input is still blank
            setUser((u) => (u.trim() ? u : j.username!));
          }
        }
      } catch {/* ignore */}
    })();
  }, []);

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      const url = new URL(`${API_BASE}/timecards/summary/day/`);
      url.searchParams.set("date", date);
      if (user.trim()) url.searchParams.set("user", user.trim());

      const r = await fetch(url.toString(), { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as SummaryResp;

      const clients = Array.isArray(j.clients) ? j.clients : [];
      clients.forEach((c) => ((c as any).tasks = Array.isArray((c as any).tasks) ? (c as any).tasks : []));

      setData({
        date: j.date || date,
        user: typeof j.user === "string" ? j.user : user,
        total_hours: Number(j.total_hours || 0),
        clients,
      });
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to load.");
      setData({ date, user, total_hours: 0, clients: [] });
    } finally {
      setBusy(false);
    }
  };

  const generate = async (status: "draft" | "pending" = "pending") => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`${API_BASE}/timecards/generate/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ date, user, status }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json();
      await load();
    } catch (e: any) {
      console.error(e);
      setErr(e?.message || "Failed to generate.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [date, user]);

  const headerUser = useMemo(() => {
    // Prefer the explicit filter value, then the server’s response, otherwise show All Users
    return user?.trim() ? user.trim() : (data?.user?.trim() ? data.user : "All Users");
  }, [user, data?.user]);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-semibold">Timecard Summary</h1>
        {whoami && (
          <span className="text-xs rounded-full border px-2 py-1 text-gray-700">
            This Mac user: <strong>{whoami}</strong>
          </span>
        )}
      </div>
      <p className="text-sm text-gray-600">Grouped by client with category breakdowns. No micro-blocks.</p>

      <div className="flex flex-wrap items-center gap-2">
        <input type="date" className="border rounded px-2 py-1" value={date} onChange={(e) => setDate(e.target.value)} />
        <input
          type="text"
          className="border rounded px-2 py-1"
          placeholder="(leave blank for all users)"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          list="user-hints"
        />
        <datalist id="user-hints">{whoami ? <option value={whoami} /> : null}</datalist>

        <button onClick={load} className="border rounded px-3 py-1 hover:bg-gray-50" disabled={busy}>Refresh</button>
        <button onClick={() => generate("pending")} className="border rounded px-3 py-1 hover:bg-gray-50" disabled={busy}>Save as Pending</button>
      </div>

      {busy && <div className="text-sm text-gray-600">Loading…</div>}
      {err && <div className="text-sm text-red-600">{err}</div>}

      {!!data && (
        <div className="bg-white border rounded-lg">
          <div className="flex items-center justify-between p-4 border-b">
            <div className="text-sm text-gray-700"><strong>{headerUser}</strong> • {data.date}</div>
            <div className="text-sm"><strong>Total: {fmtHours(data.total_hours)} h</strong></div>
          </div>

          <div className="divide-y">
            {data.clients.map((c) => (
              <div key={c.client_name} className="p-4">
                <div className="flex items-center justify-between">
                  <div className="text-lg font-medium">{c.client_name}</div>
                  <div className="text-lg font-semibold">{fmtHours(c.total_hours)} h</div>
                </div>

                <div className="mt-2 flex flex-wrap gap-2">
                  {Object.entries(c.categories || {}).length === 0 && <span className="text-gray-400 text-sm">—</span>}
                  {Object.entries(c.categories || {}).map(([cat, hrs]) => (
                    <span key={cat} className="inline-flex items-center rounded-full border px-2 py-0.5 text-sm">
                      <span className="mr-1">{cat}</span>
                      <span className="font-medium">{fmtHours(hrs)}h</span>
                    </span>
                  ))}
                </div>

                {(c as any).tasks?.length ? (
                  <div className="mt-3 ml-4 space-y-1">
                    {(c as any).tasks.map((t: any) => (
                      <div key={`${c.client_name}-${t.task_name}`} className="flex items-center justify-between text-sm">
                        <div className="text-gray-700">• {t.task_name}</div>
                        <div className="font-medium">{fmtHours(Number(t.total_hours || 0))} h</div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}

            {!data.clients.length && (
              <div className="p-6 text-center text-gray-500">No tracked time for this date.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}