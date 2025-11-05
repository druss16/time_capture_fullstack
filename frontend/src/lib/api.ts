// src/lib/api.ts
const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
export const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

export const API_ENDPOINTS = {
  authLogin:  `${API_BASE}/auth/login/`,
  authLogout: `${API_BASE}/auth/logout/`,
  authSignup: `${API_BASE}/auth/signup/`,
  whoami:     `${API_BASE}/whoami/`,
  getCsrf:    `${API_BASE}/get-csrf/`,
  timecardsSummaryDay: `${API_BASE}/timecards/summary/day/`,
  blocksToday:         `${API_BASE}/blocks-today/`,
  timecardsGenerate:   `${API_BASE}/timecards/generate/`,

  // ...other endpoints you already have...
} as const;

// ---- cookie + CSRF helpers ----
function getCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}
function needsBodyCsrf(method?: string) {
  const m = (method || "GET").toUpperCase();
  return !["GET", "HEAD", "OPTIONS", "TRACE"].includes(m);
}

/** GET once to seed csrftoken cookie. Safe to call multiple times. */
let _csrfPrimed: Promise<void> | null = null;
export function primeCsrf(): Promise<void> {
  if (_csrfPrimed) return _csrfPrimed;
  _csrfPrimed = fetch(API_ENDPOINTS.getCsrf, { credentials: "include" })
    .then(() => void 0)
    .catch(() => void 0);
  return _csrfPrimed;
}

// ---- robust JSON fetch (adds X-CSRFToken for non-GET) ----
export async function safeFetchJson<T = any>(input: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Accept": "application/json",            // <— add this
    ...(init.headers as Record<string, string> | undefined),
  };

  if (needsBodyCsrf(init.method)) {
    const token = getCookie("csrftoken");
    if (token) headers["X-CSRFToken"] = token;
  }

  const res = await fetch(input, { credentials: "include", ...init, headers });
  const ct = res.headers.get("content-type") || "";

  if (!res.ok) {
    if (ct.includes("application/json")) {
      const j = await res.json().catch(() => ({}));
      const msg = j?.error || j?.detail || JSON.stringify(j) || res.statusText;
      throw new Error(`HTTP ${res.status} ${res.statusText}: ${msg}`);
    }
    const t = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${t.slice(0, 400)}`);
  }

  if (ct.includes("application/json")) return (await res.json()) as T;
  const txt = await res.text();
  return (txt ? (JSON.parse(txt) as T) : ({} as T));
}