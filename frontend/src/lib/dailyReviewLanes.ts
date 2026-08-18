/**
 * dailyReviewLanes.ts — pure derivation of the Daily Review confidence lanes.
 *
 * The redesign (see the redesign spec) leads with the small set of blocks that
 * genuinely need a human, and files everything else quietly. This module turns
 * the raw today-time payload into the two lanes the screen renders, so the page
 * header ("N need you") and the lane body are computed from ONE source and can
 * never disagree.
 *
 * Lanes (the "Pretty sure / Filed for you" middle lane from the spec is folded
 * into Needs-you — real TL Wall data showed it was ~3% of minutes, not worth a
 * separate surface, and conservative auto-file keeps those one tap away anyway):
 *
 *   CERTAIN   — committed (auto-filed). Collapsed by default; browse by client.
 *   NEEDS YOU — pending (pick-a-client / one-tap accept) + mismatch (title names
 *               a different client than booked -> red "Move to X").
 */
import { parse, type ClientTime, type ProposedInline } from "@/components/CategorySummary";

/** Rich mismatch row from today-time's `mismatch_blocks`. */
export type MismatchBlock = {
  block_id: number;
  window_title: string;
  minutes: number;
  category: string;
  booked_client_id: number | null;
  booked_client_name: string;
  looks_like_client_id: number | null;
  looks_like_client_name: string;
};

/** One activity slice inside a split candidate (title → its own client guess). */
export type SplitSlice = {
  label: string;
  minutes: number;
  suggested_client_id: number | null;
  suggested_client_name: string | null;
  /** Category for THIS slice. A no-client block's slices don't all want the
   *  same one: the ones that name a client become billable work, the leftovers
   *  stay in the non-billable bucket the block already sits in. Absent on older
   *  backends — callers fall back to the candidate's category. */
  suggested_category?: string;
};

/** A committed block whose activities point at 2+ clients → offer a split. */
export type SplitCandidate = {
  block_id: number;
  window_title: string;
  minutes: number;
  category: string;
  booked_client_id: number | null;
  booked_client_name: string;
  slices: SplitSlice[];
};

/** One captured activity line inside a Certain client group. */
export type CertainRow = { ids: number[]; title: string; category: string; minutes: number };

/** A whole client's auto-filed work — the unit the Certain lane browses / moves. */
export type CertainGroup = {
  key: string;
  clientId: number | null;
  name: string;
  internal: boolean;      // firm-internal client -> dimmed, non-billable
  unassigned: boolean;    // committed with no client (overhead / browsing)
  minutes: number;        // display minutes = committed total minus any mismatch pulled out
  billableMinutes: number;     // per-client billable minutes (from today-time)
  nonBillableMinutes: number;  // per-client non-billable minutes
  billable: boolean;      // which section this group belongs in
  blockCount: number;     // number of captured lines shown
  repCategory: string;    // dominant category (for the Move popover default)
  rows: CertainRow[];
};

/** today-time client cards now carry a per-client billable split. */
type ClientCard = ClientTime & { billable_hours?: number; non_billable_hours?: number };

export type Lanes = {
  certain: {
    groups: CertainGroup[];
    blockCount: number;
    minutes: number;
    billableMinutes: number;
    nonBillableMinutes: number;
  };
  needsYou: {
    pending: ProposedInline[];  // guessed + no-guess, minutes desc
    mismatch: MismatchBlock[];  // minutes desc
    split: SplitCandidate[];    // multi-client blocks to split, minutes desc
    count: number;
    minutes: number;
  };
};

const isInternalClientName = (name: string) => {
  const n = (name || "").trim().toLowerCase();
  return n === "internal" || n.startsWith("internal -");
};

/** A block the user JUST confirmed, to show under its client instantly (before
 *  the slow today-time reload lands). Reconciled away once the block appears in
 *  the real payload. */
export type OptimisticConfirm = {
  blockId: number;
  clientId: number | null;
  clientName: string;
  category: string;
  minutes: number;
  title: string;
};

const NONBILLABLE_CAT = /non-?billable|personal/i;

/**
 * Fold just-confirmed blocks into the Certain lane so they appear under their
 * client the instant they're confirmed — no waiting on today-time. Adds to an
 * existing client group or creates one; skips a block already present from a
 * real reload (so it can never double-count during the brief overlap window).
 */
