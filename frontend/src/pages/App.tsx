import { Suspense, useEffect, useState, useRef } from "react";
import { lazyWithRetry } from "@/lib/lazyWithRetry";
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

import SupportWidget from "@/pages/SupportWidget";


// Account settings pages
import AccountLayout from '@/pages/account/AccountLayout';
import ProfilePage from '@/pages/account/ProfilePage';
import PasswordPage from '@/pages/account/PasswordPage';
import BillingSettingsPage from '@/pages/account/BillingSettingsPage';
import DownloadPage from '@/pages/account/DownloadPage';
import TimesheetReminderBanner from '@/components/TimesheetReminderBanner';
import NotificationsPage from '@/pages/account/NotificationsPage';
import ConnectionsPage from '@/pages/account/ConnectionsPage';
import ExecutiveGate from '@/routes/ExecutiveGate';

// --------- Lazy pages (code-splitting) ---------
// lazyWithRetry auto-reloads once on a stale-chunk 404 after a deploy so an
// already-open tab recovers instead of showing a blank screen.
const DailyReview = lazyWithRetry(() => import("./DailyReview"));
const TimecardSummary = lazyWithRetry(() => import("./TimecardSummary"));
const OrgAdminSettings = lazyWithRetry(() => import("./Settings"));
const OrganizationSettings = lazyWithRetry(() => import("./OrganizationSettings"));
const Devices = lazyWithRetry(() => import("./Devices"));
const Login = lazyWithRetry(() => import("./Login"));
const NotFound = lazyWithRetry(() => import("./NotFound"));
const BillingPage = lazyWithRetry(() => import("./BillingPage"));
const WhiteGloveOnboarding = lazyWithRetry(() => import("./settings/WhiteGloveOnboarding"));
const Home = lazyWithRetry(() => import("./Home"));
const RequestAccess = lazyWithRetry(() => import("./RequestAccess"));
const MavOpsAdmin = lazyWithRetry(() => import("./MavOpsAdmin"));
const DashboardV2 = lazyWithRetry(() => import("./DashboardV2"));
const ReportsSummary = lazyWithRetry(() => import("./ReportsSummary"));
const AIBlindSpots = lazyWithRetry(() => import("./AIBlindSpots"));
const AcceptInvite = lazyWithRetry(() => import("./AcceptInvite"));
const Welcome = lazyWithRetry(() => import("./Welcome"));
const ForgotPassword = lazyWithRetry(() => import("./ForgotPassword"));
const ResetPassword = lazyWithRetry(() => import("./ResetPassword"));

import { safeFetchJson, API_BASE } from "@/lib/api";
import { getViewAs, stopViewAs } from "@/lib/viewAs";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";
const queryClient = new QueryClient();

function AdminRoute({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((data: any) => setRole(data.role))
      .catch(() => setRole(null))
      .finally(() => setLoading(false));
  }, []);
  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="text-slate-500 font-medium">Loading...</div></div>;
  if (!role || !['owner', 'admin', 'manager'].includes(role)) return <Navigate to="/daily" replace />;
  return <>{children}</>;
}

function OwnerRoute({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((data: any) => setRole(data.role))
      .catch(() => setRole(null))
      .finally(() => setLoading(false));
  }, []);
  if (loading) return <div className="p-6 text-slate-500">Loading...</div>;
  if (role !== 'owner') return <Navigate to="/account" replace />;
  return <>{children}</>;
}

function Logout() {
  const hasLoggedOut = useRef(false);
  useEffect(() => {
    if (hasLoggedOut.current) return;
    hasLoggedOut.current = true;
    localStorage.clear();
    sessionStorage.clear();
    document.cookie.split(";").forEach((c) => {
      const name = c.trim().split("=")[0];
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
    });
    fetch(`${API_BASE}/auth/logout/`, { method: "POST", credentials: "include" }).catch(() => {});
    setTimeout(() => { window.location.replace("/login"); }, 50);
  }, []);
  return <div className="min-h-screen flex items-center justify-center"><div className="text-slate-500 font-medium">Logging out...</div></div>;
}

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior }); }, [pathname]);
  return null;
}

function MaybeProtected({ children }: { children: React.ReactNode }) {
  if (AUTH_DISABLED) return <>{children}</>;
  return <ProtectedRoute>{children}</ProtectedRoute>;
}


function AccountLayoutWrapper() {
  const [role, setRole] = useState<'owner' | 'admin' | 'manager' | 'member'>('member');
  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((data: any) => setRole(data.role || 'member'))
      .catch(() => setRole('member'));
  }, []);
  return <AccountLayout role={role} />;
}


/**
 * Persistent "you are someone else right now" bar.
 *
 * It confirms the swap from the *server's* answer, not from localStorage: the
 * identity shown is whoever whoami says request.user resolved to. If the header
 * were ever being ignored, this bar would show the admin's own name and the
 * mismatch would be visible immediately, rather than the admin quietly reading
 * their own data believing it was the customer's.
 */
