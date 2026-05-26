"""
Metric base class and registry.

Every KPI in the dashboard is an instance of `Metric` subclass, registered via
@register_metric. Lenses compose metrics by ID; the registry is the only place
the strings ↔ classes mapping lives.

To add a new metric:
  1. Create analytics_v2/metrics/<name>.py
  2. Subclass Metric, decorate with @register_metric("metric_id")
  3. Implement compute(scope, time) → MetricValue
  4. Reference "metric_id" from a Lens definition

The Metric base provides a queryset helper (`_block_qs`) that handles scope
filtering uniformly across metrics. Don't reimplement scope filtering inside
metric subclasses — extend `_block_qs` if you need more dimensions.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from tracker.models import Block, Client, Organization

from ..types import LensKey, MetricState, MetricValue, Scope, TimeRange

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type["Metric"]] = {}


def register_metric(metric_id: str):
    """Decorator that registers a Metric subclass under the given ID."""
    def decorator(cls: type["Metric"]) -> type["Metric"]:
        if metric_id in _REGISTRY:
            raise RuntimeError(f"Metric '{metric_id}' is already registered")
        cls.metric_id = metric_id
        _REGISTRY[metric_id] = cls
        return cls
    return decorator


def get_metric(metric_id: str) -> "Metric":
    """Look up and instantiate a metric by ID. Raises KeyError if missing."""
    if metric_id not in _REGISTRY:
        raise KeyError(
            f"Unknown metric '{metric_id}'. "
            f"Registered: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[metric_id]()


def all_metric_ids() -> list[str]:
    return sorted(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Threshold value object
# ---------------------------------------------------------------------------

class ThresholdRange:
    """Describes a metric's target zone. Used for status colors + threshold bars."""
    
    def __init__(
        self,
        low: float,
        high: float,
        direction: str = "higher_is_better",  # or "lower_is_better" or "in_band"
    ):
        self.low = low
        self.high = high
        self.direction = direction
    
    def zone_for(self, value: float) -> str:
        """Returns 'good' | 'watch' | 'bad' for the value's threshold position."""
        if self.direction == "higher_is_better":
            if value >= self.high:
                return "good"
            if value >= self.low:
                return "watch"
            return "bad"
        if self.direction == "lower_is_better":
            if value <= self.low:
                return "good"
            if value <= self.high:
                return "watch"
            return "bad"
        # in_band: good inside [low, high]
        if self.low <= value <= self.high:
            return "good"
        # mildly outside is watch; far outside is bad. Span is the buffer.
        span = self.high - self.low
        if abs(value - (self.low + self.high) / 2) <= span:
            return "watch"
        return "bad"


# ---------------------------------------------------------------------------
# Base Metric
# ---------------------------------------------------------------------------

