// src/lib/viewAs.ts
/**
 * MavOps "View as" — client side.
 *
 * The server swaps identity during authentication (see tracker/impersonation.py),
 * so the only thing the client owes it is one header on every API request:
 *
 *     X-View-As-User: <user id>
 *
 * Getting that header onto *every* request is the whole problem. The app has
 * ~70 modules going through safeFetchJson and another ~43 calling fetch()
 * directly, so threading it through helpers by hand would leave holes — which
 * is exactly how the first version of this feature ended up working on some
 * pages and not others. installViewAsFetch() patches window.fetch once at boot
 * instead, so a request cannot escape it no matter which helper made it.
 */

const KEY_USER_ID = "impersonating_user_id";
const KEY_USER_NAME = "impersonating_user_name";
const KEY_ORG_ID = "impersonating_org_id";
const KEY_ORG_NAME = "impersonating_org_name";

export const VIEW_AS_HEADER = "X-View-As-User";

/**
 * Paths that must always run as the real admin. The MavOps console is the one
 * the admin uses to *stop* viewing as someone — sending the header there would
 * lock them out of it, since the target user is not staff. localStorage is
 * shared across tabs, so this matters the moment a second tab is open.
 * The server enforces the same list; this keeps the client honest too.
 */
const NEVER_VIEW_AS = ["/api/mavops/", "/api/support/", "/api/auth/"];

export interface ViewAsSession {
  userId: string;
  userName: string;
  orgId: string | null;
  orgName: string | null;
}

/** The active view-as session, or null when the admin is being themselves. */
export function getViewAs(): ViewAsSession | null {
  try {
    const userId = localStorage.getItem(KEY_USER_ID);
    if (!userId) return null;
    return {
      userId,
      userName: localStorage.getItem(KEY_USER_NAME) || `user ${userId}`,
      orgId: localStorage.getItem(KEY_ORG_ID),
      orgName: localStorage.getItem(KEY_ORG_NAME),
    };
  } catch {
    return null;
  }
}

export function startViewAs(s: ViewAsSession): void {
  localStorage.setItem(KEY_USER_ID, s.userId);
  localStorage.setItem(KEY_USER_NAME, s.userName);
  if (s.orgId) localStorage.setItem(KEY_ORG_ID, s.orgId);
  if (s.orgName) localStorage.setItem(KEY_ORG_NAME, s.orgName);
}

export function stopViewAs(): void {
  [KEY_USER_ID, KEY_USER_NAME, KEY_ORG_ID, KEY_ORG_NAME].forEach((k) =>
    localStorage.removeItem(k),
  );
}

/** True when `url` is an API call that should carry the header. */
export function shouldAttachViewAs(url: string): boolean {
  let path: string;
  try {
    const u = new URL(url, window.location.origin);
    // Never attach to a third party — the header is meaningless to them and
    // naming a user id to an unrelated host is a leak.
    const apiOrigin = new URL(
      import.meta.env.VITE_API_BASE_URL || "http://localhost:7123",
      window.location.origin,
    ).origin;
    if (u.origin !== apiOrigin && u.origin !== window.location.origin) return false;
    path = u.pathname;
  } catch {
    path = url;
  }
  if (!path.includes("/api/")) return false;
  return !NEVER_VIEW_AS.some((p) => path.includes(p));
}

/** Extract a request URL from either fetch() call signature. */
function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

let installed = false;

/**
 * Attach the view-as header to every API request the app makes, from anywhere.
 * Idempotent; safe to call more than once. When no view-as is active this is a
 * pass-through, so normal sessions behave exactly as before.
 */
export function installViewAsFetch(): void {
  if (installed || typeof window === "undefined" || !window.fetch) return;
  installed = true;

  const original = window.fetch.bind(window);

  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const session = getViewAs();
    if (!session || !shouldAttachViewAs(urlOf(input))) {
      return original(input as RequestInfo, init);
    }

    // Merge into whatever headers the caller already built, preserving them.
    // Headers may arrive as a Headers instance, an array of pairs, or a plain
    // object — and on a Request object rather than in init.
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    headers.set(VIEW_AS_HEADER, session.userId);

    return original(input as RequestInfo, { ...(init || {}), headers });
  }) as typeof window.fetch;
}
