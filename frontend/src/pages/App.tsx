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

// --------- Lazy pages (code-splitting) ---------
const DailyReview = lazy(() => import("./DailyReview"));
const TimecardReview = lazy(() => import("./TimecardReview"));
const TimecardSummary = lazy(() => import("./TimecardSummary"));
const OrganizationSettings = lazy(() => import("./OrganizationSettings"));
const Devices = lazy(() => import("./Devices"));
const Login = lazy(() => import("./Login"));
const Signup = lazy(() => import("./Signup"));
const NotFound = lazy(() => import("./NotFound"));

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