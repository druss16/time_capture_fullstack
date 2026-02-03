// src/components/PairDeviceCard.tsx
import { useEffect, useState } from "react";
import { safeFetchJson } from '@/lib/api';
import { Smartphone, RefreshCw, Copy, Check } from 'lucide-react';

const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

type PairResp = { ok: boolean; code: string; expires_at: string; ttl_seconds: number };

export default function PairDeviceCard() {
  const [code, setCode] = useState("");
  const [expiresAt, setExpiresAt] = useState<Date | null>(null);
  const [left, setLeft] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);

  async function issueCode() {
    setErr("");
    setLoading(true);
    try {
      const data = await safeFetchJson<PairResp>(`${API_BASE}/agents/pair/issue/`, {
        method: "POST",
        body: JSON.stringify({ ttl_seconds: 600 }),
      });
      
      if (!data?.code) {
        throw new Error("Failed to issue code");
      }
      setCode(data.code);
      setExpiresAt(new Date(data.expires_at));
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

  const handleCopy = () => {
    if (code) {
      navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const expired = !!expiresAt && Date.now() > expiresAt.getTime();

  return (
    <div className="rounded-2xl border-2 border-teal-200 bg-white p-6 shadow-sm">
      <div className="flex items-center gap-3 mb-2">
        <div className="w-10 h-10 rounded-xl bg-teal-100 flex items-center justify-center">
          <Smartphone className="w-5 h-5 text-teal-600" />
        </div>
        <div>
          <h3 className="text-lg font-bold text-slate-900">Pair a Device</h3>
          <p className="text-sm text-slate-600 font-medium">
            Generate a code and enter it in the TimeTracker desktop app
          </p>
        </div>
      </div>

      {!code ? (
        <button
          onClick={issueCode}
          disabled={loading}
          className="mt-4 w-full rounded-xl bg-teal-500 px-4 py-3 text-white font-bold hover:bg-teal-600 disabled:opacity-50 transition-all shadow-lg shadow-teal-500/25 flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Smartphone className="w-4 h-4" />
              Generate Pairing Code
            </>
          )}
        </button>
      ) : (
        <div className="mt-4 rounded-xl border-2 border-teal-200 bg-teal-50 p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">
              <div className="text-sm text-teal-700 font-medium">Your pairing code</div>
              <div className="mt-1 font-mono text-3xl tracking-widest text-slate-900 font-bold">{code}</div>
              <div className="mt-2 text-sm text-teal-600 font-medium">
                {expired ? (
                  <span className="text-amber-600 font-semibold">Code expired</span>
                ) : (
                  <>Expires in <span className="font-bold text-teal-700">{left}s</span></>
                )}
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <button
                onClick={handleCopy}
                className="p-2.5 rounded-lg border-2 border-teal-200 hover:bg-teal-100 transition-all"
                title="Copy to clipboard"
              >
                {copied ? (
                  <Check className="w-5 h-5 text-teal-600" />
                ) : (
                  <Copy className="w-5 h-5 text-teal-600" />
                )}
              </button>
              <button
                onClick={issueCode}
                disabled={loading}
                className="p-2.5 rounded-lg border-2 border-teal-200 hover:bg-teal-100 transition-all disabled:opacity-50"
                title="Generate new code"
              >
                <RefreshCw className={`w-5 h-5 text-teal-600 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>
        </div>
      )}

      {err && (
        <div className="mt-3 rounded-xl bg-red-50 border-2 border-red-200 px-4 py-3 text-sm text-red-700 font-medium">
          {err}
        </div>
      )}

      <ol className="mt-4 list-decimal space-y-1.5 pl-6 text-sm text-slate-700 font-medium">
        <li>Open <span className="font-bold text-slate-900">TimeTracker</span> on your Mac or Windows PC</li>
        <li>Choose <span className="font-bold text-slate-900">Pair Device</span> and enter the code</li>
        <li>Once paired, time tracking starts automatically</li>
      </ol>
    </div>
  );
}