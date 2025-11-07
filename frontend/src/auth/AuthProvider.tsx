// src/auth/AuthProvider.tsx
import React, { createContext, useContext, useMemo, useState, useCallback, useEffect } from "react";
import { fetchWhoAmI, clearWhoAmICache, isTrulyAuthenticated, type WhoAmI } from "@/lib/whoami";
import { primeCsrf, getCookie } from "@/lib/csrf";  // <-- add this

function resolveApiBase() {
  const raw = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123";
  const noTrail = raw.replace(/\/+$/, "");
  return noTrail.endsWith("/api") ? noTrail : `${noTrail}/api`;
}
const API_BASE = resolveApiBase();

type AuthCtx = {
  me: WhoAmI | null;
  loading: boolean;
  isAuthenticated: boolean;
  refreshWhoAmI: () => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthCtx>(null as any);
export function useAuth() { return useContext(Ctx); }

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<WhoAmI | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshWhoAmI = useCallback(async () => {
    setLoading(true);
    try { setMe(await fetchWhoAmI(true)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void refreshWhoAmI(); }, [refreshWhoAmI]);

  const isAuthenticated = useMemo(() => isTrulyAuthenticated(me), [me]);

  const logout = useCallback(async () => {
    try {
      // Ensure csrftoken cookie exists
      await primeCsrf(API_BASE);
      const token = getCookie("csrftoken") || "";

      await fetch(`${API_BASE}/auth/logout/`, {
        method: "POST",
        credentials: "include",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": token,
          "Content-Type": "application/json",
        },
      });
    } catch {
      // ignore network hiccups
    }
    clearWhoAmICache();
    setMe({ is_authenticated: false, auth_source: "unknown", username: "" });
  }, []);

  return (
    <Ctx.Provider value={{ me, loading, isAuthenticated, refreshWhoAmI, logout }}>
      {children}
    </Ctx.Provider>
  );
}