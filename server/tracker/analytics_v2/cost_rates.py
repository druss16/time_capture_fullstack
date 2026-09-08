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


def default_cost_rate(org) -> float:
    """The org's blended fallback cost rate, carrying the same payroll burden
    that `cost_rate_map` applies to per-person rates.

    Metrics resolve a person's cost as ``rates.get(uid, default)``. If the
    default skipped the burden, an unmapped member would be costed on a
    different basis than everyone else — cheaper, and silently so.
    """
    rate = _to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
    burden = _to_float(getattr(org, "payroll_burden_multiplier", 1) or 1) or 1.0
    return rate * burden


def cost_rate_map(org, as_of=None) -> dict[int, float]:
    """Return {user_id: resolved_cost_rate} for an org.

    ``as_of`` (a date) picks the per-person override in force on that day —
    used by the historical daily rollups. If a person has overrides but none is
    effective by ``as_of`` yet, their earliest rate is used rather than falling
    back to the tier (see below). Tier assignment is current-state in Phase 1
    (not effective-dated).
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
    #
    # `as_of` picks the rate in force on that day. But a firm that enters its
    # payroll for the first time stamps every rate with TODAY's effective date,
    # and then every earlier day has no rate in force. Falling through to the
    # tier rate there is worse than useless: org 21's partners would cost $200/h
    # for July and August against a real $25, turning a +64.8% quarter into
    # -53.0%. So when a person has overrides but none effective yet, we use
    # their EARLIEST one rather than dropping to the tier placeholder.
    #
    # Effective-dating still does its job going forward: add a raise dated later
    # and history before it keeps the older rate.
    by_user: dict[int, list] = {}
    for er in (EmployeeCostRate.objects.filter(organization=org)
               .order_by("user_id", "-effective_date")):
        by_user.setdefault(er.user_id, []).append(er)

    for uid, ers in by_user.items():
        if as_of is None:
            rates[uid] = _to_float(ers[0].cost_rate)
            continue
        in_force = next((e for e in ers if e.effective_date <= as_of), None)
        # ers is newest-first, so the last entry is the earliest rate on file.
        rates[uid] = _to_float((in_force or ers[-1]).cost_rate)

    # 0) Payroll burden. Firms enter what payroll pays — a raw hourly wage —
    # which is not what an hour of that person costs the firm. Rather than ask
    # every firm to pre-multiply (and silently rot when wages change), the
    # assumption lives on the org as one number and is applied here, in the one
    # resolver every cost calculation already goes through. 1.00 is a no-op, so
    # firms that entered genuinely loaded rates are unaffected.
    burden = _to_float(getattr(org, "payroll_burden_multiplier", 1) or 1)
    if burden and burden != 1.0:
        rates = {uid: r * burden for uid, r in rates.items()}

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


def non_utilization_user_ids(org) -> set[int]:
    """Return {user_id} for members whose tier is flagged as NOT chargeable
    (counts_toward_utilization=False) — e.g. admin/ops/non-charging partners.

    These users are excluded from BOTH the numerator and denominator of firm-
    level utilization so their idle capacity doesn't drag the firm number down.
    Members with no tier, or a tier that counts, are absent from this set (they
    count normally). This is the "chargeable / fee-earner" population filter.
    """
    from tracker.models import OrganizationMembership

    return set(
        OrganizationMembership.objects
        .filter(organization=org,
                cost_tier__isnull=False,
                cost_tier__counts_toward_utilization=False)
        .values_list("user_id", flat=True)
    )
