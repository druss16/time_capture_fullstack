// src/pages/Login.tsx
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { API_ENDPOINTS, API_BASE, safeFetchJson } from "@/lib/api";

async function primeCsrf() {
  try {
    await fetch(API_ENDPOINTS.getCsrf, { credentials: "include" });
  } catch {
    /* ignore */
  }
}

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const params = new URLSearchParams(loc.search);
  const next = params.get("next") || "/";

  const [form, setForm] = useState({ username: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);

  // If already logged in, hop to next
  useEffect(() => {
    (async () => {
      try {
        const j = await safeFetchJson<{ username?: string }>(API_ENDPOINTS.whoami);
        if (j?.username) {
          nav(next, { replace: true });
          return;
        }
      } catch {
        // not logged in
      }
      await primeCsrf();
    })();
  }, [nav, next]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    try {
      // Attempt login
      const res = await safeFetchJson<{ ok: boolean; error?: string }>(API_ENDPOINTS.authLogin, {
        method: "POST",
        body: JSON.stringify(form),
      });

      if (!res?.ok) throw new Error(res?.error || "Login failed");

      // ✅ NEW: register browser identity with backend
      try {
        await fetch(`${API_BASE}/browser/hello/`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: form.username,
            host: window.location.hostname,
          }),
        });
      } catch (err) {
        console.warn("browser hello failed", err);
      }

      // Redirect after both succeed
      nav(next, { replace: true });
    } catch (e: any) {
      setErr(e?.message || "Login failed");
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