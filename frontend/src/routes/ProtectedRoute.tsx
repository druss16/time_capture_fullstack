// src/routes/ProtectedRoute.tsx
import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

const ProtectedRoute: React.FC<React.PropsWithChildren> = ({ children }) => {
  const loc = useLocation();
  const { isAuthenticated, loading } = useAuth();

  if (AUTH_DISABLED) return <>{children}</>;
  if (loading) return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  if (!isAuthenticated) {
    const next = encodeURIComponent(loc.pathname + loc.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
};

export default ProtectedRoute;