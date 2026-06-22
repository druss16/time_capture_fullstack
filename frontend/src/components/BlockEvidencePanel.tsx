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

interface EvidenceResponse {
  block: {
    id: number;
    minutes: number;
    app_name: string;
    current_client: { id: number; name: string; source: string } | null;
  };
  events: EventRow[];
  surrounding?: Surrounding | null;
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


// ─── Surrounding context section (v0.2 — honest memory-jogger) ────────────────

function NeighborFact({ side, info }: { side: "before" | "after"; info: NeighborInfo | null }) {
  const label = side === "before" ? "Right before" : "Right after";
  if (!info) {
    return (
      <div className="flex gap-2 text-[12px] py-0.5">
        <span className="text-slate-400 w-24 shrink-0">{label}</span>
        <span className="text-slate-400 italic">nothing else tracked nearby</span>
      </div>
    );
  }
  return (
    <div className="flex gap-2 text-[12px] py-0.5">
      <span className="text-slate-500 w-24 shrink-0">{label}</span>
      <span className="text-slate-700">
        <span className="font-semibold">{info.client_name}</span>
        {info.window_title ? <span className="text-slate-500"> — {info.window_title}</span> : null}
        {info.gap_seconds !== null && (
          <span className="text-slate-400"> ({fmtGapHuman(info.gap_seconds)} {side === "before" ? "earlier" : "later"})</span>
        )}
      </span>
    </div>
  );
}

function SurroundingContext({
  surrounding,
  onAssign,
  assigning,
}: {
  surrounding: Surrounding;
  onAssign: (clientId: number, clientName: string) => void;
  assigning: boolean;
}) {
  const { before, after, suggestion, day_dominant } = surrounding;
  if (!before && !after && !day_dominant) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2.5 my-2">
      {/* Plain-English explanation of what this is */}
      <div className="flex items-start gap-1.5 mb-2">
        <Compass className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
        <p className="text-[11px] text-slate-500 leading-snug">
          We couldn&rsquo;t automatically tell which client this block belongs to.
          Here&rsquo;s what you were doing around it &mdash; to help you remember.
        </p>
      </div>

      {/* Trustworthy suggestion → offer a one-click assign */}
      {suggestion && suggestion.client_id && (
        <div className={cn(
          "rounded-md border px-2.5 py-2 mb-2",
          suggestion.confidence === "high"
            ? "bg-emerald-50 border-emerald-200"
            : "bg-amber-50 border-amber-200",
        )}>
          <p className="text-[12px] leading-snug mb-1.5 text-slate-700">
            <span className="font-bold">Best guess: {suggestion.client_name}</span>
            <span className="text-slate-600"> &mdash; {suggestion.reason}</span>
          </p>
          <button
            onClick={() => onAssign(suggestion.client_id, suggestion.client_name || "")}
            disabled={assigning}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold
                       bg-white border border-slate-300 hover:bg-slate-50 disabled:opacity-50 transition-colors"
          >
            {assigning
              ? <><Check className="w-3 h-3" /> Assigning&hellip;</>
              : <>Assign to {suggestion.client_name} <ArrowRight className="w-3 h-3" /></>}
          </button>
        </div>
      )}

      {/* Neutral before/after facts — always shown, never misleading */}
      <div className="mb-1">
        <NeighborFact side="before" info={before} />
        <NeighborFact side="after" info={after} />
      </div>

      {/* Day-dominant cue — only present when one client owned the majority of the day */}
      {day_dominant && (
        <div className="mt-2 pt-2 border-t border-slate-200/70">
          <p className="text-[12px] text-slate-600 leading-snug">
            <span className="text-slate-400">Most of this day </span>
            (<span className="font-semibold tabular-nums">{day_dominant.pct}%</span>)
            <span className="text-slate-400"> was spent on </span>
            <span className="font-semibold text-slate-700">{day_dominant.client_name}</span>
            <span className="text-slate-400">, if that helps narrow it down.</span>
          </p>
          {/* Only offer the day-dominant as a click if there was NO better suggestion */}
          {!suggestion && (
            <button
              onClick={() => onAssign(day_dominant.client_id, day_dominant.client_name)}
              disabled={assigning}
              className="mt-1.5 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold
                         bg-white border border-slate-300 hover:bg-slate-50 disabled:opacity-50 transition-colors"
            >
              Assign to {day_dominant.client_name} <ArrowRight className="w-3 h-3" />
            </button>
          )}
        </div>
      )}
    </div>
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

  const handleAssign = async (clientId: number, clientName: string) => {
    setAssigning(true);
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/recategorize/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          category: "Accounting/Bookkeeping",   // QB work default; user can edit after
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

  // Find the strongest title-alias signal per event for inline highlighting
  const titleHit = (signals: Signal[]) =>
    signals.find((s) => s.type === "title_alias" && s.match_position);

  // Sort the time-breakdown summary by duration descending
  const rollupEntries = Object.entries(data.summary.events_per_client)
    .sort(([, a], [, b]) => b.duration_seconds - a.duration_seconds);

  return (
    <div className="text-[13px]">
      {/* ─── Surrounding context (only present for nameless / no-client blocks) ─── */}
      {data.surrounding && (
        <SurroundingContext
          surrounding={data.surrounding}
          onAssign={handleAssign}
          assigning={assigning}
        />
      )}

      {/* ─── Activity detail: collapsed by default. The surrounding-context
            clue above is what the user needs to decide; the raw event list is
            reference, shown only on request so the card stays scannable. ─── */}
      {(rollupEntries.length > 0 || data.events.length > 0) && (
        <div>
          <button
            onClick={(e) => { e.stopPropagation(); setShowEvents((v) => !v); }}
            className="w-full flex items-center gap-1.5 px-3 py-2 text-[11px] font-semibold
                       text-slate-400 hover:text-slate-600 transition-colors"
          >
            {showEvents ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            {showEvents ? "Hide activity" : `Show activity (${data.summary.total_events} ${data.summary.total_events === 1 ? "event" : "events"})`}
          </button>

          {showEvents && (
            <>
              {/* Time breakdown roll-up */}
              {rollupEntries.length > 0 && (
                <div className="px-3 py-2.5 border-b border-slate-200/70">
                  <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">
                    Time breakdown
                  </div>
                  <div className="space-y-1">
                    {rollupEntries.map(([cid, info]) => (
                      <div key={cid} className="flex items-baseline justify-between gap-2">
                        <span className="text-slate-700 font-medium truncate">{info.name}</span>
                        <span className="font-mono text-slate-900 tabular-nums text-xs shrink-0">
                          {fmtDuration(info.duration_seconds)}
                          <span className="text-slate-400 ml-1.5">
                            &middot; {info.event_count} {info.event_count === 1 ? "event" : "events"}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Event list (chronological) */}
              {data.events.length === 0 ? (
                <div className="px-3 py-4 text-xs text-slate-400 text-center italic">
                  No events recorded for this block.
                </div>
              ) : (
                <ol className="divide-y divide-slate-200/70">
                  {data.events.map((ev) => {
                    const hit = titleHit(ev.signals);
                    return (
                      <li key={ev.id} className="px-3 py-2.5">
                        <div className="flex items-baseline gap-2 mb-1">
                          <span className="font-mono text-[10px] text-slate-500 tabular-nums shrink-0">
                            {fmtOffset(ev.offset_seconds)}
                          </span>
                          <span className="font-mono text-[10px] text-slate-400 tabular-nums shrink-0">
                            ({fmtDuration(ev.duration_seconds)})
                          </span>
                          <span className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">
                            {ev.app_name}
                          </span>
                        </div>
                        <div className="text-[13px] text-slate-800 leading-snug break-words">
                          <HighlightedTitle
                            title={ev.window_title || "(no title)"}
                            position={hit?.match_position}
                          />
                        </div>
                        {(ev.url_host || ev.file_basename) && (
                          <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                            {ev.url_host || ev.file_basename}
                          </div>
                        )}
                        {ev.signals.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {ev.signals.map((sig, idx) => (
                              <span
                                key={idx}
                                className={cn(
                                  "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-[10px] font-semibold",
                                  sig.type === "agent_selection"
                                    ? "bg-slate-100 text-slate-600 border-slate-200"
                                    : "bg-amber-50 text-amber-800 border-amber-200"
                                )}
                                title={sig.description}
                              >
                                <SignalIcon type={sig.type} />
                                <span className="truncate max-w-[160px]">{sig.client_name}</span>
                                {sig.confidence !== undefined && (
                                  <span className="opacity-60 tabular-nums">
                                    {Math.round(sig.confidence * 100)}%
                                  </span>
                                )}
                              </span>
                            ))}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}