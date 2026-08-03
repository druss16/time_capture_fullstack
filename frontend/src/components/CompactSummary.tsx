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
import { ChevronRight, ChevronDown, Check, X, Search, Scissors } from "lucide-react";
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

  // ── Per-row detail (/why/) + Split ──────────────────────────────────────────
  // Expanding a Certain block row loads its "where the time went" breakdown and
  // the reason it was booked. A genuinely-mixed block can then be carved so each
  // activity books to its own client (opt-in Split — backend /blocks/{id}/split/).
  const [openWhy, setOpenWhy] = useState<number | null>(null);
  const [whyData, setWhyData] = useState<Record<number, WhyData>>({});
  const [whyLoading, setWhyLoading] = useState<number | null>(null);
  const toggleWhy = async (id: number | null) => {
    if (id == null) return;
    if (openWhy === id) { setOpenWhy(null); return; }
    setOpenWhy(id);
    if (!whyData[id]) {
      setWhyLoading(id);
      try {
        const d = await safeFetchJson<WhyData>(`${API_BASE}/blocks/${id}/why/`);
        setWhyData((prev) => ({ ...prev, [id]: d }));
      } catch { /* noop */ } finally { setWhyLoading(null); }
    }
  };

  const [splitFor, setSplitFor] = useState<number | null>(null);
  const [splitAssign, setSplitAssign] = useState<Record<string, number | null>>({});
  const [splitBusy, setSplitBusy] = useState(false);
  const sliceGuess = (r: Slice, currentClientId: number | null) =>
    r.suggested_client_id !== undefined ? r.suggested_client_id : currentClientId;
  const openSplit = (bid: number, breakdown: Slice[], currentClientId: number | null) => {
    if (splitFor === bid) { setSplitFor(null); return; }
    const init: Record<string, number | null> = {};
    breakdown.forEach((r) => { init[r.label] = sliceGuess(r, currentClientId); });
    setSplitAssign(init);
    setSplitFor(bid);
  };
  const splitDistinct = (a: Record<string, number | null>) =>
    new Set(Object.values(a).map((v) => (v == null ? "none" : v))).size;
  const postSplit = useCallback(async (
    bid: number, assignments: Record<string, { client_id: number | null; category: string }>,
  ) => {
    setSplitBusy(true);
    try {
      await safeFetchJson(`${API_BASE}/blocks/${bid}/split/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assignments }),
      });
      showToast("Split into separate entries", "success");
      setSplitFor(null);
      setOpenWhy((cur) => (cur === bid ? null : cur));
      setWhyData((prev) => { const next = { ...prev }; delete next[bid]; return next; });
      onRefresh();
    } catch { showToast("Couldn’t split this entry", "error"); }
    finally { setSplitBusy(false); }
  }, [onRefresh, showToast]);
  const splitBlock = (bid: number, category: string) => {
    const a: Record<string, { client_id: number | null; category: string }> = {};
    Object.entries(splitAssign).forEach(([label, cid]) => { a[label] = { client_id: cid, category }; });
    postSplit(bid, a);
  };
  const applySmartSplit = (bid: number, breakdown: Slice[], currentClientId: number | null, category: string) => {
    const a: Record<string, { client_id: number | null; category: string }> = {};
    breakdown.forEach((r) => { a[r.label] = { client_id: sliceGuess(r, currentClientId), category }; });
    postSplit(bid, a);
  };

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

  // One client group in the Certain browse: header (name · blocks · minutes · Move)
  // over its raw captured titles.
  const renderGroup = (g: CertainGroup) => {
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
          {/* per-client billable / non-billable split */}
          <span className="shrink-0 font-mono text-[12px] tabular-nums">
            {g.billableMinutes > 0 && <span className="font-semibold text-foreground">{fmtMin(g.billableMinutes)}</span>}
            {g.nonBillableMinutes > 0 && (
              <span className="text-muted-foreground/70">
                {g.billableMinutes > 0 ? " · " : ""}{fmtMin(g.nonBillableMinutes)} non-bill
              </span>
            )}
            {g.billableMinutes === 0 && g.nonBillableMinutes === 0 && (
              <span className="font-semibold text-foreground">{fmtMin(g.minutes)}</span>
            )}
          </span>
          <button
            onClick={(e) => openMove(e.currentTarget, allIds, g.clientId, g.repCategory, `Move · ${g.name}`)}
            className="shrink-0 rounded-md px-2 py-0.5 font-sans text-[12px] font-medium text-primary underline-offset-2 hover:underline">
            Move
          </button>
        </div>
        {open && (
          <div className="mb-1 flex flex-col pb-2 pl-6">
            {g.rows.map((r, i) => {
              const bid = r.ids[0] ?? null;
              const rowWhy = bid != null ? whyData[bid] : undefined;
              const rowOpen = bid != null && openWhy === bid;
              const bd = rowWhy?.breakdown ?? [];
              const smartClients = new Set(bd.map((s) => {
                const v = sliceGuess(s, g.clientId);
                return v == null ? "none" : String(v);
              }));
              const canSmart = bd.length > 1 && smartClients.size >= 2;
              const guessName = (s: Slice) => {
                const v = sliceGuess(s, g.clientId);
                if (v == null) return "No client";
                return s.suggested_client_name || availableClients.find((c) => c.id === v)?.name || "—";
              };
              return (
                <div key={i}>
                  {/* Click a row to expand its detail; use "Change" / "Split" inside. */}
                  <div onClick={() => toggleWhy(bid)}
                    className="flex cursor-pointer items-center gap-2 rounded-md py-0.5 pr-1 text-muted-foreground hover:text-foreground">
                    <ChevronRight className={cn("h-3 w-3 shrink-0 text-muted-foreground/50 transition-transform", rowOpen && "rotate-90")} />
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{r.title}</span>
                    <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/70">{fmtMin(r.minutes)}</span>
                  </div>
                  {rowOpen && (
                    <div className="mb-2 ml-5 mt-1 flex flex-col items-start gap-3 border-l-2 border-border/60 pl-3 font-sans">
                      {whyLoading === bid ? (
                        <span className="text-[11px] text-muted-foreground">Loading details…</span>
                      ) : (
                        <>
                          {/* Current category — hidden from the list to stay quiet, but
                              visible here so a miscategorization is catchable + fixable
                              (edit it via "Change client / category" below). */}
                          <div className="text-[11px]">
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Category </span>
                            <span className="font-mono text-foreground/80">{r.category}</span>
                          </div>
                          {bd.length > 1 && (
                            <div className="w-full max-w-sm">
                              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Where the time went</div>
                              <div className="flex flex-col gap-0.5">
                                {bd.map((s, j) => (
                                  <div key={j} className="flex items-center gap-2 text-[11px]">
                                    <span className="w-10 shrink-0 rounded bg-muted px-1 py-0.5 text-center font-mono text-[10.5px] font-semibold tabular-nums text-foreground/80">{fmtMin(s.minutes)}</span>
                                    <span className="min-w-0 flex-1 truncate text-foreground/80">{s.label}</span>
                                    {s.pct != null && <span className="shrink-0 tabular-nums text-muted-foreground/60">{s.pct}%</span>}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                          <div className="max-w-md">
                            <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Why this client</div>
                            <div className="text-[11px] leading-snug text-muted-foreground">{rowWhy?.explanation || "No added context for this entry."}</div>
                          </div>
                          {/* Smart split — one click books each activity to its guessed client. */}
                          {bid != null && canSmart && splitFor !== bid && (
                            <div className="w-full max-w-sm rounded-md border border-primary/30 bg-primary/5 p-2">
                              <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-primary/80">
                                <Scissors className="h-3 w-3" /> Suggested split
                              </div>
                              <div className="flex flex-col gap-1">
                                {bd.map((s, j) => (
                                  <div key={j} className="flex items-center gap-2 text-[11px]">
                                    <span className="w-10 shrink-0 rounded bg-muted px-1 py-0.5 text-center font-mono text-[10.5px] font-semibold tabular-nums text-foreground/80">{fmtMin(s.minutes)}</span>
                                    <span className="min-w-0 flex-1 truncate text-foreground/70" title={s.label}>{s.label}</span>
                                    <span className="shrink-0 text-muted-foreground/40">→</span>
                                    <span className="max-w-[8rem] shrink-0 truncate font-medium text-foreground/90" title={guessName(s)}>{guessName(s)}</span>
                                  </div>
                                ))}
                              </div>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <button disabled={splitBusy}
                                  onClick={() => applySmartSplit(bid, bd, g.clientId, r.category)}
                                  className="rounded-full bg-primary px-3 py-1 text-[11px] font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40">
                                  {splitBusy ? "Splitting…" : "Split these apart"}
                                </button>
                                <button onClick={() => openSplit(bid, bd, g.clientId)}
                                  className="text-[11px] font-medium text-muted-foreground hover:text-foreground">Adjust</button>
                              </div>
                            </div>
                          )}
                          <div className="flex flex-wrap items-center gap-2">
                            <button onClick={(e) => openMove(e.currentTarget, r.ids, g.clientId, r.category, "Change client / category")}
                              className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-[11px] font-semibold text-primary transition-colors hover:bg-primary/20">
                              Change client / category <ChevronDown className="h-3 w-3" />
                            </button>
                            {bid != null && !canSmart && bd.length > 1 && splitFor !== bid && (
                              <button onClick={() => openSplit(bid, bd, g.clientId)}
                                title="This block mixes more than one activity — book each to its own client"
                                className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1 text-[11px] font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                                <Scissors className="h-3 w-3" /> Split
                              </button>
                            )}
                          </div>
                          {/* Manual split editor */}
                          {bid != null && splitFor === bid && bd.length > 0 && (
                            <div className="w-full max-w-sm rounded-md border border-border bg-muted/30 p-2">
                              <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Adjust each activity’s client</div>
                              <div className="flex flex-col gap-1.5">
                                {bd.map((s, j) => (
                                  <div key={j} className="flex items-center gap-2 text-[11px]">
                                    <span className="w-10 shrink-0 rounded bg-muted px-1 py-0.5 text-center font-mono text-[10.5px] font-semibold tabular-nums text-foreground/80">{fmtMin(s.minutes)}</span>
                                    <span className="min-w-0 flex-1 truncate text-foreground/80" title={s.label}>{s.label}</span>
                                    <select value={splitAssign[s.label] ?? ""}
                                      onChange={(e) => { const v = e.target.value; setSplitAssign((prev) => ({ ...prev, [s.label]: v === "" ? null : Number(v) })); }}
                                      className="max-w-[8.5rem] shrink-0 rounded border border-border bg-background px-1 py-0.5 text-[11px] text-foreground">
                                      <option value="">No client</option>
                                      {availableClients.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
                                    </select>
                                  </div>
                                ))}
                              </div>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <button disabled={splitBusy || splitDistinct(splitAssign) < 2}
                                  onClick={() => splitBlock(bid, r.category)}
                                  className="rounded-full bg-primary px-3 py-1 text-[11px] font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40">
                                  {splitBusy ? "Splitting…" : "Split into separate entries"}
                                </button>
                                <button onClick={() => setSplitFor(null)} className="text-[11px] font-medium text-muted-foreground hover:text-foreground">Cancel</button>
                                {splitDistinct(splitAssign) < 2 && (<span className="text-[10.5px] text-muted-foreground/70">Give two activities different clients.</span>)}
                              </div>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={cn(sysDark && "dark")}>
      <div className="flex w-full flex-col gap-3 text-foreground">

        {/* ═══ CERTAIN ═════════════════════════════════════════════════════════ */}
        <section className="overflow-hidden rounded-xl border border-emerald-500/25 bg-emerald-500/5">
          <button
            onClick={() => setCertainOpen((v) => !v)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-emerald-500/10">
            <ChevronRight className={cn("h-4 w-4 shrink-0 text-emerald-600 transition-transform dark:text-emerald-400", certainOpen && "rotate-90")} />
            <span className="font-sans text-[15px] font-bold text-emerald-700 dark:text-emerald-300">Certain</span>
            <span className="truncate font-mono text-[12px] text-muted-foreground">
              {fmtMin(certain.billableMinutes)} billable
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
                  placeholder="Filter…"
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
                {filteredGroups.map(renderGroup)}
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

type Slice = { label: string; minutes: number; pct?: number; suggested_client_id?: number | null; suggested_client_name?: string | null };
type WhyData = {
  explanation: string;
  suggested_client_id: number | null;
  suggested_client_name: string | null;
  personal?: boolean;
  breakdown?: Slice[];
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

  // The green client and its reason MUST be the same client — otherwise the row
  // shows one name ("The New School") with another's reason ("…St. Joseph's").
  // Prefer the /why/ contextual suggestion (it carries the friendly explanation);
  // fall back to the classifier's stored proposal + its own reasoning. Never mix.
  const whyId = why?.suggested_client_id ?? null;
  const guessId = whyId ?? b.proposed_client_id ?? null;
  const guessName = whyId != null ? why?.suggested_client_name ?? null : b.proposed_client_name;
  const reason = ((whyId != null ? why?.explanation : (b.proposed_reasoning || why?.explanation)) || "").trim();

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
