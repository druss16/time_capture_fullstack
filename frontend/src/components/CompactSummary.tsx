/**
 * CompactSummary.tsx
 *
 * A dense, collapsible client → category → activity view for the user-facing
 * Daily Review. Drop-in sibling of CategorySummary (same props) rendered behind
 * the Compact/Detailed toggle in DailyReview.tsx.
 *
 * Design decisions (locked with the owner):
 *  - Follows the SYSTEM light/dark theme, scoped to this subtree only: the whole
 *    view is wrapped in a `.dark`-classed div when the OS prefers dark, so the
 *    design-system CSS vars (`.dark { --token }`) cascade here WITHOUT touching
 *    the rest of the (currently light-only) app.
 *  - Reuses the load-bearing `parse()` (the `[id:...]` block-id contract) and the
 *    proven `MovePopover` from CategorySummary — no fork of that logic.
 *  - Keeps every action: move (single / all / selection), confirm pending.
 *    Move/confirm hit the same `recategorize` endpoint CategorySummary uses.
 *  - Pending (needs-review) items live UNDER their guessed client (or "No Client"
 *    when clientless), not in a top strip.
 *  - Carries the ⚠ mismatch flags (detect_mismatch) into the user view.
 *  - The AI/mail/calendar "suggests X instead of Y" disagreement banners are
 *    intentionally NOT shown here (owner doesn't use them). Mobile-entry review
 *    prompts are kept — a separate feature.
 */

import { useState, useEffect, useMemo, useCallback } from "react";
import {
  ChevronRight, ChevronDown, AlertTriangle, Check, Smartphone, Scissors,
} from "lucide-react";
import { cn } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";
import {
  parse, MovePopover,
  type ClientTime, type ClientOption, type FlaggedBlock, type ProposedInline,
} from "@/components/CategorySummary";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type Props = {
  timeSummary: ClientTime[];
  availableClients: ClientOption[];
  availableCategories: string[];
  flaggedBlocks: FlaggedBlock[];
  proposedInline?: ProposedInline[];
  busy: boolean;
  onDismissReview: (id: number) => void;
  onResolveDisagreement: (id: number, action: "accept" | "dismiss") => void;
  onRefresh: () => void;
  showToast: (msg: string, type: "success" | "error") => void;
  /** block_id -> looks-like client name, from today-time's detect_mismatch scan */
  mismatchFlags?: Record<string, string>;
};

// Left-accent colors — 500-weight reads on both light and dark grounds.
// Amber (pending/unassigned) and rose (mismatch) are deliberately EXCLUDED so
// those colors only ever signal something that needs attention.
const ACCENTS = [
  "border-l-teal-500", "border-l-violet-500", "border-l-sky-500",
  "border-l-emerald-500", "border-l-cyan-500", "border-l-indigo-500",
];

const isInternalClient = (name: string) => {
  const n = (name || "").trim().toLowerCase();
  return n === "internal" || n.startsWith("internal -");
};

const clientKeyOf = (clientId: number | null) => (clientId != null ? `id:${clientId}` : "none");

