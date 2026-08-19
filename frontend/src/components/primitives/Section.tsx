/**
 * Section — renders one section from the backend response.
 *
 * Handles both shapes:
 *   - kpi_row    → 2-4 KPITiles in a grid
 *   - section    → titled group with mixed children (charts / tables / insights)
 *
 * This is the single point where the typed response tree turns into JSX.
 * Adding a new payload type means extending the switch in renderChild().
 */
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/design-system";
import type { Section as SectionType, SectionChild } from "@/lib/analytics_v2/types";
import { KPITile } from "./KPITile";
import { ChartCard } from "./ChartCard";
import DataTable from "./DataTable";
import { InsightCard } from "./InsightCard";

interface Props {
  section: SectionType;
  onDrilldown?: (drilldown: any) => void;
  onTileClick?: (tile: any) => void;
}

export function Section({ section, onDrilldown, onTileClick }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  if (section.type === "kpi_row") {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {section.tiles.map((tile) => (
          <KPITile
            key={tile.id}
            tile={tile}
            onClick={tile.drilldown ? () => onTileClick?.(tile) : undefined}
          />
        ))}
      </div>
    );
  }

  // section type
  return (
    <div className="space-y-3">
      {section.title && (
        <div
          className={cn(
            "flex items-center gap-2",
            section.collapsible && "cursor-pointer select-none",
          )}
          onClick={section.collapsible ? () => setCollapsed(!collapsed) : undefined}
        >
          {section.collapsible && (
            collapsed
              ? <ChevronRight className="w-4 h-4 text-slate-400" />
              : <ChevronDown className="w-4 h-4 text-slate-400" />
          )}
          <h2 className="text-sm font-semibold text-slate-900 uppercase tracking-wider">
            {section.title}
          </h2>
        </div>
      )}

      {!collapsed && (
        <div className="space-y-3">
          {section.children.map((child, i) => renderChild(child, i, onDrilldown))}
        </div>
      )}
    </div>
  );
}

function renderChild(
  child: SectionChild,
  idx: number,
  onDrilldown?: (drilldown: any) => void,
) {
  switch (child.type) {
    case "kpi_tile":
      return (
        <KPITile
          key={child.id || idx}
          tile={child}
          onClick={child.drilldown ? () => onDrilldown?.(child.drilldown) : undefined}
        />
      );
    case "chart_card":
      return <ChartCard key={child.id || idx} chart={child} />;
    case "data_table":
      return <DataTable key={child.id || idx} table={child} />;
    case "insight_card":
      return (
        <InsightCard
          key={child.id || idx}
          card={child}
          onDrilldown={child.drilldown ? () => onDrilldown?.(child.drilldown) : undefined}
        />
      );
    default:
      return null;
  }
}
