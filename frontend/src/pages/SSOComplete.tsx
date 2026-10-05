// Landing page after "Sign in with Microsoft / Google".
// The API callback redirects here with a one-time code in the URL fragment
// (never the token itself); we trade it for the same payload password login
// returns, then continue exactly as Login.tsx does.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";

function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/daily";
}

export default function SSOComplete() {
  const nav = useNavigate();
  const { refreshWhoAmI } = useAuth();
  const [err, setErr] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    // The code is single-use: StrictMode's double effect must not spend it twice.
    if (ran.current) return;
    ran.current = true;

    const params = new URLSearchParams(window.location.hash.slice(1));
    const code = params.get("code");
    const next = safeNext(params.get("next"));
    // Drop the code from the address bar and history straight away.
    window.history.replaceState(null, "", window.location.pathname);

    if (!code) {
      setErr("This sign-in link is incomplete. Please try again.");
      return;
    }

    (async () => {
      try {
        const res = await safeFetchJson<{ ok: boolean; error?: string; token?: string }>(
          API_ENDPOINTS.ssoExchange,
          { method: "POST", credentials: "include", body: JSON.stringify({ code }) }
        );
        if (!res?.ok || !res.token) throw new Error(res?.error || "Sign-in failed");
        localStorage.setItem("auth_token", res.token);
        const who = await refreshWhoAmI();
        if (!who?.is_authenticated) throw new Error("Authentication verification failed");
        nav(next, { replace: true });
      } catch (e: any) {
        localStorage.removeItem("auth_token");
        setErr(e?.message || "Sign-in failed");
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-8">
      <div className="w-full max-w-sm space-y-5 text-center">
        <img src="/timetracker-icon-circle.svg" alt="TimeTracker" className="w-10 h-10 mx-auto" />
        {err ? (
          <>
            <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm">
              {err}
            </div>
            <Link to="/login" className="text-sm font-semibold text-primary hover:underline">
              Back to sign in
            </Link>
          </>
        ) : (
          <div className="flex items-center justify-center gap-3 text-sm text-muted-foreground">
            <div className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
            Signing you in…
          </div>
        )}
      </div>
    </div>
  );
}
