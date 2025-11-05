import { useEffect, useState } from "react";

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api").replace(/\/+$/,"");

export default function PairDeviceModal() {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState<string>("");
  const [err, setErr] = useState<string|null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener("open-pair-modal", onOpen as any);
    return () => window.removeEventListener("open-pair-modal", onOpen as any);
  }, []);

  useEffect(() => {
    if (!open) return;
    (async () => {
      setBusy(true); setErr(null);
      try {
        const r = await fetch(`${BASE}/agents/pair/issue/`, { method: "POST", credentials: "include" });
        const j = r.ok ? await r.json() : null;
        setCode(j?.code || "");
      } catch {
        setErr("Could not create a pairing code.");
      } finally { setBusy(false); }
    })();
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
      <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Pair your Mac agent</h2>
          <button className="px-2 py-1" onClick={()=>setOpen(false)}>✕</button>
        </div>
        {err && <div className="text-red-600 text-sm border border-red-200 bg-red-50 p-2 rounded">{err}</div>}
        {busy ? (
          <div>Generating code…</div>
        ) : code ? (
          <>
            <div className="text-4xl font-mono tracking-widest text-center py-3">{code}</div>
            <ol className="list-decimal text-sm pl-4 space-y-1 text-muted-foreground">
              <li>Open the Mac agent.</li>
              <li>Click “Pair Device”, enter the code above.</li>
              <li>The agent will pair and start sending events.</li>
            </ol>
          </>
        ) : (
          <div className="text-sm text-muted-foreground">No code available.</div>
        )}
      </div>
    </div>
  );
}