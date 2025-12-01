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
import AdminRoute from "@/routes/AdminRoute";  // ✅ Add AdminRoute import

// Client management components
import { ClientList } from '@/components/clients/ClientList';
import { ClientImport } from '@/components/clients/ClientImport';
import { ManualClientEntry } from '@/components/clients/ManualClientEntry';
import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard';

// --------- Lazy pages (code-splitting) ---------
const DailyReview = lazy(() => import("./DailyReview"));
const TimecardReview = lazy(() => import("./TimecardReview"));
const TimecardSummary = lazy(() => import("./TimecardSummary"));
const OrgAdminSettings = lazy(() => import("./Settings"));  // ← The new one I created
const OrganizationSettings = lazy(() => import("./OrganizationSettings")); // ← Your existing AI settings
const Devices = lazy(() => import("./Devices"));
const Login = lazy(() => import("./Login"));
const Signup = lazy(() => import("./Signup"));
const NotFound = lazy(() => import("./NotFound"));

// ✅ NEW: TimeReview for hybrid categorization
const TimeReview = lazy(() => import("./TimeReview"));

import { safeFetchJson, API_BASE } from "@/lib/api";

// --------- ENV / helpers ---------
const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

const queryClient = new QueryClient();

// Sign-out helper route (clears server session, then bounce to /login)
function Logout() {
  const { logout } = useAuth();

  useEffect(() => {
    (async () => {
      await logout();
      window.location.href = '/login';
    })();
  }, [logout]);

  return <div className="p-6">Logging out...</div>;
}

// Scroll to top on route change (nice UX)
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname]);
  return null;
}

interface OnboardingCheckProps {
  children: React.ReactNode;
}

// Wrap ProtectedRoute, but bypass if AUTH is disabled (useful in dev)
function MaybeProtected({ children }: { children: React.ReactNode }) {
  if (AUTH_DISABLED) return <>{children}</>;
  return <ProtectedRoute>{children}</ProtectedRoute>;
}

// App shell with Navigation
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
                {/* Redirect root → /daily */}
                <Route path="/" element={<Navigate to="/daily" replace />} />

                {/* Public auth routes */}
                {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
                {!AUTH_DISABLED && <Route path="/signup" element={<Signup />} />}
                {!AUTH_DISABLED && <Route path="/logout" element={<Logout />} />}

                {/* Protected pages (wrapped in AppLayout) */}
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
                <Route
                  path="/timecards"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <TimecardReview />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />
                <Route
                  path="/summary"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <TimecardSummary />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />
                
                {/* ✅ Admin Settings - Team, Clients, Devices, Billing (ADMIN ONLY) */}
                <Route
                  path="/settings"
                  element={
                    <MaybeProtected>
                      <AdminRoute>
                        <AppLayout>
                          <OrgAdminSettings />
                        </AppLayout>
                      </AdminRoute>
                    </MaybeProtected>
                  }
                />

                {/* ✅ AI Classification Settings (ADMIN ONLY) */}
                <Route
                  path="/settings/ai"
                  element={
                    <MaybeProtected>
                      <AdminRoute>
                        <AppLayout>
                          <OrganizationSettings />
                        </AppLayout>
                      </AdminRoute>
                    </MaybeProtected>
                  }
                />
                
                <Route
                  path="/devices"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <Devices />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />

                {/* ✅ NEW: Time Review (Hybrid Categorization) */}
                <Route
                  path="/time-review"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <TimeReview />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />

                {/* Client Management Routes */}
                <Route
                  path="/clients"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <ClientList />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />
                <Route
                  path="/clients/import"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <ClientImport />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />
                <Route
                  path="/clients/add"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <ManualClientEntry />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />

                {/* 404 */}
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}