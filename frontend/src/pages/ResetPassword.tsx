// src/pages/ResetPassword.tsx
/**
 * /reset-password/:uid/:token — choose a new password.
 *
 * The token is Django's default_token_generator, which hashes the current
 * password and last_login into itself, so completing a reset invalidates the
 * link and a stale one cannot be replayed. There is no model behind it and no
 * migration.
 *
 * Validity is only checked on submit: verifying up front would confirm to
 * anyone holding a guessed link whether it pointed at a real account.
 */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Eye, EyeOff, KeyRound, CheckCircle2 } from "lucide-react";

const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

export default function ResetPassword() {
  const { uid = "", token = "" } = useParams();
  const nav = useNavigate();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const tooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && password !== confirm;
  const canSubmit = password.length >= 8 && password === confirm && !busy;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/auth/password-reset/confirm/`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uid, token, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.error || "We couldn't change your password.");
      setDone(true);
      setTimeout(() => nav("/login", { replace: true }), 2500);
    } catch (e: any) {
      setErr(e?.message || "We couldn't change your password.");
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-6">
        <div className="w-full max-w-md space-y-5 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <CheckCircle2 className="h-7 w-7 text-primary" />
          </div>
          <div className="space-y-2">
            <h1 className="text-[1.5rem] font-bold tracking-tight text-foreground">
              Password changed
            </h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Use it to sign in here and in the desktop app. Taking you to sign in…
            </p>
          </div>
          <Link
            to="/login"
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-white transition-all hover:bg-primary/90"
          >
            Sign in now <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-6">
      <div className="w-full max-w-sm space-y-7">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10">
            <KeyRound className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-[1.4rem] font-bold tracking-tight text-foreground">
              Choose a new password
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">At least 8 characters.</p>
          </div>
        </div>

        {err && (
          <div className="space-y-2 rounded-xl border border-destructive/20 bg-destructive/10 p-3.5 text-sm text-destructive">
            <p>{err}</p>
            <Link to="/forgot-password" className="inline-block font-semibold underline underline-offset-2">
              Request a new link
            </Link>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-foreground">New password</label>
            <div className="relative">
              <input
                type={showPw ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                autoFocus
                required
                disabled={busy}
                placeholder="At least 8 characters"
                className="w-full rounded-xl border border-border/50 bg-muted/50 px-4 py-3.5 pr-12 text-sm text-foreground transition-all placeholder:text-muted-foreground/50 focus:border-primary focus:bg-card focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50"
              />
              <button
                type="button"
                onClick={() => setShowPw(!showPw)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-muted-foreground transition-colors hover:text-foreground"
              >
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {tooShort && <p className="text-xs text-amber-600">Use at least 8 characters.</p>}
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-foreground">Confirm password</label>
            <input
              type={showPw ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
              disabled={busy}
              placeholder="Type it once more"
              className="w-full rounded-xl border border-border/50 bg-muted/50 px-4 py-3.5 text-sm text-foreground transition-all placeholder:text-muted-foreground/50 focus:border-primary focus:bg-card focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50"
            />
            {mismatch && <p className="text-xs text-amber-600">These don't match yet.</p>}
          </div>

          <button
            type="submit"
            disabled={!canSubmit}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-semibold text-white shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? (
              <>
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Saving…
              </>
            ) : (
              <>
                Change password <ArrowRight className="h-4 w-4" />
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
