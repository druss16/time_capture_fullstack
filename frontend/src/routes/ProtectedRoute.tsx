// src/routes/ProtectedRoute.tsx
import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

// Ensure API_BASE always ends with /api
const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

type Gate = "loading" | "authed" | "anon";

const ProtectedRoute: React.FC<React.PropsWithChildren> = ({ children }) => {
  const loc = useLocation();
  const { isAuthenticated } = useAuth();
  const [gate, setGate] = useState<Gate>(AUTH_DISABLED ? "authed" : "loading");

  useEffect(() => {
    if (AUTH_DISABLED) return; // skip auth checks in no-auth mode

    async function probeWhoami() {
      try {
        // always hit /api/whoami/ using our verified API_BASE
        const r = await fetch(`${API_BASE}/whoami/`, { credentials: "include" });
        const j = r.ok ? await r.json() : { username: "" };
        setGate(j?.username ? "authed" : "anon");
      } catch {
        setGate("anon");
      }
    }

    // Use existing auth context state first
    if (isAuthenticated === true) return setGate("authed");
    if (isAuthenticated === false) return void probeWhoami();

    // Undefined state (initial load)
    probeWhoami();
  }, [isAuthenticated]);

  if (gate === "loading") {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }

  if (gate === "anon") {
    const next = encodeURIComponent(loc.pathname + loc.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return <>{children}</>;
};

export default ProtectedRoute;