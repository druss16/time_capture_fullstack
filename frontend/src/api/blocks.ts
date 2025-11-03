import api, { API_ROUTES } from "./client";
import { BlockDto } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:7123/api";
export async function fetchRecentBlocks(me = false, limit = 25) {
  const u = new URL(`${API_BASE}/recent-blocks/`);
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

export type LabelPayload = {
  block_id: number;
  client?: string;
  project?: string;
  task?: string;
  notes?: string;
  create_rule?: boolean;
  create_rule_field?: "client" | "project" | "task";
  create_rule_value?: string;
  pattern?: string;
  kind?: "contains" | "regex" | "equals";
};

export async function labelBlock(payload: LabelPayload) {
  await api.post(API_ROUTES.labelBlock, payload);
}

export async function downloadTodayCsv(): Promise<Blob> {
  const { data } = await api.get(API_ROUTES.exportBlocksCsv, { responseType: "blob" });
  return data as Blob;
}

// Add this function to your api/blocks.ts file

export async function aiSuggestLabels(blockId: number) {
  const response = await fetch(`http://localhost:7123/api/ai-suggest/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
    body: JSON.stringify({ block_id: blockId }),
  });

  if (!response.ok) {
    throw new Error("Failed to get AI suggestions");
  }

  return response.json();
}