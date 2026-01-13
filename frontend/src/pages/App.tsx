import { Suspense, lazy, useEffect, useState, useRef } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/auth/AuthProvider";
import PairDeviceModal from "@/components/agent/PairDeviceModal";
import Navigation from "@/components/Navigation";
import ProtectedRoute from "@/routes/ProtectedRoute";


// Onboarding
import OnboardingWizard from '@/components/onboarding/OnboardingWizard';

// Account settings pages
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
const NotFound = lazy(() => import("./NotFound"));
const TimeReview = lazy(() => import("./TimeReview"));
const BillingPage = lazy(() => import("./BillingPage"));

import { safeFetchJson, API_BASE } from "@/lib/api";

// --------- ENV / helpers ---------
const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

const queryClient = new QueryClient();

const Clients = lazy(() => import("./pages/Clients"));


// ============================================================================
// Route Guards
// ============================================================================

/**
 * AdminRoute - Allows owner, admin, AND manager roles
 * Managers need access to /settings for the Client Access tab
 */
function AdminRoute({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((data: any) => setRole(data.role))
      .catch(() => setRole(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-slate-500 font-medium">Loading...</div>
      </div>
    );
  }

  // Allow owner, admin, AND manager
  if (!role || !['owner', 'admin', 'manager'].includes(role)) {
    return <Navigate to="/daily" replace />;
  }

  return <>{children}</>;
}

/**
 * OwnerRoute - Only allows owner role (for billing management)
 */
function OwnerRoute({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((data: any) => setRole(data.role))
      .catch(() => setRole(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="p-6 text-slate-500">Loading...</div>;
  }

  if (role !== 'owner') {
    return <Navigate to="/account" replace />;
  }

  return <>{children}</>;
}

// ============================================================================
// Helper Components
// ============================================================================

/**
 * Logout - Clears all auth state and redirects to login
 */
function Logout() {
  const hasLoggedOut = useRef(false);

  useEffect(() => {
    if (hasLoggedOut.current) return;
    hasLoggedOut.current = true;

    // 1. Clear ALL local state immediately
    localStorage.clear();
    sessionStorage.clear();

    // 2. Clear all cookies
    document.cookie.split(";").forEach((c) => {
      const name = c.trim().split("=")[0];
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
    });

    // 3. Try server logout (fire and forget - ignore errors)
    fetch(`${API_BASE}/auth/logout/`, {
      method: "POST",
      credentials: "include",
    }).catch(() => {});

    // 4. Redirect to login
    setTimeout(() => {
      window.location.replace("/login");
    }, 50);
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-slate-500 font-medium">Logging out...</div>
    </div>
  );
}

/**
 * ScrollToTop - Scrolls to top on route change
 */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname]);
  return null;
}

/**
 * MaybeProtected - Wraps ProtectedRoute, bypasses if AUTH is disabled (dev mode)
 */
function MaybeProtected({ children }: { children: React.ReactNode }) {
  if (AUTH_DISABLED) return <>{children}</>;
  return <ProtectedRoute>{children}</ProtectedRoute>;
}

/**
 * AppLayout - Main app shell with navigation
 */
function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-white">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}

/**
 * AccountLayoutWrapper - Fetches user role for account settings
 */
function AccountLayoutWrapper() {
  const [role, setRole] = useState<'owner' | 'admin' | 'manager' | 'member'>('member');

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((data: any) => setRole(data.role || 'member'))
      .catch(() => setRole('member'));
  }, []);

  return <AccountLayout role={role} />;
}

// ============================================================================
// Main App Component
// ============================================================================

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

            <Suspense
              fallback={
                <div className="min-h-screen flex items-center justify-center">
                  <div className="text-primary font-medium">Loading…</div>
                </div>
              }
            >
              <Routes>
                {/* ============================================ */}
                {/* Root Redirect                               */}
                {/* ============================================ */}
                <Route path="/" element={<Navigate to="/daily" replace />} />

                {/* ============================================ */}
                {/* Public Auth Routes                          */}
                {/* ============================================ */}
                {!AUTH_DISABLED && (
                  <>
                    <Route path="/login" element={<Login />} />
                    <Route path="/signup" element={<OnboardingWizard initialStep={1} />} />
                    <Route path="/logout" element={<Logout />} />
                  </>
                )}

                {/* ============================================ */}
                {/* Protected Routes (All Users)                */}
                {/* ============================================ */}
                
                {/* Daily Time Review */}
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

                {/* Weekly Summary */}
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

                {/* Time Review (Hybrid AI Categorization) */}
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

                {/* Devices (User's own devices) */}
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

                {/* ============================================ */}
                {/* Admin/Manager Routes                        */}
                {/* ============================================ */}

                {/* Organization Settings (Owner/Admin/Manager) */}
                {/* Includes: Organization, Team, Clients, Client Access, Billing Rates, Employee Costs, Devices, Token */}
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

                {/* AI Classification Settings (Owner/Admin/Manager) */}
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

                // Add this route (for all authenticated users):
                <Route
                  path="/clients"
                  element={
                    <MaybeProtected>
                      <AppLayout>
                        <Clients />
                      </AppLayout>
                    </MaybeProtected>
                  }
                />

                {/* ============================================ */}
                {/* Account Settings (All Users)                */}
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

                {/* ============================================ */}
                {/* Public Routes (No Auth)                     */}
                {/* ============================================ */}
                
                {/* Self-Service Onboarding */}
                <Route path="/onboarding" element={<OnboardingWizard />} />
                <Route path="/onboarding/signup" element={<OnboardingWizard initialStep={1} />} />

                {/* ============================================ */}
                {/* 404 Fallback                                */}
                {/* ============================================ */}
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}