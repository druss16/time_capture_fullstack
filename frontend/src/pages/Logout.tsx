// src/pages/Logout.tsx
import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";

export default function Logout() {
  const nav = useNavigate();
  const loc = useLocation();

  useEffect(() => {
    (async () => {
      try {
        await safeFetchJson(API_ENDPOINTS.authLogout, { method: "POST" });
      } catch {
        // ignore errors — even if already logged out
      } finally {
        nav("/login", { replace: true, state: { next: loc.pathname + loc.search } });
      }
    })();
  }, [nav, loc]);

  return <div className="p-6 text-center text-muted-foreground">Logging out…</div>;
}