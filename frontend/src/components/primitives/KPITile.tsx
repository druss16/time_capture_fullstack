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

/**
 * Threshold treatment.
 *
 * This used to tint the whole tile (`bg-emerald-50/30` and friends), which made
 * a row of KPIs read as four different kinds of card competing for attention —
 * and washed the value itself onto a coloured ground. A hairline accent on the
 * inline edge says the same thing and lets the number stay the loudest element.
 */
type Tone = "good" | "watch" | "bad" | "neutral";

/**
 * One tone per tile, driving both the edge stripe and the sparkline.
 *
 * Order matters: an explicit threshold zone is a statement about the level and
 * outranks the delta, which is only a statement about the direction. With
 * neither, the tone is NEUTRAL — the stripe is then structure, not a claim.
 * Painting every tile teal would make "fine" the default reading of figures
 * nobody has set a target for.
 */
function toneFor(m: KPITilePayload["metric"]): Tone {
  if (m.threshold_zone) return m.threshold_zone;
  // `delta_good` is the metric's own answer to "did this move the right way?"
  // — the backend decides it per metric, so labour cost rising is not good
  // while revenue rising is. Reading it here is a statement, not decoration.
  if (m.delta_good === true) return "good";
  if (m.delta_good === false) return "watch";
  // No target and no comparison: nothing is known about this figure beyond its
  // level, so the stripe stays structural and the trend line stays grey.
  return "neutral";
}

const TONE_HEX: Record<Tone, string> = {
  good: "#0d9488", watch: "#b45309", bad: "#be123c", neutral: "#64748b",
};

const TONE_STRIPE: Record<Tone, string> = {
  good:    "before:bg-teal-600",
  watch:   "before:bg-amber-500",
  bad:     "before:bg-rose-500",
  neutral: "before:bg-slate-200",
};

