// src/lib/http.ts
export async function safeFetchJson(input: RequestInfo, init?: RequestInit) {
  const res = await fetch(input, init);
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* html or empty */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.error)) || text.slice(0, 200);
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${detail}`);
  }
  return data ?? {};
}