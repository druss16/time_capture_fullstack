import { primeCsrf, getCookie } from "@/lib/csrf";
import { getViewAs, shouldAttachViewAs, VIEW_AS_HEADER } from "@/lib/viewAs";

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

// ============================================================================
// v1.3.61 AUTH FIXES
// 1. Never attach the Authorization header to auth/CSRF endpoints — sending a
//    stale token to /auth/login/ makes DRF reject the request with 403 before
//    the view runs, wedging the login page in a retry loop.
// 2. When the API says the token is expired/invalid, clear stored tokens and
//    send the user to /login ONCE — never retry-loop with a dead token.
// ============================================================================

const TOKEN_STORAGE_KEYS = ["auth_token", "tt_auth_token", "authToken", "token"];

/** Endpoints that must be called WITHOUT an Authorization header. */
function isAuthEndpoint(input: string): boolean {
  return (
    input.includes("/auth/login") ||
    input.includes("/auth/signup") ||
    input.includes("/get-csrf")
  );
}

/** True if an error body indicates a dead token (expired or invalid). */
function isTokenDeadError(message: string): boolean {
  return /token/i.test(message) && /(expired|invalid)/i.test(message);
}

/** Clear stored tokens and route to login. Safe to call from anywhere. */
export function handleTokenExpired(): void {
  TOKEN_STORAGE_KEYS.forEach((k) => localStorage.removeItem(k));
  // Avoid a redirect loop if we're already on the login page.
  if (!window.location.pathname.startsWith("/login")) {
    const next = encodeURIComponent(
      window.location.pathname + window.location.search
    );
    window.location.href = `/login?next=${next}`;
  }
}

// ============================================================================
// Error message extractor — converts raw API error bodies into human-readable strings
// Handles: Django custom errors, DRF detail/non_field_errors, plain text, etc.
// ============================================================================
function extractErrorMessage(body: any): string {
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch {}
  }
  if (typeof body === "object" && body !== null) {
    return (
      body.error ||
      body.detail ||
      body.message ||
      body.non_field_errors?.[0] ||
      "Something went wrong."
    );
  }
  return "Something went wrong. Please try again.";
}

// ============================================================================
// Safe JSON fetch with token-based auth
// ============================================================================
export async function safeFetchJson<T = any>(input: string, init: RequestInit = {}): Promise<T> {
  const makeHeaders = () => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      ...(init.headers as Record<string, string> | undefined),
    };

    // ── MavOps "View as" ──────────────────────────────────────────────────
    // The server swaps request.user during authentication, so this one header
    // is the entire client contract — no per-endpoint ?org_id=/?user_id= to
    // append, and no view left behind because it never opted in.
    // installViewAsFetch() also covers callers that bypass this helper; setting
    // it here too means the header is present even before that patch installs.
    const viewAs = getViewAs();
    if (viewAs && shouldAttachViewAs(input)) {
      headers[VIEW_AS_HEADER] = viewAs.userId;
    }

    // v1.3.61: never send the token to auth endpoints — a stale token there
    // causes a 403 before the login view ever runs.
    if (!isAuthEndpoint(input)) {
      const token = localStorage.getItem("auth_token");
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    }

    if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes((init.method || "GET").toUpperCase())) {
      const csrfToken = getCookie("csrftoken");
      if (csrfToken) headers["X-CSRFToken"] = csrfToken;
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
    const message = extractErrorMessage(body);

    // v1.3.61: dead token → clear storage + go to login. No retry loops.
    if ((res.status === 401 || res.status === 403) && isTokenDeadError(message)) {
      handleTokenExpired();
    }

    throw new Error(message);
  }
  return ct.includes("json") ? res.json() : ({} as T);
}

// ============================================================================
// Safe file upload with token-based auth
// Use this for FormData uploads (CSV, images, etc.)
// Does NOT set Content-Type - browser sets it automatically with boundary
// ============================================================================
export async function safeUploadFile<T = any>(
  url: string,
  file: File,
  fieldName = 'file',
  additionalFields?: Record<string, string>
): Promise<T> {
  const formData = new FormData();
  formData.append(fieldName, file);

  // Add any additional form fields
  if (additionalFields) {
    Object.entries(additionalFields).forEach(([key, value]) => {
      formData.append(key, value);
    });
  }

  const makeHeaders = () => {
    const headers: Record<string, string> = {
      "Accept": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      // IMPORTANT: Do NOT set Content-Type here!
      // Browser sets it automatically to multipart/form-data with correct boundary
    };

    const token = localStorage.getItem('auth_token');
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const csrfToken = getCookie("csrftoken");
    if (csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }

    return headers;
  };

  let res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: makeHeaders(),
    body: formData,
  });

  // Retry with fresh CSRF if 403
  if (res.status === 403) {
    try { await primeCsrf(); } catch {}
    res = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: makeHeaders(),
      body: formData,
    });
  }

  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    const body = ct.includes("json") ? await res.json().catch(() => ({})) : await res.text();
    const message = extractErrorMessage(body);
    if ((res.status === 401 || res.status === 403) && isTokenDeadError(message)) {
      handleTokenExpired();
    }
    throw new Error(message);
  }

  return ct.includes("json") ? res.json() : ({} as T);
}

// ============================================================================
// Safe FormData fetch (for more complex uploads with multiple files or fields)
// ============================================================================
export async function safeUploadFormData<T = any>(
  url: string,
  formData: FormData
): Promise<T> {
  const makeHeaders = () => {
    const headers: Record<string, string> = {
      "Accept": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      // IMPORTANT: Do NOT set Content-Type - browser sets it with boundary
    };

    const token = localStorage.getItem('auth_token');
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const csrfToken = getCookie("csrftoken");
    if (csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }

    return headers;
  };

  let res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: makeHeaders(),
    body: formData,
  });

  if (res.status === 403) {
    try { await primeCsrf(); } catch {}
    res = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: makeHeaders(),
      body: formData,
    });
  }

  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    const body = ct.includes("json") ? await res.json().catch(() => ({})) : await res.text();
    const message = extractErrorMessage(body);
    if ((res.status === 401 || res.status === 403) && isTokenDeadError(message)) {
      handleTokenExpired();
    }
    throw new Error(message);
  }

  return ct.includes("json") ? res.json() : ({} as T);
}