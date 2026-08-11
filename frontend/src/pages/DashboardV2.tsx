/**
 * DashboardV2 — top-level page for /analytics.
 *
 * Lifecycle:
 *   1. Read URL params → AnalyticsQueryBody
 *   2. Fire useAnalyticsQuery() with that body
 *   3. Render Sidebar + ViewSentence + Sections
 *   4. Any sidebar change → update URL → useEffect rebuilds query body
 *
 * URL is the source of truth. Bookmarks, shared links, back/forward all work.
 */
import { useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/design-system";

import { useAnalyticsQuery } from "@/hooks/useAnalyticsQuery";
import {
  parseUrlState, serializeUrlState,
} from "@/lib/analytics_v2/urlState";
import type { AnalyticsQueryBody, KPITilePayload } from "@/lib/analytics_v2/types";

import Sidebar from "@/components/Sidebar";
import ViewSentence from "@/components/ViewSentence";
import EmptyStateInvoiceless from "@/components/EmptyStateInvoiceless";
import KPITile from "@/components/primitives/KPITile";
import ChartCard from "@/components/primitives/ChartCard";
import DataTable from "@/components/primitives/DataTable";
import InsightCard from "@/components/primitives/InsightCard";
import SectionHeader from "@/components/primitives/SectionHeader";

export default function DashboardV2() {
  const location = useLocation();
  const navigate = useNavigate();

  // Derive query body from URL
  const body = useMemo<AnalyticsQueryBody>(
    () => parseUrlState(location.search),
    [location.search],
  );

  // Fire the query
  const { data, error, isLoading, isFetching, refetch } = useAnalyticsQuery(body);

  // Sidebar change handler → updates URL → triggers re-parse and re-fetch
  const handleSidebarChange = useCallback((next: Partial<AnalyticsQueryBody>) => {
    const merged: AnalyticsQueryBody = {
      scope: next.scope ?? body.scope,
      lens: next.lens ?? body.lens,
      time: next.time ?? body.time,
      compare: next.compare !== undefined ? next.compare : body.compare,
    };
    const search = serializeUrlState(merged);
    navigate({ pathname: "/analytics", search: search ? `?${search}` : "" });
  }, [body, navigate]);

  // Drilldown handler (KPI tile or insight card click)
  const handleDrilldown = useCallback((drilldown: {
    scope: AnalyticsQueryBody["scope"];
    lens: AnalyticsQueryBody["lens"];
  }) => {
    handleSidebarChange({ scope: drilldown.scope, lens: drilldown.lens });
  }, [handleSidebarChange]);

  // ─── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="flex min-h-[calc(100vh-64px)] -mx-4 -my-6">
      <Sidebar body={body} onChange={handleSidebarChange} />

      <main
        className="flex-1 min-w-0"
        style={{ backgroundColor: "#eef4f3", fontFamily: '"Inter", sans-serif' }}
      >
        <ViewSentence
          sentence={data?.view?.sentence ?? ""}
          generatedAt={data?.meta?.generated_at}
          dataFreshness={data?.meta?.data_freshness}
          isFetching={isFetching}
          onRefresh={() => refetch()}
        />

        <div className="px-6 py-6 space-y-6">
          {/* Loading state — only when there's no cached data at all */}
          {isLoading && (
            <div className="flex items-center justify-center py-24 text-slate-400">
              <Loader2 className="h-6 w-6 animate-spin mr-2" />
              <span className="text-sm">Loading dashboard…</span>
            </div>
          )}

          {/* Error state */}
          {error && (
            <ErrorPanel error={error} onRetry={() => refetch()} />
          )}

          {/* Sections — render each in turn */}
          {data && (
            <SectionRenderer
              body={body}
              data={data}
              onDrilldown={handleDrilldown}
            />
          )}
        </div>
      </main>
    </div>
  );
}

// ─── Section dispatcher ─────────────────────────────────────────────────────

function SectionRenderer({
  body, data, onDrilldown,
}: {
  body: AnalyticsQueryBody;
  data: NonNullable<ReturnType<typeof useAnalyticsQuery>["data"]>;
  onDrilldown: (d: any) => void;
}) {
  // Override: realization lens for invoice-less firms shows the empty state
  // instead of "0% realization across the board." The meta flag is populated
  // by the backend patches.
  if (body.lens === "realization" && data.meta?.invoiceless) {
    return <EmptyStateInvoiceless metric="realization" />;
  }
  if (body.lens === "trends" && data.meta?.invoiceless) {
    return <EmptyStateInvoiceless metric="trends" />;
  }

  return (
    <>
      {data.sections.map(section => {
        if (section.type === "kpi_row") {
          return (
            <div key={section.id} className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {section.tiles.map(tile => (
                <KPITile key={tile.id} tile={tile} onDrilldown={onDrilldown} />
              ))}
            </div>
          );
        }

        return (
          <section key={section.id} className="space-y-3">
            {section.title && <SectionHeader title={section.title} />}
            {section.children.map(child => {
              if (child.type === "kpi_tile") {
                return <KPITile key={child.id} tile={child as KPITilePayload} onDrilldown={onDrilldown} />;
              }
              if (child.type === "chart_card") {
                return <ChartCard key={child.id} card={child} />;
              }
              if (child.type === "data_table") {
                return <DataTable key={child.id} table={child} />;
              }
              if (child.type === "insight_card") {
                return <InsightCard key={child.id} card={child} onDrilldown={onDrilldown} />;
              }
              return null;
            })}
          </section>
        );
      })}
    </>
  );
}

// ─── Error panel ────────────────────────────────────────────────────────────

function ErrorPanel({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const message = error.message || "Something went wrong";
  const isPermissionError = /403|permission/i.test(message);

  return (
    <div className="rounded-[15px] border border-rose-200 bg-rose-50/40 p-6">
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-rose-900">
            {isPermissionError ? "Access denied" : "Couldn't load dashboard"}
          </h3>
          <p className="mt-1 text-xs text-rose-700 leading-relaxed">{message}</p>
          {!isPermissionError && (
            <button
              onClick={onRetry}
              className="mt-3 text-xs font-medium text-rose-900 underline underline-offset-2 hover:no-underline"
            >
              Try again
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
