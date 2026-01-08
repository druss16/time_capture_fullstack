// src/pages/Logout.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";

export default function Logout() {
  const nav = useNavigate();
  const { logout } = useAuth();
  const [status, setStatus] = useState("Logging out…");

  useEffect(() => {
    let mounted = true;

    (async () => {
      // 1. Clear local state FIRST (before any async operations)
      localStorage.removeItem('auth_token');
      sessionStorage.clear();
      
      // 2. Clear identity cookies
      const cookieOpts = "path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
      document.cookie = `mavops_username=; ${cookieOpts}`;
      document.cookie = `mavops_host=; ${cookieOpts}`;
      document.cookie = `mavops_ident=; ${cookieOpts}`;
      document.cookie = `sessionid=; ${cookieOpts}`;

      // 3. Try server logout but don't block/fail on errors
      try {
        await logout();
      } catch (e) {
        // Server logout failed - that's OK, we're logged out locally
        console.warn("[Logout] Server logout failed (continuing):", e);
      }

      // 4. Small delay for UX
      await new Promise(resolve => setTimeout(resolve, 200));

      // 5. Redirect to login
      if (mounted) {
        setStatus("Redirecting…");
        nav('/login', { replace: true });
      }
    })();

    return () => { mounted = false; };
  }, [logout, nav]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center space-y-4">
        <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin mx-auto" />
        <p className="text-muted-foreground">{status}</p>
      </div>
    </div>
  );
}