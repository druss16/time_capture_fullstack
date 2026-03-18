// Login.tsx - Clean redesign, left panel trimmed to breathe
import { useEffect, useState, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";
import { Eye, EyeOff, Clock, ArrowRight, Check } from "lucide-react";

const STATS = [
  { value: "Zero", label: "Manual\nentry required" },
  { value: "2+ hrs", label: "Billable time\ncaptured / day" },
  { value: "2-way", label: "QuickBooks\n& Xero sync" },
];

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const { refreshWhoAmI } = useAuth();
  const next = new URLSearchParams(loc.search).get("next") || "/daily";

  const [form, setForm] = useState({ username: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
  const hasChecked = useRef(false);

  useEffect(() => {
    if (hasChecked.current) return;
    hasChecked.current = true;
    safeFetchJson<{ is_authenticated?: boolean }>(API_ENDPOINTS.whoami, {
      credentials: "include",
    })
      .then(j => { if (j?.is_authenticated === true) nav(next, { replace: true }); })
      .catch(() => {});
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const res = await safeFetchJson<{
        ok: boolean; error?: string; token?: string;
        user?: { id: number; username: string; email: string };
      }>(API_ENDPOINTS.authLogin, { method: "POST", body: JSON.stringify(form) });

      if (!res?.ok) throw new Error(res?.error || "Login failed");
      if (!res.token) throw new Error("No token received from server");

      localStorage.setItem("auth_token", res.token);
      await new Promise(r => setTimeout(r, 50));
      const who = await refreshWhoAmI();
      if (!who?.is_authenticated) throw new Error("Authentication verification failed");
      nav(next, { replace: true });
    } catch (e: any) {
      setErr(e?.message || "Login failed");
      localStorage.removeItem("auth_token");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex bg-background">

      {/* Left Panel */}
      <div
        className="hidden lg:flex lg:w-[52%] flex-col justify-between p-14 relative overflow-hidden"
        style={{ background: "linear-gradient(145deg, #2B9D90 0%, #1F7269 60%, #174F4A 100%)" }}
      >
        {/* Background blobs */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div className="absolute -top-24 -left-24 w-[480px] h-[480px] rounded-full bg-white/[0.06] blur-3xl" />
          <div className="absolute -bottom-32 -right-16 w-[520px] h-[520px] rounded-full bg-black/[0.08] blur-3xl" />
        </div>

        {/* Logo */}
        <div className="relative z-10 flex items-center gap-2">
          <img src="/timetracker-icon-mono-white.svg" alt="TimeTracker" className="w-10 h-10" />
          <div className="leading-none">
            <p className="text-[17px] font-bold text-white tracking-tight">TimeTracker</p>
            <p className="text-[11px] text-white/50 mt-0.5">by MavOps</p>
          </div>
        </div>

        {/* Hero copy */}
        <div className="relative z-10 space-y-10">
          <div className="space-y-5">
            <div className="flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-300 animate-pulse" />
              <span className="text-[11px] font-semibold tracking-[0.15em] uppercase text-white/55">
                Built for CPA Firms
              </span>
            </div>
            <h1 className="text-[2.5rem] font-black leading-[1.2] tracking-tight">
              <span className="text-white">More revenue.</span><br />
              <span className="text-white/80">Less admin.</span><br />
              <span className="text-white/60">Smarter decisions.</span>
            </h1>

            <p className="text-[15px] text-white/60 leading-relaxed">
              TimeTracker is an AI-powered time intelligence platform built exclusively for CPA firms.
            </p>
          </div>

          {/* Icon rows */}
          <div className="space-y-5">
            {[
              { icon: Clock, title: "Runs silently on every workstation", desc: "Zero manual entry. Works on Mac & Windows in the background." },
              { icon: ArrowRight, title: "Captures every billable minute", desc: "Turns guesswork into an exact science. Recover revenue that used to get lost." },
              { icon: Check, title: "Real margin data for firm leaders", desc: "Know profitability by client, by staff, by matter — and grow with confidence." },
            ].map(({ icon: Icon, title, desc }, i) => (
              <div key={i} className="flex items-start gap-4">
                <div className="w-9 h-9 rounded-xl bg-white/15 border border-white/20 flex items-center justify-center shrink-0 mt-0.5">
                  <Icon className="w-4 h-4 text-white" />
                </div>
                <div>
                  <p className="text-[14px] font-bold text-white leading-tight">{title}</p>
                  <p className="text-[13px] text-white/50 mt-1 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Testimonial */}
          <blockquote className="border-l-4 border-white/25 pl-5 space-y-2">
            <p className="text-[16px] text-white/75 italic leading-relaxed font-medium">
              "We were leaving hours of billable time on the table every week and didn't even know it. TimeTracker fixed that in the first month."
            </p>
            <p className="text-[11px] text-white/40 font-bold tracking-widest uppercase">
              — Partner, Meridian CPA Group
            </p>
          </blockquote>
        </div>

        <p className="relative z-10 text-[11px] text-white/30">
          © {new Date().getFullYear()} MavOps. All rights reserved.
        </p>
      </div>

      {/* Right Panel */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-sm space-y-7">

          {/* Mobile logo */}
          <div className="lg:hidden flex items-center justify-center gap-3 mb-6">
            <img src="/timetracker-icon-circle.svg" alt="TimeTracker" className="w-10 h-10" />
            <span className="text-xl font-bold text-foreground">TimeTracker</span>
          </div>

          <div>
            <h2 className="text-[1.75rem] font-bold text-foreground tracking-tight">Welcome back</h2>
            <p className="text-sm text-muted-foreground mt-1">Sign in to continue to your dashboard</p>
          </div>

          {err && (
            <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm">
              {err}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-semibold text-foreground">Username or Email</label>
              <input
                type="text"
                name="username"
                autoComplete="username"
                disabled={busy}
                value={form.username}
                onChange={e => setForm({ ...form, username: e.target.value })}
                className="w-full px-4 py-3.5 rounded-xl bg-muted/50 border border-border/50 text-foreground placeholder:text-muted-foreground/50 text-sm transition-all focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none disabled:opacity-50"
                placeholder="Enter your username"
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-semibold text-foreground">Password</label>
              <div className="relative">
                <input
                  type={showPw ? "text" : "password"}
                  name="password"
                  autoComplete="current-password"
                  disabled={busy}
                  value={form.password}
                  onChange={e => setForm({ ...form, password: e.target.value })}
                  className="w-full px-4 py-3.5 pr-12 rounded-xl bg-muted/50 border border-border/50 text-foreground placeholder:text-muted-foreground/50 text-sm transition-all focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none disabled:opacity-50"
                  placeholder="Enter your password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={busy}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl bg-primary text-white text-sm font-semibold shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2"
            >
              {busy ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Signing in...
                </>
              ) : (
                <>Sign in <ArrowRight className="w-4 h-4" /></>
              )}
            </button>
          </form>

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <div className="flex-1 h-px bg-border/50" />
            Not a client yet?
            <div className="flex-1 h-px bg-border/50" />
          </div>

          <a
            href="mailto:info@mavops.ai?subject=TimeTracker%20Access%20Request&body=Hi%2C%20I%27d%20like%20to%20learn%20more%20about%20TimeTracker%20for%20my%20CPA%20firm."
            className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl border-2 border-primary/30 text-primary text-sm font-semibold hover:bg-primary/5 hover:border-primary/60 transition-all"
          >
            Request Access <ArrowRight className="w-4 h-4" />
          </a>

          <p className="text-center text-xs text-muted-foreground">
            Questions?{" "}
            <a href="mailto:info@mavops.ai" className="text-primary hover:underline font-medium">
              info@mavops.ai
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}