/**
 * DailyReview.tsx — Beta-ready (hardened)
 * - Buckets blocks into Client → Project with category rollups
 * - Uses AI if available; falls back to rule-based, then heuristics
 * - Saves classifications (chunked), learns from user corrections
 * - Compacts overlapping time (overall + per-bucket) like TimecardSummary
 * - Treats idle as first-class: "Uncategorized - Idle" (excluded from review stats)
 * - Matches TimecardSummary's date/user scoping to keep totals in sync
 * - CSRF-safe POSTs with retry-after-prime
 */

import { useEffect, useMemo, useState, useCallback } from "react";
import {
  Clock,
  User,
  RefreshCw,
  Download,
  FileText,
  Send,
  BarChart3,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Header } from "@/components/common/Header";
import { DESIGN_SYSTEM } from "@/lib/design-system";
import { BlockDto } from "@/types";
import BlockCard from "@/components/BlockCard";
import { FilterBar, ErrorBanner } from "@/components/timecard";
import { todayIso } from "@/lib/utils/date";
import { getCookie, primeCsrf } from "@/lib/csrf";
import { useWhoAmI } from "@/lib/useWhoAmI"; // ← page-level hook use only

// Normalize API base so it always ends with /api
const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// ---------- helpers ----------
type AISuggestion = {
  block_id: number;
  ai_suggestion?: {
    client?: string | null;
    project?: string | null;
    categories?: Record<string, number>; // HOURS
    confidence?: number;
    needs_review?: boolean;
    reasoning?: string;
  };
};

type LabeledBlock = BlockDto & {
  client_name?: string | null;
  project_name?: string | null;
  categories?: Record<string, number>; // HOURS
  ai_confidence?: number;
  needs_review?: boolean;
  ai_reasoning?: string;
};

function titleCase(s?: string | null) {
  if (!s) return s ?? null;
  return s.trim().toLowerCase().replace(/\b\w/g, (m) => m.toUpperCase());
}
function safeNum(n: any, d = 0) {
  const x = Number(n);
  return Number.isFinite(x) ? x : d;
}
function minutesToHours(mins: number) {
  return (mins / 60).toFixed(2);
}
function cleanName(v?: string | null) {
  if (!v) return null;
  const t = String(v).trim();
  if (!t) return null;
  const BAD = new Set(["none", "unassigned", "—", "-", "(none)"]);
  if (BAD.has(t.toLowerCase())) return null;
  return t.slice(0, 120);
}
function cleanCategories(obj: Record<string, any> | undefined | null) {
  const out: Record<string, number> = {};
  if (!obj) return out;
  for (const [k, v] of Object.entries(obj)) {
    const s = String(v).toLowerCase().replace(/hrs?|h/g, "").trim();
    const f = Number(s);
    if (Number.isFinite(f) && f >= 0) out[String(k).trim()] = f;
  }
  return out;
}

async function fetchWithTimeout(url: string, opts: RequestInit & { timeoutMs?: number } = {}) {
  const { timeoutMs = 12000, ...rest } = opts;
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...rest, signal: ctrl.signal });
    return res;
  } finally {
    clearTimeout(id);
  }
}

// Centralized CSRF-safe POST helper with one retry after priming on 403
async function postJson(url: string, data: any, { timeoutMs = 15000 } = {}) {
  const doPost = async () => {
    const csrftoken = getCookie("csrftoken");
    return fetchWithTimeout(url, {
      method: "POST",
      credentials: "include",
      timeoutMs,
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrftoken || "",
        "X-Requested-With": "XMLHttpRequest",
      } as any,
      body: JSON.stringify(data),
    });
  };

  let res = await doPost();
  if (res.status === 403) {
    try { await primeCsrf(API_BASE); } catch {}
    res = await doPost();
  }
  return res;
}

// Sanitize categories to floats in HOURS (accepts "1.25", "1.25h", 1.25)
function sanitizeCategories(cats: Record<string, any> | undefined | null) {
  const out: Record<string, number> = {};
  if (!cats || typeof cats !== "object") return out;
  for (const [k, v] of Object.entries(cats)) {
    if (v == null) continue;
    const s = String(v).toLowerCase().replace(/h(rs)?$/i, "").trim();
    const num = Number(s);
    if (Number.isFinite(num) && num >= 0) out[k] = num;
  }
  return out;
}

