/**
 * Analytics design tokens.
 *
 * THE PALETTE IS VALIDATED, NOT CHOSEN BY EYE.
 *
 * `#0d9488, #4a3aa7, #eb6834, #c2185b` on a white chart surface, checked with
 * the data-viz validator (OKLab ΔE ×100):
 *
 *   lightness band      PASS  all four inside L 0.43–0.77
 *   chroma floor        PASS  all four >= 0.1
 *   CVD separation      PASS  worst ADJACENT pair ΔE 16.6 (deutan)
 *   normal vision       PASS  worst adjacent ΔE 18.1
 *   contrast vs white   PASS  all four >= 3:1
 *
 * Adjacent pairs are the gate that governs this dashboard: every chart here is
 * an area, line, stacked bar or ranked bar, where only neighbouring series
 * touch. (Across ALL pairs, pink↔teal sits at ΔE 7.5 — inside the 6–8 band
 * that is legal only with secondary encoding. Every multi-series chart here
 * carries a legend, so that condition holds; but a scatter or bubble chart
 * added later would need to re-check.)
 *
 * Teal leads because it is the product's brand colour, not because it tested
 * best — the other three were selected around it.
 */

/** Categorical slots, in fixed order. Never cycle past the end — see SERIES_FALLBACK. */
export const SERIES = ["#0d9488", "#4a3aa7", "#eb6834", "#c2185b"] as const;

/**
 * A 5th+ series is NOT a generated hue: past four, identity stops being
 * readable under colour-vision deficiency. Anything beyond the palette renders
 * in this neutral, which reads as "everything else" rather than as a peer.
 */
export const SERIES_FALLBACK = "#94a3b8";

/**
 * Colour follows the ENTITY, not its row number, so filtering a series out
 * never repaints the survivors. Keyed on the series key from the payload.
 */
export function seriesColor(key: string, keys: readonly string[]): string {
  const i = keys.indexOf(key);
  if (i < 0 || i >= SERIES.length) return SERIES_FALLBACK;
  return SERIES[i];
}

/** Emphasis pairing: the measure that matters, and its remainder. */
export const EMPHASIS = {
  primary: SERIES[0],
  /** "Other tracked", "the rest" — present but deliberately recessive. */
  muted: "#cbd5e1",
} as const;

/** Reserved for good / watch / bad. Never reused as a categorical slot. */
export const STATUS = {
  good: "#0f766e",
  watch: "#b45309",
  bad: "#be123c",
  info: "#475569",
} as const;

/** Chart chrome. Hairline and solid — never dashed. */
export const CHROME = {
  surface: "#ffffff",
  grid: "#eef2f6",
  axis: "#cbd5e1",
  tick: "#94a3b8",
  areaFillOpacity: 0.12,
  strokeWidth: 2,
  /** A 2px surface-coloured gap between adjacent fills. */
  segmentGap: 2,
  barRadius: 5,
} as const;

/** Page surfaces. A near-white ground so white cards read as raised. */
export const SURFACE = {
  page: "#f7f9f9",
  card: "#ffffff",
  border: "rgba(15,42,60,0.08)",
  borderStrong: "rgba(15,42,60,0.14)",
  /** Two-layer: a hairline lift plus a soft ambient shadow. */
  shadow: "0 1px 2px rgba(16,27,46,0.04), 0 8px 24px -12px rgba(16,27,46,0.14)",
  shadowRaised: "0 1px 2px rgba(16,27,46,0.05), 0 16px 40px -16px rgba(16,27,46,0.22)",
} as const;
