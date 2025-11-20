// src/pages/Login.tsx
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";
import { primeCsrf } from "@/lib/csrf";
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

  // If already logged in, hop to next
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const j = await safeFetchJson<{ is_authenticated?: boolean }>(API_ENDPOINTS.whoami, {
          credentials: "include",
        });
        if (alive && j?.is_authenticated === true) {
          nav(next, { replace: true });
          return;
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

    try {
      const res = await safeFetchJson<{ 
        ok: boolean; 
        error?: string;
        token?: string;
        user?: any;
      }>(
        API_ENDPOINTS.authLogin,
        {
          method: "POST",
          body: JSON.stringify(form),
        }
      );

      if (!res?.ok) throw new Error(res?.error || "Login failed");

      // ✅ Store token FIRST
      if (res.token) {
        localStorage.setItem('auth_token', res.token);
        console.log("✅ Token stored:", res.token);
      }

      // ✅ Verify with explicit token header (bypass safeFetchJson timing issue)
      const whoamiResp = await fetch(API_ENDPOINTS.whoami, {
        headers: {
          'Authorization': `Bearer ${res.token}`
        }
      });
      
      const whoamiData = await whoamiResp.json();
      console.log("whoami response:", whoamiData);
      
      if (!whoamiData?.is_authenticated) {
        throw new Error("Authentication verification failed");
      }

      // ✅ Success! Redirect
      nav(next, { replace: true });
    } catch (e: any) {
      console.error("Login error", e);
      setErr(e?.message || "Login failed");
      localStorage.removeItem('auth_token');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-md bg-card rounded-xl p-6 shadow">
        <h1 className="text-2xl font-bold mb-2">Log in</h1>
        {err && <div className="text-red-600 text-sm mb-2 break-words">{err}</div>}

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
            className="w-full bg-primary text-white py-2 rounded-md font-semibold"
          >
            {busy ? "Signing in…" : "Log in"}
          </button>
        </form>

        <p className="text-sm text-center mt-3">
          No account?{" "}
          <Link className="underline" to={`/signup?next=${encodeURIComponent(next)}`}>  
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}