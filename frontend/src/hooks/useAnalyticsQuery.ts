/**
 * useAnalyticsQuery — TanStack Query hook for /api/analytics/query/
 *
 * Behaviors:
 *   - Stale-while-revalidate: shows last-good data while refetching
 *   - Window-focus refetch (refetchOnWindowFocus: true — default)
 *   - 30s staleTime: avoids hammering the API on rapid re-renders
 *   - 5min cacheTime: keeps data warm across nav for snappier returns
 *   - Manual refresh: refetch() exposed for the refresh button
 *
 * The QueryClient is provided at the app root (App.tsx), so this just plugs in.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, safeFetchJson } from "@/lib/api";
import { primeCsrf } from "@/lib/csrf";
import type {
  AnalyticsQueryBody,
  AnalyticsResponse,
  PermissionsResponse,
} from "@/lib/analytics_v2/types";

/**
 * Hit POST /api/analytics/query/ with a request body.
 * safeFetchJson handles tokens, CSRF, and impersonation transparently.
 */
async function fetchAnalytics(body: AnalyticsQueryBody): Promise<AnalyticsResponse> {
  // Ensure CSRF token is primed for the POST. safeFetchJson retries on 403,
  // but priming up-front avoids the wasteful round-trip.
  try { await primeCsrf(); } catch { /* swallow — retry will handle */ }

  return safeFetchJson<AnalyticsResponse>(`${API_BASE}/analytics/query/`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * Stable cache key builder. Two identical query bodies produce the same
 * cache key, so multiple components asking for the same data share one
 * network request.
 */
function buildKey(body: AnalyticsQueryBody) {
  return [
    "analytics_v2",
    body.lens,
    body.scope.type,
    body.scope.ids.slice().sort().join(","),
    typeof body.time.value === "string" ? body.time.value : JSON.stringify(body.time.value),
    body.compare
      ? (typeof body.compare.value === "string"
          ? body.compare.value
          : JSON.stringify(body.compare.value))
      : "no_compare",
  ];
}

export function useAnalyticsQuery(body: AnalyticsQueryBody) {
  const query = useQuery<AnalyticsResponse, Error>({
    queryKey: buildKey(body),
    queryFn: () => fetchAnalytics(body),
    staleTime: 30_000,          // 30s — data considered fresh
    gcTime: 5 * 60_000,         // 5m — keep in cache after unmount
    refetchOnWindowFocus: true,
    retry: 1,                   // One retry on transient failures
  });

  return {
    data: query.data,
    error: query.error,
    isLoading: query.isLoading,        // First-time load (no data yet)
    isFetching: query.isFetching,      // Any in-flight request (incl. background refetch)
    isStale: query.isStale,
    refetch: query.refetch,
  };
}

/**
 * GET /api/analytics/permissions/ — used by the sidebar to know what the
 * user can pick. Long staleTime since this rarely changes.
 */
export function useAnalyticsPermissions() {
  return useQuery<PermissionsResponse, Error>({
    queryKey: ["analytics_v2_permissions"],
    queryFn: () => safeFetchJson<PermissionsResponse>(`${API_BASE}/analytics/permissions/`),
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

/**
 * Invalidate every analytics_v2 query in the cache. Call after a manual data
 * change elsewhere (e.g. user just imported invoices).
 */
export function useInvalidateAnalytics() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["analytics_v2"] });
}