// Follows the OS theme; drives the scoped `.dark` wrapper.
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
  timeSummary, availableClients, availableCategories, flaggedBlocks,
  proposedInline = [], busy, onDismissReview,
  onRefresh, showToast, mismatchFlags = {},
}: Props) {
  const sysDark = useSystemDark();

  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [anomaliesOpen, setAnomaliesOpen] = useState(true);
  const [move, setMove] = useState<MoveState | null>(null);
  // Mismatch flags the user dismissed as false positives (persisted per browser).
  const [ignored, setIgnored] = useState<Set<string>>(() => {
    try { return new Set<string>(JSON.parse(localStorage.getItem("dr_ignored_mismatches") || "[]")); }
    catch { return new Set<string>(); }
  });
  const ignoreMismatch = (ids: number[]) =>
    setIgnored((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(String(id)));
      try { localStorage.setItem("dr_ignored_mismatches", JSON.stringify([...next])); } catch { /* noop */ }
      return next;
    });
  // A block's "looks like" client name — unless the user has ignored that flag.
  const looksLikeFor = (ids: number[]) =>
    ids.map((id) => (ignored.has(String(id)) ? undefined : mismatchFlags[String(id)])).find(Boolean);

  // "why?" for already-attributed rows — lazy-load the /why/ explanation, one open at a time.
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

  // ── Split ONE block into per-client pieces (opt-in) ──────────────────────────
  // A genuinely-mixed block (e.g. a No-Client timesheet open alongside a client's
  // workbook) can be carved so each activity books to its own client. Only one
  // split editor is open at a time; splitAssign is keyed by breakdown label.
  type Slice = { label: string; minutes: number; suggested_client_id?: number | null; suggested_client_name?: string | null };
  const [splitFor, setSplitFor] = useState<number | null>(null);
  const [splitAssign, setSplitAssign] = useState<Record<string, number | null>>({});
  const [splitBusy, setSplitBusy] = useState(false);
  // Each slice's best-guess client: the backend's per-slice suggestion, or the
  // block's current client when it made no confident guess.
  const sliceGuess = (r: Slice, currentClientId: number | null) =>
    r.suggested_client_id !== undefined ? r.suggested_client_id : currentClientId;
  const openSplit = (bid: number, breakdown: Slice[], currentClientId: number | null) => {
    if (splitFor === bid) { setSplitFor(null); return; }
    // Pre-fill from the smart per-slice guesses — the user reviews, doesn't assign.
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
      // The source block just changed shape — collapse its row and drop its cached
      // /why/ detail so the now-stale breakdown + "Suggested split" card disappear
      // (re-expanding refetches fresh; the leftover piece no longer offers a split).
      setSplitFor(null);
      setOpenWhy((cur) => (cur === bid ? null : cur));
      setWhyData((prev) => { const next = { ...prev }; delete next[bid]; return next; });
      onRefresh();
    } catch {
      showToast("Couldn’t split this entry", "error");
    } finally {
      setSplitBusy(false);
    }
  }, [onRefresh, showToast]);
  // Manual editor → apply the user's per-slice dropdown choices.
  const splitBlock = (bid: number, category: string) => {
    const a: Record<string, { client_id: number | null; category: string }> = {};
    Object.entries(splitAssign).forEach(([label, cid]) => { a[label] = { client_id: cid, category }; });
    postSplit(bid, a);
  };
  // One-click → apply the backend's smart per-slice guesses as-is.
  const applySmartSplit = (bid: number, breakdown: Slice[], currentClientId: number | null, category: string) => {
    const a: Record<string, { client_id: number | null; category: string }> = {};
    breakdown.forEach((r) => { a[r.label] = { client_id: sliceGuess(r, currentClientId), category }; });
    postSplit(bid, a);
  };

  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  const clearSel = () => setSelected(new Set());
  const toggleRow = (ids: number[]) =>
    setSelected((prev) => {
      const next = new Set(prev);
      const all = ids.length > 0 && ids.every((id) => next.has(id));
      ids.forEach((id) => (all ? next.delete(id) : next.add(id)));
      return next;
    });

  // ── Mutations ──────────────────────────────────────────────────────────────
  const moveBlocks = useCallback(async (ids: number[], clientId: number | null, category: string) => {
    if (!ids.length) return;
    try {
      await Promise.all(ids.map((id) =>
        safeFetchJson(`${API_BASE}/blocks/${id}/recategorize/`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, client_id: clientId }),
        })
      ));
      showToast(`Moved ${ids.length} ${ids.length > 1 ? "entries" : "entry"}`, "success");
      clearSel();
      onRefresh();
    } catch {
      showToast("Failed to move", "error");
    }
  }, [onRefresh, showToast]);

  // Accept a pending entry to a client — or to NO client (clientId=null), which
  // marks it not billable (mindless browsing / personal). One path for both.
  const acceptTo = useCallback(async (b: ProposedInline, clientId: number | null) => {
    try {
      await safeFetchJson(`${API_BASE}/blocks/${b.block_id}/recategorize/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: b.proposed_category || "General Client Work",
          client_id: clientId,
          source: "single_confirm",
        }),
      });
      showToast(clientId == null ? "Set to No client" : "Confirmed", "success");
      onRefresh();
    } catch {
      showToast("Couldn’t update this entry", "error");
    }
  }, [onRefresh, showToast]);

  const openMove = (
    anchor: HTMLElement, ids: number[], clientId: number | null, category: string,
    label: string, suggestClientId: number | null = null,
  ) =>
    setMove({ anchor, ids, currentClientId: clientId, currentCategory: category, label, suggestClientId });

  const selCount = selected.size;
  const catList = availableCategories.length ? availableCategories : ["General Client Work"];

  // ── Pending grouped by guessed client (so it renders UNDER that client) ──
  const pendingByKey = useMemo(() => {
    const m = new Map<string, ProposedInline[]>();
    for (const p of proposedInline) {
      const key = clientKeyOf(p.proposed_client_id);
      const arr = m.get(key);
      if (arr) arr.push(p); else m.set(key, [p]);
    }
    return m;
  }, [proposedInline]);

  // Which pending groups get absorbed into an existing client card…
  const realKeys = new Set(timeSummary.map((c) => clientKeyOf(c.client_id)));
  // …and which need a synthetic card (guessed client / No Client with no committed time today).
  const syntheticPending = useMemo(() => {
    const out: { key: string; name: string; clientId: number | null; items: ProposedInline[] }[] = [];
    pendingByKey.forEach((items, key) => {
      if (realKeys.has(key)) return;
      if (key === "none") out.push({ key, name: "No client", clientId: null, items });
      else out.push({ key, name: items[0].proposed_client_name || "Client", clientId: items[0].proposed_client_id, items });
    });
    return out;
    // realKeys derives from timeSummary; recompute when either input changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingByKey, timeSummary]);

  // Mobile-entry review prompts only (NOT the AI/mail/calendar "suggests" banners).
  const mobileReviews = useMemo(
    () => flaggedBlocks.filter((f) => f.type === "mobile_review"),
    [flaggedBlocks]
  );

  const clientCount = timeSummary.length + syntheticPending.length;

  const onChangePending = (
    anchor: HTMLElement, b: ProposedInline, cardClientId: number | null, suggestId: number | null,
  ) =>
    openMove(anchor, [b.block_id], cardClientId, b.proposed_category || catList[0], "Change client", suggestId);

  // ── Anomalies: activities whose title names a different client than booked ──
  const anomalies = useMemo(() => {
    const out: {
      ids: number[]; title: string; bookedClient: string;
      looksLike: string; looksLikeId: number | null; category: string;
    }[] = [];
    for (const client of timeSummary) {
      for (const cat of client.categories) {
        for (const a of cat.sample_activities) {
          const p = parse(a);
          const looks = looksLikeFor(p.blockIds);
          if (looks) {
            out.push({
              ids: p.blockIds, title: p.title, bookedClient: client.client,
              looksLike: looks, category: cat.name,
              looksLikeId: availableClients.find((c) => c.name === looks)?.id ?? null,
            });
          }
        }
      }
    }
    return out;
  }, [timeSummary, mismatchFlags, availableClients, ignored]);

  const fixAllAnomalies = useCallback(async () => {
    const fixable = anomalies.filter((a) => a.looksLikeId != null);
    if (!fixable.length) return;
    try {
      await Promise.all(fixable.flatMap((a) =>
        a.ids.map((id) => safeFetchJson(`${API_BASE}/blocks/${id}/recategorize/`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category: a.category, client_id: a.looksLikeId }),
        }))
      ));
      showToast(`Fixed ${fixable.length} ${fixable.length > 1 ? "entries" : "entry"}`, "success");
      onRefresh();
    } catch {
      showToast("Couldn’t fix some entries", "error");
    }
  }, [anomalies, onRefresh, showToast]);

  // ── Collapse / expand all client cards ──
  const allClientKeys = useMemo(() => [
    ...timeSummary.map((c) => `c:${clientKeyOf(c.client_id)}`),
    ...syntheticPending.map((s) => `c:${s.key}:pending`),
  ], [timeSummary, syntheticPending]);
  const allCollapsed = allClientKeys.length > 0 && allClientKeys.every((k) => collapsed.has(k));
  const toggleCollapseAll = () => setCollapsed(allCollapsed ? new Set() : new Set(allClientKeys));

  return (
    <div className={cn(sysDark && "dark")}>
      <div className="bg-background text-foreground rounded-xl">

        {/* Top Anomalies banner removed for now (per request). The inline
            "⚠ looks like X" chips + ignore stay on the activity rows. */}

        {/* ── Mobile-entry review prompts ── */}
        {mobileReviews.length > 0 && (
          <div className="mb-3 flex flex-col gap-2">
            {mobileReviews.map((f) => (
              <div key={f.block_id}
                className="flex items-center gap-3 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-2.5 text-sm">
                <Smartphone className="w-4 h-4 shrink-0 text-sky-500" />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  Mobile entry needs review — <span className="font-medium text-foreground">{f.window_title || f.client_name}</span>
                </span>
                <button onClick={() => onDismissReview(f.block_id)} disabled={busy}
                  className="shrink-0 rounded-md bg-sky-500 px-3 py-1 text-xs font-semibold text-white hover:opacity-90">
                  Looks correct
                </button>
              </div>
            ))}
          </div>
        )}

        {/* ── Section label + collapse-all ── */}
        <div className="mb-2 flex items-center gap-3 px-1">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
            Clients · {clientCount}
          </span>
          <span className="flex-1" />
          {clientCount > 0 && (
            <button onClick={toggleCollapseAll}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 px-3 py-1 font-sans text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary">
              <ChevronDown className={cn("h-3 w-3 transition-transform", allCollapsed && "-rotate-90")} />
              {allCollapsed ? "Expand all" : "Collapse all"}
            </button>
          )}
        </div>

        {clientCount === 0 && !busy && (
          <div className="py-10 text-center font-mono text-sm text-muted-foreground">no tracked time for this day</div>
        )}

        {/* ── Client cards ── */}
        <div className="flex flex-col gap-2">
          {timeSummary.map((client, ci) => {
            const cKey = `c:${clientKeyOf(client.client_id)}`;
            const open = !collapsed.has(cKey);
            const unassigned = client.client_id == null;
            const internal = isInternalClient(client.client);
            const accent = unassigned ? "border-l-amber-400" : ACCENTS[ci % ACCENTS.length];
            const pending = pendingByKey.get(clientKeyOf(client.client_id)) || [];

            const clientFlagged = client.categories.some((cat) =>
              cat.sample_activities.some((a) => !!looksLikeFor(parse(a).blockIds))
            );

            return (
              <div key={cKey}
                className={cn(
                  "overflow-hidden rounded-xl border border-l-4 bg-card", accent,
                  unassigned && "border-dashed border-amber-500/50",
                  clientFlagged && "border-rose-500/50"
                )}>
                <button onClick={() => toggle(cKey)}
                  className="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-muted/60">
                  <ChevronRight className={cn("w-3.5 h-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
                  <span className={cn("text-[15px] font-semibold",
                    unassigned ? "italic text-amber-600 dark:text-amber-300" : internal ? "text-muted-foreground" : "text-foreground")}>
                    {unassigned ? "No client" : client.client}
                  </span>
                  {clientFlagged && (
                    <span title="A title here clearly names a different client"
                      className="shrink-0 rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 font-mono text-[11px] text-rose-600 dark:text-rose-300">
                      ⚠ mismatch
                    </span>
                  )}
                  {pending.length > 0 && (
                    <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[11px] text-amber-600 dark:text-amber-300">
                      {pending.length} pending
                    </span>
                  )}
                  <span className="flex-1" />
                  <span className="shrink-0 font-mono text-sm font-bold tabular-nums text-primary">
                    {fmtH(client.total_hours)}
                  </span>
                </button>

                {open && (
                  <div className="border-t border-border px-3 pb-3 pt-2">
                    {pending.length > 0 && (
                      <PendingStrip items={pending} busy={busy} allowNoClient={client.client_id == null}
                        onAccept={(b, cid) => acceptTo(b, cid)}
                        onNoClient={(b) => acceptTo(b, null)}
                        onChange={(anchor, b, suggestId) => onChangePending(anchor, b, client.client_id, suggestId)} />
                    )}
                    {client.categories.map((cat, kx) => {
                      const catKey = `${cKey}/cat:${cat.name}`;
                      const catOpen = !collapsed.has(catKey);
                      const catBlockIds = cat.sample_activities.flatMap((a) => parse(a).blockIds);
                      return (
                        <div key={catKey} className={cn("py-1.5", kx > 0 && "border-t border-border/60")}>
                          <div className="group flex items-center gap-2 px-1 py-1">
                            <button onClick={() => toggle(catKey)} className="flex flex-1 items-center gap-2 text-left">
                              <ChevronRight className={cn("w-3 h-3 shrink-0 text-muted-foreground transition-transform", catOpen && "rotate-90")} />
                              <span className="font-mono text-[13px] font-semibold text-violet-600 dark:text-violet-300">{cat.name}</span>
                              <span className="font-mono text-xs text-muted-foreground">{fmtH(cat.hours)}</span>
                            </button>
                            {catBlockIds.length > 0 && (
                              <button
                                onClick={(e) => openMove(e.currentTarget, catBlockIds, client.client_id, cat.name, `Move all · ${cat.name}`)}
                                className="shrink-0 rounded-md border border-primary/40 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary opacity-0 transition-opacity group-hover:opacity-100">
                                Move all
                              </button>
                            )}
                          </div>

                          {catOpen && (
                            <div className="flex flex-col">
                              {cat.sample_activities.map((a, ax) => {
                                const p = parse(a);
                                const ids = p.blockIds;
                                const looksLike = looksLikeFor(ids);
                                const isSel = ids.length > 0 && ids.every((id) => selected.has(id));
                                const bid = p.blockId;
                                const rowWhy = bid != null ? whyData[bid] : undefined;
                                const rowOpen = bid != null && openWhy === bid;
                                const suggestId = looksLike
                                  ? (availableClients.find((c) => c.name === looksLike)?.id ?? null)
                                  : null;
                                // Smart split: the block's activity breakdown, with each slice's
                                // best-guess client. If those guesses span 2+ clients, we can
                                // propose the whole split with one click instead of hand-assigning.
                                const bd = rowWhy?.breakdown ?? [];
                                const smartClients = new Set(bd.map((r) => {
                                  const v = sliceGuess(r, client.client_id);
                                  return v == null ? "none" : String(v);
                                }));
                                const canSmart = bd.length > 1 && smartClients.size >= 2;
                                const guessName = (r: Slice) => {
                                  const v = sliceGuess(r, client.client_id);
                                  if (v == null) return "No client";
                                  return r.suggested_client_name
                                    || availableClients.find((c) => c.id === v)?.name || "—";
                                };
                                return (
                                  <div key={ax}>
                                    {/* Click a row to expand its detail; use "Change" to move it. */}
                                    <div
                                      onClick={(e) => {
                                        if ((e.target as HTMLElement).closest("[data-cbox]")) return;
                                        toggleWhy(bid);
                                      }}
                                      className={cn(
                                        "group/row flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 font-mono text-[12.5px]",
                                        isSel ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                                      )}>
                                      <ChevronRight className={cn("h-3 w-3 shrink-0 text-muted-foreground/60 transition-transform", rowOpen && "rotate-90")} />
                                      <span data-cbox onClick={(e) => { e.stopPropagation(); if (ids.length) toggleRow(ids); }}
                                        className={cn("grid h-3.5 w-3.5 shrink-0 place-items-center rounded border text-[10px]",
                                          isSel ? "border-primary bg-primary text-primary-foreground opacity-100"
                                            : "border-muted-foreground/50 text-transparent opacity-0 group-hover/row:opacity-100")}>
                                        <Check className="w-2.5 h-2.5" />
                                      </span>
                                      <span className="min-w-0 flex-1 truncate">{p.title}</span>
                                      {looksLike && (
                                        <span className="flex shrink-0 items-center gap-1">
                                          <span title={`Title clearly names "${looksLike}"`}
                                            className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 text-[10.5px] text-rose-600 dark:text-rose-300">
                                            ⚠ looks like {looksLike}
                                          </span>
                                          <button onClick={(e) => { e.stopPropagation(); ignoreMismatch(ids); }}
                                            title="Not a mistake — hide this flag"
                                            className="text-[10.5px] font-medium text-muted-foreground hover:text-foreground">
                                            ignore
                                          </button>
                                        </span>
                                      )}
                                    </div>

                                    {rowOpen && (
                                      <div className="mb-2 ml-6 mt-1 flex flex-col items-start gap-3 border-l-2 border-border/60 pl-3 font-sans">
                                        {whyLoading === bid ? (
                                          <span className="text-[11px] text-muted-foreground">Loading details…</span>
                                        ) : (
                                          <>
                                            {rowWhy?.breakdown && rowWhy.breakdown.length > 1 && (
                                              <div className="w-full max-w-sm">
                                                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Where the time went</div>
                                                <div className="flex flex-col gap-0.5">
                                                  {rowWhy.breakdown.map((r, j) => (
                                                    <div key={j} className="flex items-center gap-2 text-[11px]">
                                                      <span className="w-10 shrink-0 rounded bg-muted px-1 py-0.5 text-center font-mono text-[10.5px] font-semibold tabular-nums text-foreground/80">{fmtH(r.minutes / 60)}</span>
                                                      <span className="min-w-0 flex-1 truncate text-foreground/80">{r.label}</span>
                                                      <span className="shrink-0 tabular-nums text-muted-foreground/60">{r.pct}%</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}
                                            <div className="max-w-md">
                                              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Why this client</div>
                                              <div className="text-[11px] leading-snug text-muted-foreground">
                                                {rowWhy?.explanation || "No added context for this entry."}
                                              </div>
                                            </div>
                                            {/* Smart split proposal — one click books each activity to its guessed client. */}
                                            {bid != null && canSmart && splitFor !== bid && (
                                              <div onClick={(e) => e.stopPropagation()}
                                                className="w-full max-w-sm rounded-md border border-primary/30 bg-primary/5 p-2">
                                                <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-primary/80">
                                                  <Scissors className="h-3 w-3" /> Suggested split
                                                </div>
                                                <div className="flex flex-col gap-1">
                                                  {bd.map((r, j) => (
                                                    <div key={j} className="flex items-center gap-2 text-[11px]">
                                                      <span className="w-10 shrink-0 rounded bg-muted px-1 py-0.5 text-center font-mono text-[10.5px] font-semibold tabular-nums text-foreground/80">{fmtH(r.minutes / 60)}</span>
                                                      <span className="min-w-0 flex-1 truncate text-foreground/70" title={r.label}>{r.label}</span>
                                                      <span className="shrink-0 text-muted-foreground/40">→</span>
                                                      <span className="max-w-[8rem] shrink-0 truncate font-medium text-foreground/90" title={guessName(r)}>{guessName(r)}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                                <div className="mt-2 flex flex-wrap items-center gap-2">
                                                  <button disabled={splitBusy}
                                                    onClick={(e) => { e.stopPropagation(); applySmartSplit(bid, bd, client.client_id, cat.name); }}
                                                    className="rounded-full bg-primary px-3 py-1 text-[11px] font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40">
                                                    {splitBusy ? "Splitting…" : "Split these apart"}
                                                  </button>
                                                  <button onClick={(e) => { e.stopPropagation(); openSplit(bid, bd, client.client_id); }}
                                                    className="text-[11px] font-medium text-muted-foreground hover:text-foreground">Adjust</button>
                                                </div>
                                              </div>
                                            )}

                                            <div className="flex flex-wrap items-center gap-2">
                                              <button onClick={(e) => { e.stopPropagation(); openMove(e.currentTarget as HTMLElement, ids, client.client_id, cat.name, "Change client / category", suggestId); }}
                                                className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-[11px] font-semibold text-primary transition-colors hover:bg-primary/20">
                                                Change client / category <ChevronDown className="h-3 w-3" />
                                              </button>
                                              {/* Manual split entry point only when there's no confident multi-client guess. */}
                                              {bid != null && !canSmart && bd.length > 1 && splitFor !== bid && (
                                                <button onClick={(e) => { e.stopPropagation(); openSplit(bid, bd, client.client_id); }}
                                                  title="This block mixes more than one activity — book each to its own client"
                                                  className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1 text-[11px] font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                                                  <Scissors className="h-3 w-3" /> Split
                                                </button>
                                              )}
                                            </div>

                                            {bid != null && splitFor === bid && rowWhy?.breakdown && (
                                              <div onClick={(e) => e.stopPropagation()}
                                                className="w-full max-w-sm rounded-md border border-border bg-muted/30 p-2">
                                                <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                                                  Adjust each activity’s client
                                                </div>
                                                <div className="flex flex-col gap-1.5">
                                                  {rowWhy.breakdown.map((r, j) => (
                                                    <div key={j} className="flex items-center gap-2 text-[11px]">
                                                      <span className="w-10 shrink-0 rounded bg-muted px-1 py-0.5 text-center font-mono text-[10.5px] font-semibold tabular-nums text-foreground/80">{fmtH(r.minutes / 60)}</span>
                                                      <span className="min-w-0 flex-1 truncate text-foreground/80" title={r.label}>{r.label}</span>
                                                      <select value={splitAssign[r.label] ?? ""}
                                                        onChange={(e) => { const v = e.target.value; setSplitAssign((prev) => ({ ...prev, [r.label]: v === "" ? null : Number(v) })); }}
                                                        className="max-w-[8.5rem] shrink-0 rounded border border-border bg-background px-1 py-0.5 text-[11px] text-foreground">
                                                        <option value="">No client</option>
                                                        {availableClients.map((c) => (
                                                          <option key={c.id} value={c.id}>{c.name}</option>
                                                        ))}
                                                      </select>
                                                    </div>
                                                  ))}
                                                </div>
                                                <div className="mt-2 flex flex-wrap items-center gap-2">
                                                  <button disabled={splitBusy || splitDistinct(splitAssign) < 2}
                                                    onClick={(e) => { e.stopPropagation(); splitBlock(bid, cat.name); }}
                                                    className="rounded-full bg-primary px-3 py-1 text-[11px] font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40">
                                                    {splitBusy ? "Splitting…" : "Split into separate entries"}
                                                  </button>
                                                  <button onClick={(e) => { e.stopPropagation(); setSplitFor(null); }}
                                                    className="text-[11px] font-medium text-muted-foreground hover:text-foreground">Cancel</button>
                                                  {splitDistinct(splitAssign) < 2 && (
                                                    <span className="text-[10.5px] text-muted-foreground/70">Give two activities different clients.</span>
                                                  )}
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
                    })}
                  </div>
                )}
              </div>
            );
          })}

          {/* ── Synthetic cards: pending whose client has no committed time today ── */}
          {syntheticPending.map((s) => {
            const cKey = `c:${s.key}:pending`;
            const open = !collapsed.has(cKey);
            const noClient = s.clientId == null;
            return (
              <div key={cKey}
                className={cn("overflow-hidden rounded-xl border border-l-4 border-l-amber-400 bg-card",
                  noClient && "border-dashed border-amber-500/50")}>
                <button onClick={() => toggle(cKey)}
                  className="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-muted/60">
                  <ChevronRight className={cn("w-3.5 h-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
                  <span className={cn("text-[15px] font-semibold", noClient ? "italic text-amber-600 dark:text-amber-300" : "text-foreground")}>
                    {s.name}
                  </span>
                  <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[11px] text-amber-600 dark:text-amber-300">
                    {s.items.length} pending
                  </span>
                  <span className="flex-1" />
                  <span className="shrink-0 font-mono text-xs text-muted-foreground">needs review</span>
                </button>
                {open && (
                  <div className="border-t border-border px-3 pb-3 pt-2">
                    <PendingStrip items={s.items} busy={busy} allowNoClient={s.clientId == null}
                      onAccept={(b, cid) => acceptTo(b, cid)}
                      onNoClient={(b) => acceptTo(b, null)}
                      onChange={(anchor, b, suggestId) => onChangePending(anchor, b, s.clientId, suggestId)} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Floating selection bar ── */}
      {selCount > 0 && (
        <div className={cn("fixed left-1/2 bottom-6 z-40 -translate-x-1/2", sysDark && "dark")}>
          <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-2.5 shadow-2xl">
            <span className="font-mono text-sm font-bold text-foreground"><span className="text-primary">{selCount}</span> selected</span>
            <button
              onClick={(e) => openMove(e.currentTarget, Array.from(selected), null, catList[0], `Move ${selCount} entries`)}
              className="rounded-md bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground hover:opacity-90">
              Move to…
            </button>
            <button onClick={clearSel} className="rounded-md border border-border px-3 py-1 text-xs font-semibold text-muted-foreground hover:bg-muted">
              Clear
            </button>
          </div>
        </div>
      )}

      {/* ── Move popover (reused from CategorySummary) ── */}
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

// ── Pending rows ──────────────────────────────────────────────────────────────
// Module-level so each row's "why?" expand state survives parent re-renders.
type WhyData = {
  explanation: string;
  local_time: string;
  co_open_files: string[];
  tier: string;
  personal?: boolean;
  breakdown?: { label: string; minutes: number; pct: number; suggested_client_id?: number | null; suggested_client_name?: string | null }[];
  suggested_client_id: number | null;
  suggested_client_name: string | null;
};

function PendingRow({ b, busy, allowNoClient, onAccept, onNoClient, onChange }: {
  b: ProposedInline;
  busy: boolean;
  allowNoClient: boolean;   // only offer the quick "No client" out in the No-client bucket
  onAccept: (b: ProposedInline, clientId: number) => void;
  onNoClient: (b: ProposedInline) => void;
  onChange: (anchor: HTMLElement, b: ProposedInline, suggestId: number | null) => void;
}) {
  const [why, setWhy] = useState<WhyData | null>(null);

  // Load the explanation + context suggestion up front, so the reason line and
  // the best-guess button are visible without any expanding.
  useEffect(() => {
    let alive = true;
    safeFetchJson<WhyData>(`${API_BASE}/blocks/${b.block_id}/why/`)
      .then((w) => { if (alive) setWhy(w); })
      .catch(() => { if (alive) setWhy(null); });
    return () => { alive = false; };
  }, [b.block_id]);

  // Best guess = the classifier's proposed client, else the contextual suggestion.
  const guessId = b.proposed_client_id ?? why?.suggested_client_id ?? null;
  const guessName = b.proposed_client_name ?? why?.suggested_client_name ?? null;
  const reason = why?.explanation || "";
  // Primary = soft teal tint (colored, so it leads — but calm). Secondary = quiet neutral outline.
  const primary = "inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/20 px-3 py-1 font-sans text-[11px] font-semibold text-primary transition-colors hover:bg-primary/30 disabled:opacity-50";
  const ghost = "inline-flex items-center gap-1 rounded-full border border-border bg-muted/60 px-3 py-1 font-sans text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-primary disabled:opacity-50";

  return (
    <div className="py-2.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate font-mono text-xs text-foreground/90">{b.window_title || "(untitled)"}</span>
            <span className="shrink-0 font-mono text-[11px] font-semibold text-muted-foreground">{fmtH((b.minutes || 0) / 60)}</span>
            {why?.personal && (
              <span title="Looks like personal browsing — not client work"
                className="shrink-0 rounded-full border border-slate-400/40 bg-slate-400/15 px-2 py-0.5 font-sans text-[10px] font-medium text-slate-500 dark:text-slate-300">
                likely personal
              </span>
            )}
          </div>
          {reason && (
            <div className="mt-1 font-sans text-[11.5px] leading-snug text-muted-foreground">{reason}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {/* Primary: accept the best-guess client, or "No client". */}
          {guessId ? (
            <button onClick={() => onAccept(b, guessId)} disabled={busy} title={`Book to ${guessName}`}
              className={cn(primary, "max-w-[230px]")}>
              <Check className="h-3 w-3 shrink-0" /> <span className="truncate">{guessName}</span>
            </button>
          ) : (
            <button onClick={() => onNoClient(b)} disabled={busy} title="No client"
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-400/50 bg-slate-400/25 px-3 py-1 font-sans text-[11px] font-semibold text-slate-600 transition-colors hover:bg-slate-400/35 disabled:opacity-50 dark:text-slate-300">
              <Check className="h-3 w-3" /> No client
            </button>
          )}
          {/* Quick "No client" out — only in the No-client bucket, never under a client. */}
          {guessId && allowNoClient && (
            <button onClick={() => onNoClient(b)} disabled={busy} className={ghost}>No client</button>
          )}
          <button onClick={(e) => onChange(e.currentTarget, b, guessId)} disabled={busy} className={ghost}>
            Change <ChevronDown className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

function PendingStrip({ items, busy, allowNoClient, onAccept, onNoClient, onChange }: {
  items: ProposedInline[];
  busy: boolean;
  allowNoClient: boolean;
  onAccept: (b: ProposedInline, clientId: number) => void;
  onNoClient: (b: ProposedInline) => void;
  onChange: (anchor: HTMLElement, b: ProposedInline, suggestId: number | null) => void;
}) {
  return (
    <div className="mb-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5">
      <div className="mb-1 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide text-amber-600 dark:text-amber-300">
        <AlertTriangle className="w-3.5 h-3.5" /> Pending — confirm to count as billable
      </div>
      <div className="flex flex-col divide-y divide-amber-500/20">
        {items.map((b) => (
          <PendingRow key={b.block_id} b={b} busy={busy} allowNoClient={allowNoClient}
            onAccept={onAccept} onNoClient={onNoClient} onChange={onChange} />
        ))}
      </div>
    </div>
  );
}

// Hours formatter: 1.7 -> "1h 42m", 0.25 -> "15m", 2 -> "2h".
function fmtH(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}
