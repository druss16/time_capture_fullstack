// src/pages/AcceptInvite.tsx
/**
 * The first screen a new member ever sees: /invite/:token
 *
 * They arrive from the invite email holding a single-use link. All this page
 * does is trade that link for a password of their choosing, then hand them to
 * /welcome. No marketing panel — they were sold before the invite went out;
 * what they need here is to recognise their firm's name and get through.
 */
import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Eye, EyeOff, ArrowRight, Clock, AlertCircle } from "lucide-react";

const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

type InviteInfo = {
  valid: true;
  email: string;
  name: string;
  org_name: string;
  invited_by: string | null;
  role: string;
};

type InviteProblem = "expired" | "accepted" | "invalid" | "already_active" | "network";

const PROBLEM_COPY: Record<InviteProblem, { title: string; body: string; cta: string | null }> = {
  expired: {
    title: "This invitation has expired",
    body: "Invitations are good for seven days. Ask whoever invited you to send a new one — it only takes them a moment.",
    cta: null,
  },
  accepted: {
    title: "This invitation was already used",
    body: "Your account is set up. Sign in with the password you chose.",
    cta: "Go to sign in",
  },
  already_active: {
    title: "Your account is already active",
    body: "Nothing left to set up here. Sign in with your password, or reset it if you don't remember it.",
    cta: "Go to sign in",
  },
  invalid: {
    title: "We couldn't find that invitation",
    body: "The link may have been cut short by your email client. Try copying the full address from the invite email, or ask for a new one.",
    cta: null,
  },
  network: {
    title: "We couldn't reach TimeTracker",
    body: "Check your connection and reload the page. Your invitation is still valid.",
    cta: null,
  },
};

export default function AcceptInvite() {
  const { token = "" } = useParams();
  const nav = useNavigate();

  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [problem, setProblem] = useState<InviteProblem | null>(null);
  const [checking, setChecking] = useState(true);

  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // A half-finished session from another account would otherwise ride along on
  // this request and get it rejected before the view runs. Nobody is signed in
  // on this page by definition, so clearing is always the right move.
  useEffect(() => {
    ["auth_token", "tt_auth_token", "authToken", "token"].forEach((k) =>
      localStorage.removeItem(k)
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/invite/${encodeURIComponent(token)}/`, {
          credentials: "include",
        });
        const body = await res.json().catch(() => ({}));
        if (cancelled) return;
        if (res.ok && body?.valid) {
          setInfo(body as InviteInfo);
          setName(body.name || "");
        } else {
          setProblem((body?.reason as InviteProblem) || "invalid");
        }
      } catch {
        if (!cancelled) setProblem("network");
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const tooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && password !== confirm;
  const canSubmit = password.length >= 8 && password === confirm && !busy;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/invite/${encodeURIComponent(token)}/accept/`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, name: name.trim() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.error || "We couldn't finish setting up your account.");
      if (body?.token) localStorage.setItem("auth_token", body.token);
      nav("/welcome", { replace: true });
    } catch (e: any) {
      setErr(e?.message || "We couldn't finish setting up your account.");
      setBusy(false);
    }
  }

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-muted-foreground">
          <div className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          Checking your invitation…
        </div>
      </div>
    );
  }

  if (problem) {
    const copy = PROBLEM_COPY[problem];
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-6">
        <div className="w-full max-w-md text-center space-y-5">
          <div className="w-14 h-14 rounded-2xl bg-amber-50 border border-amber-200 flex items-center justify-center mx-auto">
            <AlertCircle className="w-7 h-7 text-amber-500" />
          </div>
          <div className="space-y-2">
            <h1 className="text-[1.5rem] font-bold text-foreground tracking-tight">{copy.title}</h1>
            <p className="text-sm text-muted-foreground leading-relaxed">{copy.body}</p>
          </div>
          {copy.cta && (
            <Link
              to="/login"
              className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-all"
            >
              {copy.cta} <ArrowRight className="w-4 h-4" />
            </Link>
          )}
          <p className="text-xs text-muted-foreground pt-2">
            Stuck?{" "}
            <a href="mailto:info@mavops.ai" className="text-primary hover:underline font-medium">
              info@mavops.ai
            </a>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-6">
      <div className="w-full max-w-md">
        <div className="rounded-2xl border border-border/60 bg-card shadow-sm overflow-hidden">
          {/* Their firm's name is the thing that makes this link feel legitimate,
              so it leads rather than sitting in body copy. */}
          <div
            className="px-8 py-7 text-center"
            style={{ background: "linear-gradient(145deg, #2B9D90 0%, #1F7269 100%)" }}
          >
            <div className="w-11 h-11 rounded-xl bg-white/15 border border-white/20 flex items-center justify-center mx-auto mb-3">
              <Clock className="w-5 h-5 text-white" />
            </div>
            <p className="text-[13px] text-white/70">
              {info?.invited_by ? `${info.invited_by} invited you to` : "You've been invited to"}
            </p>
            <h1 className="text-[1.35rem] font-bold text-white tracking-tight mt-0.5">
              {info?.org_name}
            </h1>
          </div>

          <div className="p-8 space-y-6">
            <div>
              <h2 className="text-[1.1rem] font-bold text-foreground tracking-tight">
                Choose a password
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                Last step before setup. You'll use this to sign in here and in the desktop app.
              </p>
            </div>

            {err && (
              <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm">
                {err}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-foreground">Email</label>
                <input
                  type="email"
                  value={info?.email || ""}
                  readOnly
                  autoComplete="username"
                  className="w-full px-4 py-3.5 rounded-xl bg-muted/70 border border-border/50 text-muted-foreground text-sm cursor-not-allowed"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-foreground">Your name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  disabled={busy}
                  placeholder="Jane Smith"
                  className="w-full px-4 py-3.5 rounded-xl bg-muted/50 border border-border/50 text-foreground placeholder:text-muted-foreground/50 text-sm transition-all focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none disabled:opacity-50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-foreground">Password</label>
                <div className="relative">
                  <input
                    type={showPw ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                    disabled={busy}
                    required
                    placeholder="At least 8 characters"
                    className="w-full px-4 py-3.5 pr-12 rounded-xl bg-muted/50 border border-border/50 text-foreground placeholder:text-muted-foreground/50 text-sm transition-all focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none disabled:opacity-50"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw(!showPw)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {tooShort && (
                  <p className="text-xs text-amber-600">Use at least 8 characters.</p>
                )}
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-foreground">Confirm password</label>
                <input
                  type={showPw ? "text" : "password"}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  disabled={busy}
                  required
                  placeholder="Type it once more"
                  className="w-full px-4 py-3.5 rounded-xl bg-muted/50 border border-border/50 text-foreground placeholder:text-muted-foreground/50 text-sm transition-all focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none disabled:opacity-50"
                />
                {mismatch && <p className="text-xs text-amber-600">These don't match yet.</p>}
              </div>

              <button
                type="submit"
                disabled={!canSubmit}
                className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl bg-primary text-white text-sm font-semibold shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2"
              >
                {busy ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Setting up…
                  </>
                ) : (
                  <>
                    Continue <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </form>
          </div>
        </div>

        <p className="text-center text-xs text-muted-foreground mt-5">
          Questions?{" "}
          <a href="mailto:info@mavops.ai" className="text-primary hover:underline font-medium">
            info@mavops.ai
          </a>
        </p>
      </div>
    </div>
  );
}
