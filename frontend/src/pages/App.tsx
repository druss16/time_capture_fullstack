import { Suspense, lazy, useEffect } from "react";
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "../auth/AuthProvider";
import ProtectedRoute from "../routes/ProtectedRoute";
import PairDeviceModal from "@/components/agent/PairDeviceModal";

// Lazy pages (code-splitting)
const DailyReview = lazy(() => import("./DailyReview"));
const TimecardReview = lazy(() => import("./TimecardReview"));
const TimecardSummary = lazy(() => import("./TimecardSummary"));
const OrganizationSettings = lazy(() => import("./OrganizationSettings"));
const Login = lazy(() => import("./Login"));
const Signup = lazy(() => import("./Signup"));
const NotFound = lazy(() => import("./NotFound"));

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api").replace(/\/+$/, "");
const queryClient = new QueryClient();

// Small helper to sign out via API then bounce to /login
function Logout() {
  const nav = useNavigate();
  const loc = useLocation();

  useEffect(() => {
    (async () => {
      try {
        await fetch(`${API_BASE}/auth/logout/`, { method: "POST", credentials: "include" });
      } catch {
        // ignore
      } finally {
        const next = encodeURIComponent((loc.state as any)?.next || "/");
        nav(`/login?next=${next}`, { replace: true });
      }
    })();
  }, [nav, loc]);

  return null;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <AuthProvider>
          <BrowserRouter>
            {/* Rendered once so any page can open the pairing UI */}
            <PairDeviceModal />

            <Suspense fallback={<div className="p-6">Loading…</div>}>
              <Routes>
                <Route
                  path="/"
                  element={
                    <ProtectedRoute>
                      <DailyReview />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/timecards"
                  element={
                    <ProtectedRoute>
                      <TimecardReview />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/summary"
                  element={
                    <ProtectedRoute>
                      <TimecardSummary />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/settings"
                  element={
                    <ProtectedRoute>
                      <OrganizationSettings />
                    </ProtectedRoute>
                  }
                />

                {/* Public auth routes */}
                {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
                {!AUTH_DISABLED && <Route path="/signup" element={<Signup />} />}
                {!AUTH_DISABLED && <Route path="/logout" element={<Logout />} />}

                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}