const ZONE_BASE =
  "relative before:absolute before:inset-y-3 before:left-0 before:w-[3px] " +
  "before:rounded-full";

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
    medium: "px-5 py-[18px]",
    large:  "px-6 py-6",
  }[tile.size];

  // -0.02em tracking on large tabular figures: default spacing makes big
  // numerals look loose and cheap.
  const valueSizeClass = {
    small:  "text-[26px] leading-none",
    medium: "text-[34px] leading-none",
    large:  "text-[42px] leading-none",
  }[tile.size];

  // ──────────── ERROR STATE ────────────
  if (m.state === "error") {
    return (
      <div className={cn(
        "rounded-2xl border border-rose-200/60 bg-rose-50/20",
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
  // Every tile gets the stripe so the row reads as one object; only its
  // COLOUR carries meaning, and only when there is meaning to carry.
  const tone = toneFor(m);
  const zoneAccent = cn(ZONE_BASE, TONE_STRIPE[tone]);
  const hasDataQualityBadge = m.data_quality !== null && m.data_quality !== undefined && m.data_quality < 0.75;

  return (
    <TileShell
      tile={tile}
      sizeClass={sizeClass}
      interactive={interactive}
      onDrilldown={onDrilldown}
      extraClass={zoneAccent}
    >
      <Label tile={tile} showTooltip={showTooltip} setShowTooltip={setShowTooltip} />

      <div className="mt-2.5 flex items-baseline gap-2.5">
        <div
          className={cn("font-semibold tabular-nums text-slate-900", valueSizeClass)}
          style={{ letterSpacing: "-0.022em", fontVariantNumeric: "tabular-nums" }}
        >
          {valueStr}
        </div>
      </div>

      {/* Trend sparkline vs the firm's own normal band (WHOOP-style baseline) */}
      {m.sparkline && m.sparkline.length >= 3 && (
        <Sparkline
          values={m.sparkline}
          low={m.threshold_low ?? null}
          high={m.threshold_high ?? null}
          benchmark={m.benchmark ?? null}
          tone={tone}
        />
      )}

      {/* Secondary value (e.g. "$8,400 vs $400 standard" for effective rate) */}
      {m.secondary_value !== null && m.secondary_value !== undefined && m.secondary_label && (
        <p className="mt-1 text-xs text-slate-500">
          {m.secondary_label}: {formatValue(m.secondary_value, m.secondary_format ?? tile.format)}
        </p>
      )}

      {/* Delta vs comparison period */}
      {m.delta_value !== null && m.delta_value !== undefined && m.delta_direction && (
        <div className="mt-3 flex items-center gap-1.5 text-xs">
          <DeltaIcon dir={m.delta_direction} good={m.delta_good ?? null} />
          <span className={cn(
            "font-semibold tabular-nums",
            m.delta_good === true && "text-teal-700",
            m.delta_good === false && "text-rose-600",
            m.delta_good === null && "text-slate-600",
          )}>
            {formatDelta(m.delta_value, tile.format)}
          </span>
          <span className="text-slate-400">vs prior</span>
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
        // The card surface is unconditional. It used to be the FALLBACK for
        // extraClass (`extraClass ?? "border ... bg-white"`), so any tile with
        // a threshold lost its border and background along with it — the zone
        // classes happened to re-supply a tint, which hid the bug until the
        // tint was removed.
        "rounded-2xl border border-[rgba(15,42,60,0.08)] bg-white text-left",
        "shadow-[0_1px_2px_rgba(16,27,46,0.04),0_8px_24px_-12px_rgba(16,27,46,0.10)]",
        "transition-[transform,box-shadow,border-color] duration-200 ease-out",
        interactive && "cursor-pointer hover:-translate-y-px hover:border-[rgba(15,42,60,0.14)] hover:shadow-[0_1px_2px_rgba(16,27,46,0.05),0_16px_40px_-16px_rgba(16,27,46,0.18)] focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600/30",
        sizeClass,
        extraClass,
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
    <div className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.13em] text-slate-400">
      <span>{tile.label}</span>
      {tile.tooltip && (
        <span
          className="relative inline-flex"
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
        >
          <Info className="h-3 w-3 text-slate-400 hover:text-slate-600 cursor-help" />
          {showTooltip && (
            <span className="absolute left-5 top-0 z-10 w-72 rounded-lg bg-slate-900 text-white text-[11px] normal-case tracking-normal p-2.5 shadow-lg leading-snug font-normal whitespace-pre-line">
              {tile.tooltip}
            </span>
          )}
        </span>
      )}
    </div>
  );
}

function Sparkline({ values, low, high, benchmark, tone }: {
  values: number[]; low: number | null; high: number | null;
  benchmark?: number | null; tone: Tone;
}) {
  const pts = values.filter(v => v !== null && v !== undefined) as number[];
  if (pts.length < 3) return null;

  // viewBox units, scaled to the tile by width:100%. The old sparkline was a
  // fixed 108px, so it sat in a puddle of dead space on a wide tile.
  const W = 120, H = 30, pad = 3;
  const lo = Math.min(...pts, low ?? Infinity, benchmark ?? Infinity);
  const hi = Math.max(...pts, high ?? -Infinity, benchmark ?? -Infinity);
  const range = hi - lo || 1;
  const x = (i: number) => pad + (i / (pts.length - 1)) * (W - 2 * pad);
  const y = (v: number) => pad + (1 - (v - lo) / range) * (H - 2 * pad);

  const line = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} ${x(pts.length - 1).toFixed(1)},${H} ${x(0).toFixed(1)},${H}`;
  const last = pts[pts.length - 1]!;
  const stroke = TONE_HEX[tone];
  const id = `spark-${tone}`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="30"
      preserveAspectRatio="none"
      className="mt-2 block overflow-visible"
      role="img"
      aria-label={`Trend over the period, ending at ${last.toFixed(1)}`}
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* The firm's own normal band, where the metric defines one. A solid
          wash, not a dashed rule — dashing reads as "projection". */}
      {low != null && high != null && (
        <rect x={0} y={y(high)} width={W} height={Math.max(0, y(low) - y(high))}
              fill={stroke} opacity="0.07" />
      )}
      <polygon points={area} fill={`url(#${id})`} />
      <polyline points={line} fill="none" stroke={stroke} strokeWidth="1.75"
                strokeLinejoin="round" strokeLinecap="round"
                vectorEffect="non-scaling-stroke" />
      {/* The endpoint is the value the tile prints, so it gets the emphasis. */}
      <circle cx={x(pts.length - 1)} cy={y(last)} r="2.4" fill={stroke} />
    </svg>
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
