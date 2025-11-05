import { useEffect, useState, useCallback } from "react";

const BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/,'') || "http://localhost:7123/api";

export function useAuth() {
  const [user, setUser] = useState<string>("");  // username
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${BASE}/whoami/`, { credentials: "include" });
      const j = r.ok ? await r.json() : { username: "" };
      setUser(j?.username || "");
    } finally {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const r = await fetch(`${BASE}/auth/login/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });
    if (!r.ok) throw new Error("Invalid login");
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await fetch(`${BASE}/auth/logout/`, { method: "POST", credentials: "include" });
    await refresh();
  }, [refresh]);

  useEffect(() => { refresh(); }, [refresh]);

  return { user, loading, login, logout, refresh };
}