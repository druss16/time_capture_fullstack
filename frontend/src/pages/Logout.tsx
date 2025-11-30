// src/pages/Logout.tsx
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";

export default function Logout() {
  const nav = useNavigate();
  const { logout } = useAuth();

  useEffect(() => {
    let mounted = true;

    (async () => {
      // 1. Call the logout function (clears token, cookies, state)
      await logout();

      // 2. Double-check localStorage is cleared
      localStorage.removeItem('auth_token');
      sessionStorage.clear();

      // 3. Clear any identity cookies
      const cookieOpts = "path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
      document.cookie = `mavops_username=; ${cookieOpts}`;
      document.cookie = `mavops_host=; ${cookieOpts}`;
      document.cookie = `mavops_ident=; ${cookieOpts}`;

      // 4. Small delay to ensure everything is cleared
      await new Promise(resolve => setTimeout(resolve, 100));

      // 5. Redirect to login
      if (mounted) {
        nav('/login', { replace: true });
      }
    })();

    return () => {
      mounted = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center text-muted-foreground">
        Logging out…
      </div>
    </div>
  );
}