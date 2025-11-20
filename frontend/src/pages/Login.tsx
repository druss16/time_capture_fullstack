// src/pages/Login.tsx
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const params = new URLSearchParams(loc.search);
  const next = params.get("next") || "/daily";
  const { refreshWhoAmI } = useAuth();

  const [form, setForm] = useState({ username: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);

  // If already logged in, redirect
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const j = await safeFetchJson<{ is_authenticated?: boolean }>(
          API_ENDPOINTS.whoami,
          { credentials: "include" }
        );
        if (alive && j?.is_authenticated === true) {
          nav(next, { replace: true });
        }
      } catch {
        /* not logged in / server warming up */
      }
    })();
    return () => { alive = false; };
  }, [nav, next]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    console.log("🔐 Submitting login for:", form.username);

    try {
      // Step 1: Call login endpoint
      const res = await safeFetchJson<{ 
        ok: boolean; 
        error?: string;
        token?: string;
        user?: { id: number; username: string; email: string };
      }>(
        API_ENDPOINTS.authLogin,
        {
          method: "POST",
          body: JSON.stringify(form),
        }
      );

      console.log("📥 Login response:", res);

      if (!res?.ok) {
        throw new Error(res?.error || "Login failed");
      }

      // Step 2: Store token in localStorage
      if (!res.token) {
        throw new Error("No token received from server");
      }

      localStorage.setItem('auth_token', res.token);
      console.log("✅ Token stored in localStorage");

      // Step 3: Small delay to ensure localStorage is synced
      await new Promise(resolve => setTimeout(resolve, 50));

      // Step 4: Refresh auth state (will use the token we just stored)
      console.log("🔄 Refreshing auth state...");
      const who = await refreshWhoAmI();
      console.log("👤 Auth state:", who);
      
      if (!who?.is_authenticated) {
        throw new Error("Authentication verification failed");
      }

      // Step 5: Success! Redirect
      console.log("✅ Login successful, redirecting to:", next);
      nav(next, { replace: true });

    } catch (e: any) {
      console.error("❌ Login error:", e);
      setErr(e?.message || "Login failed");
      // Clean up on error
      localStorage.removeItem('auth_token');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-md bg-card rounded-xl p-6 shadow">
        <h1 className="text-2xl font-bold mb-2">Log in</h1>
        
        {err && (
          <div className="text-red-600 text-sm mb-2 break-words">
            {err}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            name="username"
            placeholder="Username or email"
            autoComplete="username"
            disabled={busy}
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            className="w-full border rounded px-3 py-2"
            required
          />

          <div className="flex gap-2">
            <input
              type={showPw ? "text" : "password"}
              name="password"
              placeholder="Password"
              autoComplete="current-password"
              disabled={busy}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="w-full border rounded px-3 py-2"
              required
            />
            <button
              type="button"
              onClick={() => setShowPw((s) => !s)}
              className="px-3 rounded border text-sm"
              aria-label={showPw ? "Hide password" : "Show password"}
            >
              {showPw ? "Hide" : "Show"}
            </button>
          </div>

          <button
            type="submit"
            disabled={busy}
            className="w-full bg-primary text-white py-2 rounded-md font-semibold hover:bg-primary/90 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Log in"}
          </button>
        </form>

        <p className="text-sm text-center mt-3">
          No account?{" "}
          <Link 
            className="underline hover:text-primary" 
            to={`/signup?next=${encodeURIComponent(next)}`}
          >  
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}