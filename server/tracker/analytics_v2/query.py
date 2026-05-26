"""
Top-level query orchestrator. Called by the DRF view in views_analytics_v2.py.

Flow:
  1. parse_request_body() → Scope, Lens, TimeRange, optional compare
  2. resolve_org_for_request() → Org + role
  3. authorize_lens() + authorize_scope()
  4. get_lens(lens).assemble(org, scope, time, compare) → sections
  5. Build response envelope (view sentence + sections + meta)
"""
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from .lenses import get_lens
from .permissions import (
    OrgNotFound, PermissionDenied, authorize_lens, authorize_scope,
    resolve_org_for_request,
)
from .scopes import RequestParseError, parse_request_body
from .types import Section

logger = logging.getLogger(__name__)


def execute_query(user, body: dict, org_id_override: str | None = None) -> dict:
    """
    Execute a query and return a response dict (ready to JSON-serialize).
    Raises RequestParseError / OrgNotFound / PermissionDenied for the view to map to HTTP codes.
    """
    # 1. Parse the body
    scope, lens_key, time, compare = parse_request_body(body)
    
    # 2. Resolve org + role
    org, role = resolve_org_for_request(user, org_id_override=org_id_override)
    
    # 3. Permission checks
    authorize_lens(org, lens_key)
    scope = authorize_scope(user, role, org, scope)
    
    # 4. Build sections
    lens = get_lens(lens_key)
    sections: list[Section] = lens.assemble(org, scope, time, compare)
    
    # 5. Build sentence
    parts = [scope.label or org.name, time.label]
    if compare:
        parts.append(f"vs {compare.label}")
    sentence = " · ".join(parts)
    
    # 6. Data freshness — last Block.updated_at in this org
    from tracker.models import Block
    last_ingest = (
        Block.all_objects
        .filter(org=org)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )

    from .permissions import firm_invoices_here
    invoiceless = not firm_invoices_here(org)
    
    return {
        "view": {
            "scope": scope.to_dict(),
            "lens": lens_key,
            "time": time.to_dict(),
            "compare": compare.to_dict() if compare else None,
            "sentence": sentence,
        },
        "sections": [s.to_dict() for s in sections],
        "meta": {
            "org_id": org.id,
            "org_name": org.name,
            "plan": getattr(org, "plan", "none"),
            "role": role,
            "generated_at": timezone.now().isoformat(),
            "data_freshness": last_ingest.isoformat() if last_ingest else None,
            "version": "2.0.0-alpha.2",
            "invoiceless": invoiceless,
        },
    }