function ImpersonationBanner() {
  const [session, setSession] = useState(() => getViewAs());
  const [confirmed, setConfirmed] = useState<{ username: string; role?: string | null; org?: string | null } | null>(null);
  const [drift, setDrift] = useState(false);

  useEffect(() => {
    if (!session) return;
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((me: any) => {
        setConfirmed({ username: me?.username, role: me?.role, org: me?.org_name });
        // whoami reports the swap it actually applied. No view_as block means
        // the server served this request as the admin.
        setDrift(!me?.view_as?.active);
      })
      .catch(() => setDrift(true));
  }, [session]);

  const exit = () => {
    stopViewAs();
    setSession(null);
    window.location.reload();
  };

  if (!session) return null;

  const bg = drift ? "#7f1d1d" : "#92400e";
  return (
    <div style={{
      background: bg, color: "#fef3c7", padding: "9px 24px",
      fontSize: 13, display: "flex", justifyContent: "space-between",
      alignItems: "center", fontFamily: "monospace", gap: 16,
    }}>
      <span>
        {drift ? (
          <>⚠ View-as is NOT active on the server — this is your own account.</>
        ) : (
          <>
            👁 MavOps Admin — acting as <strong>{confirmed?.username || session.userName}</strong>
            {confirmed?.role ? <> ({confirmed.role})</> : null} @{" "}
            <strong>{confirmed?.org || session.orgName}</strong>
            {" — writes are real."}
          </>
        )}
      </span>
      <button onClick={exit} style={{
        background: "none", border: "1px solid #fef3c7aa", color: "#fef3c7",
        padding: "3px 14px", cursor: "pointer", borderRadius: 4, fontSize: 12,
        flexShrink: 0,
      }}>exit ×</button>
    </div>
  );
}

function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-white">
      <ImpersonationBanner />
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      <SupportWidget />   {/* ← floating Help button, every protected page */}
    </div>
  );
}

function HomeOrRedirect() {
  const [checking, setChecking] = useState(true);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then((data: any) => setAuthed(data?.is_authenticated === true))
      .catch(() => setAuthed(false))
      .finally(() => setChecking(false));
  }, []);

  if (checking) return null;
  if (authed) return <Navigate to="/daily" replace />;
  return <Home />;
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
            <Suspense
              fallback={
                <div className="min-h-screen flex items-center justify-center">
                  <div className="text-primary font-medium">Loading…</div>
                </div>
              }
            >
              <Routes>
                {/* Public / marketing */}
                <Route path="/" element={<HomeOrRedirect />} />
                <Route path="/request-access" element={<RequestAccess />} />
                <Route path="/invite/:token" element={<AcceptInvite />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password/:uid/:token" element={<ResetPassword />} />

                {/* Auth */}
                {!AUTH_DISABLED && (
                  <>
                    <Route path="/login" element={<Login />} />
                    {/* Self-serve signup is parked, not deleted. Onboarding is
                        white-glove right now, so the public front door asks for
                        a conversation instead of taking a card. The wizard is
                        still mounted at /onboarding for when self-serve returns
                        — swap this line back to bring it live. */}
                    <Route path="/signup" element={<Navigate to="/request-access" replace />} />
                    <Route path="/logout" element={<Logout />} />
                  </>
                )}

                {/* Protected — all users */}
                <Route path="/welcome" element={<MaybeProtected><AppLayout><Welcome /></AppLayout></MaybeProtected>} />
                <Route path="/daily" element={<MaybeProtected><AppLayout><DailyReview /></AppLayout></MaybeProtected>} />
                <Route path="/reports" element={<MaybeProtected><AppLayout><ReportsSummary /></AppLayout></MaybeProtected>} />
                <Route path="/reports/blind-spots" element={<MaybeProtected><AdminRoute><AppLayout><AIBlindSpots /></AppLayout></AdminRoute></MaybeProtected>} />
                <Route path="/timesheet" element={<MaybeProtected><AppLayout><BillingPage section="timesheet" /></AppLayout></MaybeProtected>} />
                <Route path="/billing" element={<MaybeProtected><AppLayout><BillingPage section="billing" /></AppLayout></MaybeProtected>} />
                <Route path="/devices" element={<MaybeProtected><AppLayout><Devices /></AppLayout></MaybeProtected>} />

                {/* Protected — admin/manager */}
                <Route path="/settings" element={<MaybeProtected><AdminRoute><AppLayout><OrgAdminSettings /></AppLayout></AdminRoute></MaybeProtected>} />
                <Route path="/settings/onboarding" element={<MaybeProtected><AdminRoute><AppLayout><WhiteGloveOnboarding /></AppLayout></AdminRoute></MaybeProtected>} />
                <Route path="/settings/ai" element={<MaybeProtected><AdminRoute><AppLayout><OrganizationSettings /></AppLayout></AdminRoute></MaybeProtected>} />
                <Route path="/analytics" element={<MaybeProtected><AdminRoute><AppLayout><ExecutiveGate><DashboardV2 /></ExecutiveGate></AppLayout></AdminRoute></MaybeProtected>} />

                {/* Account settings */}
                <Route path="/account" element={<MaybeProtected><AppLayout><AccountLayoutWrapper /></AppLayout></MaybeProtected>}>
                  <Route index element={<ProfilePage />} />
                  <Route path="notifications" element={<NotificationsPage />} />
                  <Route path="connections" element={<ConnectionsPage />} />
                  <Route path="download" element={<DownloadPage />} />
                  <Route path="password" element={<PasswordPage />} />
                  <Route path="billing" element={<OwnerRoute><BillingSettingsPage /></OwnerRoute>} />
                </Route>

                {/* Onboarding. /onboarding stays reachable so the wizard can be
                    driven by hand when needed; only the public signup entrance
                    is diverted. */}
                <Route path="/onboarding" element={<OnboardingWizard />} />
                <Route path="/onboarding/signup" element={<Navigate to="/request-access" replace />} />

                {/* MavOps Internal Admin — standalone, no AppLayout, no auth wrapper */}
                <Route path="/mavops-admin" element={<MavOpsAdmin />} />

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