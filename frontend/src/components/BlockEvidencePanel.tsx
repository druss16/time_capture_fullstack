/**
 * BlockEvidencePanel.tsx
 *
 * Renders the raw events backing a block, so users can see WHY the AI
 * (or mail/calendar matcher) is suggesting a different client. Mounted
 * inside the disagreement banner cards in CategorySummary, and inside the
 * Categorize-tab BlockRow expansion, expanded by the user via "Show details."
 *
 * v0.2: "Surrounding context" reworked into an honest memory-jogger. Shows a
 * one-click assign ONLY for trustworthy cases (two-sided same client, or
 * same-QuickBooks-session). Weaker cases show neutral facts ("right before you
 * were on X") plus a day-dominant cue ("most of this day was Y"), never a
 * misleading "Likely X". Helps the human attribute nameless QuickBooks
 * splash/modal blocks the classifier correctly refused to guess on.
 *
 * v0.3: clues render as same-shaped cards (merged per client), and the raw
 * event list collapses to one row per distinct window with a time summary.
 *
 * Design language follows CategorySummary:
 *   - Slate type scale, primary brand color for accents
 *   - Tabular nums for any time/count column
 */

import { useEffect, useState } from "react";
import { Sparkles, Mail, CalendarClock, Target, Compass, ArrowRight, Check, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api")
  ? RAW_BASE
  : `${RAW_BASE.replace(/\/+$/, "")}/api`;


// ─── Types ────────────────────────────────────────────────────────────────────

interface Signal {
  type: "agent_selection" | "title_alias" | "domain_match" | "mail_match" | "calendar_match";
  client_id: number;
  client_name: string;
  matched_token?: string;
  match_position?: [number, number];
  confidence?: number;
  description: string;
}

interface EventRow {
  id: number;
  offset_seconds: number;
  duration_seconds: number;
  app_name: string;
  window_title: string;
  url_host: string | null;
  file_basename: string | null;
  signals: Signal[];
}

interface ClientRollup {
  name: string;
  event_count: number;
  duration_seconds: number;
}

interface NeighborInfo {
  block_id: number;
  client_id: number;
  client_name: string | null;
  at: string | null;
  gap_seconds: number | null;
  app_name: string;
  window_title: string;
  same_app: boolean;
  same_qb_session: boolean;
  category: string;
  is_billable: boolean;
}

interface ContextSuggestion {
  client_id: number;
  client_name: string | null;
  confidence: "high" | "medium";
  reason: string;
}

interface DayDominant {
  client_id: number;
  client_name: string;
  pct: number;
  minutes: number;
}

interface Surrounding {
  before: NeighborInfo | null;
  after: NeighborInfo | null;
  suggestion: ContextSuggestion | null;
  day_dominant: DayDominant | null;
}

interface MailMatch {
  client_id: number;
  client_name: string;
  count: number;
  domains: string[];
  subject: string;
}

// Gmail sends made during this block — owner-only (the server omits `mail`
// entirely for anyone but the block's own user).
interface MailCompose {
  signal_id: number;
  sent_at: string;
  to: string[];
  subject: string;
  client_id: number | null;
  client_name: string | null;
  compose_seconds: number;
  line: string;
}

interface MailPerson {
  email: string;
  name: string;
}

interface GmailMessage {
  id: number;
  occurred_at: string;
  direction: "in" | "out";
  from: MailPerson;
  to: MailPerson[];
  cc: MailPerson[];
  subject: string;
  other_party_domain: string;
  client_id: number | null;
  client_name: string | null;
  compose_seconds: number | null;
}

interface MailEvidence {
  summary: string;
  matched: MailMatch[];
  unmapped_domains: { domain: string; count: number }[];
  signal_count: number;
  window_start: string;
  window_end: string;
  // Older API builds omit these.
  compose?: MailCompose[] | undefined;
  messages?: GmailMessage[] | undefined;
}

interface EvidenceResponse {
  block: {
    id: number;
    minutes: number;
    app_name: string;
    current_client: { id: number; name: string; source: string } | null;
  };
  events: EventRow[];
  surrounding?: Surrounding | null;
  // Absent unless the viewer is the block's own user — see
  // _build_mail_evidence in views_block_evidence.py.
  mail?: MailEvidence | null;
  summary: {
    total_events: number;
    events_per_client: Record<string, ClientRollup>;
  };
}

interface Props {
  blockId: number;
  // Optional: parent can refresh its list after a successful assign.
  onAssigned?: () => void;
}


// ─── Format helpers ───────────────────────────────────────────────────────────

function fmtOffset(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `+${m}:${String(s).padStart(2, "0")}`;
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm > 0 ? `${h}h ${rm}m` : `${h}h`;
}

function fmtGapHuman(seconds: number | null): string {
  if (seconds === null) return "";
  const m = Math.round(seconds / 60);
  if (m < 1) return "less than a minute";
  if (m === 1) return "1 minute";
  if (m < 60) return `${m} minutes`;
  const h = Math.floor(m / 60), rm = m % 60;
  return rm ? `${h}h ${rm}m` : `${h}h`;
}

// Bold the matched token inside the window title without breaking layout
function HighlightedTitle({
  title,
  position,
}: {
  title: string;
  position: [number, number] | undefined;
}) {
  if (!position || position[0] < 0 || position[1] > title.length) {
    return <span>{title}</span>;
  }
  const [start, end] = position;
  return (
    <span>
      {title.slice(0, start)}
      <mark className="bg-amber-100 font-bold text-slate-900 rounded px-0.5">
        {title.slice(start, end)}
      </mark>
      {title.slice(end)}
    </span>
  );
}

// Icon picker per signal type — keeps signal chips scannable
function SignalIcon({ type }: { type: Signal["type"] }) {
  const cls = "w-2.5 h-2.5 opacity-70";
  switch (type) {
    case "agent_selection": return <Target className={cls} />;
    case "title_alias":     return <Sparkles className={cls} />;
    case "domain_match":    return <Sparkles className={cls} />;
    case "mail_match":      return <Mail className={cls} />;
    case "calendar_match":  return <CalendarClock className={cls} />;
    default: return null;
  }
}


// ─── Mail evidence ────────────────────────────────────────────────────────────
// Stage 7 works out which emails sat around this block and what they said, then
// discards that reasoning. This is it, rendered. The unmapped half matters as
// much as the matched half: mail from an unmapped domain can never attribute to
// anyone, and nothing else in the product ever mentions it.

function MailEvidenceSection({ mail }: { mail: MailEvidence }) {
  const top = mail.matched[0];

  return (
    <div className="mb-3 px-3 py-2.5 rounded-lg bg-slate-50 border border-slate-200">
      <div className="flex items-start gap-2">
        <Mail className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-slate-700">{mail.summary}</p>

          {mail.matched.length > 1 && (
            <p className="text-slate-500 mt-1">
              Also in this window:{" "}
              {mail.matched.slice(1).map((m) => `${m.client_name} (${m.count})`).join(", ")}
            </p>
          )}

          {mail.unmapped_domains.length > 0 && (
            <p className="text-slate-500 mt-1">
              {top ? "Not mapped to any client: " : "From: "}
              {mail.unmapped_domains.map((u) => u.domain).join(", ")}
              {!top && " — mail from these can't point at a client until someone maps them."}
            </p>
          )}

          {/* Gmail sends in this block: "Emailed jane@acme.com — ~6 min composing". */}
          {(mail.compose?.length ?? 0) > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {mail.compose!.map((c) => (
                <li key={c.signal_id} className="text-slate-600">
                  {c.line}
                  {c.client_name && <span className="text-slate-500"> → {c.client_name}</span>}
                  {c.subject && <span className="text-slate-400"> · “{c.subject}”</span>}
                </li>
              ))}
            </ul>
          )}

          {/* Other Gmail messages around this time (only visible to you). */}
          {(mail.messages?.length ?? 0) > 0 && (
            <details className="mt-1.5">
              <summary className="text-slate-500 cursor-pointer select-none">
                {mail.messages!.length} Gmail message{mail.messages!.length !== 1 ? "s" : ""} around this time
                <span className="text-slate-400"> · only you can see these</span>
              </summary>
              <ul className="mt-1 space-y-0.5">
                {mail.messages!.map((m) => {
                  const who = m.direction === "in"
                    ? `From ${m.from.name || m.from.email}`
                    : `To ${m.to.map((p) => p.email).join(", ") || m.other_party_domain}`;
                  return (
                    <li key={m.id} className="text-slate-600 truncate">
                      {new Date(m.occurred_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}{" "}
                      {who}
                      {m.subject && <span className="text-slate-400"> · “{m.subject}”</span>}
                      {m.client_name && <span className="text-slate-500"> → {m.client_name}</span>}
                    </li>
                  );
                })}
              </ul>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}


// ─── Surrounding context section (v0.3 — clue cards) ─────────────────────────
// Every clue (best guess, before, after, most-of-day) renders as the same card
// shape side by side, so the choice reads as "pick one of these" instead of a
// stack of differently styled sentences. Clues naming the same client merge
// into one card carrying every reason.

interface Clue {
  client_id: number;
  client_name: string;
  labels: string[];
  billable: boolean | null;
  category?: string | undefined;
  strong: boolean;
}

function buildClues(s: Surrounding): Clue[] {
  const clues: Clue[] = [];
  const add = (c: Omit<Clue, "labels"> & { label: string }) => {
    const hit = clues.find((x) => x.client_id === c.client_id);
    if (hit) {
      hit.labels.push(c.label);
      hit.strong = hit.strong || c.strong;
      if (hit.billable === null) hit.billable = c.billable;
      hit.category = hit.category ?? c.category;
      return;
    }
    const { label, ...rest } = c;
    clues.push({ ...rest, labels: [label] });
  };
  if (s.suggestion?.client_id) {
    add({
      client_id: s.suggestion.client_id, client_name: s.suggestion.client_name || "",
      label: "Best guess", billable: null, strong: true,
    });
  }
  for (const side of ["before", "after"] as const) {
    const n = s[side];
    if (!n?.client_id) continue;
    const gap = n.gap_seconds !== null ? `${fmtGapHuman(n.gap_seconds)} ` : "";
    add({
      client_id: n.client_id, client_name: n.client_name || "",
      label: side === "before" ? `${gap}before` : `${gap}after`,
      billable: n.is_billable, category: n.category, strong: false,
    });
  }
  if (s.day_dominant) {
    add({
      client_id: s.day_dominant.client_id, client_name: s.day_dominant.client_name,
      label: `${s.day_dominant.pct}% of your day`, billable: null, strong: false,
    });
  }
  // A client that shows up for several reasons is the stronger clue.
  return clues.sort((a, b) => Number(b.strong) - Number(a.strong) || b.labels.length - a.labels.length);
}

function SurroundingContext({
  surrounding,
  onAssign,
  assigning,
}: {
  surrounding: Surrounding;
  onAssign: (clientId: number, clientName: string, category?: string) => void;
  assigning: boolean;
}) {
  const clues = buildClues(surrounding);
  if (clues.length === 0) return null;

  return (
    <div className="border-b border-slate-200/70 px-3 py-3">
      <div className="mb-2 flex items-center gap-1.5">
        <Compass className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
          Clues from around this time
        </span>
        <span className="truncate text-[11px] text-slate-400">&middot; no client name in the block itself</span>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {clues.map((c) => (
          <button
            key={c.client_id}
            onClick={() => onAssign(c.client_id, c.client_name, c.category)}
            disabled={assigning}
            title={`Assign to ${c.client_name}`}
            className={cn(
              "group flex min-w-0 flex-col items-start gap-1 rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-50",
              c.strong
                ? "border-emerald-300 bg-emerald-50 hover:bg-emerald-100/70"
                : "border-slate-200 bg-white hover:border-emerald-300 hover:bg-emerald-50/60",
            )}
          >
            <div className="flex w-full flex-wrap gap-1">
              {c.labels.map((l) => (
                <span key={l} className={cn(
                  "rounded px-1.5 py-px text-[10px] font-semibold",
                  l === "Best guess" ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-500",
                )}>
                  {l}
                </span>
              ))}
            </div>
            <span className="w-full truncate text-[13px] font-semibold text-slate-800">{c.client_name}</span>
            <span className="flex w-full items-center justify-between text-[11px]">
              <span className="text-slate-400">
                {c.billable === null ? "\u00a0" : c.billable ? "billable" : "non-billable"}
              </span>
              <span className="inline-flex items-center gap-0.5 font-semibold text-emerald-700 opacity-60 transition-opacity group-hover:opacity-100">
                Use <ArrowRight className="h-3 w-3" />
              </span>
            </span>
          </button>
        ))}
      </div>

      {surrounding.suggestion?.reason && (
        <p className="mt-2 text-[11px] leading-snug text-slate-500">
          <span className="font-semibold text-slate-600">Why the best guess:</span> {surrounding.suggestion.reason}
        </p>
      )}
    </div>
  );
}


// ─── Activity digest ──────────────────────────────────────────────────────────
// The raw list repeated app name, title and host on three lines per event, so
// a 15-event block scrolled forever and repeats of one window read as new work.
// Instead: a one-line "where the time went" summary, then one row per distinct
// window (same app + title + host), in the order first seen.

interface ActivityGroup {
  key: string;
  first_offset: number;
  duration_seconds: number;
  app_name: string;
  title: string;
  where: string | null;
  signals: Signal[];
  hit: Signal | undefined;
}

function groupEvents(events: EventRow[]): ActivityGroup[] {
  const groups = new Map<string, ActivityGroup>();
  for (const ev of events) {
    const where = ev.url_host || ev.file_basename;
    const key = `${ev.app_name}\u0000${ev.window_title}\u0000${where ?? ""}`;
    const g = groups.get(key);
    const hit = ev.signals.find((s) => s.type === "title_alias" && s.match_position);
    if (g) {
      g.duration_seconds += ev.duration_seconds;
      for (const s of ev.signals) {
        if (!g.signals.some((x) => x.type === s.type && x.client_id === s.client_id)) g.signals.push(s);
      }
      g.hit = g.hit ?? hit;
    } else {
      groups.set(key, {
        key, first_offset: ev.offset_seconds, duration_seconds: ev.duration_seconds,
        app_name: ev.app_name, title: ev.window_title || "(no title)", where,
        signals: [...ev.signals], hit,
      });
    }
  }
  return [...groups.values()].sort((a, b) => a.first_offset - b.first_offset);
}

// Top places (site, file or app) by time, for the one-line summary.
function topPlaces(events: EventRow[], n = 3): { name: string; seconds: number }[] {
  const by = new Map<string, number>();
  for (const ev of events) {
    const name = ev.url_host || ev.file_basename || ev.app_name || "Unknown";
    by.set(name, (by.get(name) ?? 0) + ev.duration_seconds);
  }
  return [...by.entries()]
    .map(([name, seconds]) => ({ name, seconds }))
    .sort((a, b) => b.seconds - a.seconds)
    .slice(0, n);
}

function SignalChip({ sig }: { sig: Signal }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[10px] font-semibold",
        sig.type === "agent_selection"
          ? "border-slate-200 bg-slate-100 text-slate-600"
          : "border-amber-200 bg-amber-50 text-amber-800",
      )}
      title={sig.description}
    >
      <SignalIcon type={sig.type} />
      <span className="max-w-[140px] truncate">{sig.client_name}</span>
      {sig.confidence !== undefined && (
        <span className="tabular-nums opacity-60">{Math.round(sig.confidence * 100)}%</span>
      )}
    </span>
  );
}


// ─── Component ────────────────────────────────────────────────────────────────

export function BlockEvidencePanel({ blockId, onAssigned }: Props) {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [assignedTo, setAssignedTo] = useState<string | null>(null);
  const [showEvents, setShowEvents] = useState(false);
  const [showAllGroups, setShowAllGroups] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    safeFetchJson<EvidenceResponse>(`${API_BASE}/blocks/${blockId}/evidence/`)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err: any) => {
        if (!cancelled) {
          setError(err?.message || "Failed to load");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [blockId]);

const handleAssign = async (clientId: number, clientName: string, category?: string) => {
    setAssigning(true);
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/recategorize/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          category: category || "Accounting/Bookkeeping",
        }),
      });
      setAssignedTo(clientName);
      if (onAssigned) onAssigned();
    } catch (err: any) {
      setError(err?.message || "Failed to assign");
    } finally {
      setAssigning(false);
    }
  };

  if (loading) {
    return (
      <div className="px-3 py-4 text-xs text-slate-400 italic">
        Loading event details&hellip;
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-3 py-3 text-xs text-rose-600">
        Could not load details: {error}
      </div>
    );
  }

  if (!data) return null;

  // Post-assign confirmation — keep the panel calm, just acknowledge.
  if (assignedTo) {
    return (
      <div className="px-3 py-3 flex items-center gap-2 text-[13px] text-emerald-700">
        <Check className="w-4 h-4" />
        Assigned to <span className="font-semibold">{assignedTo}</span>.
      </div>
    );
  }

  const groups = groupEvents(data.events);
  const places = topPlaces(data.events);
  const totalSeconds = data.events.reduce((t, e) => t + e.duration_seconds, 0);
  const rollupEntries = Object.values(data.summary.events_per_client)
    .sort((a, b) => b.duration_seconds - a.duration_seconds);
  // Don't hide a single straggler behind a "show all" click.
  const VISIBLE = 6;
  const collapsible = groups.length > VISIBLE + 2;
  const shownGroups = showAllGroups || !collapsible ? groups : groups.slice(0, VISIBLE);

  return (
    <div className="text-[13px]">
      {/* ─── What the mailbox saw around this block (own user only) ─── */}
      {data.mail && <MailEvidenceSection mail={data.mail} />}

      {/* ─── Surrounding context (only present for nameless / no-client blocks) ─── */}
      {data.surrounding && (
        <SurroundingContext
          surrounding={data.surrounding}
          onAssign={handleAssign}
          assigning={assigning}
        />
      )}

      {/* ─── Activity: collapsed by default. The clues above are what the
            user decides from; this is reference, one row per distinct window. ─── */}
      {data.events.length > 0 && (
        <div>
          <button
            onClick={(e) => { e.stopPropagation(); setShowEvents((v) => !v); }}
            className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[11px] text-slate-400 transition-colors hover:text-slate-600"
          >
            {showEvents ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
            <span className="font-semibold">{showEvents ? "Hide activity" : "What you were doing"}</span>
            <span className="truncate">
              &middot; {groups.length} {groups.length === 1 ? "window" : "windows"}
              {places.length > 0 && <> &middot; mostly {places[0].name}</>}
            </span>
          </button>

          {showEvents && (
            <div className="px-3 pb-3">
              {/* Where the time went: a proportional strip plus legend. */}
              {totalSeconds > 0 && (
                <div className="mb-3">
                  {places.length > 1 && <div className="flex h-1.5 overflow-hidden rounded-full bg-slate-100">
                    {places.map((p, i) => (
                      <div
                        key={p.name}
                        className={["bg-slate-500", "bg-slate-400", "bg-slate-300"][i]}
                        style={{ width: `${(p.seconds / totalSeconds) * 100}%` }}
                      />
                    ))}
                  </div>}
                  <div className={cn("flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500", places.length > 1 && "mt-1.5")}>
                    {places.map((p, i) => (
                      <span key={p.name} className="inline-flex items-center gap-1">
                        <span className={cn("h-1.5 w-1.5 rounded-full", ["bg-slate-500", "bg-slate-400", "bg-slate-300"][i])} />
                        <span className="font-mono">{p.name}</span>
                        <span className="tabular-nums text-slate-400">{fmtDuration(p.seconds)}</span>
                      </span>
                    ))}
                    {rollupEntries.length > 0 && (
                      <span className="inline-flex items-center gap-1">
                        <span className="text-slate-400">client names seen:</span>
                        {rollupEntries.map((r) => (
                          <span key={r.name} className="font-semibold text-slate-600">
                            {r.name} <span className="font-normal tabular-nums text-slate-400">{fmtDuration(r.duration_seconds)}</span>
                          </span>
                        ))}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* One row per distinct window, in the order first seen. */}
              <ol className="divide-y divide-slate-100 rounded-md border border-slate-200/70">
                {shownGroups.map((g) => (
                  <li key={g.key} className="flex items-start gap-3 px-2.5 py-1.5">
                    <span className="w-11 shrink-0 pt-px font-mono text-[10.5px] tabular-nums text-slate-400">
                      {fmtOffset(g.first_offset)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-baseline gap-2">
                        <span className="truncate text-[13px] text-slate-800" title={g.title}>
                          <HighlightedTitle title={g.title} position={g.hit?.match_position} />
                        </span>
                        <span className="shrink-0 truncate font-mono text-[10.5px] text-slate-400">
                          {g.where || g.app_name}
                        </span>
                      </div>
                      {g.signals.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {g.signals.map((sig, i) => <SignalChip key={i} sig={sig} />)}
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 pt-px text-right font-mono text-[11px] tabular-nums text-slate-600">
                      {fmtDuration(g.duration_seconds)}
                    </span>
                  </li>
                ))}
              </ol>
              {collapsible && (
                <button
                  onClick={(e) => { e.stopPropagation(); setShowAllGroups((v) => !v); }}
                  className="mt-1.5 text-[11px] font-semibold text-slate-400 hover:text-slate-600"
                >
                  {showAllGroups ? "Show fewer" : `Show all ${groups.length} windows`}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}