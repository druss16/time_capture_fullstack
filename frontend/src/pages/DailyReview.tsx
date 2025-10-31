/**
 * DailyReview.tsx — Beta-ready (hardened)
 * - Buckets blocks into Client → Project with category rollups
 * - Uses AI if available; falls back to rule-based, then heuristics
 * - Saves classifications (chunked), learns from user corrections
 */

import { useEffect, useMemo, useState } from "react";
import { BlockDto } from "../types";
import { downloadTodayCsv, fetchBlocksToday } from "../api/blocks";
import BlockCard from "../components/BlockCard";
import Navigation from "../components/Navigation";

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
  const BAD = new Set(["none","unassigned","—","-","(none)"]);
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

async function classifyBlock(id: number, payload: { client?: string|null; project?: string|null; categories?: Record<string, number> }) {
  const client = cleanName(payload.client ?? null);
  const project = cleanName(payload.project ?? null);
  const categories = cleanCategories(payload.categories || {});
  if (!client && !project && Object.keys(categories).length === 0) return; // no-op

  const res = await fetch(`${API_BASE}/blocks/${id}/classify/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client, project, categories }),
  });
  if (!res.ok) {
    let detail = "";
    try { detail = JSON.stringify(await res.json()); }
    catch { detail = await res.text(); }
    console.warn(`[classifyBlock] ${id} -> ${res.status} ${res.statusText} :: ${detail}`);
  }
}


async function fetchWithTimeout(
  url: string,
  opts: RequestInit & { timeoutMs?: number } = {}
) {
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


// Lightweight heuristic when AI isn’t available
function heuristicSuggest(block: BlockDto) {
  const u = block.url || "";
  const h = (block as any).hints || {};
  const host = (() => {
    try {
      return u ? new URL(u).host.replace(/^www\./, "") : "";
    } catch {
      return "";
    }
  })();

  // Try browser-origin → repo → workspace → jira/github → hostname
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

  // Default category guess (HOURS)
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

// --------- main component ----------
export default function DailyReview() {
  const [blocks, setBlocks] = useState<LabeledBlock[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [autoClassifying, setAutoClassifying] = useState(false);

  // Core loader: ask server for suggestions (which compacts), then fetch blocks, merge, save best-effort
  const load = async () => {
    setBusy(true);
    try {
      setAutoClassifying(true);

      // 1) Suggestions: AI → rule-based → []
      let ai: AISuggestion[] = [];
      try {
        const r = await fetchWithTimeout(
          `${API_BASE}/blocks/suggestions/?timeout_ms=12000&limit=120`,
          { timeoutMs: 13000 }
        );
        if (r.ok) ai = await r.json();
        else throw new Error(`AI ${r.status}`);
      } catch {
        try {
          const r2 = await fetchWithTimeout(
            `${API_BASE}/blocks/suggestions/rule-based/?limit=120`,
            { timeoutMs: 6000 }
          );
          if (r2.ok) ai = await r2.json();
        } catch {
          ai = [];
        }
      }

      // 2) Today’s blocks (IDs should match what the server just compacted)
      const rawBlocks = await fetchBlocksToday();

      // 3) Merge AI (or heuristics) onto blocks
      const withAI: LabeledBlock[] = rawBlocks.map((b) => {
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

      setBlocks(withAI);

      // 4) Opportunistic save (chunked). Ignore non-OK responses; UI remains responsive.
      await bulkClassify(withAI, 12);
    } catch (e) {
      console.error("DailyReview load failed:", e);
      // Final fallback: show raw blocks with review needed
      const rawBlocks = await fetchBlocksToday();
      setBlocks(
        rawBlocks.map((b) => ({
          ...b,
          needs_review: true,
          ai_confidence: 0,
          categories: {},
        }))
      );
    } finally {
      setBusy(false);
      setAutoClassifying(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --------- bucket & rollups ----------
  type Bucket = {
    client: string;
    project: string | null;
    minutes: number;
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

      const ex = acc.get(key) || {
        client,
        project,
        minutes: 0,
        categories: {},
        blocks: [],
        highConfidenceCount: 0,
        needsReviewCount: 0,
      };

      ex.minutes += b.minutes || 0;

      // categories are in HOURS here
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

    // If no categories provided, backfill a single “General” bucket in HOURS
    acc.forEach((bucket) => {
      const hasAny = Object.keys(bucket.categories).length > 0;
      if (!hasAny) {
        const hours = safeNum(bucket.minutes, 0) / 60;
        bucket.categories["General"] = (bucket.categories["General"] || 0) + hours;
      }
    });

    return Array.from(acc.values()).sort((a, b) => b.minutes - a.minutes);
  }, [blocks]);

  const totalMinutes = useMemo(
    () => (blocks?.reduce((acc, b) => acc + (b.minutes || 0), 0) ?? 0),
    [blocks]
  );

  const stats = useMemo(() => {
    if (!blocks) return { total: 0, autoClassified: 0, needsReview: 0, highConfidence: 0 };
    return {
      total: blocks.length,
      autoClassified: blocks.filter((b) => (b.ai_confidence || 0) > 0).length,
      needsReview: blocks.filter((b) => b.needs_review).length,
      highConfidence: blocks.filter((b) => (b.ai_confidence || 0) >= 0.8).length,
    };
  }, [blocks]);

  // ---------- UI ----------
  const downloadCsv = async () => {
    const blob = await downloadTodayCsv();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "blocks_today.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Navigation />
      <div className="p-6 max-w-5xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Daily Review</h1>
            <p className="text-sm text-gray-600 mt-1">
              {autoClassifying
                ? "🤖 AI is auto-classifying your time blocks..."
                : "AI has labeled your time. Review and correct any mistakes."}
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={load} className="border rounded-lg px-4 py-2 hover:bg-gray-50">
              Refresh
            </button>
            <button onClick={downloadCsv} className="border rounded-lg px-4 py-2 hover:bg-gray-50">
              Export CSV
            </button>
          </div>
        </header>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-white rounded-lg border p-4">
            <div className="text-2xl font-bold">{stats.total}</div>
            <div className="text-sm text-gray-600">Total Blocks</div>
          </div>
          <div className="bg-green-50 rounded-lg border border-green-200 p-4">
            <div className="text-2xl font-bold text-green-700">{stats.autoClassified}</div>
            <div className="text-sm text-green-700">Auto-Classified</div>
          </div>
          <div className="bg-blue-50 rounded-lg border border-blue-200 p-4">
            <div className="text-2xl font-bold text-blue-700">{stats.highConfidence}</div>
            <div className="text-sm text-blue-700">High Confidence</div>
          </div>
          <div className="bg-yellow-50 rounded-lg border border-yellow-200 p-4">
            <div className="text-2xl font-bold text-yellow-700">{stats.needsReview}</div>
            <div className="text-sm text-yellow-700">Needs Review</div>
          </div>
        </div>

        {/* Suggested Timecard Summary */}
        {buckets.length > 0 && (
          <div className="bg-white border rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium text-lg">Suggested Timecard (by Client → Project)</h3>
              <div className="text-sm text-gray-600">
                <strong>Total: {minutesToHours(totalMinutes)} h</strong>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left p-2 border-b">Client</th>
                    <th className="text-left p-2 border-b">Project</th>
                    <th className="text-left p-2 border-b">Categories (hrs)</th>
                    <th className="text-right p-2 border-b">Total (hrs)</th>
                    <th className="text-right p-2 border-b">HC / Review</th>
                  </tr>
                </thead>
                <tbody>
                  {buckets.map((bk) => (
                    <tr key={`${bk.client}:${bk.project || "-"}`} className="hover:bg-gray-50">
                      <td className="p-2 border-b">{bk.client}</td>
                      <td className="p-2 border-b">{bk.project || "—"}</td>
                      <td className="p-2 border-b">
                        {Object.keys(bk.categories).length ? (
                          <div className="flex flex-wrap gap-2">
                            {Object.entries(bk.categories).map(([k, v]) => (
                              <span
                                key={k}
                                className="inline-flex items-center rounded-full border px-2 py-0.5"
                              >
                                <span className="mr-1">{k}</span>
                                <span className="font-medium">{safeNum(v, 0).toFixed(2)}h</span>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-500">—</span>
                        )}
                      </td>
                      <td className="p-2 border-b text-right font-medium">
                        {minutesToHours(bk.minutes)}
                      </td>
                      <td className="p-2 border-b text-right">
                        <span title="High Confidence / Needs Review">
                          {bk.highConfidenceCount} / {bk.needsReviewCount}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="font-semibold">
                    <td className="p-2 border-t">Total</td>
                    <td className="p-2 border-t"></td>
                    <td className="p-2 border-t"></td>
                    <td className="p-2 border-t text-right">{minutesToHours(totalMinutes)}</td>
                    <td className="p-2 border-t"></td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Tip: You can correct labels on the blocks below—your corrections train the model.
            </p>
          </div>
        )}

        {/* Total Time */}
        <div className="text-sm text-gray-600">
          {busy ? (
            "Loading..."
          ) : (
            <>
              <strong>Total: {minutesToHours(totalMinutes)} hours</strong> across{" "}
              {blocks?.length ?? 0} blocks
            </>
          )}
        </div>

        {/* Blocks List */}
        <div className="space-y-4">
          {blocks?.map((b) => (
            <BlockCard
              key={b.id}
              block={b}
              onLabeled={async (updatedData, originalSuggestion) => {
                // 1) Classify with the latest user choice (names)
                const clientName =
                  updatedData.client_name || updatedData.client || b.client_name || null;
                const projectName =
                  updatedData.project_name || updatedData.project || b.project_name || null;

                try {
                  await classifyBlock(b.id, {
                    client: clientName,
                    project: projectName,
                    categories: updatedData.category_hours || b.categories || {},
                  });
                } catch (err) {
                  console.error("Failed to classify block:", err);
                }

                // 2) Save a training example (optional, non-blocking)
                try {
                  await fetch(`${API_BASE}/settings/training/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      block_id: b.id,
                      text_content: `${b.title || ""} ${b.description || ""}`.trim(),
                      // If your API expects IDs instead of names, adapt here:
                      correct_client_id: updatedData.client_id,
                      correct_project_id: updatedData.project_id,
                      correct_categories: updatedData.category_hours || {},
                      original_prediction: originalSuggestion || {},
                    }),
                  });
                  console.log("✓ AI learned from your correction!");
                } catch (error) {
                  console.error("Failed to save training:", error);
                }

                // 3) Refresh
                await load();
              }}
            />
          ))}

          {!blocks?.length && !busy && (
            <div className="text-center py-12 text-gray-500">
              <p className="text-4xl mb-4">📅</p>
              <p>No blocks yet today.</p>
              <p className="text-sm mt-2">Your calendar events and activity will appear here automatically.</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
