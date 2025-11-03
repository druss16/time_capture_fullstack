// src/api/blocks.ts
import { BlockDto } from "../types";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

export async function fetchBlocksToday(): Promise<BlockDto[]> {
  try {
    const response = await fetch(`${API_BASE}/blocks/today`);
    if (!response.ok) {
      throw new Error(`Failed to fetch blocks: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    console.error("Error fetching blocks:", error);
    return [];
  }
}

export async function downloadTodayCsv(): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/blocks/today/csv`);
    if (!response.ok) {
      throw new Error(`Failed to download CSV: ${response.statusText}`);
    }
    
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `timetrack_${new Date().toISOString().split("T")[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  } catch (error) {
    console.error("Error downloading CSV:", error);
    throw error;
  }
}

export async function classifyBlock(
  id: number,
  payload: { client?: string | null; project?: string | null; categories?: Record<string, number> }
): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/blocks/${id}/classify`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    
    if (!response.ok) {
      throw new Error(`Failed to classify block: ${response.statusText}`);
    }
  } catch (error) {
    console.error("Error classifying block:", error);
    throw error;
  }
}
