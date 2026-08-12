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
import { ChevronRight, ChevronDown, Check, X, Search, Scissors, GripVertical } from "lucide-react";
import { cn } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";
import { MovePopover, suggestAliasFromTitle, type ClientOption, type ProposedInline } from "@/components/CategorySummary";
import type { Lanes, CertainGroup, MismatchBlock, SplitCandidate } from "@/lib/dailyReviewLanes";

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
  // Pending / mismatch rows are UNRESOLVED, so applying the current selection
  // (even unchanged, e.g. "keep as No client · Non-Billable") is a valid commit.
  allowUnchanged?: boolean;
  // Pre-fills the "Remember as alias" field when it's opened — a distinctive
  // token derived from the block title, so teaching the mapping is one click.
  defaultAlias?: string;
};

export default function CompactSummary({
  lanes, availableClients, availableCategories, busy,
  autoFiled, onRefresh, showToast, onIgnoreMismatch,
}: Props) {
  const sysDark = useSystemDark();
  const { certain, needsYou } = lanes;

  const [certainOpen, setCertainOpen] = useState(false);

  // Lane order is a personal preference (some users want "Needs you" on top).
  // Drag either section's grip handle onto the other to swap; persisted locally.
  const [laneOrder, setLaneOrder] = useState<("certain" | "needsYou")[]>(() =>
    (typeof localStorage !== "undefined" && localStorage.getItem("dr_lane_order") === "needs-first")
      ? ["needsYou", "certain"]
      : ["certain", "needsYou"]
  );
  const [dragLane, setDragLane] = useState<string | null>(null);
  const swapLanes = () => setLaneOrder((prev) => {
    const next = [prev[1], prev[0]] as ("certain" | "needsYou")[];
    try { localStorage.setItem("dr_lane_order", next[0] === "needsYou" ? "needs-first" : "certain-first"); } catch { /* noop */ }
    return next;
  });
  const laneDnd = (id: "certain" | "needsYou") => ({
    onDragOver: (e: React.DragEvent) => { if (dragLane && dragLane !== id) e.preventDefault(); },
    onDrop: (e: React.DragEvent) => { e.preventDefault(); if (dragLane && dragLane !== id) swapLanes(); },
  });
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [move, setMove] = useState<MoveState | null>(null);

  const catList = availableCategories.length ? availableCategories : ["General Client Work"];

  const toggleGroup = (key: string) =>
    setOpenGroup((prev) => (prev === key ? null : key));

  const openMove = (
    anchor: HTMLElement, ids: number[], clientId: number | null, category: string,
    label: string, suggestClientId: number | null = null, allowUnchanged = false,
    defaultAlias = "",
  ) => setMove({ anchor, ids, currentClientId: clientId, currentCategory: category, label, suggestClientId, allowUnchanged, defaultAlias });

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

  // "Always file titles like this here": confirm this block AND turn it into a
  // hard, firm-wide rule (a client alias derived from the title) so future
  // matching captures auto-file on the next occurrence — no waiting for
  // pattern-learning confidence to build.
  const alwaysFile = useCallback(async (b: ProposedInline, clientId: number) => {
    try {
      const r = await safeFetchJson<{ alias?: string; client_name?: string }>(
        `${API_BASE}/blocks/${b.block_id}/always-file/`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_id: clientId }) },
      );
      await recategorize(b.block_id, clientId, b.proposed_category || "General Client Work", "single_confirm");
      showToast(r?.alias ? `Now always filing “${r.alias}” here` : "Rule created", "success");
      onRefresh();
    } catch (e: any) {
      showToast(e?.data?.error || "Couldn’t make that a rule", "error");
    }
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

  // "Switch all": one click applies the same title-based fix to every block in
  // an identical-filename group (see groupMismatches). Purely fans out the
  // per-block fix — no merging of blocks, so billing/totals are unaffected.
  const fixMismatchGroup = useCallback(async (items: MismatchBlock[]) => {
    const targets = items.filter((m) => m.looks_like_client_id != null);
    if (!targets.length) return;
    try {
      await Promise.all(
        targets.map((m) =>
          recategorize(m.block_id, m.looks_like_client_id as number, m.category || "General Client Work"),
        ),
      );
      showToast(`Moved ${targets.length} blocks to ${targets[0].looks_like_client_name}`, "success");
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
  // One-click apply a flagged split candidate: book each activity to the client
  // its filename names (the backend's per-slice guess).
  const applySplitCandidate = useCallback((sc: SplitCandidate) => {
    const a: Record<string, { client_id: number | null; category: string }> = {};
    sc.slices.forEach((s) => { a[s.label] = { client_id: s.suggested_client_id, category: sc.category }; });
    postSplit(sc.block_id, a);
  }, [postSplit]);
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
    const open = openGroup === g.key || !!q;
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
          {/* per-client total time (billable split lives in the hero, not per row) */}
          <span className="shrink-0 font-mono text-[12px] tabular-nums font-semibold text-foreground">
            {fmtMin(g.minutes)}
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
                            <button onClick={(e) => openMove(e.currentTarget, r.ids, g.clientId, r.category, "Change client / category", null, false, suggestAliasFromTitle(r.title))}
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

        {/* ═══ CERTAIN ═══ quiet: neutral card, teal dot; color only on actions ══ */}
        <section
          style={{ order: laneOrder.indexOf("certain") }}
          {...laneDnd("certain")}
          className={cn("overflow-hidden rounded-[15px] border bg-card shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)] transition-colors",
            dragLane && dragLane !== "certain" ? "border-primary/50" : "border-border/70")}>
          <button
            onClick={() => setCertainOpen((v) => !v)}
            className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-muted/40">
            <span
              draggable
              onDragStart={() => setDragLane("certain")}
              onDragEnd={() => setDragLane(null)}
              onClick={(e) => e.stopPropagation()}
              title="Drag to reorder"
              className="-ml-1 shrink-0 cursor-grab text-muted-foreground/40 hover:text-muted-foreground active:cursor-grabbing">
              <GripVertical className="h-3.5 w-3.5" />
            </span>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-primary" />
            <span className="font-sans text-[15px] font-bold tracking-[-0.01em] text-primary">Certain</span>
            <span className="truncate font-mono text-[11.5px] text-muted-foreground">
              {fmtMin(certain.billableMinutes)} billable
            </span>
            <span className="flex-1" />
            <span className="shrink-0 rounded-lg border border-border bg-card px-3 py-1.5 font-sans text-[12px] font-medium text-muted-foreground shadow-[0_1px_2px_rgba(16,27,46,0.05)]">
              {certainOpen ? "Hide" : "Browse these"}
            </span>
          </button>

          {certainOpen && (
            <div className="border-t border-border/70 bg-card px-3 pb-3 pt-3">
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

        {/* ═══ NEEDS YOU ═══ quiet: neutral card, amber dot; color only on actions ══ */}
        <section
          style={{ order: laneOrder.indexOf("needsYou") }}
          {...laneDnd("needsYou")}
          className={cn("overflow-hidden rounded-[15px] border bg-card shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)] transition-colors",
            dragLane && dragLane !== "needsYou" ? "border-primary/50" : "border-border/70")}>
          <div className={cn("flex items-center gap-3 px-4 py-3.5", needsYou.count > 0 && "border-b border-border/70")}>
            <span
              draggable
              onDragStart={() => setDragLane("needsYou")}
              onDragEnd={() => setDragLane(null)}
              title="Drag to reorder"
              className="-ml-1 shrink-0 cursor-grab text-muted-foreground/40 hover:text-muted-foreground active:cursor-grabbing">
              <GripVertical className="h-3.5 w-3.5" />
            </span>
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", needsYou.count > 0 ? "bg-amber-500" : "bg-primary")} />
            <span className={cn("font-sans text-[15px] font-bold tracking-[-0.01em]",
              needsYou.count > 0 ? "text-amber-600 dark:text-amber-400" : "text-primary")}>
              Needs you
            </span>
            <span className="font-mono text-[11.5px] text-muted-foreground">
              {needsYou.count > 0
                ? `${needsYou.count} ${needsYou.count === 1 ? "item" : "items"} · ${fmtMin(needsYou.minutes)}`
                : "nothing — you’re done"}
            </span>
          </div>

          {needsYou.count > 0 && (
            <div className="flex flex-col">
              {/* Unassigned + pending, then mismatches — each block already minutes-desc. */}
              {needsYou.pending.map((b) => (
                <PendingRow
                  key={`p${b.block_id}`} b={b} busy={busy}
                  onAccept={(cid) => acceptTo(b, cid)}
                  onAlwaysFile={(cid) => alwaysFile(b, cid)}
                  onNotBillable={() => acceptTo(b, null)}
                  onPick={(anchor) => openMove(anchor, [b.block_id], null, b.proposed_category || catList[0], "Pick a client", null, true, suggestAliasFromTitle(b.window_title || ""))}
                  // "Change" means the shown suggestion was wrong, so open on a
                  // neutral No client · Non-Billable default — never pre-fill an
                  // unrelated client the user would have to notice and undo.
                  onChange={(anchor) => openMove(anchor, [b.block_id], null, "Personal/Non-Billable", "Change client", null, true, suggestAliasFromTitle(b.window_title || ""))}
                />
              ))}
              {groupMismatches(needsYou.mismatch).map((group) =>
                group.length === 1 ? (
                  <MismatchRow
                    key={`m${group[0].block_id}`} m={group[0]} busy={busy}
                    onFix={() => fixMismatch(group[0])}
                    onKeep={() => onIgnoreMismatch([group[0].block_id])}
                    onPick={(anchor) => openMove(anchor, [group[0].block_id], group[0].booked_client_id, group[0].category || catList[0], "Move to…", group[0].looks_like_client_id, true, suggestAliasFromTitle(group[0].window_title || ""))}
                  />
                ) : (
                  <MismatchGroupRow
                    key={`mg${group[0].block_id}`} items={group} busy={busy}
                    onFixAll={() => fixMismatchGroup(group)}
                    onKeepAll={() => onIgnoreMismatch(group.map((m) => m.block_id))}
                    onFixOne={(m) => fixMismatch(m)}
                    onKeepOne={(m) => onIgnoreMismatch([m.block_id])}
                    onPickOne={(m, anchor) => openMove(anchor, [m.block_id], m.booked_client_id, m.category || catList[0], "Move to…", m.looks_like_client_id, true, suggestAliasFromTitle(m.window_title || ""))}
                  />
                ),
              )}
              {needsYou.split.map((sc) => (
                <SplitCandidateRow
                  key={`s${sc.block_id}`} sc={sc} busy={busy || splitBusy}
                  onSplit={() => applySplitCandidate(sc)}
                  onKeep={() => onIgnoreMismatch([sc.block_id])}
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
          allowUnchanged={move.allowUnchanged ?? false}
          defaultAlias={move.defaultAlias ?? ""}
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
function PendingRow({ b, busy, onAccept, onAlwaysFile, onNotBillable, onPick, onChange }: {
  b: ProposedInline;
  busy: boolean;
  onAccept: (clientId: number) => void;
  onAlwaysFile: (clientId: number) => void;
  onNotBillable: () => void;
  onPick: (anchor: HTMLElement) => void;
  onChange: (anchor: HTMLElement) => void;
}) {
  // The /why/ suggestion is embedded in the today-time payload (why_*), so the
  // green client + reason paint with the page — no per-row fetch, no lag. Fall
  // back to a lazy /why/ fetch only if the backend didn't embed it (deploy skew).
  const hasEmbedded = b.why_suggested_client_id !== undefined || b.why_explanation !== undefined;
  const [why, setWhy] = useState<WhyData | null>(null);
  useEffect(() => {
    if (hasEmbedded) return;
    let alive = true;
    safeFetchJson<WhyData>(`${API_BASE}/blocks/${b.block_id}/why/`)
      .then((w) => { if (alive) setWhy(w); })
      .catch(() => { if (alive) setWhy(null); });
    return () => { alive = false; };
  }, [b.block_id, hasEmbedded]);

  // The green client and its reason MUST be the same client — prefer the /why/
  // contextual suggestion (carries the friendly explanation), else the
  // classifier's stored proposal + its own reasoning. Never mix.
  const whyId = (hasEmbedded ? b.why_suggested_client_id : why?.suggested_client_id) ?? null;
  const whyName = (hasEmbedded ? b.why_suggested_client_name : why?.suggested_client_name) ?? null;
  const whyReason = (hasEmbedded ? b.why_explanation : why?.explanation) || "";
  const guessId = whyId ?? b.proposed_client_id ?? null;
  const guessName = whyId != null ? whyName : b.proposed_client_name;
  const reason = ((whyId != null ? whyReason : (b.proposed_reasoning || whyReason)) || "").trim();

  return (
    <div className={ROW}>
      <span className={CHIP}>{fmtMin(b.minutes || 0)}</span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          {sourceLabel(b.app_name) && (
            <span className="shrink-0 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-sans text-[10px] font-medium text-muted-foreground"
              title={`Captured from ${b.app_name}`}>
              {sourceLabel(b.app_name)}
            </span>
          )}
          <span className="truncate font-mono text-[12.5px] text-foreground">{b.window_title || "(untitled)"}</span>
          {why?.personal && (
            <span title="Looks like personal browsing — not client work"
              className="shrink-0 rounded-full border border-slate-400/40 bg-slate-400/15 px-2 py-0.5 font-sans text-[10px] font-medium text-slate-500 dark:text-slate-300">
              likely personal
            </span>
          )}
        </div>
        {reason && <div className="mt-1 font-sans text-[11.5px] leading-snug text-muted-foreground">{reason}</div>}
        {guessId != null && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            {b.learning && !b.learning.mature && b.learning.remaining != null && (
              <span className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/[0.08] px-2.5 py-1"
                title={`This suggestion is being learned — after about ${b.learning.remaining} more confirm${b.learning.remaining === 1 ? "" : "s"}, blocks like this file automatically.`}>
                <span className="inline-flex gap-[3px]" aria-hidden>
                  {[0, 1, 2, 3, 4].map((i) => (
                    <span key={i} className={cn("h-1.5 w-1.5 rounded-full",
                      i < Math.min(5, Math.max(0, 5 - (b.learning!.remaining || 0))) ? "bg-primary" : "bg-primary/25")} />
                  ))}
                </span>
                <span className="font-sans text-[10.5px] font-medium text-primary/80">
                  Learning — ~{b.learning.remaining} more to auto-file
                </span>
              </span>
            )}
            <button
              onClick={() => onAlwaysFile(guessId)}
              disabled={busy}
              title={`Make a firm-wide rule: always file titles like this under ${guessName}`}
              className="inline-flex items-center gap-1 font-sans text-[11px] font-medium text-primary/75 transition-colors hover:text-primary hover:underline disabled:opacity-50">
              <Check className="h-3 w-3" /> Always file titles like this here
            </button>
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {guessId ? (
          <>
            <button onClick={() => onAccept(guessId)} disabled={busy} title={`Book to ${guessName}`} className={PILL_TEAL}>
              <Check className="h-3 w-3 shrink-0" /> <span className="truncate">{guessName}</span>
            </button>
            <button onClick={(e) => onChange(e.currentTarget)} disabled={busy} className={PILL_GHOST}
              title="Change client or category, or mark not billable">
              Change <ChevronDown className="h-2.5 w-2.5" />
            </button>
          </>
        ) : (
          <>
            <button onClick={(e) => onPick(e.currentTarget)} disabled={busy} className={PILL_AMBER}>Pick a client…</button>
            <button onClick={onNotBillable} disabled={busy} className={PILL_GHOST}>Not billable</button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Shared row + pill styles (quiet + sharpened) ────────────────────────────
// Inset hairline via ::before, hidden on the first row of the lane.
const ROW = "group relative flex items-start gap-3 bg-card px-4 py-3.5 before:absolute before:left-[68px] before:right-4 before:top-0 before:h-px before:bg-border/60 before:content-[''] first:before:hidden";
const CHIP = "mt-0.5 min-w-[40px] shrink-0 rounded-md bg-muted px-1 py-1 text-center font-mono text-[10px] font-bold tabular-nums text-muted-foreground";
const CHIP_AMBER = "mt-0.5 min-w-[40px] shrink-0 rounded-md bg-amber-500/[0.14] px-1 py-1 text-center font-mono text-[10px] font-bold tabular-nums text-amber-600 dark:text-amber-400";
// Fixed widths so the action buttons line up into clean columns across rows.
const PILL_TEAL = "inline-flex w-[212px] items-center justify-center gap-1 rounded-full border border-primary/50 bg-primary/[0.14] px-3 py-1.5 font-sans text-[11px] font-bold text-primary shadow-[0_1px_2px_rgba(16,27,46,0.05)] transition-colors hover:bg-primary/20 disabled:opacity-50";
const PILL_AMBER = "inline-flex w-[212px] items-center justify-center gap-1 rounded-full border border-amber-500/60 bg-amber-500/[0.14] px-3 py-1.5 font-sans text-[11px] font-bold text-amber-700 shadow-[0_1px_2px_rgba(16,27,46,0.05)] transition-colors hover:bg-amber-500/20 disabled:opacity-50 dark:text-amber-400";
const PILL_GHOST = "inline-flex w-[104px] items-center justify-center gap-0.5 rounded-full border border-border bg-card px-3 py-1.5 font-sans text-[11px] font-medium text-muted-foreground shadow-[0_1px_2px_rgba(16,27,46,0.05)] transition-colors hover:bg-muted disabled:opacity-50";

/** Fold mismatch rows for the *identical* file into one group, so eight 1-minute
 *  slivers of the same document don't list as eight rows. Grouped by exact title
 *  AND same suggested target, so "Switch all to X" is unambiguous; reused
 *  template names that point at different clients never collapse together.
 *  Display-only: this never merges blocks — each block keeps its own identity
 *  and the group action just fans the per-block fix out. First-seen order kept. */
function groupMismatches(items: MismatchBlock[]): MismatchBlock[][] {
  const groups: MismatchBlock[][] = [];
  const idx: Record<string, number> = {};
  for (const m of items) {
    const key = `${(m.window_title || "").trim().toLowerCase()}|${m.looks_like_client_id ?? "none"}`;
    if (idx[key] == null) { idx[key] = groups.length; groups.push([m]); }
    else groups[idx[key]].push(m);
  }
  return groups;
}

/** Collapsed view of N identical-file mismatch rows: one amber row with the
 *  combined time, an "N identical blocks" tag, and a single "Switch all"/"Keep
 *  all". Expands to the individual rows, each still independently actionable. */
function MismatchGroupRow({ items, busy, onFixAll, onKeepAll, onFixOne, onKeepOne, onPickOne }: {
  items: MismatchBlock[];
  busy: boolean;
  onFixAll: () => void;
  onKeepAll: () => void;
  onFixOne: (m: MismatchBlock) => void;
  onKeepOne: (m: MismatchBlock) => void;
  onPickOne: (m: MismatchBlock, anchor: HTMLElement) => void;
}) {
  const [open, setOpen] = useState(false);
  const total = items.reduce((s, m) => s + (m.minutes || 0), 0);
  const target = items[0].looks_like_client_name;
  const canFix = items.some((m) => m.looks_like_client_id != null);
  // Distinct "filed under" client names, first-seen order.
  const seen = new Set<string>();
  const filed: string[] = [];
  for (const m of items) {
    const n = m.booked_client_name || "this client";
    if (!seen.has(n)) { seen.add(n); filed.push(n); }
  }
  return (
    <div>
      <div className={ROW}>
        <span className={CHIP_AMBER}>{fmtMin(total)}</span>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          title={open ? "Collapse" : "Show the individual blocks"}
        >
          <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`} />
          <div className="min-w-0 flex-1">
            <div className="truncate font-mono text-[12.5px] text-foreground">{items[0].window_title || "(untitled)"}</div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-sans text-[11.5px]">
              <span className="rounded-full border border-border bg-muted px-2 py-0.5 font-semibold text-muted-foreground">
                {items.length} identical blocks
              </span>
              <span className="text-muted-foreground">Filed</span>
              <span className="rounded-md border border-border bg-muted/70 px-2 py-0.5 font-medium text-muted-foreground line-through decoration-muted-foreground/50">
                {filed.length === 1 ? filed[0] : `${filed.length} clients`}
              </span>
              <span className="font-bold text-muted-foreground/70">→</span>
              <span className="rounded-md border border-amber-500/40 bg-amber-500/[0.14] px-2 py-0.5 font-semibold text-amber-700 dark:text-amber-400">
                {target}
              </span>
              <span className="text-muted-foreground">— the title says so</span>
            </div>
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-2">
          <button onClick={onFixAll} disabled={busy || !canFix} className={PILL_AMBER}>
            <span className="max-w-[190px] truncate">Switch all to {target}</span>
          </button>
          <button onClick={onKeepAll} disabled={busy} className={PILL_GHOST}>Keep all</button>
        </div>
      </div>
      {open && (
        <div className="ml-6 border-l border-border pl-1">
          {items.map((m) => (
            <MismatchRow
              key={`m${m.block_id}`} m={m} busy={busy}
              onFix={() => onFixOne(m)}
              onKeep={() => onKeepOne(m)}
              onPick={(anchor) => onPickOne(m, anchor)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Mismatch: this block is filed under one client but its title names another.
 *  Framed as a calm "switch" (amber, not alarm-red): filed under X → looks like Y. */
function MismatchRow({ m, busy, onFix, onKeep, onPick }: {
  m: MismatchBlock;
  busy: boolean;
  onFix: () => void;
  onKeep: () => void;
  onPick: (anchor: HTMLElement) => void;
}) {
  const canFix = m.looks_like_client_id != null;
  return (
    <div className={ROW}>
      <span className={CHIP_AMBER}>{fmtMin(m.minutes || 0)}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[12.5px] text-foreground">{m.window_title || "(untitled)"}</div>
        {/* filed under X  →  looks like Y — the title says so */}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-sans text-[11.5px]">
          <span className="text-muted-foreground">Filed</span>
          <span className="rounded-md border border-border bg-muted/70 px-2 py-0.5 font-medium text-muted-foreground line-through decoration-muted-foreground/50">
            {m.booked_client_name || "this client"}
          </span>
          <span className="font-bold text-muted-foreground/70">→</span>
          <span className="rounded-md border border-amber-500/40 bg-amber-500/[0.14] px-2 py-0.5 font-semibold text-amber-700 dark:text-amber-400">
            {m.looks_like_client_name}
          </span>
          <span className="text-muted-foreground">— the title says so</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button onClick={(e) => (canFix ? onFix() : onPick(e.currentTarget))} disabled={busy} className={PILL_AMBER}>
          <span className="max-w-[190px] truncate">Switch to {m.looks_like_client_name}</span>
        </button>
        <button onClick={onKeep} disabled={busy} className={PILL_GHOST}>Keep here</button>
      </div>
    </div>
  );
}

/** Split candidate: one committed block whose activities point at 2+ clients.
 *  Offers a one-click split that books each activity to the client it names. */
function SplitCandidateRow({ sc, busy, onSplit, onKeep }: {
  sc: SplitCandidate;
  busy: boolean;
  onSplit: () => void;
  onKeep: () => void;
}) {
  // Distinct client names across the slices, in first-seen order.
  const seen = new Set<string>();
  const clients: string[] = [];
  for (const s of sc.slices) {
    const name = s.suggested_client_name || (s.suggested_client_id == null ? "No client" : "");
    if (name && !seen.has(name)) { seen.add(name); clients.push(name); }
  }
  return (
    <div className={ROW}>
      <span className={CHIP_AMBER}>{fmtMin(sc.minutes || 0)}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[12.5px] text-foreground">{sc.window_title || "(untitled)"}</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-sans text-[11.5px]">
          <span className="text-muted-foreground">Mixes {clients.length} clients:</span>
          {clients.slice(0, 4).map((c) => (
            <span key={c} className="rounded-md border border-amber-500/40 bg-amber-500/[0.14] px-2 py-0.5 font-semibold text-amber-700 dark:text-amber-400">{c}</span>
          ))}
          {clients.length > 4 && <span className="text-muted-foreground">+{clients.length - 4} more</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button onClick={onSplit} disabled={busy} className={PILL_AMBER}>
          <Scissors className="h-3 w-3" /> <span>Split apart</span>
        </button>
        <button onClick={onKeep} disabled={busy} className={PILL_GHOST}>Keep here</button>
      </div>
    </div>
  );
}

// A friendly "where did this come from" label from the capturing app, so a
// bare title like "Kennedy Barnes" reads as "Email · Kennedy Barnes" (an Outlook
// thread), not a mystery. Returns null when the app is unknown/uninformative.
function sourceLabel(app?: string): string | null {
  const a = (app || "").toLowerCase();
  if (!a) return null;
  if (a.includes("outlook")) return "Email";
  if (a.includes("teams")) return "Teams";
  if (a.includes("slack")) return "Slack";
  if (a.includes("qbw") || a.includes("quickbook")) return "QuickBooks";
  if (a.includes("excel")) return "Excel";
  if (a.includes("winword") || a.includes("word.exe")) return "Word";
  if (a.includes("powerpnt") || a.includes("powerpoint")) return "PowerPoint";
  if (a.includes("acrobat") || a.includes("acrord") || a.includes("acrodist")) return "PDF";
  if (a.includes("lacerte") || a.includes("ultratax") || a.includes("proseries") ||
      a.includes("drake") || a.includes("professional suite")) return "Tax software";
  if (a.includes("msedge") || a.includes("chrome") || a.includes("firefox") ||
      a.includes("edge") || a.includes("opera") || a.includes("brave")) return "Web";
  const cleaned = (app || "").replace(/\.exe$/i, "").trim();
  return cleaned || null;
}

// minutes -> "1h 13m" / "45m" / "2h"
function fmtMin(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}
