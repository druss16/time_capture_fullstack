// src/pages/settings/TeamActivation.tsx
/**
 * Live rollout status for a firm — who is actually running, and who is stuck.
 *
 * White-glove onboarding is only white-glove if someone can see where each
 * member stalled. The team list can't show that: a member who never opened
 * their invite and a member whose agent died both just look like a row. This
 * ranks people by how far they got, worst first, and gives the one action that
 * unblocks the most common case (a lapsed invite).
 */
import { useCallback, useEffect, useState } from "react";
import { safeFetchJson, API_BASE } from "@/lib/api";
import {
  RefreshCw,
  Send,
  Check,
  AlertTriangle,
  Clock,
  Monitor,
  KeyRound,
  Mail,
  Copy,
} from "lucide-react";
import { cn } from "@/lib/design-system";

type Stage = "invited" | "password_set" | "device_paired" | "time_flowing";

type Member = {
  user_id: number;
  name: string;
  email: string;
  role: string;
  is_you: boolean;
  stage: Stage;
  invite_state: string;
  invite_sent_at: string | null;
  invite_expires_at: string | null;
  has_password: boolean;
  signed_in: boolean;
  can_resend_invite: boolean;
  last_login: string | null;
  device_count: number;
  device_last_seen: string | null;
  block_count: number;
  last_block_at: string | null;
};

type Payload = {
  org_name: string;
  total: number;
  ready: number;
  counts: Record<Stage, number>;
  members: Member[];
};

const STAGES: { key: Stage; label: string; icon: React.ElementType }[] = [
  { key: "invited", label: "Invited", icon: Mail },
  { key: "password_set", label: "Signed in", icon: KeyRound },
  { key: "device_paired", label: "Device paired", icon: Monitor },
  { key: "time_flowing", label: "Time flowing", icon: Check },
];

