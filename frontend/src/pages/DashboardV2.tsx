/**
 * Analytics — the executive dashboard at /analytics.
 *
 * Lifecycle:
 *   1. URL params → AnalyticsQueryBody
 *   2. useAnalyticsQuery() fires with that body
 *   3. Backend returns typed sections; this file renders them
 *   4. Any control change → new URL → re-parse → re-fetch
 *
 * The URL is the source of truth, so a view is a link: bookmarks, shared
 * links and back/forward all work, including through a drilldown.
 *
 * The page renders whatever sections the backend sends rather than hard-coding
 * a layout. That is what keeps a metric's definition, its formatting, its
 * tooltip and — importantly — its cost redaction in one place on the server,
 * instead of split across two languages that can disagree.
 */
import { useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/design-system";
import { SURFACE } from "@/lib/analytics_v2/theme";

import { useAnalyticsPermissions, useAnalyticsQuery } from "@/hooks/useAnalyticsQuery";
import {
  VIEW_OPTIONS, parseUrlState, serializeUrlState,
} from "@/lib/analytics_v2/urlState";
import type {
  AnalyticsQueryBody, DataTablePayload, KPITilePayload, LensKey, Scope,
  Section as SectionPayload, SectionChild,
} from "@/lib/analytics_v2/types";

import ControlBar from "@/components/analytics/ControlBar";
import ViewSentence from "@/components/ViewSentence";
import EmptyStateInvoiceless from "@/components/EmptyStateInvoiceless";
import KPITile from "@/components/primitives/KPITile";
import ChartCard from "@/components/primitives/ChartCard";
import DataTable from "@/components/primitives/DataTable";
import InsightCard from "@/components/primitives/InsightCard";
import SectionHeader from "@/components/primitives/SectionHeader";
import TabbedSection from "@/components/analytics/TabbedSection";

export default function DashboardV2() {
  const location = useLocation();
  const navigate = useNavigate();

  const body = useMemo<AnalyticsQueryBody>(
    () => parseUrlState(location.search),
    [location.search],
  );

  const { data, error, isLoading, isFetching, refetch } = useAnalyticsQuery(body);
  const { data: perms } = useAnalyticsPermissions();

  // Until permissions land, offer the executive dashboard only. Showing every
  // view and greying them out a moment later is worse than showing the four
  // that are always available on a paid plan.
  const availableViews = useMemo(() => {
    const allowed = perms?.capabilities?.available_lenses;
    return new Set<LensKey>(
      allowed?.length
        ? VIEW_OPTIONS.filter(v => allowed.includes(v.value)).map(v => v.value)
        : ["overview", "clients", "team", "distribution"],
    );
  }, [perms]);

  const push = useCallback((next: Partial<AnalyticsQueryBody>) => {
    const merged: AnalyticsQueryBody = {
      scope: next.scope ?? body.scope,
      lens: next.lens ?? body.lens,
      time: next.time ?? body.time,
      compare: next.compare !== undefined ? next.compare : body.compare,
    };
    const search = serializeUrlState(merged);
    navigate({ pathname: "/analytics", search: search ? `?${search}` : "" });
  }, [body, navigate]);

  /** KPI tiles and insight cards carry a fully-formed scope + lens. */
  const handleDrilldown = useCallback(
    (d: { scope: Scope; lens: LensKey }) => {
      // Filters are deliberately carried through a drilldown: they are the
      // viewer's standing narrowing of the whole dashboard, not a property of
      // the tile they happened to click.
      push({
        scope: { ...d.scope, filters: body.scope.filters },
        lens: d.lens,
      });
    },
    [push, body.scope.filters],
  );

  /** Table rows carry a descriptor instead; build the scope from the row. */
  const rowHandler = useCallback(
    (table: DataTablePayload) => {
      const dd = table.row_drilldown;
      if (!dd) return undefined;
      return (row: Record<string, any>) => {
        const id = row[dd.id_key];
        // A row with no id is a real case — "No client assigned", or the
        // "+ 14 more" tail row. There is nothing to drill into, so the row
        // simply isn't a link.
        if (id === null || id === undefined) return;
        push({
          scope: {
            type: dd.scope_type,
            ids: [Number(id)],
            label: String(row[dd.label_key] ?? ""),
            filters: body.scope.filters,
          },
          lens: dd.lens,
        });
      };
    },
    [push, body.scope.filters],
  );

  return (
    <div className="-mx-4 -my-6 min-h-[calc(100vh-64px)] print:m-0 print:min-h-0"
         style={{ backgroundColor: SURFACE.page, fontFamily: '"Inter", sans-serif' }}>
      <ControlBar
        body={body}
        availableViews={availableViews}
        scopeLabel={data?.view?.scope?.label}
        onChange={push}
      />

      <ViewSentence
        sentence={data?.view?.sentence ?? ""}
        generatedAt={data?.meta?.generated_at}
        dataFreshness={data?.meta?.data_freshness}
        isFetching={isFetching}
        onRefresh={() => refetch()}
      />

      <main className="mx-auto max-w-[1560px] px-6 py-8 print:px-0 print:py-3">
        {isLoading && (
          <div className="flex items-center justify-center py-24 text-slate-400">
            <Loader2 className="mr-2 h-6 w-6 animate-spin" />
            <span className="text-sm">Loading…</span>
          </div>
        )}

        {error && <ErrorPanel error={error} onRetry={() => refetch()} />}

        {data && (
          <div className="space-y-10 print:space-y-4">
            <SectionRenderer
              body={body}
              data={data}
              onDrilldown={handleDrilldown}
              rowHandler={rowHandler}
            />
          </div>
        )}
      </main>
    </div>
  );
}

// ─── Sections ────────────────────────────────────────────────────────────────

function SectionRenderer({
  body, data, onDrilldown, rowHandler,
}: {
  body: AnalyticsQueryBody;
  data: NonNullable<ReturnType<typeof useAnalyticsQuery>["data"]>;
  onDrilldown: (d: { scope: Scope; lens: LensKey }) => void;
  rowHandler: (t: DataTablePayload) => ((row: Record<string, any>) => void) | undefined;
}) {
  // Realization and invoice trends have no numerator without invoices. A 0%
  // reads as catastrophic billing performance rather than as missing data.
  if (data.meta?.invoiceless && (body.lens === "realization" || body.lens === "trends")) {
    return <EmptyStateInvoiceless metric={body.lens} />;
  }

  const renderChild = (child: SectionChild) => {
    switch (child.type) {
      case "kpi_tile":
        return <KPITile key={child.id} tile={child as KPITilePayload} onDrilldown={onDrilldown} />;
      case "chart_card":
        return <ChartCard key={child.id} card={child} />;
      case "data_table":
        return <DataTable key={child.id} table={child} onRowClick={rowHandler(child)} />;
      case "insight_card":
        return <InsightCard key={child.id} card={child} onDrilldown={onDrilldown} />;
      default:
        return null;
    }
  };

  return (
    <>
      {data.sections.map(section => {
        if (section.type === "kpi_row") {
          return (
            <div
              key={section.id}
              className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
            >
              {section.tiles.map(tile => (
                <KPITile key={tile.id} tile={tile} onDrilldown={onDrilldown} />
              ))}
            </div>
          );
        }

        const s = section as SectionPayload;
        if (s.tabbed) {
          return <TabbedSection key={s.id} section={s} renderChild={renderChild} />;
        }

        return (
          <CollapsibleSection key={s.id} section={s}>
            <div className="space-y-4">{s.children.map(renderChild)}</div>
          </CollapsibleSection>
        );
      })}
    </>
  );
}

function CollapsibleSection({
  section, children,
}: { section: SectionPayload; children: React.ReactNode }) {
  if (!section.collapsible) {
    return (
      <section className="space-y-3">
        {section.title && <SectionHeader title={section.title} />}
        {children}
      </section>
    );
  }
  return (
    <details className="group space-y-3" open={!section.collapsed}>
      <summary className="cursor-pointer list-none text-sm font-semibold text-slate-700 hover:text-slate-900">
        <span className="inline-flex items-center gap-1.5">
          <span className="text-slate-400 transition-transform group-open:rotate-90">▸</span>
          {section.title}
        </span>
      </summary>
      <div className="pt-3">{children}</div>
    </details>
  );
}

// ─── Error ───────────────────────────────────────────────────────────────────

function ErrorPanel({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const message = error.message || "Something went wrong";
  const isPermissionError = /403|permission/i.test(message);

  return (
    <div className={cn("rounded-2xl border border-rose-200 bg-rose-50/40 p-6")}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-rose-900">
            {isPermissionError ? "Access denied" : "Couldn't load dashboard"}
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-rose-700">{message}</p>
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