async function classifyBlock(
  id: number,
  payload: { client?: string | null; project?: string | null; categories?: Record<string, number> }
) {
  const client = cleanName(payload.client ?? null);
  const project = cleanName(payload.project ?? null);
  const categories = cleanCategories(payload.categories || {});
  if (!client && !project && Object.keys(categories).length === 0) return; // no-op

  const res = await postJson(`${API_BASE}/blocks/${id}/classify/`, { client, project, categories });
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await res.json());
    } catch {
      detail = await res.text();
    }
    console.warn(`[classifyBlock] ${id} -> ${res.status} ${res.statusText} :: ${detail}`);
  }
}

async function bulkClassify(blocks: LabeledBlock[], chunkSize = 12) {
  const items = blocks.filter((b) => {
    const client = cleanName(b.client_name || null);
    const project = cleanName(b.project_name || null);
    const cats = cleanCategories(b.categories || {});
    return !!client || !!project || Object.keys(cats).length > 0;
  });

  for (let i = 0; i < items.length; i += chunkSize) {
    const slice = items.slice(i, i + chunkSize);
    await Promise.allSettled(
      slice.map((b) =>
        classifyBlock(b.id, {
          client: cleanName(b.client_name || null),
          project: cleanName(b.project_name || null),
          categories: cleanCategories(b.categories || {}),
        })
      )
    );
  }
}

// ---------- Idle helpers ----------
function isIdle(b: BlockDto) {
  const t = (b.window_title || (b as any).title || "").trim();
  return (b as any).bundle_id === "__idle__" || (b as any).app_name === "Idle" || t === "Uncategorized - Idle";
}

