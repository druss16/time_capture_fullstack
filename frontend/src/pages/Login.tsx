// Login.tsx - Fixed version
import { useEffect, useState, useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { API_ENDPOINTS, safeFetchJson } from "@/lib/api";
import { useAuth } from "@/auth/AuthProvider";
import { Eye, EyeOff, Clock, ArrowRight, Sparkles } from "lucide-react";

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  
  // Memoize `next` so it doesn't change on every render
  const next = useMemo(() => {
    const params = new URLSearchParams(loc.search);
    return params.get("next") || "/daily";
  }, [loc.search]);
  
  const { refreshWhoAmI } = useAuth();

  const [form, setForm] = useState({ username: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
  const [checking, setChecking] = useState(true); // Add loading state

  // Check if already logged in
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
        // Not logged in - stay on login page
      } finally {
        if (alive) setChecking(false);
      }
    })();
    
    return () => { alive = false; };
  }, [nav, next]); // Add proper dependencies

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    try {
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

      if (!res?.ok) {
        throw new Error(res?.error || "Login failed");
      }

      if (!res.token) {
        throw new Error("No token received from server");
      }

      localStorage.setItem('auth_token', res.token);
      await new Promise(resolve => setTimeout(resolve, 50));

      const who = await refreshWhoAmI();
      
      if (!who?.is_authenticated) {
        throw new Error("Authentication verification failed");
      }

      nav(next, { replace: true });

    } catch (e: any) {
      setErr(e?.message || "Login failed");
      localStorage.removeItem('auth_token');
    } finally {
      setBusy(false);
    }
  }

  // Show loading while checking auth
  if (checking) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }


  return (
    <div className="min-h-screen bg-background flex">
      {/* Left Panel - Branding */}
      <div className="
        hidden lg:flex lg:w-1/2 
        bg-gradient-to-br from-primary via-primary to-primary/90
        flex-col justify-between
        p-12
        relative overflow-hidden
      ">
        {/* Background Pattern */}
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-20 left-20 w-72 h-72 bg-white rounded-full blur-3xl" />
          <div className="absolute bottom-20 right-20 w-96 h-96 bg-white rounded-full blur-3xl" />
        </div>
        
        {/* Logo */}
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="
              w-12 h-12 rounded-xl 
              bg-white/20 backdrop-blur
              flex items-center justify-center
            ">
              <Clock className="w-6 h-6 text-white" />
            </div>
            <div>
              <span className="text-2xl font-bold text-white">TimeTracker</span>
              <span className="text-sm text-white/70 block">by MavOps</span>
            </div>
          </div>
        </div>

        {/* Hero Content */}
        <div className="relative z-10 space-y-6">
          <h1 className="text-4xl font-bold text-white leading-tight">
            Your time is finite.<br />
            <span className="text-white/80">Make it count.</span>
          </h1>
          <p className="text-lg text-white/70 max-w-md">
            Automate timesheets, capture every billable minute, 
            and gain insights into how your time is really spent.
          </p>
          
          {/* Features */}
          <div className="space-y-4 pt-4">
            {[
              "AI-powered time categorization",
              "Automatic activity tracking",
              "Client billing integration"
            ].map((feature, i) => (
              <div key={i} className="flex items-center gap-3 text-white/90">
                <div className="w-6 h-6 rounded-full bg-white/20 flex items-center justify-center">
                  <Sparkles className="w-3.5 h-3.5 text-white" />
                </div>
                <span className="text-sm font-medium">{feature}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="relative z-10 text-white/50 text-sm">
          © {new Date().getFullYear()} MavOps. All rights reserved.
        </div>
      </div>

      {/* Right Panel - Login Form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md space-y-8">
          {/* Mobile Logo */}
          <div className="lg:hidden flex items-center justify-center gap-3 mb-8">
            <div className="
              w-12 h-12 rounded-xl 
              bg-primary
              flex items-center justify-center
              shadow-lg shadow-primary/25
            ">
              <Clock className="w-6 h-6 text-white" />
            </div>
            <span className="text-2xl font-bold text-foreground">TimeTracker</span>
          </div>

          {/* Header */}
          <div className="text-center lg:text-left">
            <h2 className="text-3xl font-bold text-foreground tracking-tight">
              Welcome back
            </h2>
            <p className="text-muted-foreground mt-2">
              Sign in to continue to your dashboard
            </p>
          </div>

          {/* Error Banner */}
          {err && (
            <div className="
              p-4 rounded-xl 
              bg-destructive/10 border border-destructive/20
              text-destructive text-sm
              animate-slide-up
            ">
              {err}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Username */}
            <div className="space-y-2">
              <label className="text-sm font-semibold text-foreground">
                Username or Email
              </label>
              <input
                type="text"
                name="username"
                autoComplete="username"
                disabled={busy}
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="
                  w-full px-4 py-3.5 rounded-xl
                  bg-muted/50 border border-border/50
                  text-foreground font-medium
                  placeholder:text-muted-foreground/60
                  transition-all duration-200
                  focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none
                  disabled:opacity-50
                "
                placeholder="Enter your username"
                required
              />
            </div>

            {/* Password */}
            <div className="space-y-2">
              <label className="text-sm font-semibold text-foreground">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPw ? "text" : "password"}
                  name="password"
                  autoComplete="current-password"
                  disabled={busy}
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  className="
                    w-full px-4 py-3.5 pr-12 rounded-xl
                    bg-muted/50 border border-border/50
                    text-foreground font-medium
                    placeholder:text-muted-foreground/60
                    transition-all duration-200
                    focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none
                    disabled:opacity-50
                  "
                  placeholder="Enter your password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="
                    absolute right-3 top-1/2 -translate-y-1/2
                    p-2 rounded-lg
                    text-muted-foreground hover:text-foreground
                    hover:bg-muted
                    transition-colors
                  "
                  aria-label={showPw ? "Hide password" : "Show password"}
                >
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={busy}
              className="
                w-full flex items-center justify-center gap-2
                px-6 py-3.5 rounded-xl
                bg-primary text-primary-foreground
                font-semibold
                shadow-lg shadow-primary/25
                hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30
                focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2
                disabled:opacity-50 disabled:cursor-not-allowed
                transition-all duration-200
              "
            >
              {busy ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Signing in...
                </>
              ) : (
                <>
                  Sign in
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Sign Up Link */}
          <p className="text-center text-sm text-muted-foreground">
            Don't have an account?{" "}
            <Link 
              className="font-semibold text-primary hover:text-primary/80 transition-colors" 
              to={`/signup?next=${encodeURIComponent(next)}`}
            >
              Sign up
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
