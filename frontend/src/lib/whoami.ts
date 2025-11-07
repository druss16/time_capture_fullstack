// src/lib/whoami.ts
function resolveApiBase() {
  const raw = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123";
  const noTrail = raw.replace(/\/+$/, "");
  return noTrail.endsWith("/api") ? noTrail : `${noTrail}/api`;
}
const API_BASE = resolveApiBase();

export type WhoAmI = {
  username?: string;
  is_authenticated: boolean;
  auth_source?: "agent" | "session" | "cookie" | "cookie_legacy" | "ip" | "unknown";
  [k: string]: any;
};

let cached: WhoAmI | null = null;
let inflight: Promise<WhoAmI> | null = null;

// small helper
async function tryFetch(url: string, init: RequestInit, retries = 2): Promise<Response> {
  for (let i = 0; i <= retries; i++) {
    try {
      const r = await fetch(url, init);
      return r;
    } catch (e) {
      if (i === retries) throw e;               // bubble last one
      await new Promise(r => setTimeout(r, 250)); // tiny backoff
    }
  }
  // ts appeasement
  return new Response(null, { status: 599 });
}

export async function fetchWhoAmI(force = false): Promise<WhoAmI> {
  if (cached && !force) return cached;
  if (inflight) return inflight;

  inflight = tryFetch(`${API_BASE}/whoami/`, {
    credentials: "include",
    headers: { "X-Requested-With": "XMLHttpRequest" },
  })
    .then(async (r) => (r.ok ? ((await r.json()) as WhoAmI) : ({ is_authenticated: false } as WhoAmI)))
    .catch(() => ({ is_authenticated: false } as WhoAmI))
    .then((j) => {
      if (typeof j.is_authenticated !== "boolean") j.is_authenticated = false;
      cached = j;
      return cached!;
    })
    .finally(() => { inflight = null; });

  return inflight;
}

export function primeWhoAmIFromCache() { return cached; }
export function clearWhoAmICache() { cached = null; inflight = null; }

// src/lib/whoami.ts (or wherever it lives)
export function isTrulyAuthenticated(me?: { is_authenticated?: boolean; auth_source?: string } | null) {
  if (!me) return false;
  // Only session or agent count as a login
  if (me.is_authenticated === true) return true;
  if (me.auth_source === "session" || me.auth_source === "agent") return true;
  return false;
}