// Lightweight heuristic when AI isn't available (idle-aware)
function heuristicSuggest(block: BlockDto) {
  if (isIdle(block)) {
    const hours = safeNum(block.minutes ?? 0) / 60;
    return {
      client: null,
      project: null,
      categories: { "Uncategorized - Idle": hours },
      confidence: 1.0,
      needs_review: false,
      reasoning: "Idle time (mouse/keyboard inactivity).",
    };
  }

  const u = block.url || "";
  const h = (block as any).hints || {};
  const host = (() => {
    try {
      return u ? new URL(u).host.replace(/^www\./, "") : "";
    } catch {
      return "";
    }
  })();

  let client: string | null =
    (h.browser_origin?.replace(/^https?:\/\//, "").replace(/^www\./, "") as string | undefined) ||
    host ||
    null;
  if (client && client.includes("/")) client = client.split("/")[0];

  const project: string | null =
    h.github_repo ||
    h.workspace ||
    (h.repo_root ? String(h.repo_root).split("/").slice(-1)[0] : null) ||
    null;

  const hours = safeNum(block.minutes ?? 0) / 60;
  const categories: Record<string, number> = {};
  if (host?.includes("mail.google.com")) categories["Email"] = hours;
  else if (host?.includes("meet.google.com")) categories["Meetings"] = hours;
  else if (project) categories["Build/Dev"] = hours;
  else categories["General"] = hours;

  return {
    client: client ? titleCase(client) : null,
    project: project ? titleCase(project) : null,
    categories,
    confidence: 0.55,
    needs_review: true,
    reasoning: "Heuristic classification based on URL/hints.",
  };
}

// ---- time compaction helpers (minutes, no double-counting) ----
type WithSpan = { start?: string | Date; end?: string | Date };
function toEpoch(d?: string | Date) {
  if (!d) return NaN;
  try {
    return typeof d === "string" ? new Date(d).getTime() : (d as Date).getTime();
  } catch {
    return NaN;
  }
}
/** Returns union duration in **minutes** across all [start,end) intervals */
function unionMinutes(spans: WithSpan[]): number {
  const ranges = spans
    .map((s) => [toEpoch(s.start), toEpoch(s.end)] as const)
    .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && a < b)
    .sort((A, B) => A[0] - B[0]);

  let totalMs = 0;
  let curStart = -1,
    curEnd = -1;

  for (const [s, e] of ranges) {
    if (curStart < 0) {
      curStart = s;
      curEnd = e;
      continue;
    }
    if (s <= curEnd) {
      if (e > curEnd) curEnd = e; // extend
    } else {
      totalMs += curEnd - curStart;
      curStart = s;
      curEnd = e;
    }
  }
  if (curStart >= 0) totalMs += curEnd - curStart;
  return totalMs / 60000;
}

// Merge adjacent blocks that have identical (client, project, categories signature) and ≤ maxGap minutes gap
function catSig(cats?: Record<string, number>) {
  const entries = Object.entries(cats || {}).sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify(entries);
}
function compactBlocks(items: LabeledBlock[], maxGapMin = 2): LabeledBlock[] {
  if (!items?.length) return items || [];
  const sorted = [...items].sort((a, b) => +new Date(a.start as any) - +new Date(b.start as any));
  const out: LabeledBlock[] = [];
  for (const cur of sorted) {
    const last = out[out.length - 1];
    if (
      last &&
      (last.client_name || null) === (cur.client_name || null) &&
      (last.project_name || null) === (cur.project_name || null) &&
      catSig(last.categories) === catSig(cur.categories)
    ) {
      const gapMin = (+new Date(cur.start as any) - +new Date(last.end as any)) / 60000;
      if (gapMin <= maxGapMin) {
        last.end = cur.end;
        last.minutes = safeNum(last.minutes, 0) + safeNum(cur.minutes, 0);
        continue;
      }
    }
    out.push({ ...cur });
  }
  return out;
}

// ---------- API parity with TimecardSummary ----------
type BlockMeta = { id: number; start: string; end: string; minutes?: number; client_name?: string | null; project_name?: string | null };
async function fetchBlocksForDay(date: string, user: string) {
  const url = new URL(`${API_BASE}/blocks/today/`);
  url.searchParams.set("date", date);
  if (user?.trim()) url.searchParams.set("user", user.trim());
  const res = await fetch(url.toString(), { credentials: "include" });
  return res.ok ? ((await res.json()) as BlockMeta[]) : [];
}

export default function DailyReview() {
  // identity (page-level only)
  const me = useWhoAmI();
  const whoami = (me?.username || "").trim();

  const [blocks, setBlocks] = useState<LabeledBlock[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [autoClassifying, setAutoClassifying] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [user, setUser] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());

  // keep user in sync with whoami once it resolves
  useEffect(() => {
    if (!user && whoami) setUser(whoami);
  }, [whoami, user]);

  // Prime CSRF on mount (so POSTs have a cookie to send)
  useEffect(() => {
    (async () => { try { await primeCsrf(API_BASE); } catch {} })();
  }, []);

  // Core loader: suggestions (AI/rules) → fetch day blocks (scoped) → merge → compact → save
  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      setAutoClassifying(true);

      // 1) Suggestions: AI → rule-based → []
      let ai: AISuggestion[] = [];
      try {
        const sUrl = new URL(`${API_BASE}/blocks/suggestions/`);
        sUrl.searchParams.set("timeout_ms", "12000");
        sUrl.searchParams.set("limit", "160");
        sUrl.searchParams.set("date", date);
        if (user.trim()) sUrl.searchParams.set("user", user.trim());

        const r = await fetchWithTimeout(sUrl.toString(), { timeoutMs: 13000, credentials: "include" });
        if (r.ok) ai = await r.json();
        else throw new Error(`AI ${r.status}`);
      } catch {
        try {
          const r2 = await fetchWithTimeout(
            `${API_BASE}/blocks/suggestions/rule-based/?limit=160&date=${encodeURIComponent(date)}${
              user.trim() ? `&user=${encodeURIComponent(user.trim())}` : ""
            }`,
            { timeoutMs: 6000, credentials: "include" }
          );
          if (r2.ok) ai = await r2.json();
        } catch {
          ai = [];
        }
      }

      // 2) Day-scoped blocks (match Summary exactly)
      const dayBlocks = await fetchBlocksForDay(date, user);

      // 3) Merge AI (or heuristics) onto blocks
      const withAI: LabeledBlock[] = dayBlocks.map((b: any) => {
        const match = ai.find((s) => s.block_id === b.id);
        const picked =
          match?.ai_suggestion && (match.ai_suggestion.client || match.ai_suggestion.project)
            ? match.ai_suggestion
            : heuristicSuggest(b);

        return {
          ...b,
          client_name: picked.client || b.client_name || null,
          project_name: picked.project || b.project_name || null,
          categories: sanitizeCategories(picked.categories || {}),
          ai_confidence: safeNum(picked.confidence, 0),
          needs_review: Boolean(picked.needs_review ?? true),
          ai_reasoning: picked.reasoning || "",
        };
      });

      // 3.5) Trim micro-fragments (mirror backend if it drops very tiny slices)
      const MIN_KEEP_MIN = 0.05; // ~3 seconds
      const trimmed = withAI.filter((b) => safeNum(b.minutes, 0) >= MIN_KEEP_MIN);

      // 3.6) Merge adjacent same-signature blocks to reduce review noise
      const compacted = compactBlocks(trimmed, 2);

      setBlocks(compacted);

      // 4) Opportunistic save (chunked) — save compacted set
      await bulkClassify(compacted, 12);
    } catch (e: any) {
      console.error("DailyReview load failed:", e);
      setErr(e?.message || "Failed to load suggestions.");

      // Final fallback: raw day blocks with idle-aware defaults
      const raw = await fetchBlocksForDay(date, user);
      setBlocks(
        raw.map((b: any) => ({
          ...b,
          needs_review: !isIdle(b),
          ai_confidence: isIdle(b) ? 1 : 0,
          categories: isIdle(b) ? { "Uncategorized - Idle": safeNum(b.minutes ?? 0) / 60 } : {},
        }))
      );
    } finally {
      setBusy(false);
      setAutoClassifying(false);
    }
  }, [date, user]);

  // Auto-load on first render and when date/user changes
  useEffect(() => {
    const t = setTimeout(() => load(), 200);
    return () => clearTimeout(t);
  }, [load]);

  // --------- bucket & rollups ----------
  type Bucket = {
    client: string;
    project: string | null;
    minutes: number; // COMPACTED minutes (union of spans)
    categories: Record<string, number>; // HOURS
    blocks: LabeledBlock[];
    highConfidenceCount: number;
    needsReviewCount: number;
  };

  const buckets: Bucket[] = useMemo(() => {
    const acc = new Map<string, Bucket>();

    (blocks || []).forEach((b) => {
      const client = titleCase(b.client_name) || "Unassigned";
      const project = titleCase(b.project_name) || null;
      const key = `${client}::${project || "-"}`;

      const ex =
        acc.get(key) ||
        ({
          client,
          project,
          minutes: 0,
          categories: {},
          blocks: [],
          highConfidenceCount: 0,
          needsReviewCount: 0,
        } as Bucket);

      const cats = b.categories || {};
      Object.entries(cats).forEach(([k, v]) => {
        const cur = ex.categories[k] || 0;
        ex.categories[k] = cur + safeNum(v, 0);
      });

      ex.blocks.push(b);
      if ((b.ai_confidence || 0) >= 0.8) ex.highConfidenceCount += 1;
      if (b.needs_review) ex.needsReviewCount += 1;

      acc.set(key, ex);
    });

    acc.forEach((bucket) => {
      bucket.minutes = Math.round(
        unionMinutes(bucket.blocks.map((b) => ({ start: b.start as any, end: b.end as any })))
      );

      const hasAny = Object.keys(bucket.categories).length > 0;
      const bucketHasIdle = bucket.blocks.some((b) => isIdle(b));
      if (!hasAny) {
        const hours = safeNum(bucket.minutes, 0) / 60;
        if (bucketHasIdle) {
          bucket.categories["Uncategorized - Idle"] =
            (bucket.categories["Uncategorized - Idle"] || 0) + hours;
        } else {
          bucket.categories["General"] = (bucket.categories["General"] || 0) + hours;
        }
      }
    });

    return Array.from(acc.values()).sort((a, b) => b.minutes - a.minutes);
  }, [blocks]);

  // Compacted overall total minutes (global union)
  const totalMinutes = useMemo(() => {
    const arr = blocks ?? [];
    return Math.round(unionMinutes(arr.map((b) => ({ start: b.start as any, end: b.end as any }))));
  }, [blocks]);

  // Stats (exclude idle from auto/needs/high)
  const stats = useMemo(() => {
    if (!blocks) return { total: 0, autoClassified: 0, needsReview: 0, highConfidence: 0 };
    const notIdle = blocks.filter((b) => !isIdle(b));
    return {
      total: blocks.length,
      autoClassified: notIdle.filter((b) => (b.ai_confidence || 0) > 0).length,
      needsReview: notIdle.filter((b) => b.needs_review).length,
      highConfidence: notIdle.filter((b) => (b.ai_confidence || 0) >= 0.8).length,
    };
  }, [blocks]);

  // ---- overlap warning (client-side heuristic, diagnostic only)
  const rawTotalMins = (blocks ?? []).reduce((a, b) => a + (b.minutes || 0), 0);
  const hasSpan = (blocks ?? []).length > 0;
  const spanHours = hasSpan
    ? (Math.max(...(blocks ?? []).map((b) => +new Date(b.end as any))) -
        Math.min(...(blocks ?? []).map((b) => +new Date(b.start as any)))) /
      3600000
    : 0;
  const overlapRatio = spanHours ? rawTotalMins / 60 / spanHours : 1;
  const hasOverlap = overlapRatio > 1.15;

  // Create/generate timecard directly from Daily Review
  async function generateTimecard(status: "draft" | "pending" = "pending") {
    const actingUser = (user || whoami);
    if (!actingUser) {
      console.warn("Username not available, cannot generate timecard.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await postJson(`${API_BASE}/timecards/generate/`, { date, user: actingUser, status });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      console.log(`Timecard saved as ${status} successfully.`);
    } catch (e: any) {
      console.error("Timecard generation failed:", e);
      setErr(e?.message || "Failed to save timecard.");
    } finally {
      setBusy(false);
    }
  }

  // ---------- UI ----------
  const downloadCsvClick = async () => {
    const url = new URL(`${API_BASE}/blocks/export/csv`);
    url.searchParams.set("date", date);
    if (user?.trim()) url.searchParams.set("user", user.trim());
    const res = await fetch(url.toString(), { credentials: "include" });
    const blob = await res.blob();
    const link = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = link;
    a.download = `blocks_${date}.csv`;
    a.click();
    URL.revokeObjectURL(link);
  };

  const headerUser = useMemo(() => {
    return user?.trim() ? user.trim() : whoami?.trim() ? whoami : "All Users";
  }, [user, whoami]);

  return (
    <div className="min-h-screen bg-background">
      <Header
        title="Daily Review"
        subtitle={
          autoClassifying
            ? "🤖 AI is auto-classifying your time blocks..."
            : "AI has labeled your time. Review and correct any mistakes."
        }
        icon={<Clock className="w-6 h-6 text-primary-foreground" />}
        rightContent={
          headerUser && (
            <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-primary/20 to-accent/20 border border-primary/30 text-sm hover:border-primary/50 transition-all shadow-sm">
              <User className="w-4 h-4 text-primary" />
              <span className="font-semibold text-primary">{headerUser}</span>
            </div>
          )
        }
      />

      <div className={DESIGN_SYSTEM.spacing.container + " " + DESIGN_SYSTEM.spacing.section}>
        {/* Match Summary controls */}
        <FilterBar
          date={date}
          user={user}
          whoami={whoami}
          onDateChange={setDate}
          onUserChange={setUser}
          onRefresh={load}
          onDraft={undefined as any}
          onSubmit={undefined as any}
          isLoading={busy}
        />

        {hasOverlap && (
          <div className="mb-4 p-3 rounded-md border border-red-200 bg-red-50 text-red-700 text-sm">
            Totals may be inflated due to overlapping segments. Refresh after compaction.
          </div>
        )}

        {err && <ErrorBanner message={err} />}

        {/* Stats - colorful cards */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {/* Total Blocks */}
          <div className="bg-gradient-to-br from-primary-light to-white rounded-lg border border-primary/30 p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between mb-2">
              <BarChart3 className="w-5 h-5 text-primary" />
            </div>
            <div className="text-2xl font-bold text-primary">{stats.total}</div>
            <div className="text-sm text-primary">Total Blocks</div>
          </div>

          {/* Auto-Classified */}
          <div className="bg-gradient-to-br from-success-light to-white rounded-lg border border-success/30 p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between mb-2">
              <CheckCircle2 className="w-5 h-5 text-success" />
            </div>
            <div className="text-2xl font-bold text-success">{stats.autoClassified}</div>
            <div className="text-sm text-success">Auto-Classified</div>
          </div>

          {/* High Confidence */}
          <div className="bg-gradient-to-br from-info-light to-white rounded-lg border border-info/30 p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between mb-2">
              <CheckCircle2 className="w-5 h-5 text-info" />
            </div>
            <div className="text-2xl font-bold text-info">{stats.highConfidence}</div>
            <div className="text-sm text-info">High Confidence</div>
          </div>

          {/* Needs Review */}
          <div className="bg-gradient-to-br from-warning-light to-white rounded-lg border border-warning/30 p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between mb-2">
              <AlertCircle className="w-5 h-5 text-warning" />
            </div>
            <div className="text-2xl font-bold text-warning">{stats.needsReview}</div>
            <div className="text-sm text-warning">Needs Review</div>
          </div>
        </div>

        {/* Suggested Timecard Summary */}
        {buckets.length > 0 && (
          <div className="bg-card border border-border rounded-lg p-6 mb-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="font-semibold text-xl text-foreground flex items-center gap-2">
                  <FileText className="w-5 h-5 text-primary" />
                  Suggested Timecard
                </h3>
                <p className="text-sm text-muted-foreground mt-1">Grouped by Client → Project</p>
              </div>
              <div className="flex flex-col items-end gap-3">
                <div className="px-4 py-2 bg-primary-light rounded-lg border border-primary/30">
                  <span className="text-sm text-muted-foreground">Total Hours: </span>
                  <span className="text-lg font-bold text-primary">{minutesToHours(totalMinutes)}h</span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => generateTimecard("draft")}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/80 text-secondary-foreground border border-border transition-all disabled:opacity-50 shadow-sm hover:shadow-md"
                    disabled={busy}
                  >
                    <FileText className="w-4 h-4" />
                    Save as Draft
                  </button>
                  <button
                    onClick={() => generateTimecard("pending")}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground transition-all disabled:opacity-50 shadow-sm hover:shadow-md"
                    disabled={busy}
                  >
                    <Send className="w-4 h-4" />
                    Submit for Review
                  </button>
                </div>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted">
                  <tr>
                    <th className="text-left p-3 border-b border-border text-foreground font-semibold">Client</th>
                    <th className="text-left p-3 border-b border-border text-foreground font-semibold">Project</th>
                    <th className="text-left p-3 border-b border-border text-foreground font-semibold">Categories</th>
                    <th className="text-right p-3 border-b border-border text-foreground font-semibold">Total Hours</th>
                    <th className="text-center p-3 border-b border-border text-foreground font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {buckets.map((bk) => (
                    <tr key={`${bk.client}:${bk.project || "-"}`} className="hover:bg-accent/50 transition-colors">
                      <td className="p-3 border-b border-border">
                        <span className="font-medium text-foreground">{bk.client}</span>
                      </td>
                      <td className="p-3 border-b border-border text-muted-foreground">{bk.project || "—"}</td>
                      <td className="p-3 border-b border-border">
                        {Object.keys(bk.categories).length ? (
                          <div className="flex flex-wrap gap-2">
                            {Object.entries(bk.categories).map(([k, v]) => (
                              <span
                                key={k}
                                className="inline-flex items-center rounded-full border border-purple/30 bg-purple-light px-3 py-1 text-purple text-xs font-medium"
                              >
                                <span className="mr-1">{k}</span>
                                <span className="font-bold">{safeNum(v, 0).toFixed(2)}h</span>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="p-3 border-b border-border text-right">
                        <span className="font-bold text-primary text-base">{minutesToHours(bk.minutes)}h</span>
                      </td>
                      <td className="p-3 border-b border-border text-center">
                        <div className="flex items-center justify-center gap-3">
                          <span className="inline-flex items-center gap-1 text-xs">
                            <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                            <span className="text-success font-medium">{bk.highConfidenceCount}</span>
                          </span>
                          <span className="inline-flex items-center gap-1 text-xs">
                            <AlertCircle className="w-3.5 h-3.5 text-warning" />
                            <span className="text-warning font-medium">{bk.needsReviewCount}</span>
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-muted">
                  <tr className="font-semibold">
                    <td className="p-3 border-t border-border text-foreground">Total</td>
                    <td className="p-3 border-t border-border"></td>
                    <td className="p-3 border-t border-border"></td>
                    <td className="p-3 border-t border-border text-right text-primary text-lg">
                      {minutesToHours(totalMinutes)}h
                    </td>
                    <td className="p-3 border-t border-border"></td>
                  </tr>
                </tfoot>
              </table>
            </div>

            <div className="mt-4 p-3 bg-info-light border border-info/30 rounded-lg flex items-start gap-2">
              <BarChart3 className="w-4 h-4 text-info flex-shrink-0 mt-0.5" />
              <p className="text-xs text-info">
                <strong>Tip:</strong> You can correct labels on the blocks below—your corrections train the AI model to
                improve future predictions.
              </p>
            </div>
          </div>
        )}

        {/* Total Time Summary */}
        <div className="mb-4 p-4 bg-gradient-to-r from-primary-light to-accent-light border border-primary/30 rounded-lg shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-primary" />
              {busy ? (
                <span className="text-muted-foreground">Loading...</span>
              ) : (
                <>
                  <span className="text-2xl font-bold text-primary">{minutesToHours(totalMinutes)}h</span>
                  <span className="text-muted-foreground">across {blocks?.length ?? 0} blocks</span>
                </>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={downloadCsvClick}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card hover:bg-info/10 text-card-foreground border border-border transition-all shadow-sm hover:shadow-md hover:border-info/30"
              >
                <Download className="w-4 h-4 text-info" />
                <span>Export CSV</span>
              </button>
              <button
                onClick={load}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card hover:bg-accent/10 text-card-foreground border border-border transition-all disabled:opacity-50 shadow-sm hover:shadow-md"
                disabled={busy}
              >
                <RefreshCw className={`w-4 h-4 ${busy ? "animate-spin text-primary" : ""}`} />
                <span>Refresh</span>
              </button>
            </div>
          </div>
        </div>

        {/* Blocks List */}
        <div className="space-y-4">
          {blocks?.map((b) => (
            <BlockCard
              key={b.id}
              block={b}
              onLabeled={async (updatedData, originalSuggestion) => {
                const clientName = updatedData.client_name || updatedData.client || b.client_name || null;
                const projectName = updatedData.project_name || updatedData.project || b.project_name || null;

                try {
                  await classifyBlock(b.id, {
                    client: clientName,
                    project: projectName,
                    categories: updatedData.category_hours || b.categories || {},
                  });
                } catch (err) {
                  console.error("Failed to classify block:", err);
                }

                // Optional training signal (non-blocking)
                try {
                  const res = await postJson(`${API_BASE}/settings/training/`, {
                    block_id: b.id,
                    text_content: `${(b as any).title || ""} ${(b as any).description || ""}`.trim(),
                    correct_client_id: (updatedData as any).client_id,
                    correct_project_id: (updatedData as any).project_id,
                    correct_categories: updatedData.category_hours || {},
                    original_prediction: originalSuggestion || {},
                  });
                  if (!res.ok) console.warn("Training save failed", res.status);
                } catch (error) {
                  console.error("Failed to save training:", error);
                }

                await load();
              }}
            />
          ))}

          {!blocks?.length && !busy && (
            <div className="text-center py-16 bg-card border border-border rounded-lg shadow-sm">
              <div className="w-16 h-16 bg-primary-light rounded-full flex items-center justify-center mx-auto mb-4">
                <Clock className="w-8 h-8 text-primary" />
              </div>
              <p className="text-xl font-semibold text-foreground mb-2">No blocks yet</p>
              <p className="text-sm text-muted-foreground max-w-md mx-auto">
                Your calendar events and activity will appear here automatically as you work throughout the day.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}