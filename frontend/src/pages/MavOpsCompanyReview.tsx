// src/pages/MavOpsCompanyReview.tsx
/**
 * MavOps → Daily Review → "Needs You" — one firm's whole review queue, every
 * user in a single list, actionable from the admin console.
 *
 * Why it works this way
 * ---------------------
 * The customer-facing Daily Review answers "what needs a human today?" for ONE
 * user, and the answer is derived by `today-time` + `deriveLanes` — several
 * hundred lines of matcher, mismatch detector, ambiguity grouping and split
 * detection. Re-deriving any of that here would guarantee the console and the
 * firm's own screen eventually disagree about what needs review, which is the
 * one thing this view must never do.
 *
 * So it doesn't. It fans `today-time` out across the firm's members using the
 * existing MavOps view-as identity swap (X-View-As-User, see
 * tracker/impersonation.py), runs each payload through the *same* `deriveLanes`
 * the real screen uses, and concatenates the Needs-You lanes into one queue.
 * Writes go back through the same per-block endpoints under the same header, so
 * every change is a real, audited write made as the block's owner — identical to
 * what would have happened had that user clicked it themselves.
 *
 * Consequences worth knowing:
 *   · No new backend, no migration. Parity with the user's screen is structural.
 *   · One `today-time` request per member (they are expensive), so the fan-out
 *     is pooled and results stream in as they land rather than blocking on the
 *     slowest user.
 *   · "Keep" / "Skip" only dismisses locally (localStorage), exactly like the
 *     customer screen — there is no server-side "ignore this mismatch".
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import {
  deriveLanes,
  type AmbiguousGroup,
  type Lanes,
  type MismatchBlock,
  type SplitCandidate,
} from "@/lib/dailyReviewLanes";
import type { ClientTime, ProposedInline } from "@/components/CategorySummary";

// ─── Console theme (mirrors MavOpsAdmin / MavOpsAdminRules) ───────────────────
const T = {
  bg: "#0f1419",
  surface: "#1a2231",
  surfaceHi: "#222d3f",
  border: "#2a3548",
  borderHi: "#3d4a63",
  text: "#f1f5f9",
  textSub: "#b0bccd",
  textMuted: "#8593a8",
  teal: "#2dd4bf",
  tealHi: "#5eead4",
  yellow: "#fbbf24",
  red: "#f87171",
  purple: "#c4b5fd",
  green: "#34d399",
};
const mono = { fontFamily: "'DM Mono', monospace" };
const card: CSSProperties = {
  background: T.surface,
  border: `1px solid ${T.border}`,
  padding: 20,
  marginBottom: 10,
  borderRadius: 8,
};
const inputStyle: CSSProperties = {
  background: T.bg,
  border: `1px solid ${T.border}`,
  color: T.text,
  padding: "7px 10px",
  fontSize: 12,
  outline: "none",
  borderRadius: 4,
  ...mono,
};

// ─── Types ────────────────────────────────────────────────────────────────────
export interface OrgLite {
  id: number;
  name: string;
}
interface Member {
  user_id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
}
interface ClientOpt {
  id: number;
  name: string;
}

/** today-time's raw payload, only the parts the lanes need. */
interface TodayTime {
  clients: ClientTime[];
  proposed_inline?: ProposedInline[];
  mismatch_blocks?: MismatchBlock[];
  split_candidates?: SplitCandidate[];
  ambiguous_groups?: AmbiguousGroup[];
}

/** One member's slice of the queue, plus whether their fetch succeeded. */
interface UserSlice {
  member: Member;
  lanes: Lanes | null;
  error: string | null;
}

/** A row in the merged queue. `key` is stable and identifies it for dismissal. */
type Row =
  | { kind: "pending"; key: string; uid: number; who: string; minutes: number; blockIds: number[]; item: ProposedInline }
  | { kind: "ambiguous"; key: string; uid: number; who: string; minutes: number; blockIds: number[]; item: AmbiguousGroup }
  | { kind: "mismatch"; key: string; uid: number; who: string; minutes: number; blockIds: number[]; item: MismatchBlock }
  | { kind: "split"; key: string; uid: number; who: string; minutes: number; blockIds: number[]; item: SplitCandidate };

type RowKind = Row["kind"];

