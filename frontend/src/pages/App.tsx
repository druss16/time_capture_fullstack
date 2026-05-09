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
import DownloadPage from '@/pages/account/DownloadPage';
import TimesheetReminderBanner from '@/components/TimesheetReminderBanner';
import NotificationsPage from '@/pages/account/NotificationsPage';
import ConnectionsPage from '@/pages/account/ConnectionsPage';
import TaxReturnsTab from "./TaxReturnsTab";

// --------- Lazy pages (code-splitting) ---------
const DailyReview = lazy(() => import("./DailyReview"));
const TimecardSummary = lazy(() => import("./TimecardSummary"));
const OrgAdminSettings = lazy(() => import("./Settings"));
const OrganizationSettings = lazy(() => import("./OrganizationSettings"));
const Devices = lazy(() => import("./Devices"));
const Login = lazy(() => import("./Login"));
const NotFound = lazy(() => import("./NotFound"));
const BillingPage = lazy(() => import("./BillingPage"));
const WhiteGloveOnboarding = lazy(() => import("./settings/WhiteGloveOnboarding"));
const ExecutiveDashboard = lazy(() => import("./ExecutiveDashboard"));
const Home = lazy(() => import("./Home"));
const RequestAccess = lazy(() => import("./RequestAccess"));
const MavOpsAdmin = lazy(() => import("./MavOpsAdmin")); // ← NEW

import { safeFetchJson, API_BASE } from "@/lib/api";

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


function ImpersonationBanner() {
  const [orgId, setOrgId]     = useState(() => localStorage.getItem("impersonating_org_id"));
  const [orgName, setOrgName] = useState(() => localStorage.getItem("impersonating_org_name"));
  const [userName, setUserName] = useState(() => localStorage.getItem("impersonating_user_name"));
  if (!orgId) return null;
  return (
    <div style={{
      background: "#92400e", color: "#fef3c7", padding: "9px 24px",
      fontSize: 13, display: "flex", justifyContent: "space-between",
      alignItems: "center", fontFamily: "monospace",
    }}>
      <span>
        👁 MavOps Admin — viewing as <strong>{userName}</strong> @ <strong>{orgName}</strong>
      </span>
      <button onClick={() => {
        localStorage.removeItem("impersonating_org_id");
        localStorage.removeItem("impersonating_org_name");
        localStorage.removeItem("impersonating_user_id");
        localStorage.removeItem("impersonating_user_name");
        setOrgId(null); setOrgName(null); setUserName(null);
        window.location.reload();
      }} style={{
        background: "none", border: "1px solid #fef3c7aa", color: "#fef3c7",
        padding: "3px 14px", cursor: "pointer", borderRadius: 4, fontSize: 12,
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

                {/* Auth */}
                {!AUTH_DISABLED && (
                  <>
                    <Route path="/login" element={<Login />} />
                    <Route path="/signup" element={<OnboardingWizard initialStep={1} />} />
                    <Route path="/logout" element={<Logout />} />
                  </>
                )}

                {/* Protected — all users */}
                <Route path="/daily" element={<MaybeProtected><AppLayout><DailyReview /></AppLayout></MaybeProtected>} />
                <Route path="/summary" element={<MaybeProtected><AppLayout><TimecardSummary /></AppLayout></MaybeProtected>} />
                <Route path="/billing" element={<MaybeProtected><AppLayout><BillingPage /></AppLayout></MaybeProtected>} />
                <Route path="/devices" element={<MaybeProtected><AppLayout><Devices /></AppLayout></MaybeProtected>} />

                {/* Protected — admin/manager */}
                <Route path="/settings" element={<MaybeProtected><AdminRoute><AppLayout><OrgAdminSettings /></AppLayout></AdminRoute></MaybeProtected>} />
                <Route path="/settings/onboarding" element={<MaybeProtected><AdminRoute><AppLayout><WhiteGloveOnboarding /></AppLayout></AdminRoute></MaybeProtected>} />
                <Route path="/settings/ai" element={<MaybeProtected><AdminRoute><AppLayout><OrganizationSettings /></AppLayout></AdminRoute></MaybeProtected>} />
                <Route path="/analytics" element={<MaybeProtected><AdminRoute><AppLayout><ExecutiveDashboard apiBase={API_BASE} /></AppLayout></AdminRoute></MaybeProtected>} />

                {/* Account settings */}
                <Route path="/account" element={<MaybeProtected><AppLayout><AccountLayoutWrapper /></AppLayout></MaybeProtected>}>
                  <Route index element={<ProfilePage />} />
                  <Route path="notifications" element={<NotificationsPage />} />
                  <Route path="connections" element={<ConnectionsPage />} />
                  <Route path="download" element={<DownloadPage />} />
                  <Route path="password" element={<PasswordPage />} />
                  <Route path="billing" element={<OwnerRoute><BillingSettingsPage /></OwnerRoute>} />
                </Route>

                {/* Onboarding */}
                <Route path="/onboarding" element={<OnboardingWizard />} />
                <Route path="/onboarding/signup" element={<OnboardingWizard initialStep={1} />} />

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