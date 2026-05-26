/**
 * Format a numeric value according to a NumberFormat string from the backend.
 * Used by every tile, table cell, and chart label.
 */
import type { NumberFormat } from "./types";

export function formatValue(value: number | null | undefined, format: NumberFormat): string {
  if (value === null || value === undefined || (typeof value === "number" && isNaN(value))) {
    return "—";
  }

  switch (format) {
    case "percent_1dp":
      return `${value.toFixed(1)}%`;
    case "percent_0dp":
      return `${Math.round(value)}%`;
    case "currency_0dp":
      return `$${Math.round(value).toLocaleString()}`;
    case "currency_2dp":
      return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    case "hours_1dp":
      return `${value.toFixed(1)}h`;
    case "days_1dp":
      return `${value.toFixed(1)}d`;
    case "integer":
      return Math.round(value).toLocaleString();
    case "decimal_1dp":
      return value.toFixed(1);
    case "decimal_2dp":
      return value.toFixed(2);
    case "text":
      return String(value);
    default:
      return String(value);
  }
}

/**
 * Format a delta value with sign. Used for "▲ +$1,200" style deltas.
 */
export function formatDelta(
  value: number | null | undefined,
  format: NumberFormat,
): string {
  if (value === null || value === undefined) return "";
  const sign = value > 0 ? "+" : value < 0 ? "" : "";
  return `${sign}${formatValue(value, format)}`;
}

/**
 * "Q2 2026 vs Q1 2026" → human-friendly sentence parts
 */
export function shortTimeLabel(label: string): string {
  return label.length > 24 ? label.slice(0, 22) + "…" : label;
}
