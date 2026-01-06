import { Suspense, lazy, useEffect, useState } from "react";
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
import AdminRoute from "@/routes/AdminRoute";

// Client management components
import { ClientList } from '@/components/clients/ClientList';
import { ClientImport } from '@/components/clients/ClientImport';
import { ManualClientEntry } from '@/components/clients/ManualClientEntry';
import OnboardingWizard from '@/components/onboarding/OnboardingWizard';

// ✅ NEW: Account settings pages
import AccountLayout from '@/pages/account/AccountLayout';
import ProfilePage from '@/pages/account/ProfilePage';
import PasswordPage from '@/pages/account/PasswordPage';
import BillingSettingsPage from '@/pages/account/BillingSettingsPage';

// --------- Lazy pages (code-splitting) ---------
const DailyReview = lazy(() => import("./DailyReview"));
const TimecardSummary = lazy(() => import("./TimecardSummary"));
const OrgAdminSettings = lazy(() => import("./Settings"));
const OrganizationSettings = lazy(() => import("./OrganizationSettings"));
const Devices = lazy(() => import("./Devices"));
const Login = lazy(() => import("./Login"));
const Signup = lazy(() => import("./Signup"));
const NotFound = lazy(() => import("./NotFound"));
const TimeReview = lazy(() => import("./TimeReview"));

// Billing page with timesheets, approvals, and client billing
const BillingPage = lazy(() => import("./BillingPage"));

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

// ✅ NEW: Owner-only route guard (fetches role from whoami)
function OwnerRoute({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then(data => setRole(data.role))
      .catch(() => setRole(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6">Loading...</div>;
  if (role !== 'owner') return <Navigate to="/account" replace />;
  
  return <>{children}</>;
}

// ✅ NEW: Account layout wrapper that fetches role
function AccountLayoutWrapper() {
  const [role, setRole] = useState<'owner' | 'admin' | 'manager' | 'member'>('member');

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then(data => setRole(data.role || 'member'))
      .catch(() => setRole('member'));
  }, []);
  
  return <AccountLayout role={role} />;
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
                {!AUTH_DISABLED && <Route path="/signup" element={<OnboardingWizard initialStep={1} />} />}
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
                  path="/summary"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <TimecardSummary />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />

                {/* Billing - Timesheets, Approvals, Client Billing */}
                <Route
                  path="/billing"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <BillingPage />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />
                
                {/* Admin Settings - Team, Clients, Devices, Billing (ADMIN ONLY) */}
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

                {/* AI Classification Settings (ADMIN ONLY) */}
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

                {/* Time Review (Hybrid Categorization) */}
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

                {/* ============================================ */}
                {/* ✅ NEW: Account Settings Routes              */}
                {/* ============================================ */}
                <Route
                  path="/account"
                  element={
                    <MaybeProtected>
                      <AccountLayoutWrapper />
                    </MaybeProtected>
                  }
                >
                  {/* /account - Profile page */}
                  <Route index element={<ProfilePage />} />
                  
                  {/* /account/password - Change password */}
                  <Route path="password" element={<PasswordPage />} />
                  
                  {/* /account/billing - Stripe subscription (OWNER ONLY) */}
                  <Route 
                    path="billing" 
                    element={
                      <OwnerRoute>
                        <BillingSettingsPage />
                      </OwnerRoute>
                    } 
                  />
                </Route>

                {/* Self-Service Onboarding (public - no auth required) */}
                <Route path="/onboarding" element={<OnboardingWizard />} />
                <Route path="/onboarding/signup" element={<OnboardingWizard initialStep={1} />} />

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