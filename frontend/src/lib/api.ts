import { primeCsrf, getCookie } from "@/lib/csrf";

const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
export const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

export const API_ENDPOINTS = {
  whoami: `${API_BASE}/whoami/`,
  getCsrf: `${API_BASE}/get-csrf/`,
  timecardsSummaryDay: `${API_BASE}/timecards/summary/day/`,
  timecardsGenerate: `${API_BASE}/timecards/generate/`,
  blocksToday: `${API_BASE}/blocks-today/`,
  authLogin: `${API_BASE}/auth/login/`,
  authLogout: `${API_BASE}/auth/logout/`,
  authSignup: `${API_BASE}/auth/signup/`,
} as const;

// Safe JSON fetch
export async function safeFetchJson<T = any>(input: string, init: RequestInit = {}): Promise<T> {
  const makeHeaders = () => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      ...(init.headers as Record<string, string> | undefined),
    };
    if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes((init.method || "GET").toUpperCase())) {
      const token = getCookie("csrftoken");
      if (token) headers["X-CSRFToken"] = token;
    }
    return headers;
  };

  let res = await fetch(input, { credentials: "include", ...init, headers: makeHeaders() });

  if (res.status === 403) {
    try { await primeCsrf(); } catch {}
    res = await fetch(input, { credentials: "include", ...init, headers: makeHeaders() });
  }

  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    const body = ct.includes("json") ? await res.json().catch(() => ({})) : await res.text();
    throw new Error(`HTTP ${res.status}: ${JSON.stringify(body).slice(0, 200)}`);
  }

  return ct.includes("json") ? res.json() : ({} as T);
}