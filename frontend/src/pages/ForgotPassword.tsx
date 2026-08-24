// src/pages/ForgotPassword.tsx
/**
 * /forgot-password — ask for a reset link.
 *
 * Until this existed, a forgotten password had no self-serve route at all: no
 * endpoint, no page, no link on the login screen. Every one became a message
 * to whoever runs the firm's rollout.
 *
 * The confirmation never says whether the address was found. A different
 * answer for a real account would make this a way to enumerate a firm's staff.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, KeyRound, MailCheck } from "lucide-react";

const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/auth/password-reset/`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.error || "Something went wrong.");
      setSent(true);
    } catch (e: any) {
      setErr(e?.message || "We couldn't reach TimeTracker. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-6">
        <div className="w-full max-w-md space-y-5 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <MailCheck className="h-7 w-7 text-primary" />
          </div>
          <div className="space-y-2">
            <h1 className="text-[1.5rem] font-bold tracking-tight text-foreground">Check your email</h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              If <span className="font-medium text-foreground">{email.trim()}</span> has an account,
              a reset link is on its way. It works once and expires in 72 hours.
            </p>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Nothing after a few minutes? Check spam, then ask whoever set up your account —
              they can send you a fresh link directly.
            </p>
          </div>
          <Link
            to="/login"
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-white transition-all hover:bg-primary/90"
          >
            Back to sign in <ArrowRight className="h-4 w-4" />
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
              Reset your password
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              We'll email you a link to choose a new one.
            </p>
          </div>
        </div>

        {err && (
          <div className="rounded-xl border border-destructive/20 bg-destructive/10 p-3.5 text-sm text-destructive">
            {err}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-foreground">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              disabled={busy}
              placeholder="you@yourfirm.com"
              className="w-full rounded-xl border border-border/50 bg-muted/50 px-4 py-3.5 text-sm text-foreground transition-all placeholder:text-muted-foreground/50 focus:border-primary focus:bg-card focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50"
            />
          </div>

          <button
            type="submit"
            disabled={busy || !email.trim()}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-semibold text-white shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? (
              <>
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Sending…
              </>
            ) : (
              <>
                Send reset link <ArrowRight className="h-4 w-4" />
              </>
            )}
          </button>
        </form>

        <Link
          to="/login"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
        </Link>
      </div>
    </div>
  );
}
