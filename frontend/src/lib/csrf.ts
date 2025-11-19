// src/lib/csrf.ts
const DEFAULT_API_BASE = (() => {
  const raw = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123";
  const base = raw.replace(/\/+$/, "");
  return base.endsWith("/api") ? base : `${base}/api`;
})();

/** Hit /api/get-csrf/ and store token in sessionStorage */
export async function primeCsrf(apiBase?: string) {
  const base = (apiBase || DEFAULT_API_BASE).replace(/\/+$/, "");
  try {
    const response = await fetch(`${base}/get-csrf/`, {
      credentials: "include",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    
    const data = await response.json();
    
    // ✅ Store token in sessionStorage (fallback for blocked cookies)
    if (data.csrfToken) {
      sessionStorage.setItem('csrfToken', data.csrfToken);
    }
  } catch {
    // swallow; we'll retry on 403 during POST
  }
}

export function getCookie(name: string) {
  // Try cookie first
  const cookieValue = document.cookie
    .split("; ")
    .find((row) => row.startsWith(name + "="))
    ?.split("=")[1];
  
  if (cookieValue) return cookieValue;
  
  // ✅ Fallback to sessionStorage if cookie blocked
  if (name === 'csrftoken') {
    return sessionStorage.getItem('csrfToken') || undefined;
  }
  
  return undefined;
}

/** Small helper used by callers. Retries once after priming CSRF. */
export async function postJson(
  url: string,
  data: any,
  opts: { timeoutMs?: number; retryApiBase?: string } = {}
) {
  const { timeoutMs = 15000, retryApiBase } = opts;
  
  const fetchWithTimeout = async (u: string, init: RequestInit) => {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(u, { ...init, signal: ctrl.signal });
    } finally {
      clearTimeout(id);
    }
  };
  
  const doPost = async () => {
    const csrftoken = getCookie("csrftoken") || "";
    return fetchWithTimeout(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrftoken,
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(data),
    });
  };
  
  let res = await doPost();
  if (res.status === 403) {
    try { 
      await primeCsrf(retryApiBase || DEFAULT_API_BASE); 
    } catch {}
    res = await doPost();
  }
  return res;
}