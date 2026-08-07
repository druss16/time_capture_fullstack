import { lazy, type ComponentType } from "react";

// One-time reload guard key. After a deploy, hashed chunk filenames change and
// an already-open tab will 404 when it tries to fetch an old chunk. We reload
// once to pick up the fresh index.html; the sessionStorage flag stops a loop
// if the reload somehow doesn't resolve the failure.
const RELOAD_FLAG = "chunk-reload-attempted";

function isChunkLoadError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  return (
    /Loading chunk [\d]+ failed/i.test(msg) ||
    /Loading CSS chunk/i.test(msg) ||
    /Failed to fetch dynamically imported module/i.test(msg) ||
    /error loading dynamically imported module/i.test(msg) ||
    /Importing a module script failed/i.test(msg)
  );
}

/**
 * Drop-in replacement for React.lazy that recovers from stale-chunk failures
 * after a deploy. On a chunk-load error it triggers a single full-page reload
 * (which re-fetches the current index.html and its up-to-date chunk hashes)
 * instead of leaving the user on a blank screen.
 *
 * Uses `ComponentType<any>` to match React.lazy's own constraint so per-page
 * prop types (e.g. BillingPage's `section`) are preserved at the call site.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyWithRetry<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>
) {
  return lazy(async () => {
    try {
      const mod = await factory();
      // Success — clear the guard so future deploys can reload again.
      window.sessionStorage.removeItem(RELOAD_FLAG);
      return mod;
    } catch (err) {
      if (isChunkLoadError(err)) {
        const alreadyTried = window.sessionStorage.getItem(RELOAD_FLAG);
        if (!alreadyTried) {
          window.sessionStorage.setItem(RELOAD_FLAG, "1");
          window.location.reload();
          // Return a never-resolving promise so nothing renders before reload.
          return new Promise<{ default: T }>(() => {});
        }
      }
      throw err;
    }
  });
}
