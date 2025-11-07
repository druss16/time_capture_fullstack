// src/components/PairDeviceCard.tsx
import { useEffect, useState } from "react";

const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

function getCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

type PairResp = { ok: boolean; code: string; expires_at: string; ttl_seconds: number };

export default function PairDeviceCard() {
  const [code, setCode] = useState("");
  const [expiresAt, setExpiresAt] = useState<Date | null>(null);
  const [left, setLeft] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function issueCode() {
    setErr("");
    setLoading(true);
    try {
      // make sure CSRF cookie exists (your app already calls /api/get-csrf/ at startup via AuthProvider)
      const csrftoken = getCookie("csrftoken") || "";

      const res = await fetch(`${API_BASE}/agents/pair/issue/`, {
        method: "POST",
        credentials: "include",                  // send session cookie
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrftoken,              // required for Django session-auth POST
        },
        body: JSON.stringify({ ttl_seconds: 600 }),
      });

      const data = (await res.json()) as Partial<PairResp>;
      if (!res.ok || !data?.code) {
        throw new Error((data as any)?.error || "Failed to issue code");
      }
      setCode(data.code!);
      setExpiresAt(new Date(data.expires_at!));
    } catch (e: any) {
      setErr(e.message || "Error issuing code");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = setInterval(() => {
      if (!expiresAt) return setLeft(0);
      setLeft(Math.max(0, Math.floor((expiresAt.getTime() - Date.now()) / 1000)));
    }, 500);
    return () => clearInterval(t);
  }, [expiresAt]);

  const expired = !!expiresAt && Date.now() > expiresAt.getTime();

  return (
    <div className="rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
      <h3 className="text-xl font-semibold text-blue-900">Pair this Mac</h3>
      <p className="mt-1 text-sm text-blue-700">
        Generate a one-time code and enter it in the Time Capture app on your Mac.
      </p>

      {!code ? (
        <button
          onClick={issueCode}
          disabled={loading}
          className="mt-4 rounded-xl bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Generating…" : "Generate Pairing Code"}
        </button>
      ) : (
        <div className="mt-4 flex items-center justify-between rounded-xl border border-blue-100 bg-blue-50 p-4">
          <div>
            <div className="text-sm text-blue-800">Your pairing code</div>
            <div className="mt-1 font-mono text-3xl tracking-widest text-blue-900">{code}</div>
            <div className="mt-1 text-xs text-blue-700">
              Expires in <span className="font-semibold">{left}s</span> {expired && "(expired)"}
            </div>
          </div>
          <button
            onClick={issueCode}
            className="rounded-lg border border-blue-300 px-3 py-2 text-sm text-blue-700 hover:bg-blue-100"
          >
            Regenerate
          </button>
        </div>
      )}

      {err && <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <ol className="mt-4 list-decimal space-y-1 pl-6 text-sm text-blue-800">
        <li>Open <span className="font-medium">Time Capture</span> on your Mac.</li>
        <li>Choose <span className="font-medium">Pair Device</span>, paste the code.</li>
        <li>Once paired, events will stream to your account automatically.</li>
      </ol>
    </div>
  );
}