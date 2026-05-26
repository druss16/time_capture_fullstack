"""
Permission enforcement for analytics v2.

Two responsibilities:
  1. Determine what scopes a user is *allowed* to query (powers the sidebar UI)
  2. Validate a specific incoming scope against the user's permissions

Role hierarchy (matches OrganizationMembership.role choices):
  owner   → full firm + any sub-scope, plus all admin actions
  admin   → full firm + any sub-scope
  manager → team scope (self + direct reports) + sub-scopes within team
  staff   → self scope only (NOTE: model still has 'member' label; migration
            renames to 'staff' in the same release)

Staff (Django is_staff/is_superuser) gets the v1 admin override: they can pass
?org_id=X to view any org. This mirrors the existing executive_dashboard()
behavior and powers MavOps admin tooling.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser

from tracker.models import (
    Client as ClientModel,
    Organization,
    OrganizationMembership,
)

from .types import Scope

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PermissionDenied(Exception):
    """Raised when a user's role doesn't permit the requested scope/lens.
    Serialized as HTTP 403."""

    def __init__(self, message: str, upgrade_required: bool = False):
        super().__init__(message)
        self.message = message
        self.upgrade_required = upgrade_required


class OrgNotFound(Exception):
    """Raised when no org can be resolved for the user. HTTP 404."""


# ---------------------------------------------------------------------------
# Role normalization
# ---------------------------------------------------------------------------

# Roles that have firm-wide read access for analytics
FIRM_ROLES = {"owner", "admin"}
# Roles that can see team members beyond themselves
TEAM_ROLES = {"owner", "admin", "manager"}
# Anyone with a membership can at least see themselves
SELF_ROLES = {"owner", "admin", "manager", "staff", "member"}


def _normalize_role(role: str) -> str:
    """Treat legacy 'member' the same as 'staff' until the migration runs."""
    return "staff" if role == "member" else role


# ---------------------------------------------------------------------------
# Org resolution (mirrors v1's _get_user_org pattern with override support)
# ---------------------------------------------------------------------------

def resolve_org_for_request(
    user: AbstractUser,
    org_id_override: Optional[str] = None,
) -> tuple[Organization, Optional[str]]:
    """
    Resolve which org this request operates on, and what role the user has there.
    
    Override flow (matches v1 executive_dashboard):
      - If user is Django staff/superuser AND org_id_override is provided,
        load that org and return role=None (impersonation, bypasses role checks).
      - Otherwise, find the user's most relevant membership.
    
    Returns (Organization, role_or_None). Raises OrgNotFound or PermissionDenied.
    """
    # Admin override path
    if org_id_override and (user.is_staff or user.is_superuser):
        try:
            org = Organization.objects.get(id=org_id_override)
        except (Organization.DoesNotExist, ValueError):
            raise OrgNotFound(f"Organization {org_id_override} not found")
        logger.info(
            "[ANALYTICS_V2] Admin override: user=%s org_id=%s",
            getattr(user, "username", "?"), org_id_override,
        )
        return org, None
    
    # Regular path: find the user's membership
    membership = (
        OrganizationMembership.objects
        .filter(user=user, role="owner")
        .select_related("organization")
        .first()
    )
    if not membership:
        membership = (
            OrganizationMembership.objects
            .filter(user=user)
            .select_related("organization")
            .order_by("-id")
            .first()
        )
    
    if not membership:
        raise OrgNotFound("No organization membership found for this user")
    
    return membership.organization, _normalize_role(membership.role)


# ---------------------------------------------------------------------------
# Direct reports helper (for manager scope)
# ---------------------------------------------------------------------------

def get_direct_report_ids(user: AbstractUser, org: Organization) -> set[int]:
    """
    Return the set of user IDs a manager can query against.
    Always includes the manager themselves.
    
    NOTE: Your current OrganizationMembership has no `manager` FK. Until that
    column is added, managers can see ALL non-admin/non-owner members of their
    org as "their team." This matches the v1 behavior (a manager could query
    any staff member). When you add a proper reporting hierarchy, update this
    function and the rest of the codebase picks it up.
    """
    # Self
    ids = {user.id}
    # All other members below admin level in the same org
    member_ids = OrganizationMembership.objects.filter(
        organization=org,
        role__in=["manager", "member", "staff"],
    ).values_list("user_id", flat=True)
    ids.update(member_ids)
    return ids


# ---------------------------------------------------------------------------
# Plan gating
# ---------------------------------------------------------------------------

# Lenses that require the Executive plan. Pulse and basic Profitability are
# included with Professional; deep AI / Trends require Executive.
EXECUTIVE_ONLY_LENSES = {"trends"}
# All other lenses are available on Professional+.


def authorize_lens(org: Organization, lens: str) -> None:
    """Raise PermissionDenied if the org's plan doesn't include this lens."""
    plan = (getattr(org, "plan", "none") or "none").lower()
    
    # No plan at all → no analytics
    if not any(plan.startswith(p) for p in ("professional", "executive", "trial")):
        raise PermissionDenied(
            "Analytics requires a Professional or Executive plan.",
            upgrade_required=True,
        )
    
    # Executive-only lens on a Professional plan → blocked
    if lens in EXECUTIVE_ONLY_LENSES and not plan.startswith(("executive", "trial")):
        raise PermissionDenied(
            f"The '{lens}' lens requires the Executive plan.",
            upgrade_required=True,
        )


# ---------------------------------------------------------------------------
# Scope authorization
# ---------------------------------------------------------------------------

def authorize_scope(
    user: AbstractUser,
    role: Optional[str],
    org: Organization,
    scope: Scope,
) -> Scope:
    """
    Validate (and label) the requested scope against the user's role.
    Returns the same Scope with .label populated.
    
    Raises PermissionDenied if the user can't query this scope.
    
    role=None means admin override is active (no role check, full access).
    """
    # Admin override skips role checks entirely
    if role is None:
        return _label_scope(scope, org)
    
    # --- firm scope ---
    if scope.type == "firm":
        if role not in FIRM_ROLES:
            raise PermissionDenied(
                f"Firm-wide view requires owner or admin role (your role: {role})."
            )
        return _label_scope(scope, org)
    
    # --- staff scope ---
    if scope.type == "staff":
        if role in FIRM_ROLES:
            # Any staff is fair game
            return _label_scope(scope, org)
        if role == "manager":
            allowed = get_direct_report_ids(user, org)
            if not set(scope.ids).issubset(allowed):
                raise PermissionDenied(
                    "Manager scope can only include yourself and your direct reports."
                )
            return _label_scope(scope, org)
        # staff/member role → only self
        if set(scope.ids) != {user.id}:
            raise PermissionDenied(
                "Staff can only view their own data."
            )
        return _label_scope(scope, org)
    
    # --- client scope ---
    if scope.type == "client":
        # Verify clients belong to this org (multi-tenant safety)
        existing = set(
            ClientModel.objects.filter(id__in=scope.ids, org=org)
            .values_list("id", flat=True)
        )
        missing = set(scope.ids) - existing
        if missing:
            raise PermissionDenied(
                f"Clients not in your organization: {sorted(missing)}"
            )
        
        # Staff role: restrict to assigned clients only
        if role == "staff":
            assigned = set(
                ClientModel.objects.filter(
                    id__in=scope.ids,
                    assignments__user=user,
                ).values_list("id", flat=True)
            )
            if assigned != set(scope.ids):
                raise PermissionDenied(
                    "You can only view clients assigned to you."
                )
        
        return _label_scope(scope, org)
    
    # --- service / engagement / composite ---
    # These are read-only filters that don't expose any new data beyond what
    # the user's role already allows. No additional check needed beyond ensuring
    # the user has at least *some* access.
    if scope.type in ("service", "engagement", "composite"):
        if role not in SELF_ROLES:
            raise PermissionDenied(
                f"Role '{role}' cannot query analytics."
            )
        return _label_scope(scope, org)
    
    raise PermissionDenied(f"Unknown scope type: {scope.type}")


# ---------------------------------------------------------------------------
# Scope labeling — turns IDs into human-readable text for the response sentence
# ---------------------------------------------------------------------------

def _label_scope(scope: Scope, org: Organization) -> Scope:
    """Populate scope.label for the response sentence header."""
    if scope.label:
        return scope  # Pre-labeled by caller
    
    if scope.type == "firm":
        return Scope(type=scope.type, ids=scope.ids, filters=scope.filters,
                     label=org.name)
    
    if scope.type == "client":
        names = list(
            ClientModel.objects.filter(id__in=scope.ids, org=org)
            .values_list("name", flat=True)
        )
        if not names:
            label = f"{len(scope.ids)} clients"
        elif len(names) == 1:
            label = names[0]
        elif len(names) <= 3:
            label = ", ".join(names)
        else:
            label = f"{names[0]} + {len(names) - 1} others"
        return Scope(type=scope.type, ids=scope.ids, filters=scope.filters, label=label)
    
    if scope.type == "staff":
        users = list(
            User.objects.filter(id__in=scope.ids)
            .values_list("first_name", "last_name", "username")
        )
        if not users:
            label = f"{len(scope.ids)} staff"
        elif len(users) == 1:
            fn, ln, un = users[0]
            label = f"{fn} {ln}".strip() or un
        elif len(users) <= 3:
            label = ", ".join((f"{fn} {ln}".strip() or un) for fn, ln, un in users)
        else:
            first = users[0]
            first_label = f"{first[0]} {first[1]}".strip() or first[2]
            label = f"{first_label} + {len(users) - 1} others"
        return Scope(type=scope.type, ids=scope.ids, filters=scope.filters, label=label)
    
    # service / engagement / composite — use whatever's in filters
    return Scope(type=scope.type, ids=scope.ids, filters=scope.filters,
                 label=scope.label or str(scope.type))


# ---------------------------------------------------------------------------
# Available scopes for sidebar UI
# ---------------------------------------------------------------------------

def get_available_scopes(user: AbstractUser, role: Optional[str], org: Organization) -> dict:
    """
    Used by /api/analytics/permissions/ — tells the frontend which scope
    options to render in the sidebar for this user.
    """
    if role is None:
        # Admin override — full access
        return {
            "can_firm": True,
            "can_pick_any_client": True,
            "can_pick_any_staff": True,
            "available_lenses": list(_all_lens_keys_for_plan(org)),
        }
    
    return {
        "can_firm": role in FIRM_ROLES,
        "can_pick_any_client": role in FIRM_ROLES or role == "manager",
        "can_pick_any_staff": role in FIRM_ROLES,
        "available_lenses": list(_all_lens_keys_for_plan(org)),
    }


def _all_lens_keys_for_plan(org: Organization) -> set[str]:
    plan = (getattr(org, "plan", "none") or "none").lower()
    base = {"pulse", "profitability", "utilization", "wip", "realization"}
    if plan.startswith(("executive", "trial")):
        base.add("trends")
    return base

def firm_invoices_here(org) -> bool:
    """
    Returns True if this org has ever recorded an Invoice in TimeTracker.
    
    Used by lenses to swap their behavior for firms (like TL Wall) that
    log time but invoice elsewhere. False means "show graceful empty states
    for invoice-dependent metrics; emphasize block-based metrics instead."
    
    This is a cheap query (single COUNT with index hit) so we call it on
    every request rather than caching it. If perf becomes a concern, add
    a `has_invoices` boolean to Organization populated by the rollup task.
    """
    from tracker.models import Invoice
    return Invoice.objects.filter(org=org).exists()
