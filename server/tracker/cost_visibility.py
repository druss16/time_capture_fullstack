"""Owner-only visibility for labor cost data.

What a firm pays its people is the most sensitive number in the system. A firm
hands us salaries on the understanding that the partners are the only ones who
ever see them back — a manager reading a peer's loaded cost off an analytics
table is a breach of that deal, not a feature.

Visibility had been welded to the permission role, and the role ladder puts
manager above the settings line: ``IsOrgAdmin`` resolves to owner/admin/manager,
so managers could read (and write) the cost roster, and the profitability lens
handed them per-staff ``cost`` at staff scope. This module is the one place that
decides otherwise.

Scope of the lock is COST only. Bill rates stay visible: they already drive
revenue, WIP, realization and effective-rate figures that managers and staff
work from every day, and hiding them would blank working screens to protect a
number the firm publishes anyway.

Two enforcement shapes, both driven from here:

  * Endpoints that exist to serve cost (the cost-tier settings, the economics
    import, the per-person overrides) refuse outright — see ``require_cost_access``.
  * Endpoints that carry cost as *part* of a wider payload (analytics) are
    redacted rather than refused, so a manager keeps their utilization and
    revenue and simply loses the cost columns — see ``redact_cost_sections``.
"""
from __future__ import annotations

from typing import Any

# Metric ids (== KPI tile ids, see lenses/helpers.kpi_tile) that are cost or are
# a straight function of cost. Margin is revenue MINUS cost: publish revenue and
# margin to the same person and they have cost by subtraction.
COST_METRIC_IDS = frozenset({
    "labor_cost",
    "overhead_cost",
    "gross_margin",
    "operating_margin",
})

# Row/column/series keys carrying cost or a cost-derived figure.
COST_FIELD_KEYS = frozenset({
    "cost",
    "cost_rate",
    "worked_cost",
    "labor_cost",
    "overhead_cost",
    "margin",
    "margin_pct",
    "margin_percent",
    "margin_dollars",
    "override_rate",
    "default_cost",
})


def can_view_cost_data(user, org) -> bool:
    """True only for an owner of ``org`` (or a MavOps superuser doing support).

    Deliberately NOT role-in-a-list: 'owner' is the whole list. Django staff is
    excluded — is_staff is broad enough in this codebase to be a side door;
    is_superuser is the vendor operator who can already read the database.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if org is None:
        return False

    from .models import OrganizationMembership
    return OrganizationMembership.objects.filter(
        user=user, organization=org, role="owner"
    ).exists()


def cost_denied_response():
    """The 403 body used by every cost endpoint, so the message reads the same."""
    from rest_framework.response import Response
    return Response(
        {
            "error": "cost_data_restricted",
            "message": (
                "Labor cost data is visible to firm owners only."
            ),
        },
        status=403,
    )


# ---------------------------------------------------------------------------
# Redaction — used where cost rides along inside a larger payload
# ---------------------------------------------------------------------------

def _scrub_subtitle(subtitle: str) -> str:
    """Drop ' · '-separated clauses that quote a cost/margin figure.

    Lenses fold summary stats into subtitles ("Q3 · median client margin 42%"),
    which would survive column-level redaction and leak the aggregate. Only the
    offending clause goes; the period label in front of it stays.
    """
    if not subtitle:
        return subtitle
    kept = [
        part for part in subtitle.split(" · ")
        if "margin" not in part.lower() and "cost" not in part.lower()
    ]
    return " · ".join(kept)


def _redact_node(node: Any) -> Any:
    """Strip cost from one serialized section/payload dict, recursively."""
    if isinstance(node, list):
        return [_redact_node(n) for n in node]
    if not isinstance(node, dict):
        return node

    ntype = node.get("type")

    if ntype == "kpi_row":
        node["tiles"] = [
            t for t in node.get("tiles") or []
            if t.get("id") not in COST_METRIC_IDS
        ]
        return node

    if ntype == "data_table":
        node["columns"] = [
            c for c in node.get("columns") or []
            if c.get("key") not in COST_FIELD_KEYS
        ]
        node["rows"] = [
            {k: v for k, v in row.items() if k not in COST_FIELD_KEYS}
            for row in node.get("rows") or []
        ]
        # A default sort pointing at a column that no longer exists would leave
        # the table sorted by nothing; fall back to the first surviving column.
        sort = node.get("default_sort") or {}
        if sort.get("key") in COST_FIELD_KEYS:
            first = node["columns"][0]["key"] if node["columns"] else None
            node["default_sort"] = {"key": first, "direction": "desc"} if first else None
        node["subtitle"] = _scrub_subtitle(node.get("subtitle") or "")
        return node

    if ntype == "chart_card":
        node["series"] = [
            s for s in node.get("series") or []
            if s.get("key") not in COST_FIELD_KEYS
        ]
        node["data"] = [
            {k: v for k, v in point.items() if k not in COST_FIELD_KEYS}
            if isinstance(point, dict) else point
            for point in node.get("data") or []
        ]
        node["subtitle"] = _scrub_subtitle(node.get("subtitle") or "")
        return node

    if ntype == "insight_card":
        node["evidence"] = [
            {k: v for k, v in e.items() if k not in COST_FIELD_KEYS}
            if isinstance(e, dict) else e
            for e in node.get("evidence") or []
        ]
        return node

    if "children" in node:
        node["children"] = [_redact_node(c) for c in node["children"]]
        # A section whose only content was cost (a lone margin table) becomes an
        # empty shell; drop it rather than render a titled void.
        node["children"] = [c for c in node["children"] if not _is_empty_table(c)]

    return node


def _is_empty_table(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and node.get("type") == "data_table"
        and not node.get("columns")
    )


def redact_cost_sections(sections: list[dict]) -> list[dict]:
    """Remove every cost/margin figure from serialized analytics sections.

    Returns sections that still render — the viewer keeps hours, revenue,
    utilization and realization; the cost columns and margin tiles are simply
    not there. Sections left with no children at all are dropped.
    """
    out = []
    for section in sections:
        node = _redact_node(section)
        if node.get("type") == "kpi_row" and not node.get("tiles"):
            continue
        if node.get("type") == "section" and not node.get("children"):
            continue
        out.append(node)
    return out


def strip_cost_fields(obj: Any) -> Any:
    """Deep-remove every COST_FIELD_KEYS key from a plain JSON structure.

    For the v1 analytics payloads, which nest cost several levels down (client
    rows carry a per-service breakdown that carries its own cost). Structure is
    otherwise preserved, so the caller's shape still renders.
    """
    if isinstance(obj, dict):
        return {
            k: strip_cost_fields(v)
            for k, v in obj.items()
            if k not in COST_FIELD_KEYS
        }
    if isinstance(obj, list):
        return [strip_cost_fields(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# DRF permission class — for class-based views whose whole payload is cost
# ---------------------------------------------------------------------------

class CanViewCostData:
    """Owner-only DRF permission. Use on views that exist to serve cost.

    Kept duck-typed rather than subclassing BasePermission so this module stays
    importable from management commands and tests without DRF side effects.
    """
    message = "Labor cost data is visible to firm owners only."

    def has_permission(self, request, view):
        from .views import get_user_org
        return can_view_cost_data(request.user, get_user_org(request.user))

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