export function mergeOptimisticConfirms(lanes: Lanes, confirms: OptimisticConfirm[]): Lanes {
  if (!confirms.length) return lanes;
  const groups: CertainGroup[] = lanes.certain.groups.map((g) => ({ ...g, rows: [...g.rows] }));
  const byKey = new Map(groups.map((g) => [g.key, g]));
  let dMin = 0, dBill = 0, dNon = 0, dCount = 0;
  for (const c of confirms) {
    const key = clientKeyOf(c.clientId);
    let g = byKey.get(key);
    if (g && g.rows.some((r) => r.ids.includes(c.blockId))) continue; // already in from a reload
    const internal = isInternalClientName(c.clientName);
    const billable = c.clientId != null && !internal && !NONBILLABLE_CAT.test(c.category);
    const row: CertainRow = { ids: [c.blockId], title: c.title || "(entry)", category: c.category, minutes: c.minutes };
    if (!g) {
      g = {
        key, clientId: c.clientId,
        name: c.clientId == null ? "No client" : (c.clientName || "Client"),
        internal, unassigned: c.clientId == null,
        minutes: 0, billableMinutes: 0, nonBillableMinutes: 0,
        billable, blockCount: 0, repCategory: c.category, rows: [],
      };
      byKey.set(key, g);
      groups.push(g);
    }
    g.rows.unshift(row);
    g.minutes += c.minutes;
    g.blockCount += 1;
    if (billable) g.billableMinutes += c.minutes; else g.nonBillableMinutes += c.minutes;
    g.billable = g.billableMinutes > 0;
    dMin += c.minutes; dCount += 1;
    if (billable) dBill += c.minutes; else dNon += c.minutes;
  }
  groups.sort((a, b) => {
    if (a.billable !== b.billable) return a.billable ? -1 : 1;
    return b.minutes - a.minutes;
  });
  return {
    ...lanes,
    certain: {
      groups,
      blockCount: lanes.certain.blockCount + dCount,
      minutes: lanes.certain.minutes + dMin,
      billableMinutes: lanes.certain.billableMinutes + dBill,
      nonBillableMinutes: lanes.certain.nonBillableMinutes + dNon,
    },
  };
}

const clientKeyOf = (clientId: number | null) => (clientId != null ? `id:${clientId}` : "none");

// Within one client, fold rows whose title is identical once the trailing
// per-block "(Nm)" duration tag is stripped — the same file/activity should be
// ONE line, not one per block. The tag is stripped from the DISPLAYED title in
// both cases: the row's minutes column now carries that same real duration (see
// deriveLanes), so leaving it inline would print the number twice. Grouped by
// title alone so identical titles always pair (rows are already per-client,
// never crosses clients). Display-only: the client's total minutes / billable
// are untouched.
const stripDurTag = (t: string) => t.replace(/\s*\(\d+m\)\s*$/i, "").trim();
const parseDurTag = (t: string): number => {
  const m = t.match(/\((\d+)m\)\s*$/i);
  return m ? parseInt(m[1], 10) : 0;
};
function mergeRowsByTitle(rows: CertainRow[]): CertainRow[] {
  type Acc = { ids: number[]; base: string; category: string; minutes: number };
  const accs: Acc[] = [];
  const idx = new Map<string, number>();
  for (const r of rows) {
    const base = stripDurTag(r.title);
    const key = base.toLowerCase();
    const at = idx.get(key);
    if (at === undefined) {
      idx.set(key, accs.length);
      accs.push({ ids: [...r.ids], base, category: r.category, minutes: r.minutes });
    } else {
      const a = accs[at];
      a.ids = [...a.ids, ...r.ids];
      a.minutes += r.minutes;
    }
  }
  return accs.map((a) => ({
    ids: a.ids,
    category: a.category,
    minutes: a.minutes,
    title: a.base,
  }));
}

/**
 * Derive the two lanes from the raw today-time slices.
 * @param ignored  mismatch block_ids the user dismissed as false positives.
 */
