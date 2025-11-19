// api/blocks.ts
import api, { API_ROUTES } from "./client";
import { BlockDto } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";

// --- helpers ---
function fullUrlOrRoute(route: string | undefined, fallbackPath: string) {
  // If API_ROUTES gives a full URL, use it. If it gives a relative path, let axios baseURL handle it.
  // If undefined, fall back to absolute URL using API_BASE.
  if (!route) return `${API_BASE.replace(/\/+$/, "")}${fallbackPath}`;
  return route;
}

// -------- fetchers --------
export async function fetchRecentBlocks(me = false, limit = 25) {
  // Leave this as a direct fetch (you had it this way already)
  const u = new URL(`${API_BASE.replace(/\/+$/, "")}/recent-blocks/`);
  if (me) u.searchParams.set("me", "1");
  u.searchParams.set("limit", String(limit));
  const r = await fetch(u.toString(), { credentials: "include" });
  if (!r.ok) throw new Error(`Failed: ${r.status}`);
  return r.json();
}

export async function fetchBlocksToday(): Promise<BlockDto[]> {
  const { data } = await api.get<BlockDto[]>(API_ROUTES.blocksToday);
  return data;
}

export async function fetchSuggestionsToday(): Promise<BlockDto[]> {
  const { data } = await api.get<BlockDto[]>(API_ROUTES.suggestionsToday);
  return data;
}

// -------- labeling --------
export type LabelPayload = {
  block_id: number;
  client?: string | null;
  project?: string | null;
  /**
   * Category hours in HOURS (numbers), e.g. { "Email": 0.5, "Meetings": 1.25 }
   * DO NOT send for “pure idle”; skip posting in the UI for idle-only blocks.
   */
  categories?: Record<string, number>;
  notes?: string;
  // (Optional legacy rule maker flags — safe to keep, backend can ignore)
  create_rule?: boolean;
  create_rule_field?: "client" | "project" | "task";
  create_rule_value?: string;
  pattern?: string;
  kind?: "contains" | "regex" | "equals";
};

export async function labelBlock(payload: LabelPayload) {
  // Backend: path("label-block/", views.label_block, name="label_block"),
  const url = fullUrlOrRoute(API_ROUTES?.labelBlock, "/label-block/");
  // NOTE: axios 'api' already has baseURL; if API_ROUTES.labelBlock is relative, axios will prefix it.
  // If API_ROUTES.labelBlock is missing, we fall back to absolute `${API_BASE}/label-block/`.
  const res = await api.post(url, payload);
  return res.data ?? {};
}

// -------- exports --------
export async function downloadTodayCsv(): Promise<Blob> {
  const { data } = await api.get(API_ROUTES.exportBlocksCsv, { responseType: "blob" });
  return data as Blob;
}

// Optional: AI suggestion endpoint (kept, but made robust to baseURL)
export async function aiSuggestLabels(blockId: number) {
  const url = fullUrlOrRoute(API_ROUTES?.aiSuggest, "/ai-suggest/");
  const { data } = await api.post(url, { block_id: blockId });
  return data;
}