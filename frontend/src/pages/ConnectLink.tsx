// src/pages/ConnectLink.tsx — the firm's QuickBooks admin approves the
// QuickBooks Online / QuickBooks Time connection from one emailed link.
// No login: the token in the URL is the credential (server: services/connect_link.py).
//
// Intuit sends the browser back to /connect/return (the server stores only a
// hash of the token, so it can't build /connect/<token>). The token is kept in
// sessionStorage for that one hop, and the return page bounces back here.
import { useCallback, useEffect, useState } from "react";
import { Navigate, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { connectRequest, type ConnectProvider, type ConnectStatus } from "./onboard/api";
import { primaryBtnClass } from "./settings/ui";

const TOKEN_KEY = "tt_connect_link";

const REASONS: Record<string, string> = {
  access_denied: "The connection was cancelled in QuickBooks.",
  invalid_state: "That attempt was already used or replaced. Please click Connect again.",
  token_exchange_failed: "QuickBooks didn't complete the connection. Please try again.",
  missing_code: "QuickBooks didn't complete the connection. Please try again.",
};

export default function ConnectLink() {
  const { token = "" } = useParams();
  const [params] = useSearchParams();
  const [status, setStatus] = useState<ConnectStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<ConnectProvider | null>(null);
  const returned = params.get("status");
  const returnedLabel = params.get("provider") === "qb_time" ? "QuickBooks Time" : "QuickBooks Online";
  const returnError = returned === "error" ? (REASONS[params.get("reason") || ""] || REASONS.token_exchange_failed) : null;

  const load = useCallback(() => {
    connectRequest(token).then((s) => { setStatus(s); setErr(null); }).catch((e) => setErr(e.message));
  }, [token]);

  useEffect(() => { load(); }, [load]);

  // QuickBooks Time's first import runs right after the grant; refresh until it settles.
  useEffect(() => {
    const qbt = status?.providers.find((p) => p.key === "qb_time");
    if (!qbt?.connected || !["pending", "running"].includes(qbt.sync_status || "")) return;
    const t = setTimeout(load, 4000);
    return () => clearTimeout(t);
  }, [status, load]);

  const connect = async (p: ConnectProvider) => {
    setBusy(p); setErr(null);
    try {
      const r = await connectRequest(token, p);
      try { sessionStorage.setItem(TOKEN_KEY, token); } catch { /* the return page falls back to a plain message */ }
      window.location.href = r.auth_url;
    } catch (e: any) { setErr(e.message); setBusy(null); }
  };

  if (!status) {
    return <Shell><div className="py-20 text-center text-sm text-slate-600">{err || "Loading…"}</div></Shell>;
  }

  const allDone = status.providers.every((p) => p.connected);

  return (
    <Shell firm={status.firm}>
      {returned === "connected" && (
        <Banner tone="green">{returnedLabel} is connected. Thank you!</Banner>
      )}
      {returnError && <Banner tone="amber">{returnError}</Banner>}

      <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5">
        {status.providers.map((p) => (
          <div key={p.key} className="flex flex-col gap-3 border-b border-slate-100 pb-4 last:border-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="font-semibold">{p.label}</div>
              {p.connected ? (
                <div className="mt-0.5 text-sm text-emerald-700">
                  Connected
                  {p.key === "quickbooks" && typeof p.clients === "number" && ` · ${p.clients} customers imported`}
                </div>
              ) : !p.configured ? (
                <div className="mt-0.5 text-sm text-amber-700">Not available yet — Mavops has been told.</div>
              ) : (
                <div className="mt-0.5 text-sm text-slate-600">
                  {p.key === "quickbooks"
                    ? "Lets TimeTracker read your customers so time can be filed against them."
                    : "One connection for the whole team: approved time goes to each person's QuickBooks Time timesheet."}
                </div>
              )}
              {p.key === "qb_time" && p.connected && ["pending", "running"].includes(p.sync_status || "") && (
                <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500"><Loader2 className="h-3 w-3 animate-spin" /> Matching your team…</div>
              )}
              {p.key === "qb_time" && p.connected && (p.unmatched?.length ?? 0) > 0 && (
                <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                  <div className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" /> No QuickBooks Time user with the same email:</div>
                  <ul className="mt-1 list-disc pl-5">
                    {p.unmatched!.map((u) => <li key={u.email}>{u.name} <span className="text-amber-700">({u.email})</span></li>)}
                  </ul>
                  <div className="mt-1 text-xs text-amber-800">Their time can't reach QuickBooks Time until the email in QuickBooks Time matches. Tell Mavops if they use a different address there.</div>
                </div>
              )}
            </div>
            {!p.connected && p.configured && status.open && (
              <button className={primaryBtnClass + " shrink-0"} disabled={!!busy} onClick={() => connect(p.key)}>
                {busy === p.key && <Loader2 className="h-4 w-4 animate-spin" />} Connect {p.label}
              </button>
            )}
          </div>
        ))}
      </section>

      {!status.open && !allDone && <Banner tone="amber">This link has expired. Ask Mavops for a new one.</Banner>}
      {allDone && <p className="text-sm text-slate-600">All done — you can close this page.</p>}
      {err && <Banner tone="amber">{err}</Banner>}

      <p className="text-xs text-slate-500">
        You'll sign in to QuickBooks on Intuit's own page; TimeTracker never sees your QuickBooks password.
        This link can't be used to sign in to TimeTracker.
      </p>
    </Shell>
  );
}

/** Intuit lands here; hop back to the link's own page. */
export function ConnectReturn() {
  const [params] = useSearchParams();
  let token: string | null = null;
  try { token = sessionStorage.getItem(TOKEN_KEY); } catch { token = null; }
  if (token) return <Navigate to={`/connect/${encodeURIComponent(token)}?${params.toString()}`} replace />;
  const ok = params.get("status") === "connected";
  return (
    <Shell>
      <Banner tone={ok ? "green" : "amber"}>
        {ok ? "Connected. Thank you — you can close this page."
          : (REASONS[params.get("reason") || ""] || REASONS.token_exchange_failed) + " Open the link from your email again to retry."}
      </Banner>
    </Shell>
  );
}

function Banner({ tone, children }: { tone: "green" | "amber"; children: React.ReactNode }) {
  const cls = tone === "green"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : "border-amber-200 bg-amber-50 text-amber-900";
  const Icon = tone === "green" ? CheckCircle2 : AlertTriangle;
  return (
    <div className={`flex items-start gap-3 rounded-2xl border p-4 text-sm ${cls}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" /><div>{children}</div>
    </div>
  );
}

function Shell({ firm, children }: { firm?: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 font-[Inter,system-ui,sans-serif] text-slate-900">
      <div className="mx-auto max-w-2xl space-y-5 px-4 py-8 sm:px-6">
        <header>
          <div className="text-xs font-semibold uppercase tracking-wider text-primary">TimeTracker · Mavops</div>
          <h1 className="mt-1 text-2xl font-semibold">{firm ? `Connect ${firm}'s QuickBooks` : "Connect QuickBooks"}</h1>
          {firm && <p className="mt-1 text-sm text-slate-600">About two minutes. Click Connect and sign in to QuickBooks as you normally would.</p>}
        </header>
        {children}
      </div>
    </div>
  );
}
