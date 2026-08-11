"""Robust-statistics helpers shared across lenses.

The recurring failure mode in firm analytics is *one number poisoning the
whole*: a two-hour client with a fixed fee shows a 900% margin, a mid-period
new hire shows 4% utilization, and any naive mean or unfiltered ranking is
distorted. These helpers give every lens the same defenses:

  * ``median`` / ``quantile`` — central tendency that shrugs off outliers,
    for "typical" summaries (headlines stay pooled ratios).
  * ``winsorize`` — clamp extreme values into a percentile band for display.
  * ``partition_material`` — split a row set into the material contributors
    (which drive headlines and rankings) and the immaterial tail (shown, but
    never ranked or averaged into the story).

Keep these pure and dependency-free so any metric/lens/rollup can import them.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence


def median(values: Sequence[float]) -> float | None:
    """Median of a numeric sequence, or None if empty."""
    xs = sorted(v for v in values if v is not None)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return float(xs[mid])
    return (xs[mid - 1] + xs[mid]) / 2.0


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated quantile (q in [0, 1]), or None if empty."""
    xs = sorted(v for v in values if v is not None)
    n = len(xs)
    if n == 0:
        return None
    if n == 1:
        return float(xs[0])
    q = min(1.0, max(0.0, q))
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def winsorize(value: float, values: Sequence[float], limits: float = 0.05) -> float:
    """Clamp ``value`` to the [limits, 1-limits] percentile band of ``values``.

    Use for *display* of an outlier-prone per-entity figure so a single 900%
    reading doesn't blow out an axis or a color scale. Never mutate the stored
    number — winsorize at the edge, keep the raw value in tooltips/tables."""
    lo = quantile(values, limits)
    hi = quantile(values, 1 - limits)
    if lo is None or hi is None:
        return value
    return min(hi, max(lo, value))


def partition_material(
    rows: list[dict[str, Any]],
    weight_key: str,
    *,
    min_weight: float = 1.0,
    min_share: float = 0.01,
    revenue_key: str | None = None,
    min_revenue: float = 250.0,
) -> tuple[list[dict], list[dict]]:
    """Split ``rows`` into (material, immaterial).

    A row is *material* if it carries real weight — either an absolute floor
    (``min_weight`` of the weight column, e.g. billable hours), a relative
    floor (``min_share`` of the total weight), OR, when ``revenue_key`` is
    given, at least ``min_revenue`` of recognized revenue (so a small-hours
    but real-dollar flat-fee client still counts). Everything else is the
    immaterial tail: worth showing, never worth ranking or averaging.

    Preserves input order within each group; the caller sorts.
    """
    total_weight = sum(float(r.get(weight_key) or 0) for r in rows)
    share_floor = total_weight * min_share if total_weight > 0 else 0.0
    floor = max(min_weight, share_floor)

    material: list[dict] = []
    immaterial: list[dict] = []
    for r in rows:
        w = float(r.get(weight_key) or 0)
        rev = float(r.get(revenue_key) or 0) if revenue_key else 0.0
        if w >= floor or (revenue_key and rev >= min_revenue):
            material.append(r)
        else:
            immaterial.append(r)
    return material, immaterial
