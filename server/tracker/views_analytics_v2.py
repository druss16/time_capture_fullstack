"""
DRF views for analytics v2.

Endpoints:
  POST /api/analytics/query/         — main query endpoint
  GET  /api/analytics/permissions/   — what scopes/lenses can this user see?
  GET  /api/analytics/saved-views/   — list user's saved views
  POST /api/analytics/saved-views/   — create a saved view
  PATCH/DELETE /api/analytics/saved-views/<id>/   — update/delete

The query endpoint mirrors the v1 executive_dashboard() admin override pattern:
Django staff users can pass ?org_id=<id> to view any org.
"""
from __future__ import annotations

import json
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .analytics_v2.permissions import (
    OrgNotFound, PermissionDenied, authorize_analytics_access,
    get_available_scopes, resolve_org_for_request,
)
from .analytics_v2.query import execute_query
from .analytics_v2.scopes import RequestParseError
from .analytics_v2.rollups.models import SavedView

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main query endpoint
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def analytics_query(request):
    """
    POST /api/analytics/query/
    
    Body shape:
        {
            "scope":   {"type": "firm", "ids": []},
            "lens":    "pulse",
            "time":    {"type": "relative", "value": "this_quarter"},
            "compare": {"type": "relative", "value": "last_quarter"}
        }
    
    Admin override: ?org_id=<id> works for Django staff.
    """
    org_id_override = request.GET.get("org_id")
    body = request.data if isinstance(request.data, dict) else {}
    
    try:
        response = execute_query(request.user, body, org_id_override=org_id_override)
        return Response(response, status=status.HTTP_200_OK)
    
    except RequestParseError as exc:
        return Response(
            {"error": "bad_request", "message": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    except OrgNotFound as exc:
        return Response(
            {"error": "org_not_found", "message": str(exc)},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    except PermissionDenied as exc:
        return Response(
            {
                "error": "permission_denied",
                "message": exc.message,
                "upgrade_required": exc.upgrade_required,
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    
    except Exception as exc:
        # Unexpected error — log full trace, return generic 500
        logger.exception("[ANALYTICS_V2] Unhandled error in /query/: %s", exc)
        return Response(
            {"error": "internal_error", "message": "Something went wrong"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# Permissions / capabilities endpoint
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analytics_permissions(request):
    """
    GET /api/analytics/permissions/
    
    Returns what this user can query, used to populate the sidebar UI.
    Includes admin-override support for Django staff via ?org_id=<id>.
    """
    org_id_override = request.GET.get("org_id")
    try:
        org, role = resolve_org_for_request(request.user, org_id_override=org_id_override)
    except OrgNotFound as exc:
        return Response(
            {"error": "org_not_found", "message": str(exc)},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    try:
        authorize_analytics_access(role)
    except PermissionDenied as exc:
        return Response(
            {"error": "permission_denied", "message": exc.message,
             "upgrade_required": exc.upgrade_required},
            status=status.HTTP_403_FORBIDDEN,
        )

    caps = get_available_scopes(request.user, role, org)
    return Response({
        "org_id": org.id,
        "org_name": org.name,
        "plan": getattr(org, "plan", "none"),
        "role": role,
        "capabilities": caps,
    })


# ---------------------------------------------------------------------------
# Saved views CRUD
# ---------------------------------------------------------------------------

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def saved_views_list(request):
    org_id_override = request.GET.get("org_id")
    try:
        org, _role = resolve_org_for_request(request.user, org_id_override=org_id_override)
    except OrgNotFound as exc:
        return Response({"error": "org_not_found", "message": str(exc)},
                        status=status.HTTP_404_NOT_FOUND)
    
    if request.method == "GET":
        # User's own views + views explicitly shared with them
        own = SavedView.objects.filter(user=request.user, org=org)
        shared = SavedView.objects.filter(org=org, shared_with=request.user).exclude(user=request.user)
        rows = [_serialize_view(v, owned=True) for v in own] + \
               [_serialize_view(v, owned=False) for v in shared]
        return Response({"saved_views": rows})
    
    # POST: create
    body = request.data if isinstance(request.data, dict) else {}
    name = (body.get("name") or "").strip()
    query = body.get("query")
    if not name or not isinstance(query, dict):
        return Response(
            {"error": "bad_request", "message": "name and query are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    view = SavedView.objects.create(
        org=org, user=request.user,
        name=name, query=query,
        pinned=bool(body.get("pinned", False)),
        schedule=body.get("schedule"),
    )
    return Response(_serialize_view(view, owned=True), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def saved_view_detail(request, view_id: int):
    try:
        view = SavedView.objects.get(id=view_id, user=request.user)
    except SavedView.DoesNotExist:
        return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == "DELETE":
        view.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    # PATCH
    body = request.data if isinstance(request.data, dict) else {}
    if "name" in body:
        view.name = (body["name"] or "").strip() or view.name
    if "query" in body and isinstance(body["query"], dict):
        view.query = body["query"]
    if "pinned" in body:
        view.pinned = bool(body["pinned"])
    if "schedule" in body:
        view.schedule = body["schedule"]
    view.save()
    return Response(_serialize_view(view, owned=True))


def _serialize_view(v: SavedView, owned: bool) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "query": v.query,
        "pinned": v.pinned,
        "schedule": v.schedule,
        "owned": owned,
        "created_at": v.created_at.isoformat(),
        "updated_at": v.updated_at.isoformat(),
    }
