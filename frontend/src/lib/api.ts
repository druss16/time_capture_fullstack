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
  // ── Org + user impersonation override ───────────────────────────────────
  const impersonatingOrgId  = localStorage.getItem("impersonating_org_id");
  const impersonatingUserId = localStorage.getItem("impersonating_user_id");
  if (impersonatingOrgId) {
    try {
      const u = new URL(input, window.location.origin);
      u.searchParams.set("org_id", impersonatingOrgId);
      if (impersonatingUserId) u.searchParams.set("user_id", impersonatingUserId);
      input = u.toString();
    } catch {}
  }

  const makeHeaders = () => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      ...(init.headers as Record<string, string> | undefined),
    };

    const token = localStorage.getItem('auth_token');
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
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
    throw new Error(extractErrorMessage(body));
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
    
    // Add Authorization header with token (if exists)
    const token = localStorage.getItem('auth_token');
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    
    // Add CSRF token for POST requests
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
    throw new Error(extractErrorMessage(body));
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
    throw new Error(extractErrorMessage(body));
  }
  
  return ct.includes("json") ? res.json() : ({} as T);
}