class Metric:
    """
    Subclass and decorate with @register_metric to add a KPI.
    
    Class attrs to override:
      label              — Human-readable name shown on the tile
      format             — "percent_1dp" | "currency_0dp" | "hours_1dp" | ...
      tooltip            — One-sentence formula explanation
      threshold          — Optional ThresholdRange
      calibration_days   — How many days of data needed before showing the real
                           value (returns CALIBRATING state until then)
      valid_scopes       — Which scope types this metric supports
      delta_good_when    — "up" or "down": which direction is good for this metric
      required_plan      — "professional" or "executive"
    
    Subclasses must implement:
      compute(scope, time) → MetricValue
    
    May implement:
      sparkline(scope, time) → list[float]  (defaults to None)
    """
    # Set by @register_metric
    metric_id: str = ""
    
    # Defaults — override in subclasses
    label: str = ""
    format: str = "decimal_1dp"
    tooltip: str = ""
    threshold: Optional[ThresholdRange] = None
    calibration_days: int = 0
    valid_scopes: tuple = ("firm", "client", "staff", "service", "engagement")
    delta_good_when: str = "up"  # or "down"
    required_plan: str = "professional"
    
    # ------------------------------------------------------------------------
    # Default queryset construction — handles scope filtering uniformly
    # ------------------------------------------------------------------------
    
    def _block_qs(self, org: Organization, scope: Scope, time: TimeRange,
                  billable_only: bool = False) -> QuerySet:
        """
        Return a Block QuerySet filtered by org + scope + time.
        Subclasses call this and add their own annotations.
        """
        qs = Block.objects.filter(
            org=org,
            day__gte=time.start,
            day__lte=time.end,
        )
        
        if billable_only:
            qs = qs.filter(is_billable=True)
        
        return self._apply_scope(qs, scope)
    
    def _apply_scope(self, qs: QuerySet, scope: Scope) -> QuerySet:
        """Add scope filters to an existing queryset."""
        if scope.type == "firm":
            return qs
        
        if scope.type == "client":
            return qs.filter(client_id__in=scope.ids)
        
        if scope.type == "staff":
            return qs.filter(user_id__in=scope.ids)
        
        if scope.type == "service":
            # Service = task_type. scope.ids holds task_type IDs.
            return qs.filter(task_type_id__in=scope.ids)
        
        if scope.type == "engagement":
            # Engagement = project. scope.ids holds project IDs.
            return qs.filter(project_id__in=scope.ids)
        
        if scope.type == "composite":
            # Filters live in scope.filters dict
            for dim, ids in scope.filters.items():
                if not ids:
                    continue
                if dim == "client":
                    qs = qs.filter(client_id__in=ids)
                elif dim == "staff":
                    qs = qs.filter(user_id__in=ids)
                elif dim == "service":
                    qs = qs.filter(task_type_id__in=ids)
                elif dim == "engagement":
                    qs = qs.filter(project_id__in=ids)
            return qs
        
        return qs
    
    # ------------------------------------------------------------------------
    # Calibration check
    # ------------------------------------------------------------------------
    
    def _days_of_data(self, org: Organization, scope: Scope) -> int:
        """How many days of relevant block data exist for this scope?
        Used to decide CALIBRATING vs READY."""
        from datetime import date, timedelta
        qs = Block.objects.filter(org=org).filter(day__isnull=False)
        # Apply scope but ignore time window — we want lifetime data
        qs = self._apply_scope(qs, scope)
        earliest = qs.order_by("day").values_list("day", flat=True).first()
        if not earliest:
            return 0
        return (date.today() - earliest).days
    
    def _check_calibration(
        self, org: Organization, scope: Scope, real_value: Optional[float]
    ) -> Optional[MetricValue]:
        """
        Return a MetricValue with state=CALIBRATING if this metric needs more
        data, or None to proceed with the real value.
        """
        if self.calibration_days <= 0:
            return None
        days_in = self._days_of_data(org, scope)
        if days_in >= self.calibration_days:
            return None
        return MetricValue(
            state=MetricState.CALIBRATING,
            preview_value=real_value,
            days_in=days_in,
            days_needed=self.calibration_days,
        )
    
    # ------------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------------
    
    def supports_scope(self, scope_type: str) -> bool:
        return scope_type in self.valid_scopes
    
    def compute(
        self,
        org: Organization,
        scope: Scope,
        time: TimeRange,
    ) -> MetricValue:
        """Must be overridden by subclasses."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.compute() not implemented"
        )
    
    def sparkline(
        self,
        org: Organization,
        scope: Scope,
        time: TimeRange,
    ) -> Optional[list[float]]:
        """Override to provide a sparkline. Return ~7-12 values."""
        return None
    
    def safe_compute(
        self,
        org: Organization,
        scope: Scope,
        time: TimeRange,
        compare: Optional[TimeRange] = None,
    ) -> MetricValue:
        """
        Wraps compute() with:
          - exception handling → returns ERROR state
          - scope validation
          - threshold zone calculation
          - comparison delta calculation
        """
        if not self.supports_scope(scope.type):
            return MetricValue(
                state=MetricState.ERROR,
                error_message=f"Metric '{self.metric_id}' doesn't support scope type '{scope.type}'",
            )
        
        try:
            value = self.compute(org, scope, time)
        except Exception as exc:
            logger.exception(
                "[ANALYTICS_V2] Metric '%s' failed for org=%s scope=%s",
                self.metric_id, org.id, scope.type,
            )
            return MetricValue(state=MetricState.ERROR, error_message=str(exc))
        
        if value.state != MetricState.READY:
            return value
        
        # Apply threshold zone
        if self.threshold and value.value is not None:
            value.threshold_low = self.threshold.low
            value.threshold_high = self.threshold.high
            value.threshold_zone = self.threshold.zone_for(value.value)  # type: ignore
        
        # Apply comparison delta
        if compare is not None and value.value is not None:
            try:
                prior = self.compute(org, scope, compare)
                if prior.state == MetricState.READY and prior.value is not None:
                    delta = value.value - prior.value
                    value.delta_value = round(delta, 2)
                    value.delta_direction = (
                        "flat" if abs(delta) < 0.01
                        else "up" if delta > 0 else "down"
                    )
                    value.delta_good = (
                        (value.delta_direction == "up" and self.delta_good_when == "up")
                        or (value.delta_direction == "down" and self.delta_good_when == "down")
                        or value.delta_direction == "flat"
                    )
            except Exception as exc:
                logger.warning(
                    "[ANALYTICS_V2] Compare failed for '%s': %s",
                    self.metric_id, exc,
                )
                # Don't fail the whole metric just because compare failed
        
        return value
