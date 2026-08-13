/**
 * KPITile — renders a single KPI tile.
 *
 * Handles the full state machine: ready / empty / calibrating / error.
 * Shows delta and threshold zone when present.
 * Honors data_quality badge (Option B realization) when below 0.75.
 */
import { useState } from "react";
import { Info, TrendingUp, TrendingDown, Minus, AlertTriangle, Sparkles } from "lucide-react";
import { cn } from "@/lib/design-system";
import { formatValue, formatDelta } from "@/lib/analytics_v2/format";
import type { KPITilePayload, ThresholdZone } from "@/lib/analytics_v2/types";

interface Props {
  tile: KPITilePayload;
  onDrilldown?: (drilldown: NonNullable<KPITilePayload["drilldown"]>) => void;
}

const ZONE_RING: Record<ThresholdZone, string> = {
  good:  "ring-emerald-200/60 bg-emerald-50/30",
  watch: "ring-amber-200/60 bg-amber-50/30",
  bad:   "ring-rose-200/60 bg-rose-50/30",
};

const ZONE_DOT: Record<ThresholdZone, string> = {
  good:  "bg-emerald-500",
  watch: "bg-amber-500",
  bad:   "bg-rose-500",
};

export default function KPITile({ tile, onDrilldown }: Props) {
  const [showTooltip, setShowTooltip] = useState(false);
  const m = tile.metric;
  const interactive = !!(tile.drilldown && onDrilldown);

  // Container sizing
  const sizeClass = {
    small:  "p-4",
    medium: "p-5",
    large:  "p-6",
  }[tile.size];

  const valueSizeClass = {
    small:  "text-2xl",
    medium: "text-3xl",
    large:  "text-4xl",
  }[tile.size];

  // ──────────── ERROR STATE ────────────
  if (m.state === "error") {
    return (
      <div className={cn(
        "rounded-[15px] border border-rose-200/60 bg-rose-50/20",
        sizeClass,
      )}>
        <div className="flex items-center gap-2 text-rose-700 text-sm">
          <AlertTriangle className="h-4 w-4" />
          <span className="font-medium">{tile.label}</span>
        </div>
        <p className="mt-2 text-xs text-rose-600 line-clamp-2">
          {m.error_message || "Couldn't compute this metric."}
        </p>
      </div>
    );
  }

  // ──────────── EMPTY STATE ────────────
  if (m.state === "empty") {
    return (
      <TileShell tile={tile} sizeClass={sizeClass} interactive={interactive} onDrilldown={onDrilldown}>
        <Label tile={tile} showTooltip={showTooltip} setShowTooltip={setShowTooltip} />
        <div className={cn("font-bold tracking-tight tabular-nums text-slate-300 mt-1", valueSizeClass)}>—</div>
        <p className="mt-1 text-xs text-slate-500">No data for this period</p>
      </TileShell>
    );
  }

  // ──────────── CALIBRATING STATE ────────────
  if (m.state === "calibrating") {
    const pct = m.days_needed ? Math.min(100, Math.round(((m.days_in ?? 0) / m.days_needed) * 100)) : 0;
    return (
      <TileShell tile={tile} sizeClass={sizeClass} interactive={interactive} onDrilldown={onDrilldown}>
        <Label tile={tile} showTooltip={showTooltip} setShowTooltip={setShowTooltip} />
        <div className="flex items-baseline gap-2 mt-1">
          <div className={cn("font-bold tracking-tight tabular-nums text-slate-700", valueSizeClass)}>
            {m.preview_value !== null && m.preview_value !== undefined
              ? formatValue(m.preview_value, tile.format)
              : "—"}
          </div>
          <Sparkles className="h-4 w-4 text-primary" />
        </div>
        <div className="mt-2 space-y-1">
          <p className="text-xs text-slate-600">
            Calibrating · {m.days_in ?? 0} of {m.days_needed} days
          </p>
          <div className="h-1 w-full bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
      </TileShell>
    );
  }

  // ──────────── READY STATE ────────────
  const valueStr = formatValue(m.value, tile.format);
  const zoneRing = m.threshold_zone ? ZONE_RING[m.threshold_zone] : "ring-slate-200/60 bg-white";
  const hasDataQualityBadge = m.data_quality !== null && m.data_quality !== undefined && m.data_quality < 0.75;

  return (
    <TileShell
      tile={tile}
      sizeClass={sizeClass}
      interactive={interactive}
      onDrilldown={onDrilldown}
      extraClass={cn("ring-1", zoneRing)}
    >
      <Label tile={tile} showTooltip={showTooltip} setShowTooltip={setShowTooltip} />

      <div className="flex items-baseline gap-3 mt-1.5">
        <div className={cn("font-bold text-slate-900 tracking-tight tabular-nums", valueSizeClass)}>
          {valueStr}
        </div>
        {m.threshold_zone && (
          <div className={cn("h-2 w-2 rounded-full", ZONE_DOT[m.threshold_zone])} />
        )}
      </div>

      {/* Trend sparkline vs the firm's own normal band (WHOOP-style baseline) */}
      {m.sparkline && m.sparkline.length >= 3 && (
        <Sparkline values={m.sparkline} low={m.threshold_low ?? null} high={m.threshold_high ?? null} />
      )}

      {/* Secondary value (e.g. "$8,400 vs $400 standard" for effective rate) */}
      {m.secondary_value !== null && m.secondary_value !== undefined && m.secondary_label && (
        <p className="mt-1 text-xs text-slate-500">
          {m.secondary_label}: {formatValue(m.secondary_value, m.secondary_format ?? tile.format)}
        </p>
      )}

      {/* Delta vs comparison period */}
      {m.delta_value !== null && m.delta_value !== undefined && m.delta_direction && (
        <div className="mt-2 flex items-center gap-1.5 text-xs">
          <DeltaIcon dir={m.delta_direction} good={m.delta_good ?? null} />
          <span className={cn(
            "font-medium",
            m.delta_good === true && "text-emerald-700",
            m.delta_good === false && "text-rose-700",
            m.delta_good === null && "text-slate-600",
          )}>
            {formatDelta(m.delta_value, tile.format)}
          </span>
          <span className="text-slate-500">vs prior</span>
        </div>
      )}

      {/* Data quality badge — Option B realization */}
      {hasDataQualityBadge && (
        <div className="mt-2 flex items-start gap-1.5 text-[11px] text-amber-700 bg-amber-50/60 rounded px-2 py-1.5">
          <Info className="h-3 w-3 mt-0.5 shrink-0" />
          <span className="leading-tight">
            Low data quality ({Math.round((m.data_quality ?? 0) * 100)}%)
            {m.data_quality_note && (
              <button
                className="ml-1 underline underline-offset-2 hover:text-amber-900"
                onClick={(e) => { e.stopPropagation(); alert(m.data_quality_note); }}
              >
                why?
              </button>
            )}
          </span>
        </div>
      )}
    </TileShell>
  );
}

