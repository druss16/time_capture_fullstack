import api, { API_ROUTES } from "./client";
import { BlockDto } from "../types";

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
