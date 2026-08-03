/**
 * CompactSummary.tsx — the Daily Review "confidence lanes" body.
 *
 * Two lanes, computed upstream by deriveLanes() so the page header and this body
 * never disagree:
 *
 *   CERTAIN   — everything auto-filed. Collapsed to one line by default; "Browse
 *               these" opens a filterable, client-grouped audit trail. No green
 *               buttons here — a finished lane is done, not pending.
 *   NEEDS YOU — always open, always visible. Two row types:
 *                 • pending   — pick a client / one-tap accept the guess
 *                 • mismatch  — title names a different client than booked; the
 *                               fix ("Move to X") is the primary action, in red.
 *
 * Visual grammar (load-bearing — see spec):
 *   green = action required · grey+past-tense = done · red = contradiction ·
 *   amber = unassigned · mono = text captured off screen · sans = product voice ·
 *   every triage row leads with its minutes.
 */
import { useState, useEffect, useMemo, useCallback } from "react";
import { ChevronRight, ChevronDown, Check, X, Search } from "lucide-react";
import { cn } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";
import { MovePopover, type ClientOption, type ProposedInline } from "@/components/CategorySummary";
import type { Lanes, CertainGroup, MismatchBlock } from "@/lib/dailyReviewLanes";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type Props = {
  lanes: Lanes;
  availableClients: ClientOption[];
  availableCategories: string[];
  busy: boolean;
  /** Whether the auto-file pass has run — tunes the Certain lane's subtitle. */
  autoFiled: boolean;
  onRefresh: () => void;
  showToast: (msg: string, type: "success" | "error") => void;
  /** Dismiss a mismatch flag as a false positive ("Keep here"). */
  onIgnoreMismatch: (ids: number[]) => void;
};

function useSystemDark(): boolean {
  const [dark, setDark] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia
      && window.matchMedia("(prefers-color-scheme: dark)").matches
  );
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const h = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, []);
  return dark;
}

type MoveState = {
  anchor: HTMLElement;
  ids: number[];
  currentClientId: number | null;
  currentCategory: string;
  label: string;
  suggestClientId?: number | null;
};

