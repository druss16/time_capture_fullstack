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
import type { Client, TeamMember } from "@/pages/settings/types";

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
    // Filters MUST be in the key. They change the answer to every question on
    // the page, so leaving them out would serve the unfiltered response from
    // cache while the control bar showed a filter as applied.
    stableFilters(body.scope.filters),
    typeof body.time.value === "string" ? body.time.value : JSON.stringify(body.time.value),
    body.compare
      ? (typeof body.compare.value === "string"
          ? body.compare.value
          : JSON.stringify(body.compare.value))
      : "no_compare",
    // Grain changes the chart's rows AND its window, so it is a different
    // response, not a different rendering of one.
    body.grain ?? "auto",
  ];
}

/** Key-sorted, id-sorted rendering of the filters so equal sets hash equal. */
function stableFilters(filters: AnalyticsQueryBody["scope"]["filters"]): string {
  if (!filters) return "";
  return Object.keys(filters)
    .sort()
    .map(k => {
      const v = (filters as Record<string, unknown>)[k];
      return Array.isArray(v)
        ? `${k}:${[...(v as number[])].sort((a, b) => a - b).join(",")}`
        : `${k}:${String(v)}`;
    })
    .join("|");
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
 * Client list for the "By client" scope picker. Reuses the Settings clients
 * endpoint. Only fetched when the user is allowed to pick clients (pass the
 * capability flag as `enabled`) so we don't hit the API for members who can't.
 */
export function useAnalyticsClients(enabled: boolean) {
  return useQuery<Client[], Error>({
    queryKey: ["analytics_v2_clients"],
    queryFn: () => safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`),
    enabled,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

/**
 * Team/staff list for the "By staff" scope picker. Reuses the Settings team
 * endpoint. Gated on the can_pick_any_staff capability via `enabled`.
 */
export function useAnalyticsStaff(enabled: boolean) {
  return useQuery<TeamMember[], Error>({
    queryKey: ["analytics_v2_staff"],
    queryFn: () => safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`),
    enabled,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

/** Project list for the Project filter. */
export function useAnalyticsProjects(enabled: boolean) {
  return useQuery<Array<{ id: number; name: string; client: number | null }>, Error>({
    queryKey: ["analytics_v2_projects"],
    queryFn: () => safeFetchJson(`${API_BASE}/options/projects/`),
    enabled,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });
}

/** Task types — "Category" in the UI — for the Category filter. */
export function useAnalyticsCategories(enabled: boolean) {
  return useQuery<Array<{ id: number; name: string; code?: string }>, Error>({
    queryKey: ["analytics_v2_categories"],
    queryFn: () => safeFetchJson(`${API_BASE}/options/task-types/`),
    enabled,
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
