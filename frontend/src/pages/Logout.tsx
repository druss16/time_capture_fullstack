// src/pages/Logout.tsx
import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { API_ENDPOINTS, safeFetchJson, primeCsrf } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider"; // if you have this

export default function Logout() {
  const nav = useNavigate();
  const loc = useLocation();
  const { setAuthenticated } = useAuth?.() ?? { setAuthenticated: undefined };

  // helper: clear the non-HttpOnly browser identity cookies you set in /browser/hello/
  function clearBrowserIdentityCookies() {
    const opts = "path=/; samesite=Lax";
    document.cookie = `mavops_username=; expires=Thu, 01 Jan 1970 00:00:00 GMT; ${opts}`;
    document.cookie = `mavops_host=; expires=Thu, 01 Jan 1970 00:00:00 GMT; ${opts}`;
  }

  useEffect(() => {
    (async () => {
      try {
        // 1) make sure csrftoken exists so POST /auth/logout/ succeeds
        await primeCsrf();
        // 2) tell the server to end the session
        await safeFetchJson(API_ENDPOINTS.authLogout, { method: "POST" });
      } catch {
        // ignore — even if already logged out
      } finally {
        // 3) local cleanup
        clearBrowserIdentityCookies();
        if (typeof setAuthenticated === "function") setAuthenticated(false);

        // 4) send them to login with a next= hint
        const next = (loc.state as any)?.next || (loc.pathname + loc.search) || "/";
        nav(`/login?next=${encodeURIComponent(next)}`, { replace: true });
      }
    })();
  }, [nav, loc, setAuthenticated]);

  return <div className="p-6 text-center text-muted-foreground">Logging out…</div>;
}