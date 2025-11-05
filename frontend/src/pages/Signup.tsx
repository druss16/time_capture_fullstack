// src/pages/Signup.tsx
import { useEffect, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { API_ENDPOINTS, API_BASE, safeFetchJson } from "@/lib/api";

async function primeCsrf() {
  try {
    await fetch(API_ENDPOINTS.getCsrf, { credentials: "include" });
  } catch {
    /* ignore */
  }
}

export default function Signup() {
  const nav = useNavigate();
  const loc = useLocation();
  const params = new URLSearchParams(loc.search);
  const next = params.get("next") || "/";

  const [form, setForm] = useState({ username: "", password: "", email: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Ensure csrftoken exists before first POST
  useEffect(() => {
    primeCsrf();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    try {
      // 1) Create account
      const res = await safeFetchJson<{ ok: boolean; error?: string }>(API_ENDPOINTS.authSignup, {
        method: "POST",
        body: JSON.stringify(form),
      });
      if (!res?.ok) throw new Error(res?.error || "Signup failed");

      // 2) Register browser identity (cookie for /whoami + AgentSession update)
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
      } catch (e) {
        console.warn("browser hello failed", e);
      }

      // 3) Go to next page
      nav(next, { replace: true });
    } catch (e: any) {
      setErr(e?.message || "Signup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-md bg-card rounded-xl p-6 shadow">
        <h1 className="text-2xl font-bold mb-2">Sign up</h1>
        {err && <div className="text-red-600 text-sm mb-2 break-words">{err}</div>}

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            name="username"
            placeholder="Username"
            autoComplete="username"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            className="w-full border rounded px-3 py-2"
            required
          />
          <input
            name="email"
            type="email"
            placeholder="Email (optional)"
            autoComplete="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="w-full border rounded px-3 py-2"
          />
          <input
            type="password"
            name="password"
            placeholder="Password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            className="w-full border rounded px-3 py-2"
            required
          />
          <button
            type="submit"
            disabled={busy}
            className="w-full bg-primary text-white py-2 rounded-md font-semibold"
          >
            {busy ? "Creating account…" : "Sign up"}
          </button>
        </form>

        <p className="text-sm text-center mt-3">
          Already have an account?{" "}
          <Link className="underline" to={`/login?next=${encodeURIComponent(next)}`}>
            Log in
          </Link>
        </p>
      </div>
    </div>
  );
}