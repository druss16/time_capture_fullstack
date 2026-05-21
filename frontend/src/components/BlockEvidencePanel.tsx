/**
 * BlockEvidencePanel.tsx
 *
 * Renders the raw events backing a block, so users can see WHY the AI
 * (or mail/calendar matcher) is suggesting a different client. Mounted
 * inside the disagreement banner cards in CategorySummary, expanded by
 * the user via "Show details."
 *
 * Design language follows CategorySummary:
 *   - Same fmt() time formatter
 *   - Slate type scale, primary brand color for accents
 *   - Inset white card on a tinted parent (parent provides color)
 *   - Tabular nums for any time/count column
 */

import { useEffect, useState } from "react";
import { Sparkles, Mail, CalendarClock, Target } from "lucide-react";
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

interface EvidenceResponse {
  block: {
    id: number;
    minutes: number;
    app_name: string;
    current_client: { id: number; name: string; source: string } | null;
  };
  events: EventRow[];
  summary: {
    total_events: number;
    events_per_client: Record<string, ClientRollup>;
  };
}

interface Props {
  blockId: number;
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

// ─── Component ────────────────────────────────────────────────────────────────

export function BlockEvidencePanel({ blockId }: Props) {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  // Find the strongest title-alias signal per event for inline highlighting
  const titleHit = (signals: Signal[]) =>
    signals.find((s) => s.type === "title_alias" && s.match_position);

  // Sort the time-breakdown summary by duration descending
  const rollupEntries = Object.entries(data.summary.events_per_client)
    .sort(([, a], [, b]) => b.duration_seconds - a.duration_seconds);

  return (
    <div className="text-[13px]">
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