export default function CompactSummary({
  lanes, availableClients, availableCategories, busy,
  autoFiled, onRefresh, showToast, onIgnoreMismatch,
}: Props) {
  const sysDark = useSystemDark();
  const { certain, needsYou } = lanes;

  const [certainOpen, setCertainOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [move, setMove] = useState<MoveState | null>(null);

  const catList = availableCategories.length ? availableCategories : ["General Client Work"];

  const toggleGroup = (key: string) =>
    setOpenGroups((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  const openMove = (
    anchor: HTMLElement, ids: number[], clientId: number | null, category: string,
    label: string, suggestClientId: number | null = null,
  ) => setMove({ anchor, ids, currentClientId: clientId, currentCategory: category, label, suggestClientId });

  // ── Mutations (both hit the shared recategorize endpoint) ───────────────────
  const recategorize = (id: number, clientId: number | null, category: string, source?: string) =>
    safeFetchJson(`${API_BASE}/blocks/${id}/recategorize/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, client_id: clientId, ...(source ? { source } : {}) }),
    });

  const moveBlocks = useCallback(async (ids: number[], clientId: number | null, category: string) => {
    if (!ids.length) return;
    try {
      await Promise.all(ids.map((id) => recategorize(id, clientId, category)));
      showToast(`Moved ${ids.length} ${ids.length > 1 ? "entries" : "entry"}`, "success");
      onRefresh();
    } catch { showToast("Failed to move", "error"); }
  }, [onRefresh, showToast]);

  // Accept a pending row to a client — or to NO client (null = not billable).
  const acceptTo = useCallback(async (b: ProposedInline, clientId: number | null) => {
    try {
      await recategorize(b.block_id, clientId, b.proposed_category || "General Client Work", "single_confirm");
      showToast(clientId == null ? "Set to not billable" : "Confirmed", "success");
      onRefresh();
    } catch { showToast("Couldn’t update this entry", "error"); }
  }, [onRefresh, showToast]);

  // One-click mismatch fix: reassign to the client the title actually names,
  // preserving the block's category.
  const fixMismatch = useCallback(async (m: MismatchBlock) => {
    if (m.looks_like_client_id == null) return;
    try {
      await recategorize(m.block_id, m.looks_like_client_id, m.category || "General Client Work");
      showToast(`Moved to ${m.looks_like_client_name}`, "success");
      onRefresh();
    } catch { showToast("Failed to move", "error"); }
  }, [onRefresh, showToast]);

  // ── Certain lane: filter groups + rows by the query ─────────────────────────
  const q = filter.trim().toLowerCase();
  const filteredGroups = useMemo(() => {
    if (!q) return certain.groups;
    return certain.groups
      .map((g) => {
        if (g.name.toLowerCase().includes(q)) return g;
        const rows = g.rows.filter((r) => r.title.toLowerCase().includes(q));
        return rows.length ? { ...g, rows } : null;
      })
      .filter(Boolean) as CertainGroup[];
  }, [certain.groups, q]);

  return (
    <div className={cn(sysDark && "dark")}>
      <div className="mx-auto flex max-w-3xl flex-col gap-3 text-foreground">

        {/* ═══ CERTAIN ═════════════════════════════════════════════════════════ */}
        <section className="overflow-hidden rounded-xl border border-emerald-500/25 bg-emerald-500/5">
          <button
            onClick={() => setCertainOpen((v) => !v)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-emerald-500/10">
            <ChevronRight className={cn("h-4 w-4 shrink-0 text-emerald-600 transition-transform dark:text-emerald-400", certainOpen && "rotate-90")} />
            <span className="font-sans text-[15px] font-bold text-emerald-700 dark:text-emerald-300">Certain</span>
            <span className="truncate font-mono text-[12px] text-muted-foreground">
              {certain.blockCount} blocks · {fmtMin(certain.minutes)} · {autoFiled ? "auto-filed, exact client match" : "exact client match"}
            </span>
            <span className="flex-1" />
            <span className="shrink-0 rounded-md border border-border bg-card px-3 py-1 font-sans text-[12px] font-medium text-muted-foreground">
              {certainOpen ? "Hide" : "Browse these"}
            </span>
          </button>

          {certainOpen && (
            <div className="border-t border-emerald-500/20 bg-card px-3 pb-3 pt-3">
              {/* Filter box — 17+ rows is past scanning range. */}
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
                <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={`Filter these ${certain.blockCount} blocks…`}
                  className="w-full bg-transparent font-sans text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none" />
                {filter && (
                  <button onClick={() => setFilter("")} className="shrink-0 text-muted-foreground hover:text-foreground">
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              {filteredGroups.length === 0 && (
                <div className="py-6 text-center font-mono text-[12px] text-muted-foreground">no matches</div>
              )}

              <div className="flex flex-col divide-y divide-border">
                {filteredGroups.map((g) => {
                  const open = openGroups.has(g.key) || !!q;
                  const allIds = g.rows.flatMap((r) => r.ids);
                  return (
                    <div key={g.key}>
                      <div className="group flex items-center gap-2 py-2">
                        <button onClick={() => toggleGroup(g.key)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                          <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
                          <span className={cn("truncate font-sans text-[14px] font-semibold",
                            g.unassigned ? "italic text-muted-foreground" : g.internal ? "text-muted-foreground" : "text-foreground")}>
                            {g.name}
                          </span>
                        </button>
                        <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{g.blockCount} blocks</span>
                        <span className="shrink-0 font-mono text-[12px] font-semibold tabular-nums text-foreground">{fmtMin(g.minutes)}</span>
                        <button
                          onClick={(e) => openMove(e.currentTarget, allIds, g.clientId, g.repCategory, `Move · ${g.name}`)}
                          className="shrink-0 rounded-md px-2 py-0.5 font-sans text-[12px] font-medium text-primary underline-offset-2 hover:underline">
                          Move
                        </button>
                      </div>
                      {open && (
                        <div className="mb-1 flex flex-col gap-0.5 pb-2 pl-6">
                          {g.rows.map((r, i) => (
                            <div key={i} className="flex items-center gap-3 py-0.5">
                              <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground">{r.title}</span>
                              <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/70">{fmtMin(r.minutes)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        {/* ═══ NEEDS YOU ═══════════════════════════════════════════════════════ */}
        <section className={cn(
          "overflow-hidden rounded-xl border",
          needsYou.count > 0 ? "border-amber-500/40 bg-amber-500/[0.06]" : "border-teal-500/30 bg-teal-500/[0.06]",
        )}>
          <div className="flex items-center gap-3 px-4 py-3">
            <span className={cn("font-sans text-[15px] font-bold",
              needsYou.count > 0 ? "text-amber-700 dark:text-amber-300" : "text-teal-700 dark:text-teal-300")}>
              Needs you
            </span>
            {needsYou.count > 0 ? (
              <span className="font-mono text-[12px] text-muted-foreground">
                {needsYou.count} {needsYou.count === 1 ? "item" : "items"} · {fmtMin(needsYou.minutes)}
              </span>
            ) : (
              <span className="font-mono text-[12px] text-muted-foreground">nothing — you’re done</span>
            )}
          </div>

          {needsYou.count > 0 && (
            <div className="flex flex-col gap-px bg-border">
              {/* Unassigned + pending, then mismatches — each block already minutes-desc. */}
              {needsYou.pending.map((b) => (
                <PendingRow
                  key={`p${b.block_id}`} b={b} busy={busy}
                  onAccept={(cid) => acceptTo(b, cid)}
                  onNotBillable={() => acceptTo(b, null)}
                  onPick={(anchor) => openMove(anchor, [b.block_id], null, b.proposed_category || catList[0], "Pick a client")}
                  onChange={(anchor) => openMove(anchor, [b.block_id], b.proposed_client_id, b.proposed_category || catList[0], "Change client", b.proposed_client_id)}
                />
              ))}
              {needsYou.mismatch.map((m) => (
                <MismatchRow
                  key={`m${m.block_id}`} m={m} busy={busy}
                  onFix={() => fixMismatch(m)}
                  onKeep={() => onIgnoreMismatch([m.block_id])}
                  onPick={(anchor) => openMove(anchor, [m.block_id], m.booked_client_id, m.category || catList[0], "Move to…", m.looks_like_client_id)}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      {move && (
        <MovePopover
          anchorEl={move.anchor}
          clients={availableClients}
          categories={catList}
          currentClientId={move.currentClientId}
          currentCategory={move.currentCategory}
          label={move.label}
          suggestClientId={move.suggestClientId ?? null}
          onApply={(clientId, category) => { moveBlocks(move.ids, clientId, category); setMove(null); }}
          onClose={() => setMove(null)}
        />
      )}
    </div>
  );
}

// ── Needs-you rows ──────────────────────────────────────────────────────────

type WhyData = {
  explanation: string;
  suggested_client_id: number | null;
  suggested_client_name: string | null;
  personal?: boolean;
};

/** Pending: accept the green suggested client in one tap (with the contextual
 *  reason from /why/), or pick a client / mark not billable when there's no guess. */
function PendingRow({ b, busy, onAccept, onNotBillable, onPick, onChange }: {
  b: ProposedInline;
  busy: boolean;
  onAccept: (clientId: number) => void;
  onNotBillable: () => void;
  onPick: (anchor: HTMLElement) => void;
  onChange: (anchor: HTMLElement) => void;
}) {
  // Load the explanation + contextual suggestion so the reason line and the
  // green best-guess button are visible without expanding anything.
  const [why, setWhy] = useState<WhyData | null>(null);
  useEffect(() => {
    let alive = true;
    safeFetchJson<WhyData>(`${API_BASE}/blocks/${b.block_id}/why/`)
      .then((w) => { if (alive) setWhy(w); })
      .catch(() => { if (alive) setWhy(null); });
    return () => { alive = false; };
  }, [b.block_id]);

  // Best guess = classifier's proposed client, else the contextual suggestion.
  const guessId = b.proposed_client_id ?? why?.suggested_client_id ?? null;
  const guessName = b.proposed_client_name ?? why?.suggested_client_name ?? null;
  // Prefer the friendly /why/ explanation ("Right before this, you were working
  // on X") over the raw classifier reasoning ("second-pass: unrecognized").
  const reason = (why?.explanation || b.proposed_reasoning || "").trim();

  // Soft green pill = suggested client (leads, but calm). Neutral outline = secondary.
  const green = "inline-flex max-w-[200px] items-center gap-1 rounded-full border border-primary/40 bg-primary/15 px-2.5 py-0.5 font-sans text-[11px] font-semibold text-primary transition-colors hover:bg-primary/25 disabled:opacity-50";
  const ghost = "inline-flex items-center gap-0.5 rounded-full border border-border bg-muted/60 px-2.5 py-0.5 font-sans text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-primary disabled:opacity-50";

  return (
    <div className="flex items-start gap-3 bg-card px-4 py-3">
      <span className="mt-0.5 shrink-0 font-mono text-[11px] font-semibold tabular-nums text-muted-foreground">{fmtMin(b.minutes || 0)}</span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-[12.5px] text-foreground">{b.window_title || "(untitled)"}</span>
          {why?.personal && (
            <span title="Looks like personal browsing — not client work"
              className="shrink-0 rounded-full border border-slate-400/40 bg-slate-400/15 px-2 py-0.5 font-sans text-[10px] font-medium text-slate-500 dark:text-slate-300">
              likely personal
            </span>
          )}
        </div>
        {reason && <div className="mt-0.5 font-sans text-[11.5px] leading-snug text-muted-foreground">{reason}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {guessId ? (
          <>
            <button onClick={() => onAccept(guessId)} disabled={busy} title={`Book to ${guessName}`} className={green}>
              <Check className="h-3 w-3 shrink-0" /> <span className="truncate">{guessName}</span>
            </button>
            <button onClick={onNotBillable} disabled={busy} className={ghost}>No client</button>
            <button onClick={(e) => onChange(e.currentTarget)} disabled={busy} className={ghost}>
              Change <ChevronDown className="h-2.5 w-2.5" />
            </button>
          </>
        ) : (
          <>
            <button onClick={(e) => onPick(e.currentTarget)} disabled={busy}
              className="inline-flex items-center gap-1 rounded-full border border-amber-500/60 bg-amber-500/10 px-2.5 py-0.5 font-sans text-[11px] font-semibold text-amber-700 transition-colors hover:bg-amber-500/20 disabled:opacity-50 dark:text-amber-300">
              Pick a client…
            </button>
            <button onClick={onNotBillable} disabled={busy} className={ghost}>Not billable</button>
          </>
        )}
      </div>
    </div>
  );
}

/** Mismatch: title names a different client than booked. Red; the fix leads. */
function MismatchRow({ m, busy, onFix, onKeep, onPick }: {
  m: MismatchBlock;
  busy: boolean;
  onFix: () => void;
  onKeep: () => void;
  onPick: (anchor: HTMLElement) => void;
}) {
  const canFix = m.looks_like_client_id != null;
  return (
    <div className="flex items-start gap-3 bg-rose-500/[0.06] px-4 py-3">
      <span className="mt-0.5 shrink-0 font-mono text-[11px] font-semibold tabular-nums text-rose-600 dark:text-rose-300">{fmtMin(m.minutes || 0)}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[12.5px] text-foreground">{m.window_title || "(untitled)"}</div>
        <div className="mt-0.5 font-sans text-[11.5px] leading-snug text-rose-600/90 dark:text-rose-300/90">
          Filed under {m.booked_client_name || "this client"}, but the title names {m.looks_like_client_name}.
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          onClick={(e) => (canFix ? onFix() : onPick(e.currentTarget))} disabled={busy}
          className="inline-flex max-w-[210px] items-center gap-1 rounded-full border border-rose-500/50 bg-rose-500/15 px-2.5 py-0.5 font-sans text-[11px] font-semibold text-rose-600 transition-colors hover:bg-rose-500/25 disabled:opacity-50 dark:text-rose-300">
          <span className="truncate">Move to {m.looks_like_client_name}</span>
        </button>
        <button onClick={onKeep} disabled={busy}
          className="rounded-full border border-border bg-card px-2.5 py-0.5 font-sans text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50">
          Keep here
        </button>
      </div>
    </div>
  );
}

// minutes -> "1h 13m" / "45m" / "2h"
function fmtMin(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}