export function deriveLanes(
  timeSummary: ClientCard[],
  proposedInline: ProposedInline[],
  mismatchBlocks: MismatchBlock[],
  ignored: Set<string>,
  splitCandidates: SplitCandidate[] = [],
): Lanes {
  // Active (non-ignored) mismatches, indexed by the block they flag.
  const activeMismatch = mismatchBlocks.filter((m) => !ignored.has(String(m.block_id)));
  const activeSplit = splitCandidates.filter((s) => !ignored.has(String(s.block_id)));
  // Blocks pulled out of the Certain browse (shown in Needs-you instead).
  const pulledIds = new Set<number>([
    ...activeMismatch.map((m) => m.block_id),
    ...activeSplit.map((s) => s.block_id),
  ]);

  // Minutes pulled OUT of each booked client so the Certain browse total for
  // that client doesn't double-count the block now living in Needs-you.
  const pulledMinByClient = new Map<string, number>();
  for (const row of [...activeMismatch, ...activeSplit]) {
    const k = clientKeyOf(row.booked_client_id);
    pulledMinByClient.set(k, (pulledMinByClient.get(k) || 0) + (row.minutes || 0));
  }

  // ── Certain lane: one group per committed client card ──────────────────────
  const groups: CertainGroup[] = [];
  let certainBlockCount = 0;
  let certainMinutes = 0;
  let certainBillable = 0;
  let certainNonBillable = 0;

  for (const client of timeSummary) {
    const key = clientKeyOf(client.client_id);
    const rows: CertainRow[] = [];
    const catMinutes = new Map<string, number>();

    for (const cat of client.categories) {
      // Each row shows its OWN real duration, straight off `cat.activities`.
      //
      // Two worse sources this replaced, in order: (1) categoryTotal / lineCount,
      // an even split that invented every number on screen and smeared the time
      // of activities past today-time's top-10 cap into the survivors; (2) the
      // "(Nm)" tag parsed back out of the display string, which is right for
      // sub-hour rows but unparseable for the "1h" / "1.5h" form the backend
      // emits at 60m+ — those silently fell back to the even split, and 1.5h
      // can't express 92m anyway.
      //
      // The tag parse survives ONLY as the pre-`activities` backend fallback:
      // frontend and backend deploy separately, so a new bundle can briefly talk
      // to an old API. It now understands the hour forms too.
      const perLine = cat.sample_activities.length
        ? (cat.hours * 60) / cat.sample_activities.length
        : 0;
      const lines: { ids: number[]; title: string; minutes: number }[] =
        cat.activities?.length
          ? cat.activities.map((a) => ({ ids: a.ids, title: a.title, minutes: a.minutes }))
          : cat.sample_activities.map((a) => {
              const p = parse(a);
              const tagged = parseDurTag(p.title);
              return { ids: p.blockIds, title: p.title, minutes: tagged > 0 ? tagged : Math.round(perLine) };
            });
      for (const line of lines) {
        // A line whose block is flagged (mismatch or split) is shown in Needs-you.
        if (line.ids.some((id) => pulledIds.has(id))) continue;
        rows.push({ ids: line.ids, title: line.title, category: cat.name, minutes: line.minutes });
        catMinutes.set(cat.name, (catMinutes.get(cat.name) || 0) + line.minutes);
      }
    }

    if (!rows.length) continue; // whole client was mismatches -> nothing left to browse

    // Collapse identical-title rows (same file → one line, not one per block),
    // then order the whole client by size. Rows arrive category by category, so
    // without this the durations reset partway down the list (1h, 42m, 31m …
    // 5m, 3m, 15m, 12m) and the biggest item in a client isn't findable by eye —
    // which is the question this lane exists to answer.
    const mergedRows = mergeRowsByTitle(rows).sort((a, b) => b.minutes - a.minutes);

    const pulled = pulledMinByClient.get(key) || 0;
    const minutes = Math.max(0, Math.round(client.total_hours * 60 - pulled));
    // Per-client billable split. Prefer today-time's exact per-client figures;
    // when the backend hasn't shipped them yet (fields absent), fall back to a
    // heuristic — a real (non-internal) client's time is billable, internal /
    // no-client overhead is not — so the split still works. Mismatch minutes
    // (pulled into Needs-you) come off billable, since booked time is billable.
    const hasBackendSplit =
      client.billable_hours !== undefined || client.non_billable_hours !== undefined;
    const inferBillable = client.client_id != null && !isInternalClientName(client.client);
    const billableMinutes = hasBackendSplit
      ? Math.max(0, Math.round((client.billable_hours ?? 0) * 60 - pulled))
      : Math.max(0, (inferBillable ? minutes : 0));
    const nonBillableMinutes = hasBackendSplit
      ? Math.max(0, Math.round((client.non_billable_hours ?? 0) * 60))
      : (inferBillable ? 0 : minutes);
    const repCategory =
      [...catMinutes.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ||
      client.categories[0]?.name ||
      "General Client Work";

    groups.push({
      key,
      clientId: client.client_id,
      name: client.client_id == null ? "No client" : client.client,
      internal: isInternalClientName(client.client),
      unassigned: client.client_id == null,
      minutes,
      billableMinutes,
      nonBillableMinutes,
      // A group is billable if it holds any billable time (a real client's work);
      // internal / no-client overhead has none and falls to the non-billable section.
      billable: billableMinutes > 0,
      blockCount: mergedRows.length,
      repCategory,
      rows: mergedRows,
    });
    certainBlockCount += mergedRows.length;
    certainMinutes += minutes;
    certainBillable += billableMinutes;
    certainNonBillable += nonBillableMinutes;
  }

  // Billable section first, then non-billable overhead; each by time desc.
  groups.sort((a, b) => {
    if (a.billable !== b.billable) return a.billable ? -1 : 1;
    return b.minutes - a.minutes;
  });

  // ── Needs-you lane: pending + mismatch + split (each minutes desc) ──────────
  const pending = [...proposedInline].sort((a, b) => (b.minutes || 0) - (a.minutes || 0));
  const mismatch = [...activeMismatch].sort((a, b) => (b.minutes || 0) - (a.minutes || 0));
  const split = [...activeSplit].sort((a, b) => (b.minutes || 0) - (a.minutes || 0));
  const needsMinutes =
    pending.reduce((s, p) => s + (p.minutes || 0), 0) +
    mismatch.reduce((s, m) => s + (m.minutes || 0), 0) +
    split.reduce((s, x) => s + (x.minutes || 0), 0);

  return {
    certain: {
      groups,
      blockCount: certainBlockCount,
      minutes: certainMinutes,
      billableMinutes: certainBillable,
      nonBillableMinutes: certainNonBillable,
    },
    needsYou: {
      pending,
      mismatch,
      split,
      count: pending.length + mismatch.length + split.length,
      minutes: needsMinutes,
    },
  };
}
