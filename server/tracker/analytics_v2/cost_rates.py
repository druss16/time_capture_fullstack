"""Single source of truth for per-user loaded labor cost.

Resolution priority (highest first):
  1. Per-person EmployeeCostRate override (manual / imported / payroll-synced)
  2. The member's CostTier rate
  3. (caller's org default — applied via ``.get(user_id, default)``)

Every profitability calculation (LaborCostMetric, the profitability lens, the
daily rollups, and the v1 analytics views) calls ``cost_rate_map`` so tiers and
overrides take effect everywhere at once. Users with neither an override nor a
tier are intentionally omitted so the caller's ``.get(uid, org_default)`` still
supplies the org blended default.
"""
from __future__ import annotations


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def cost_rate_map(org, as_of=None) -> dict[int, float]:
    """Return {user_id: resolved_cost_rate} for an org.

    ``as_of`` (a date) bounds the per-person override to rates effective on or
    before that day — used by the historical daily rollups. Tier assignment is
    current-state in Phase 1 (not effective-dated).
    """
    from tracker.models import EmployeeCostRate, OrganizationMembership

    rates: dict[int, float] = {}

    # 2) Tier rate for assigned members.
    for m in (OrganizationMembership.objects
              .filter(organization=org, cost_tier__isnull=False)
              .select_related("cost_tier")):
        cr = m.cost_tier.cost_rate
        if cr is not None:
            rates[m.user_id] = _to_float(cr)

    # 1) Per-person override wins over the tier.
    q = EmployeeCostRate.objects.filter(organization=org)
    if as_of is not None:
        q = q.filter(effective_date__lte=as_of)
    seen: set[int] = set()
    for er in q.order_by("user_id", "-effective_date"):
        if er.user_id in seen:
            continue
        seen.add(er.user_id)
        rates[er.user_id] = _to_float(er.cost_rate)

    return rates


def bill_rate_map(org) -> dict[int, float]:
    """Return {user_id: tier_bill_rate} for members whose cost tier has a bill_rate.

    This is the REVENUE fallback by seniority: a block's own rate and the client
    rate win first; this fills the gap (instead of the flat org default) for a
    member whose tier has a bill_rate set. Members with no tier — or a tier with
    a null bill_rate — are omitted so callers' ``.get(uid, org_default)`` applies
    the org billing_rate_default.
    """
    from tracker.models import OrganizationMembership

    rates: dict[int, float] = {}
    for m in (OrganizationMembership.objects
              .filter(organization=org, cost_tier__isnull=False)
              .select_related("cost_tier")):
        br = m.cost_tier.bill_rate
        if br is not None:
            rates[m.user_id] = _to_float(br)
    return rates


def capacity_map(org) -> dict[int, float]:
    """Return {user_id: weekly_capacity_hours} for members whose tier sets it.

    Available working hours/week per person, used as the denominator for
    capacity-based utilization (billable ÷ available). Members with no tier — or
    a tier with null hours_per_week — are omitted so callers apply the org
    default (Organization.capacity_hours_per_week).
    """
    from tracker.models import OrganizationMembership

    caps: dict[int, float] = {}
    for m in (OrganizationMembership.objects
              .filter(organization=org, cost_tier__isnull=False)
              .select_related("cost_tier")):
        hpw = m.cost_tier.hours_per_week
        if hpw is not None:
            caps[m.user_id] = _to_float(hpw)
    return caps