const STAGE_TONE: Record<Stage, string> = {
  invited: "bg-amber-50 text-amber-700 border-amber-200",
  password_set: "bg-amber-50 text-amber-700 border-amber-200",
  device_paired: "bg-sky-50 text-sky-700 border-sky-200",
  time_flowing: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

/** What is actually blocking this person, in the words you'd use on a call. */
function diagnose(m: Member): string {
  if (m.stage === "time_flowing") {
    return m.last_block_at ? `Last captured ${ago(m.last_block_at)}` : "Capturing normally";
  }
  if (m.stage === "device_paired") {
    return m.block_count > 0
      ? `Paired, but nothing captured since ${ago(m.last_block_at)} — agent may be stopped`
      : "Paired, but no time captured yet — agent may not be running";
  }
  if (m.stage === "password_set") {
    return `Signed in ${ago(m.last_login)}, but never installed the desktop app`;
  }
  if (m.invite_state === "invite_expired") return "Invitation expired — resend to unblock";
  if (m.invite_state === "invite_pending")
    return `Invited ${ago(m.invite_sent_at)}, never signed in`;
  // Pre-dates link invites: issued a password by email and never used it.
  return "Never signed in — resend to send them a fresh setup link";
}

function ago(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function TeamActivation() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [resending, setResending] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // A link that could not be emailed. Held here so it can be handed over by
  // hand — with no mail provider configured this is the normal path, not an
  // error case, so the link has to be on screen rather than "in the response".
  const [handoff, setHandoff] = useState<{ email: string; url: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const d = await safeFetchJson<Payload>(`${API_BASE}/settings/team/activation/`);
      setData(d);
    } catch (e: any) {
      setErr(e?.message || "Couldn't load activation status");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function resend(m: Member) {
    setResending(m.user_id);
    setNote(null);
    try {
      const r = await safeFetchJson<any>(
        `${API_BASE}/settings/team/${m.user_id}/resend-invite/`,
        { method: "POST" }
      );
      if (r?.email_sent) {
        setNote(`New invitation sent to ${m.email}.`);
        setHandoff(null);
      } else {
        setNote(null);
        setHandoff({ email: m.email, url: r?.invite_url || "" });
      }
      load();
    } catch (e: any) {
      setHandoff(null);
      setNote(e?.message || "Couldn't resend that invitation");
    } finally {
      setResending(null);
    }
  }

  if (loading) {
    return (
      <div className="rounded-2xl border border-border/60 bg-card p-6 text-sm text-muted-foreground">
        Loading rollout status…
      </div>
    );
  }

  if (err || !data) {
    return (
      <div className="rounded-2xl border border-border/60 bg-card p-6">
        <p className="text-sm text-muted-foreground">{err || "No data"}</p>
        <button
          onClick={load}
          className="mt-3 inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-muted/50"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Retry
        </button>
      </div>
    );
  }

  const stuck = data.total - data.ready;

  return (
    <div className="rounded-2xl border border-border/60 bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div>
          <div className="text-sm font-semibold text-foreground">Rollout status</div>
          <div className="mt-0.5 text-sm text-muted-foreground">
            {data.ready} of {data.total} capturing time
            {stuck > 0 && (
              <>
                {" · "}
                <span className="font-medium text-amber-700">
                  {stuck} need{stuck === 1 ? "s" : ""} attention
                </span>
              </>
            )}
          </div>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {/* Funnel — where the firm is losing people. */}
      <div className="grid grid-cols-2 gap-px border-y border-border/60 bg-border/60 sm:grid-cols-4">
        {STAGES.map(({ key, label, icon: Icon }) => (
          <div key={key} className="bg-card px-4 py-3">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              <Icon className="h-3 w-3" />
              {label}
            </div>
            <div className="mt-1 font-mono text-[20px] font-bold tabular-nums text-foreground">
              {data.counts[key] ?? 0}
            </div>
          </div>
        ))}
      </div>

      {note && (
        <div className="border-b border-border/60 bg-muted/40 px-5 py-3 text-sm text-foreground">
          {note}
        </div>
      )}

      {handoff && (
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-amber-900">
                Invitation created — but it could not be emailed
              </p>
              <p className="mt-0.5 text-[13px] text-amber-800">
                Send this link to {handoff.email} yourself. It works once and expires in 7 days.
              </p>
            </div>
            <button
              onClick={() => setHandoff(null)}
              className="shrink-0 rounded-md px-2 py-1 text-[12px] font-medium text-amber-800 hover:bg-amber-100"
            >
              Dismiss
            </button>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <input
              readOnly
              value={handoff.url}
              onFocus={(e) => e.currentTarget.select()}
              className="min-w-0 flex-1 rounded-lg border border-amber-300 bg-card px-3 py-2 font-mono text-[12px] text-foreground"
            />
            <button
              onClick={() => {
                navigator.clipboard.writeText(handoff.url);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-300 bg-card px-3 py-2 text-[12.5px] font-semibold text-amber-900 hover:bg-amber-100"
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}

      <div className="divide-y divide-border/60">
        {data.members.map((m) => {
          const ok = m.stage === "time_flowing";
          const canResend = m.can_resend_invite;
          return (
            <div key={m.user_id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-foreground">{m.name}</span>
                  <span className="shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                    {m.role}
                  </span>
                  {m.is_you && (
                    <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                      you
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                  {!ok && <AlertTriangle className="h-3 w-3 shrink-0 text-amber-500" />}
                  {ok && <Clock className="h-3 w-3 shrink-0 text-muted-foreground/60" />}
                  <span className="truncate">{diagnose(m)}</span>
                </div>
              </div>

              <span
                className={cn(
                  "shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold",
                  STAGE_TONE[m.stage]
                )}
              >
                {STAGES.find((s) => s.key === m.stage)?.label}
              </span>

              {canResend && (
                <button
                  onClick={() => resend(m)}
                  disabled={resending === m.user_id}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12.5px] font-medium text-foreground hover:bg-muted/50 disabled:opacity-50"
                >
                  <Send className="h-3 w-3" />
                  {resending === m.user_id ? "Sending…" : "Resend invite"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