interface Props {
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  filterOrg: number | null;
  setFilterOrg: (id: number | null) => void;
  orgs: OrgLite[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fmtMin = (m: number) => {
  const mins = Math.round(m || 0);
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const r = mins % 60;
  return r ? `${h}h ${r}m` : `${h}h`;
};

const memberName = (m: Member) =>
  `${m.first_name} ${m.last_name}`.trim() || m.username || `user ${m.user_id}`;

/** Short display name so a long user label doesn't dominate a row. */
const shortWho = (m: Member) => {
  const full = memberName(m);
  const parts = full.split(/\s+/);
  return parts.length > 1 ? `${parts[0]} ${parts[1][0]}.` : full;
};

const DISMISS_KEY = "mavops_company_review_dismissed";

const loadDismissed = (): Set<string> => {
  try {
    return new Set<string>(JSON.parse(localStorage.getItem(DISMISS_KEY) || "[]"));
  } catch {
    return new Set<string>();
  }
};

/**
 * How many members' `today-time` calls are in flight at once.
 *
 * Each one re-derives why / mismatch / split for a whole day, so this is the
 * dial between "fills fast" and "stampedes the API". The real ceiling is the
 * backend's worker count, not this number — past that, extra requests just
 * queue server-side and nothing gets faster.
 */
const FANOUT_CONCURRENCY = 8;

/**
 * Lanes already fetched, keyed by firm + window + user.
 *
 * Module-level on purpose: the Needs You / Audit toggle unmounts this
 * component, and re-paying a 13-request fan-out to glance at the audit and come
 * back is the slowest thing about the screen. A write invalidates just that
 * user's entry (see `invalidateUser`) so a remount refetches the one person
 * whose data actually changed — without it, a row you just fixed would come
 * back from cache looking unfixed.
 */
const laneCache = new Map<string, Lanes>();
const cacheKey = (orgId: number, windowKey: string, uid: number) => `${orgId}|${windowKey}|${uid}`;
const invalidateUser = (orgId: number, windowKey: string, uid: number) =>
  laneCache.delete(cacheKey(orgId, windowKey, uid));

/**
 * The firm's roster and client list, per org.
 *
 * These matter more than they look. Caching the lanes alone did not make the
 * Needs You / Audit toggle instant, because `load` still awaited the members
 * and clients calls before it could so much as look at the lane cache — a fully
 * cached return still paid a round trip and flashed empty. With all three
 * cached, a return paints synchronously and issues no request at all.
 *
 * Neither changes within a sitting; the Load button clears both.
 */
const memberCache = new Map<number, Member[]>();
const clientCache = new Map<number, ClientOpt[]>();

/**
 * Run `fn` over `items` with at most `limit` in flight.
 */
async function pooled<T>(items: T[], limit: number, fn: (item: T) => Promise<void>) {
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    for (;;) {
      const i = cursor++;
      if (i >= items.length) return;
      await fn(items[i]);
    }
  });
  await Promise.all(workers);
}

// ─── Small presentational pieces ──────────────────────────────────────────────
function Pill({ text, color, title }: { text: string; color: string; title?: string }) {
  return (
    <span
      title={title}
      style={{
        color,
        background: `${color}1e`,
        border: `1px solid ${color}55`,
        padding: "1px 7px",
        borderRadius: 3,
        fontSize: 10.5,
        whiteSpace: "nowrap",
        ...mono,
      }}
    >
      {text}
    </span>
  );
}

function ActionBtn({
  label,
  onClick,
  color = T.teal,
  outline = false,
  disabled = false,
  title,
}: {
  label: string;
  onClick: () => void;
  color?: string;
  outline?: boolean;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        background: outline ? "transparent" : `${color}22`,
        border: `1px solid ${color}${outline ? "44" : "77"}`,
        color: disabled ? T.textMuted : color,
        padding: "4px 10px",
        fontSize: 11.5,
        cursor: disabled ? "not-allowed" : "pointer",
        borderRadius: 4,
        whiteSpace: "nowrap",
        opacity: disabled ? 0.5 : 1,
        ...mono,
      }}
    >
      {label}
    </button>
  );
}

/**
 * Filterable client list. A firm can have 300+ clients, so a <select> per row
 * is both slow to render and unusable to scan — this opens under the row and
 * narrows as you type.
 */
