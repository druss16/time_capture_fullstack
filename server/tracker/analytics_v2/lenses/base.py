"""
Lens base class and registry.

A Lens is a composition of metrics + chart cards + data tables that answers a
single question ("how profitable are we?", "what's our utilization?"). The
same lens reshapes itself based on scope — Profitability at firm scope shows
"top 10 clients by margin," at single-client scope shows "service line mix
for this client."

Adding a new lens:
  1. Create analytics_v2/lenses/<key>.py
  2. Subclass Lens, decorate with @register_lens("key")
  3. Override assemble() to return list[Section]
  4. Reference the lens key from frontend's sidebar lens list
"""
from __future__ import annotations

import logging
from typing import Optional

from tracker.models import Organization

from ..types import Scope, Section, TimeRange

logger = logging.getLogger(__name__)


_LENS_REGISTRY: dict[str, type["Lens"]] = {}


def register_lens(key: str):
    def decorator(cls: type["Lens"]) -> type["Lens"]:
        if key in _LENS_REGISTRY:
            raise RuntimeError(f"Lens '{key}' already registered")
        cls.key = key
        _LENS_REGISTRY[key] = cls
        return cls
    return decorator


def get_lens(key: str) -> "Lens":
    if key not in _LENS_REGISTRY:
        raise KeyError(f"Unknown lens '{key}'. Registered: {sorted(_LENS_REGISTRY)}")
    return _LENS_REGISTRY[key]()


def all_lens_keys() -> list[str]:
    return sorted(_LENS_REGISTRY)


class Lens:
    key: str = ""
    label: str = ""
    required_plan: str = "professional"
    
    def assemble(
        self,
        org: Organization,
        scope: Scope,
        time: TimeRange,
        compare: Optional[TimeRange] = None,
    ) -> list[Section]:
        """Override. Return the sections (KPI rows, charts, tables) for this lens."""
        raise NotImplementedError
