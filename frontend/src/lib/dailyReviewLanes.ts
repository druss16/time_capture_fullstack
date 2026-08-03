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
    count: number;
    minutes: number;
  };
};

const isInternalClientName = (name: string) => {
  const n = (name || "").trim().toLowerCase();
  return n === "internal" || n.startsWith("internal -");
};

const clientKeyOf = (clientId: number | null) => (clientId != null ? `id:${clientId}` : "none");

/**
 * Derive the two lanes from the raw today-time slices.
 * @param ignored  mismatch block_ids the user dismissed as false positives.
 */
export function deriveLanes(
  timeSummary: ClientCard[],
  proposedInline: ProposedInline[],
  mismatchBlocks: MismatchBlock[],
  ignored: Set<string>,
): Lanes {
  // Active (non-ignored) mismatches, indexed by the block they flag.
  const activeMismatch = mismatchBlocks.filter((m) => !ignored.has(String(m.block_id)));
  const mismatchIds = new Set(activeMismatch.map((m) => m.block_id));

  // Minutes pulled OUT of each booked client so the Certain browse total for
  // that client doesn't double-count the block now living in Needs-you.
  const mismatchMinByClient = new Map<string, number>();
  for (const m of activeMismatch) {
    const k = clientKeyOf(m.booked_client_id);
    mismatchMinByClient.set(k, (mismatchMinByClient.get(k) || 0) + (m.minutes || 0));
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
      const perLine = cat.sample_activities.length
        ? (cat.hours * 60) / cat.sample_activities.length
        : 0;
      for (const a of cat.sample_activities) {
        const p = parse(a);
        // A line whose block is flagged as a mismatch is shown in Needs-you, not here.
        if (p.blockIds.some((id) => mismatchIds.has(id))) continue;
        rows.push({ ids: p.blockIds, title: p.title, category: cat.name, minutes: Math.round(perLine) });
        catMinutes.set(cat.name, (catMinutes.get(cat.name) || 0) + perLine);
      }
    }

    if (!rows.length) continue; // whole client was mismatches -> nothing left to browse

    const pulled = mismatchMinByClient.get(key) || 0;
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
      blockCount: rows.length,
      repCategory,
      rows,
    });
    certainBlockCount += rows.length;
    certainMinutes += minutes;
    certainBillable += billableMinutes;
    certainNonBillable += nonBillableMinutes;
  }

  // Billable section first, then non-billable overhead; each by time desc.
  groups.sort((a, b) => {
    if (a.billable !== b.billable) return a.billable ? -1 : 1;
    return b.minutes - a.minutes;
  });

  // ── Needs-you lane: pending (minutes desc) + mismatch (minutes desc) ────────
  const pending = [...proposedInline].sort((a, b) => (b.minutes || 0) - (a.minutes || 0));
  const mismatch = [...activeMismatch].sort((a, b) => (b.minutes || 0) - (a.minutes || 0));
  const needsMinutes =
    pending.reduce((s, p) => s + (p.minutes || 0), 0) +
    mismatch.reduce((s, m) => s + (m.minutes || 0), 0);

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
      count: pending.length + mismatch.length,
      minutes: needsMinutes,
    },
  };
}
