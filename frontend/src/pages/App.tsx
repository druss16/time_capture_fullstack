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
import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard';

// --------- Lazy pages (code-splitting) ---------
const DailyReview = lazy(() => import("./DailyReview"));
const TimecardReview = lazy(() => import("./TimecardReview"));
const TimecardSummary = lazy(() => import("./TimecardSummary"));
const OrganizationSettings = lazy(() => import("./OrganizationSettings"));
const Devices = lazy(() => import("./Devices"));
const Login = lazy(() => import("./Login"));
const Signup = lazy(() => import("./Signup"));
const NotFound = lazy(() => import("./NotFound"));

import { safeFetchJson, API_BASE } from '@/api/api';


// --------- ENV / helpers ---------
const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

const queryClient = new QueryClient();

// Sign-out helper route (clears server session, then bounce to /login)
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

// Scroll to top on route change (nice UX)
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname]);
  return null;
}

// 👇 NEW: Check if user needs onboarding
// Find the OnboardingCheck component (around line 42-66)
// Replace the checkOnboarding function:


function OnboardingCheck({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    // Skip check on login, signup, and onboarding pages
    const skipPaths = ['/login', '/signup', '/onboarding'];
    if (skipPaths.includes(location.pathname)) {
      return;
    }

    // Check onboarding status
    const checkOnboarding = async () => {
      try {
        // ✅ FIXED: Use safeFetchJson with API_BASE
        const data = await safeFetchJson(`${API_BASE}/profile/`);
        
        // Redirect to onboarding if not completed
        if (!data.onboarding_completed) {
          navigate('/onboarding');
        }
      } catch (error) {
        console.error('Error checking onboarding:', error);
      }
    };

    checkOnboarding();
  }, [navigate, location.pathname]);

  return <>{children}</>;
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
            {/* 👇 NEW: Add onboarding check globally */}
            <OnboardingCheck>
              {/* Globally-mounted pairing modal so any page can open it */}
              <PairDeviceModal />

              <Suspense fallback={<div className="p-6 text-blue-800">Loading…</div>}>
                <Routes>
                  {/* Redirect root → /daily */}
                  <Route path="/" element={<Navigate to="/daily" replace />} />

                  {/* Public auth routes */}
                  {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
                  {!AUTH_DISABLED && <Route path="/signup" element={<Signup />} />}
                  {!AUTH_DISABLED && <Route path="/logout" element={<Logout />} />}

                  {/* 👇 NEW: Onboarding route (no AppLayout - full screen) */}
                  <Route
                    path="/onboarding"
                    element={
                      <MaybeProtected>
                        <OnboardingWizard />
                      </MaybeProtected>
                    }
                  />

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
                  <Route
                    path="/settings"
                    element={
                      <MaybeProtected>
                        <AppLayout>
                          <OrganizationSettings />
                        </AppLayout>
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

                  {/* 👇 UPDATED: Client Management Routes - now properly wrapped */}
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
            </OnboardingCheck>
          </BrowserRouter>
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}