// ─── Internal subcomponents ──────────────────────────────────────────────────

function TileShell({
  tile, sizeClass, interactive, onDrilldown, extraClass, children,
}: {
  tile: KPITilePayload;
  sizeClass: string;
  interactive: boolean;
  onDrilldown?: (d: NonNullable<KPITilePayload["drilldown"]>) => void;
  extraClass?: string;
  children: React.ReactNode;
}) {
  const Wrapper: any = interactive ? "button" : "div";
  return (
    <Wrapper
      onClick={interactive
        ? () => tile.drilldown && onDrilldown && onDrilldown(tile.drilldown)
        : undefined}
      className={cn(
        "rounded-[15px] text-left transition-all shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)]",
        interactive && "hover:shadow-md hover:-translate-y-0.5 cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/30",
        sizeClass,
        extraClass ?? "border border-border/70 bg-white",
      )}
    >
      {children}
    </Wrapper>
  );
}

function Label({
  tile, showTooltip, setShowTooltip,
}: {
  tile: KPITilePayload;
  showTooltip: boolean;
  setShowTooltip: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-slate-500 font-medium">
      <span>{tile.label}</span>
      {tile.tooltip && (
        <span
          className="relative inline-flex"
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
        >
          <Info className="h-3 w-3 text-slate-400 hover:text-slate-600 cursor-help" />
          {showTooltip && (
            <span className="absolute left-5 top-0 z-10 w-64 rounded-lg bg-slate-900 text-white text-[11px] normal-case tracking-normal p-2.5 shadow-lg leading-snug font-normal">
              {tile.tooltip}
            </span>
          )}
        </span>
      )}
    </div>
  );
}

function Sparkline({ values, low, high }: { values: number[]; low: number | null; high: number | null }) {
  const pts = values.filter((v) => v !== null && v !== undefined) as number[];
  if (pts.length < 2) return null;
  const W = 108, H = 28, pad = 3;
  const lo = Math.min(...pts, low ?? Infinity);
  const hi = Math.max(...pts, high ?? -Infinity);
  const range = hi - lo || 1;
  const x = (i: number) => pad + (i / (pts.length - 1)) * (W - 2 * pad);
  const y = (v: number) => pad + (1 - (v - lo) / range) * (H - 2 * pad);
  const line = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  const inBand = low != null && last >= low;   // at/above your normal floor
  return (
    <div className="mt-2" title="Trend vs your firm's normal range (last ~12 weeks)">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {low != null && high != null && (
          <rect x={0} y={y(high)} width={W} height={Math.max(0, y(low) - y(high))} fill="#0d9488" opacity="0.10" />
        )}
        <polyline points={line} fill="none" stroke="#94a3b8" strokeWidth="1.5" strokeLinejoin="round" />
        <circle cx={x(pts.length - 1)} cy={y(last)} r="2.6" fill={inBand ? "#0d9488" : "#f59e0b"} />
      </svg>
    </div>
  );
}

function DeltaIcon({ dir, good }: { dir: "up" | "down" | "flat"; good: boolean | null }) {
  const colorClass = good === true ? "text-emerald-600"
    : good === false ? "text-rose-600"
    : "text-slate-500";
  if (dir === "up")   return <TrendingUp   className={cn("h-3.5 w-3.5", colorClass)} />;
  if (dir === "down") return <TrendingDown className={cn("h-3.5 w-3.5", colorClass)} />;
  return <Minus className={cn("h-3.5 w-3.5", colorClass)} />;
}
