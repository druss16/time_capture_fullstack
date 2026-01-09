// src/auth/AuthProvider.tsx
import React, { createContext, useContext, useMemo, useState, useCallback, useEffect } from "react";
import { fetchWhoAmI, clearWhoAmICache, isTrulyAuthenticated, type WhoAmI } from "@/lib/whoami";

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
  refreshWhoAmI: () => Promise<WhoAmI | null>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthCtx>(null as any);

export function useAuth() {
  return useContext(Ctx);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<WhoAmI | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshWhoAmI = useCallback(async (): Promise<WhoAmI | null> => {
    setLoading(true);
    try {
      const data = await fetchWhoAmI(true);
      setMe(data);
      return data;
    } catch (error) {
      setMe(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshWhoAmI();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const isAuthenticated = useMemo(() => isTrulyAuthenticated(me), [me]);

  const logout = useCallback(async () => {
    // Clear local state first
    localStorage.removeItem('auth_token');
    sessionStorage.clear();
    clearWhoAmICache();
    setMe(null);

    // Clear all cookies
    document.cookie.split(";").forEach((c) => {
      const name = c.trim().split("=")[0];
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=.onrender.com;`;
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=timetracker-api-k375.onrender.com;`;
    });

    // Try backend logout (fire and forget)
    try {
      const csrftoken = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1] || '';
      
      await fetch(`${API_BASE}/auth/logout/`, {
        method: "POST",
        credentials: "include",
        headers: {
          "X-CSRFToken": csrftoken,
          "Content-Type": "application/json",
        },
      });
    } catch {
      // Ignore - local logout is sufficient
    }
  }, []);

  return (
    <Ctx.Provider value={{ me, loading, isAuthenticated, refreshWhoAmI, logout }}>
      {children}
    </Ctx.Provider>
  );
}