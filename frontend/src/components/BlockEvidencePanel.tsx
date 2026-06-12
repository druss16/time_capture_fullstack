/**
 * BlockEvidencePanel.tsx
 *
 * Renders the raw events backing a block, so users can see WHY the AI
 * (or mail/calendar matcher) is suggesting a different client. Mounted
 * inside the disagreement banner cards in CategorySummary, expanded by
 * the user via "Show details."
 *
 * v0.1: adds a "Surrounding context" section for blocks with NO client —
 * shows the nearest attributed work before/after (with same-QuickBooks-
 * session detection) and a one-click assign. Helps the human attribute
 * nameless QuickBooks splash/modal blocks ("Preview Paycheck", the bare
 * product title) that the classifier correctly refused to guess on.
 *
 * Design language follows CategorySummary:
 *   - Same fmt() time formatter
 *   - Slate type scale, primary brand color for accents
 *   - Inset white card on a tinted parent (parent provides color)
 *   - Tabular nums for any time/count column
 */

import { useEffect, useState } from "react";
import { Sparkles, Mail, CalendarClock, Target, Compass, ArrowRight, Check } from "lucide-react";
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
  confidence: "high" | "medium" | "low";
  reason: string;
}

interface Surrounding {
  before: NeighborInfo | null;
  after: NeighborInfo | null;
  suggestion: ContextSuggestion | null;
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

function fmtGap(seconds: number | null): string {
  if (seconds === null) return "";
  const m = Math.round(seconds / 60);
  if (m < 1) return "<1 min";
  return `${m} min`;
}

function fmtClock(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
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

// ─── Surrounding context section ──────────────────────────────────────────────

function NeighborLine({ side, info }: { side: "Before" | "After"; info: NeighborInfo | null }) {
  if (!info) {
    return (
      <div className="flex items-baseline gap-2 text-[12px]">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-300 w-12 shrink-0">
          {side}
        </span>
        <span className="text-slate-400 italic">no attributed work nearby</span>
      </div>
    );
  }
  return (
    <div className="flex items-baseline gap-2 text-[12px]">
      <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 w-12 shrink-0">
        {side}
      </span>
      <span className="font-semibold text-slate-700 truncate">{info.client_name}</span>
      {info.same_qb_session && (
        <span className="text-[9px] font-bold uppercase tracking-wide text-emerald-600 bg-emerald-50 border border-emerald-200 rounded px-1 shrink-0">
          same QB
        </span>
      )}
      <span className="text-slate-400 shrink-0 ml-auto tabular-nums">
        {fmtClock(info.at)}{info.gap_seconds !== null && ` · ${fmtGap(info.gap_seconds)} gap`}
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
  const { before, after, suggestion } = surrounding;
  if (!before && !after) return null;

  const tierStyle = {
    high:   "bg-emerald-50 border-emerald-200 text-emerald-800",
    medium: "bg-amber-50 border-amber-200 text-amber-800",
    low:    "bg-slate-50 border-slate-200 text-slate-600",
  } as const;

  return (
    <div className="px-3 py-2.5 border-b border-slate-200/70">
      <div className="flex items-center gap-1.5 mb-2">
        <Compass className="w-3 h-3 text-slate-400" />
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
          Surrounding context
        </span>
      </div>

      <div className="space-y-1 mb-2">
        <NeighborLine side="Before" info={before} />
        <NeighborLine side="After" info={after} />
      </div>

      {suggestion && suggestion.client_id ? (
        <div className={cn("rounded-lg border px-2.5 py-2 mt-2", tierStyle[suggestion.confidence])}>
          <p className="text-[12px] leading-snug mb-2">
            <span className="font-bold">Likely {suggestion.client_name}</span>
            <span className="opacity-80"> — {suggestion.reason}</span>
          </p>
          <button
            onClick={() => onAssign(suggestion.client_id, suggestion.client_name || "")}
            disabled={assigning}
            className={cn(
              "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold transition-all",
              "bg-white/70 hover:bg-white border border-current/20 disabled:opacity-50"
            )}
          >
            {assigning
              ? <><Check className="w-3 h-3" /> Assigning…</>
              : <>Assign to {suggestion.client_name} <ArrowRight className="w-3 h-3" /></>}
          </button>
        </div>
      ) : (
        <p className="text-[11px] text-slate-400 italic mt-1.5">
          The work around this block points to different clients — no confident
          suggestion. Use the context above to decide.
        </p>
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
      // Reuse the existing recategorize endpoint. Category left undefined so
      // the backend keeps/derives it; the point here is client attribution.
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/recategorize/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId }),
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
        Loading event details…
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

      {/* ─── Time breakdown roll-up ─── */}
      {rollupEntries.length > 0 && (
        <div className="px-3 py-2.5 border-b border-slate-200/70">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">
            Time breakdown
          </div>
          <div className="space-y-1">
            {rollupEntries.map(([cid, info]) => (
              <div
                key={cid}
                className="flex items-baseline justify-between gap-2"
              >
                <span className="text-slate-700 font-medium truncate">
                  {info.name}
                </span>
                <span className="font-mono text-slate-900 tabular-nums text-xs shrink-0">
                  {fmtDuration(info.duration_seconds)}
                  <span className="text-slate-400 ml-1.5">
                    · {info.event_count} {info.event_count === 1 ? "event" : "events"}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─── Event list (chronological) ─── */}
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
                {/* Row meta: offset, duration, app */}
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

                {/* Window title (with optional highlight) */}
                <div className="text-[13px] text-slate-800 leading-snug break-words">
                  <HighlightedTitle
                    title={ev.window_title || "(no title)"}
                    position={hit?.match_position}
                  />
                </div>

                {/* Host or filename, if present */}
                {(ev.url_host || ev.file_basename) && (
                  <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                    {ev.url_host || ev.file_basename}
                  </div>
                )}

                {/* Signal chips */}
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
    </div>
  );
}