function ClientPicker({
  clients,
  onPick,
  onCancel,
  allowNoClient = true,
}: {
  clients: ClientOpt[];
  onPick: (clientId: number | null, name: string) => void;
  onCancel: () => void;
  allowNoClient?: boolean;
}) {
  const [q, setQ] = useState("");
  const matches = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = needle
      ? clients.filter((c) => c.name.toLowerCase().includes(needle))
      : clients;
    return list.slice(0, 60);
  }, [clients, q]);

  return (
    <div
      style={{
        marginTop: 8,
        padding: 10,
        background: T.bg,
        border: `1px solid ${T.borderHi}`,
        borderRadius: 6,
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onCancel();
            if (e.key === "Enter" && matches.length === 1) onPick(matches[0].id, matches[0].name);
          }}
          placeholder="type to find a client…"
          style={{ ...inputStyle, flex: 1 }}
        />
        {allowNoClient && (
          <ActionBtn label="no client" color={T.textMuted} outline onClick={() => onPick(null, "No client")} />
        )}
        <ActionBtn label="cancel" color={T.textMuted} outline onClick={onCancel} />
      </div>
      <div style={{ maxHeight: 190, overflowY: "auto", display: "flex", flexWrap: "wrap", gap: 6 }}>
        {matches.length === 0 && (
          // The client list is fetched alongside the fan-out rather than ahead
          // of it, so on a cold load the picker can open before it lands.
          <span style={{ color: T.textMuted, fontSize: 12, ...mono }}>
            {clients.length === 0 ? "loading clients…" : "no clients match"}
          </span>
        )}
        {matches.map((c) => (
          <button
            key={c.id}
            onClick={() => onPick(c.id, c.name)}
            style={{
              background: T.surface,
              border: `1px solid ${T.border}`,
              color: T.text,
              padding: "4px 9px",
              fontSize: 11.5,
              cursor: "pointer",
              borderRadius: 4,
              ...mono,
            }}
          >
            {c.name}
          </button>
        ))}
        {clients.length > matches.length && !q && (
          <span style={{ color: T.textMuted, fontSize: 11, alignSelf: "center", ...mono }}>
            …{clients.length - matches.length} more — type to narrow
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────
export default function MavOpsCompanyReview({ apiFetch, flash, filterOrg, setFilterOrg, orgs }: Props) {
  const today = new Date().toISOString().slice(0, 10);

  const [rangeMode, setRangeMode] = useState(false);
  const [date, setDate] = useState(today);
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);

  const [slices, setSlices] = useState<UserSlice[]>([]);
  const [clients, setClients] = useState<ClientOpt[]>([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number }>({ done: 0, total: 0 });

  const [kindFilter, setKindFilter] = useState<RowKind | "all">("all");
  const [userFilter, setUserFilter] = useState<number | "all">("all");
  const [groupByUser, setGroupByUser] = useState(false);

  // Rows the admin has acted on or skipped. Hidden immediately so the queue
  // drains as they work; a failed write puts the row back.
  const [handled, setHandled] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(loadDismissed);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [picking, setPicking] = useState<string | null>(null);

  // Guards a slow fan-out from writing into a newer one's results.
  const runId = useRef(0);
  // The window key the currently-loaded slices belong to, so a write can drop
  // exactly that user's cache entry.
  const windowKeyRef = useRef("");

  // ── Requests as a given member ─────────────────────────────────────────────
  /**
   * The whole feature in one function: any non-/api/mavops/ endpoint, executed
   * as `uid`. Auth re-validates the header on every request and refuses it for
   * a non-staff caller, so this grants the console nothing it did not already
   * have — it just makes each request land on the right person's data.
   */
  const asUser = useCallback(
    (uid: number, path: string, opts: RequestInit = {}) =>
      apiFetch(path, {
        ...opts,
        headers: { ...((opts.headers as Record<string, string>) || {}), "X-View-As-User": String(uid) },
      }),
    [apiFetch],
  );

  const recategorize = useCallback(
    (uid: number, blockId: number, clientId: number | null, category: string, source?: string) =>
      asUser(uid, `/blocks/${blockId}/recategorize/`, {
        method: "PATCH",
        body: JSON.stringify({ category, client_id: clientId, ...(source ? { source } : {}) }),
      }),
    [asUser],
  );

  // ── Load ───────────────────────────────────────────────────────────────────
  /** `force` = the admin pressed Load, so refetch everything and ignore the cache. */
  const load = useCallback(async (force = false) => {
    if (!filterOrg) {
      flash("Select a firm above first.", "err");
      return;
    }
    const mine = ++runId.current;
    setHandled(new Set());
    setPicking(null);

    const dateQuery = rangeMode
      ? `start=${startDate}&end=${endDate}`
      : `date=${date}`;
    windowKeyRef.current = dateQuery;

    if (force) {
      for (const k of [...laneCache.keys()]) {
        if (k.startsWith(`${filterOrg}|${dateQuery}|`)) laneCache.delete(k);
      }
      memberCache.delete(filterOrg);
      clientCache.delete(filterOrg);
    }

    // ── Paint whatever is cached, synchronously, before awaiting anything ────
    // This branch is the whole point of the cache: on a toggle back it renders
    // the queue on the first frame with no request and no empty flash.
    const knownMembers = memberCache.get(filterOrg);
    const knownClients = clientCache.get(filterOrg);
    if (knownClients) setClients(knownClients);
    if (knownMembers) {
      setSlices(
        knownMembers.map((m) => ({
          member: m,
          lanes: laneCache.get(cacheKey(filterOrg, dateQuery, m.user_id)) || null,
          error: null,
        })),
      );
      const missing = knownMembers.filter(
        (m) => !laneCache.has(cacheKey(filterOrg, dateQuery, m.user_id)),
      );
      setProgress({ done: knownMembers.length - missing.length, total: knownMembers.length });
      if (!missing.length && knownClients) {
        // Nothing left to fetch. Press Load for fresh data.
        setLoading(false);
        return;
      }
    } else {
      setSlices([]);
      setProgress({ done: 0, total: 0 });
    }

    setLoading(true);
    try {
      const members: Member[] =
        knownMembers ||
        ((await apiFetch(`/mavops/orgs/${filterOrg}/members/`))?.members ?? []);
      if (runId.current !== mine) return;
      memberCache.set(filterOrg, members);

      if (!knownClients) {
        // Clients are org-wide; ?org_id= is the staff override the console
        // already uses elsewhere, so this needs no view-as. Not awaited with the
        // roster — it only feeds the "pick a client" popover, and blocking the
        // whole queue on it would trade the fan-out's head start for nothing.
        apiFetch(`/options/clients/?org_id=${filterOrg}`)
          .then((resp: any) => {
            const list: ClientOpt[] = (Array.isArray(resp) ? resp : [])
              .map((c: any) => ({ id: c.id, name: c.name }))
              .filter((c: ClientOpt) => c.id != null && c.name);
            clientCache.set(filterOrg, list);
            if (runId.current === mine) setClients(list);
          })
          .catch(() => { /* picker falls back to an empty list */ });
      }

      if (!knownMembers) {
        setSlices(
          members.map((m) => ({
            member: m,
            lanes: laneCache.get(cacheKey(filterOrg, dateQuery, m.user_id)) || null,
            error: null,
          })),
        );
      }
      const toFetch = members.filter(
        (m) => !laneCache.has(cacheKey(filterOrg, dateQuery, m.user_id)),
      );
      setProgress({ done: members.length - toFetch.length, total: members.length });

      await pooled(toFetch, FANOUT_CONCURRENCY, async (m) => {
        let patch: Partial<UserSlice>;
        try {
          const d: TodayTime = await asUser(m.user_id, `/today-time/?${dateQuery}`);
          patch = {
            lanes: deriveLanes(
              (d.clients || []) as ClientTime[],
              d.proposed_inline || [],
              d.mismatch_blocks || [],
              new Set<string>(), // dismissal is applied at render, not here
              d.split_candidates || [],
              d.ambiguous_groups || [],
            ),
            error: null,
          };
          if (patch.lanes) laneCache.set(cacheKey(filterOrg, dateQuery, m.user_id), patch.lanes);
        } catch (e: any) {
          patch = { lanes: null, error: e?.message || "failed" };
        }
        if (runId.current !== mine) return;
        setSlices((prev) =>
          prev.map((s) => (s.member.user_id === m.user_id ? { ...s, ...patch } : s)),
        );
        setProgress((p) => ({ ...p, done: p.done + 1 }));
      });
    } catch {
      if (runId.current === mine) flash("Failed to load the firm's review queue.", "err");
    } finally {
      if (runId.current === mine) setLoading(false);
    }
  }, [apiFetch, asUser, flash, filterOrg, rangeMode, date, startDate, endDate]);

  // Auto-load on firm change; date changes wait for the Load button (each load
  // is N expensive requests).
  useEffect(() => {
    if (filterOrg) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterOrg]);

  // ── Merge every member's Needs-You lane into one queue ─────────────────────
  const allRows: Row[] = useMemo(() => {
    const out: Row[] = [];
    for (const s of slices) {
      if (!s.lanes) continue;
      const uid = s.member.user_id;
      const who = shortWho(s.member);
      const n = s.lanes.needsYou;
      for (const p of n.pending) {
        out.push({
          kind: "pending", key: `p:${uid}:${p.block_id}`, uid, who,
          minutes: p.minutes || 0, blockIds: [p.block_id], item: p,
        });
      }
      for (const g of n.ambiguous) {
        out.push({
          kind: "ambiguous", key: `a:${uid}:${g.block_ids[0]}`, uid, who,
          minutes: g.minutes || 0, blockIds: g.block_ids, item: g,
        });
      }
      for (const m of n.mismatch) {
        out.push({
          kind: "mismatch", key: `m:${uid}:${m.block_id}`, uid, who,
          minutes: m.minutes || 0, blockIds: [m.block_id], item: m,
        });
      }
      for (const sp of n.split) {
        out.push({
          kind: "split", key: `s:${uid}:${sp.block_id}`, uid, who,
          minutes: sp.minutes || 0, blockIds: [sp.block_id], item: sp,
        });
      }
    }
    return out.sort((a, b) => b.minutes - a.minutes);
  }, [slices]);

  const liveRows = useMemo(
    () => allRows.filter((r) => !handled.has(r.key) && !dismissed.has(r.key)),
    [allRows, handled, dismissed],
  );

  const visibleRows = useMemo(
    () =>
      liveRows.filter(
        (r) =>
          (kindFilter === "all" || r.kind === kindFilter) &&
          (userFilter === "all" || r.uid === userFilter),
      ),
    [liveRows, kindFilter, userFilter],
  );

  const orderedRows = useMemo(() => {
    if (!groupByUser) return visibleRows;
    return [...visibleRows].sort((a, b) => (a.who === b.who ? b.minutes - a.minutes : a.who.localeCompare(b.who)));
  }, [visibleRows, groupByUser]);

  const counts = useMemo(() => {
    const c: Record<RowKind, number> = { pending: 0, ambiguous: 0, mismatch: 0, split: 0 };
    for (const r of liveRows) c[r.kind] += 1;
    return c;
  }, [liveRows]);

  const totalMinutes = liveRows.reduce((s, r) => s + r.minutes, 0);
  const loadedUsers = slices.filter((s) => s.lanes).length;
  const failedUsers = slices.filter((s) => s.error);

  // ── Mutations ──────────────────────────────────────────────────────────────
  const markBusy = (key: string, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  /** A write changed this user's day; their cached lanes are now stale. */
  const dropCache = useCallback(
    (uid: number) => {
      if (filterOrg) invalidateUser(filterOrg, windowKeyRef.current, uid);
    },
    [filterOrg],
  );

  /** Apply one client decision to every block behind a row. */
  const applyRow = useCallback(
    async (row: Row, clientId: number | null, category: string, label: string, source?: string) => {
      markBusy(row.key, true);
      setHandled((prev) => new Set(prev).add(row.key)); // optimistic: row leaves the queue
      setPicking(null);
      try {
        await Promise.all(
          row.blockIds.map((id) => recategorize(row.uid, id, clientId, category, source)),
        );
        dropCache(row.uid);
        flash(
          `${row.who}: ${row.blockIds.length > 1 ? `${row.blockIds.length} blocks ` : ""}→ ${label}`,
          "ok",
        );
      } catch {
        setHandled((prev) => {
          const next = new Set(prev);
          next.delete(row.key);
          return next;
        });
        flash(`Couldn't update ${row.who}'s entry.`, "err");
      } finally {
        markBusy(row.key, false);
      }
    },
    [dropCache, flash, recategorize],
  );

  /** "Always file titles like this here" — confirm AND make it a firm-wide rule. */
  const alwaysFile = useCallback(
    async (row: Row & { kind: "pending" }, clientId: number, name: string) => {
      const category = row.item.proposed_category || "General Client Work";
      markBusy(row.key, true);
      setHandled((prev) => new Set(prev).add(row.key));
      setPicking(null);
      try {
        const r = await asUser(row.uid, `/blocks/${row.item.block_id}/always-file/`, {
          method: "POST",
          body: JSON.stringify({ client_id: clientId }),
        });
        await recategorize(row.uid, row.item.block_id, clientId, category, "single_confirm");
        dropCache(row.uid);
        flash(r?.alias ? `Now always filing “${r.alias}” → ${name}` : `Rule created → ${name}`, "ok");
      } catch (e: any) {
        setHandled((prev) => {
          const next = new Set(prev);
          next.delete(row.key);
          return next;
        });
        flash(`Couldn't make that a rule (${e?.message || "failed"}).`, "err");
      } finally {
        markBusy(row.key, false);
      }
    },
    [asUser, dropCache, flash, recategorize],
  );

  /** Carve a mixed block so each activity books to its own suggested client. */
  const applySplit = useCallback(
    async (row: Row & { kind: "split" }) => {
      const sc = row.item;
      const assignments: Record<string, { client_id: number | null; category: string }> = {};
      for (const slice of sc.slices) {
        assignments[slice.label] = {
          client_id: slice.suggested_client_id ?? sc.booked_client_id,
          category: slice.suggested_category || sc.category || "General Client Work",
        };
      }
      markBusy(row.key, true);
      setHandled((prev) => new Set(prev).add(row.key));
      try {
        await asUser(row.uid, `/blocks/${sc.block_id}/split/`, {
          method: "POST",
          body: JSON.stringify({ assignments }),
        });
        dropCache(row.uid);
        flash(`${row.who}: split into ${sc.slices.length} entries`, "ok");
      } catch {
        setHandled((prev) => {
          const next = new Set(prev);
          next.delete(row.key);
          return next;
        });
        flash("Couldn't split that entry.", "err");
      } finally {
        markBusy(row.key, false);
      }
    },
    [asUser, dropCache, flash],
  );

  /** Local-only "leave it alone", same as the customer screen's Keep / Skip. */
  const dismiss = useCallback((row: Row) => {
    setDismissed((prev) => {
      const next = new Set(prev).add(row.key);
      try {
        localStorage.setItem(DISMISS_KEY, JSON.stringify([...next]));
      } catch {
        /* noop */
      }
      return next;
    });
  }, []);

  const clearDismissed = () => {
    setDismissed(new Set());
    try {
      localStorage.removeItem(DISMISS_KEY);
    } catch {
      /* noop */
    }
  };

  // ── Row rendering ──────────────────────────────────────────────────────────
  const KIND_META: Record<RowKind, { label: string; color: string }> = {
    pending: { label: "pick a client", color: T.teal },
    ambiguous: { label: "which one?", color: T.purple },
    mismatch: { label: "mismatch", color: T.red },
    split: { label: "split", color: T.yellow },
  };

  const renderActions = (row: Row) => {
    const disabled = busy.has(row.key);

    if (row.kind === "pending") {
      const p = row.item;
      const category = p.proposed_category || "General Client Work";
      const guessId = p.why_suggested_client_id ?? p.proposed_client_id;
      const guessName = p.why_suggested_client_name || p.proposed_client_name;
      return (
        <>
          {guessId != null && guessName && (
            <>
              <ActionBtn
                label={`✓ ${guessName}`}
                color={T.green}
                disabled={disabled}
                onClick={() => applyRow(row, guessId, category, guessName, "single_confirm")}
              />
              <ActionBtn
                label="always file here"
                color={T.green}
                outline
                disabled={disabled}
                title="Confirm this AND create a firm-wide alias so titles like it auto-file next time"
                onClick={() => alwaysFile(row as Row & { kind: "pending" }, guessId, guessName)}
              />
            </>
          )}
          <ActionBtn
            label={guessId != null ? "other…" : "pick client…"}
            outline={guessId != null}
            disabled={disabled}
            onClick={() => setPicking(picking === row.key ? null : row.key)}
          />
          <ActionBtn
            label="not billable"
            color={T.textMuted}
            outline
            disabled={disabled}
            onClick={() => applyRow(row, null, "Personal/Non-Billable", "not billable", "single_confirm")}
          />
        </>
      );
    }

    if (row.kind === "ambiguous") {
      const g = row.item;
      const category = g.category || "General Client Work";
      return (
        <>
          {/* Every candidate is the row's own purple. They used to split green
              (worked recently) / purple (not), which was wrong twice over: it
              implied the green one was RECOMMENDED — on the one row type that
              exists precisely because the matcher refused to recommend — and it
              collided with the green ✓ accept button on pending rows, so green
              meant two different things on one screen. Recency is real and
              useful, so it stays: as a ● that the row's own context line names
              in words, rather than a colour nobody can look up. */}
          {g.candidates.slice(0, 4).map((c) => (
            <ActionBtn
              key={c.client_id}
              label={c.recent ? `● ${c.short_name}` : c.short_name}
              color={T.purple}
              disabled={disabled}
              title={`${c.client_name}${c.recent ? " — you have worked this client recently" : ""}`}
              onClick={() => applyRow(row, c.client_id, category, c.client_name)}
            />
          ))}
          <ActionBtn
            label="other…"
            outline
            disabled={disabled}
            onClick={() => setPicking(picking === row.key ? null : row.key)}
          />
          <ActionBtn label="skip" color={T.textMuted} outline disabled={disabled} onClick={() => dismiss(row)} />
        </>
      );
    }

    if (row.kind === "mismatch") {
      const m = row.item;
      const category = m.category || "General Client Work";
      return (
        <>
          {m.looks_like_client_id != null && (
            <ActionBtn
              label={`→ ${m.looks_like_client_name}`}
              color={T.red}
              disabled={disabled}
              onClick={() => applyRow(row, m.looks_like_client_id, category, m.looks_like_client_name)}
            />
          )}
          <ActionBtn
            label="other…"
            outline
            disabled={disabled}
            onClick={() => setPicking(picking === row.key ? null : row.key)}
          />
          <ActionBtn
            label="keep"
            color={T.textMuted}
            outline
            disabled={disabled}
            title="Leave it booked where it is (dismissed in this browser only)"
            onClick={() => dismiss(row)}
          />
        </>
      );
    }

    const sc = row.item;
    const namedSlices = sc.slices.filter((s) => s.suggested_client_id != null).length;
    return (
      <>
        <ActionBtn
          label={`split into ${sc.slices.length}`}
          color={T.yellow}
          disabled={disabled || namedSlices === 0}
          title={
            namedSlices === 0
              ? "No slice names a client — nothing to split to"
              : "Book each activity to its own suggested client"
          }
          onClick={() => applySplit(row as Row & { kind: "split" })}
        />
        <ActionBtn
          label="all to one…"
          outline
          disabled={disabled}
          onClick={() => setPicking(picking === row.key ? null : row.key)}
        />
        <ActionBtn label="skip" color={T.textMuted} outline disabled={disabled} onClick={() => dismiss(row)} />
      </>
    );
  };

  const renderContext = (row: Row) => {
    if (row.kind === "mismatch") {
      const m = row.item;
      return (
        <span style={{ fontSize: 11.5, color: T.textMuted, ...mono }}>
          booked <span style={{ color: T.text }}>{m.booked_client_name || "No client"}</span>
          <span style={{ color: T.red, margin: "0 6px" }}>→</span>
          title names <span style={{ color: T.yellow }}>{m.looks_like_client_name}</span>
        </span>
      );
    }
    if (row.kind === "ambiguous") {
      const g = row.item;
      const anyRecent = g.candidates.slice(0, 4).some((c) => c.recent);
      return (
        <span style={{ fontSize: 11.5, color: T.textMuted, ...mono }}>
          {g.block_count} block{g.block_count > 1 ? "s" : ""} · {g.candidates.length} look-alike client
          {g.candidates.length > 1 ? "s" : ""} share this name
          {anyRecent && (
            <span> · <span style={{ color: T.purple }}>●</span> = {row.who} worked it recently</span>
          )}
        </span>
      );
    }
    if (row.kind === "split") {
      const sc = row.item;
      return (
        <span style={{ fontSize: 11.5, color: T.textMuted, ...mono }}>
          booked <span style={{ color: T.text }}>{sc.booked_client_name || "No client"}</span> ·{" "}
          {sc.slices
            .map((s) => `${s.suggested_client_name || "?"} (${fmtMin(s.minutes)})`)
            .join("  ·  ")}
        </span>
      );
    }
    const p = row.item;
    const why = p.why_explanation || p.proposed_reasoning;
    if (!why) return null;
    return <span style={{ fontSize: 11.5, color: T.textMuted, ...mono }}>{why}</span>;
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  let lastWho: string | null = null;

  return (
    <div>
      {/* ── Controls ── */}
      <div style={{ ...card, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span
          style={{
            color: T.textMuted,
            fontSize: 11,
            letterSpacing: 1,
            textTransform: "uppercase",
            fontWeight: 600,
          }}
        >
          Firm
        </span>
        <select
          value={filterOrg || ""}
          onChange={(e) => setFilterOrg(e.target.value ? Number(e.target.value) : null)}
          style={{ ...inputStyle, cursor: "pointer", color: filterOrg ? T.teal : T.textSub }}
        >
          <option value="">— select firm —</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>

        <div style={{ width: 1, height: 24, background: T.border }} />

        {rangeMode ? (
          <>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={inputStyle} />
            <span style={{ color: T.textMuted, fontSize: 12 }}>→</span>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={inputStyle} />
          </>
        ) : (
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={inputStyle} />
        )}

        <label
          style={{ display: "flex", alignItems: "center", gap: 6, color: T.textSub, fontSize: 12, cursor: "pointer", ...mono }}
        >
          <input
            type="checkbox"
            checked={rangeMode}
            onChange={(e) => setRangeMode(e.target.checked)}
            style={{ cursor: "pointer" }}
          />
          date range
        </label>

        <ActionBtn label={loading ? "loading…" : "load"} onClick={() => load(true)} disabled={loading || !filterOrg} />

        {loading && progress.total > 0 && (
          <span style={{ color: T.textMuted, fontSize: 12, ...mono }}>
            {progress.done}/{progress.total} users
          </span>
        )}
        {dismissed.size > 0 && (
          <>
            <div style={{ flex: 1 }} />
            <ActionBtn
              label={`un-skip ${dismissed.size}`}
              color={T.textMuted}
              outline
              onClick={clearDismissed}
              title="Bring back rows dismissed with Keep / Skip (this browser only)"
            />
          </>
        )}
      </div>

      {!filterOrg && (
        <div style={{ color: T.textMuted, fontSize: 14, ...mono, paddingTop: 48, textAlign: "center" }}>
          select a firm to work its whole Needs-You queue in one list
        </div>
      )}

      {filterOrg && (
        <>
          {/* ── Summary ── */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, margin: "20px 0" }}>
            {(
              [
                ["Needs you", String(liveRows.length), liveRows.length > 0 ? T.yellow : T.green],
                ["Time waiting", fmtMin(totalMinutes), T.text],
                ["Users loaded", `${loadedUsers}/${slices.length}`, T.textSub],
                ["Clients", String(clients.length), T.textMuted],
              ] as [string, string, string][]
            ).map(([label, value, color]) => (
              <div key={label} style={{ ...card, marginBottom: 0, padding: 16 }}>
                <div
                  style={{
                    color: T.textMuted,
                    fontSize: 10,
                    letterSpacing: 2,
                    textTransform: "uppercase",
                    marginBottom: 6,
                    fontWeight: 600,
                  }}
                >
                  {label}
                </div>
                <div style={{ color, fontSize: 22, fontWeight: 700, ...mono }}>{value}</div>
              </div>
            ))}
          </div>

          {failedUsers.length > 0 && (
            <div style={{ ...card, borderColor: `${T.red}66`, background: `${T.red}0c`, fontSize: 12, ...mono, color: T.red }}>
              couldn't load {failedUsers.length} user{failedUsers.length > 1 ? "s" : ""}:{" "}
              {failedUsers.map((s) => memberName(s.member)).join(", ")}
            </div>
          )}

          {/* ── Filters ── */}
          <div style={{ ...card, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", padding: "12px 20px" }}>
            {(["all", "pending", "ambiguous", "mismatch", "split"] as const).map((k) => {
              const active = kindFilter === k;
              const meta = k === "all" ? { label: "all", color: T.text } : KIND_META[k];
              const n = k === "all" ? liveRows.length : counts[k];
              return (
                <button
                  key={k}
                  onClick={() => setKindFilter(k)}
                  style={{
                    background: active ? `${meta.color}22` : "transparent",
                    border: `1px solid ${active ? meta.color : T.border}`,
                    color: active ? meta.color : T.textSub,
                    padding: "5px 12px",
                    fontSize: 11.5,
                    cursor: "pointer",
                    borderRadius: 4,
                    ...mono,
                  }}
                >
                  {meta.label} <span style={{ color: T.textMuted }}>{n}</span>
                </button>
              );
            })}

            <div style={{ flex: 1 }} />

            <select
              value={userFilter}
              onChange={(e) => setUserFilter(e.target.value === "all" ? "all" : Number(e.target.value))}
              style={{ ...inputStyle, cursor: "pointer" }}
            >
              <option value="all">all users</option>
              {slices.map((s) => (
                <option key={s.member.user_id} value={s.member.user_id}>
                  {memberName(s.member)}
                </option>
              ))}
            </select>

            <label
              style={{ display: "flex", alignItems: "center", gap: 6, color: T.textSub, fontSize: 12, cursor: "pointer", ...mono }}
            >
              <input
                type="checkbox"
                checked={groupByUser}
                onChange={(e) => setGroupByUser(e.target.checked)}
                style={{ cursor: "pointer" }}
              />
              group by user
            </label>
          </div>

          {/* ── Queue ── */}
          {!loading && orderedRows.length === 0 && slices.length > 0 && (
            <div style={{ color: T.green, fontSize: 14, ...mono, padding: "40px 0", textAlign: "center" }}>
              ✓ nothing needs a human across {loadedUsers} user{loadedUsers === 1 ? "" : "s"}
            </div>
          )}

          {orderedRows.map((row) => {
            const meta = KIND_META[row.kind];
            const showWhoHeader = groupByUser && row.who !== lastWho;
            if (showWhoHeader) lastWho = row.who;
            const title = row.item.window_title;
            const context = renderContext(row);

            return (
              <div key={row.key}>
                {showWhoHeader && (
                  <div
                    style={{
                      color: T.textMuted,
                      fontSize: 11,
                      letterSpacing: 2,
                      textTransform: "uppercase",
                      fontWeight: 600,
                      margin: "18px 0 8px",
                    }}
                  >
                    {row.who}
                  </div>
                )}
                <div
                  style={{
                    ...card,
                    marginBottom: 6,
                    padding: "12px 16px",
                    borderLeft: `3px solid ${meta.color}`,
                    opacity: busy.has(row.key) ? 0.5 : 1,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    {!groupByUser && <Pill text={row.who} color={T.textSub} title={`user ${row.uid}`} />}
                    <Pill text={meta.label} color={meta.color} />
                    <span style={{ ...mono, fontSize: 12, color: T.teal, fontWeight: 600, minWidth: 46 }}>
                      {fmtMin(row.minutes)}
                    </span>
                    <span
                      style={{
                        color: T.text,
                        fontSize: 12.5,
                        flex: "1 1 320px",
                        minWidth: 200,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        ...mono,
                      }}
                      title={title}
                    >
                      {title || "(untitled)"}
                    </span>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{renderActions(row)}</div>
                  </div>

                  {context && <div style={{ marginTop: 6, paddingLeft: 2 }}>{context}</div>}

                  {picking === row.key && (
                    <ClientPicker
                      clients={clients}
                      onCancel={() => setPicking(null)}
                      onPick={(clientId, name) => {
                        const category =
                          row.kind === "pending"
                            ? row.item.proposed_category || "General Client Work"
                            : row.item.category || "General Client Work";
                        applyRow(
                          row,
                          clientId,
                          clientId == null ? "Personal/Non-Billable" : category,
                          name,
                          row.kind === "pending" ? "single_confirm" : undefined,
                        );
                      }}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
