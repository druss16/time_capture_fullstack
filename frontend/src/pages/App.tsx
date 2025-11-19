import { Suspense, lazy, useEffect } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import PairDeviceModal from "@/components/agent/PairDeviceModal";
import Navigation from "@/components/Navigation";
import ProtectedRoute from "@/routes/ProtectedRoute";

// Client management components
import { ClientList } from '@/components/clients/ClientList';
import { ClientImport } from '@/components/clients/ClientImport';
import { ManualClientEntry } from '@/components/clients/ManualClientEntry';
// ❌ DELETE: import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard';

// Lazy pages
const DailyReview = lazy(() => import("./DailyReview"));
const TimecardReview = lazy(() => import("./TimecardReview"));
const TimecardSummary = lazy(() => import("./TimecardSummary"));
const OrganizationSettings = lazy(() => import("./OrganizationSettings"));
const Devices = lazy(() => import("./Devices"));
const Login = lazy(() => import("./Login"));
const Signup = lazy(() => import("./Signup"));
const NotFound = lazy(() => import("./NotFound"));

import { safeFetchJson, API_BASE } from "@/lib/api";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";
const queryClient = new QueryClient();

function Logout() {
  const nav = useNavigate();
  const { logout } = useAuth();
  useEffect(() => {
    (async () => {
      try {
        await logout();
      } finally {
        const next = encodeURIComponent("/");
        nav(`/login?next=${next}`, { replace: true });
      }
    })();
  }, [logout, nav]);
  return null;
}

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname]);
  return null;
}

// ❌ DELETE: OnboardingCheck function (entire thing)

function MaybeProtected({ children }: { children: React.ReactNode }) {
  if (AUTH_DISABLED) return <>{children}</>;
  return <ProtectedRoute>{children}</ProtectedRoute>;
}

function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-white">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <AuthProvider>
          <BrowserRouter>
            <ScrollToTop />
            <PairDeviceModal />
            <Suspense fallback={<div className="p-6 text-blue-800">Loading…</div>}>
              <Routes>
                <Route path="/" element={<Navigate to="/daily" replace />} />
                
                {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
                {!AUTH_DISABLED && <Route path="/signup" element={<Signup />} />}
                {!AUTH_DISABLED && <Route path="/logout" element={<Logout />} />}

                {/* ❌ DELETE: onboarding route */}

                <Route
                  path="/daily"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <DailyReview />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />
                
                {/* ... rest of routes ... */}
                
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}