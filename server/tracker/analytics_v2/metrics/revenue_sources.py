"""
Revenue-source helpers — make analytics aware of ALL three billing models.

Background: the block/invoice metrics only see hourly revenue (Block.billing_amount)
and imported invoices (Invoice.amount). Flat-fee / retainer clients
(ClientBillingProfile.billing_type='flat_fee') therefore contribute $0 to
profitability, which makes retainer-heavy firms look empty or unprofitable.

This module resolves flat-fee revenue by pro-rating each retainer to the analytics
time window, so firm/client scopes reflect the true revenue mix. Hourly clients
are unchanged (their revenue still comes from blocks/invoices); this only fills the
flat-fee gap.

Design:
  * `_prorate_flat_fee` is a PURE function (amount, period, window days) → dollars,
    so the money math is unit-testable without a database.
  * The DB-touching helpers are thin wrappers that read ClientBillingProfile and
    apply the analytics Scope.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from tracker.models import Block, ClientBillingProfile

from ..types import Scope, TimeRange, to_float

# Average calendar length of each period, used to derive a daily accrual rate.
# Days-based proration handles partial windows (this week, this quarter, MTD)
# without special cases.
_DAYS_PER_PERIOD = {
    "monthly": 30.4375,     # 365.25 / 12
    "quarterly": 91.3125,   # 365.25 / 4
    "annual": 365.25,
}


def _prorate_flat_fee(amount: float, period: str, window_days: int) -> float:
    """
    Pro-rate a flat fee to a window of `window_days` days.

    monthly/quarterly/annual → accrue a daily share across the window.
    per_project              → not time-based; the caller decides whether the
                               project is active in the window (returns full
                               `amount` here, gated on activity by the caller).
    blank/unknown period     → treated as monthly (the most common retainer
                               cadence) so a fee with a missing period still
                               contributes rather than silently reading $0.
    """
    amount = to_float(amount)
    if amount <= 0 or window_days <= 0:
        return 0.0

    if period == "per_project":
        # One-time fee — the caller only calls this when the project is active.
        return round(amount, 2)

    days_per = _DAYS_PER_PERIOD.get(period) or _DAYS_PER_PERIOD["monthly"]
    return round(amount / days_per * window_days, 2)


def _window_days(time: TimeRange) -> int:
    return (time.end - time.start).days + 1


def _scoped_client_ids(scope: Scope) -> tuple[bool, set[int] | None]:
    """
    Resolve which clients a scope allows for flat-fee revenue.

    Returns (supported, client_ids):
      supported=False           → scope has no client dimension (staff/service/
                                   engagement); flat fee isn't defined there.
      client_ids=None           → firm scope; all flat-fee clients.
      client_ids={...}           → restrict to these client ids.
    """
    if scope.type == "firm":
        return True, None
    if scope.type == "client":
        return True, set(scope.ids)
    if scope.type == "composite":
        ids = scope.filters.get("client")
        if ids:
            return True, set(ids)
        return True, None
    # staff / service / engagement — no client dimension
    return False, None


def flat_fee_by_client(org, scope: Scope, time: TimeRange) -> dict[int, dict]:
    """
    Pro-rated flat-fee revenue per client for this scope + window.

    Returns {client_id: {"name", "flat_amount", "period", "revenue"}} where
    `revenue` is the amount recognized in the window. Only flat-fee clients with a
    positive fee are included. Empty dict when the scope has no client dimension.
    """
    supported, allowed = _scoped_client_ids(scope)
    if not supported:
        return {}

    qs = (
        ClientBillingProfile.objects
        .filter(org=org, billing_type="flat_fee", flat_amount__isnull=False,
                flat_amount__gt=Decimal("0"))
        .select_related("client")
    )
    if allowed is not None:
        if not allowed:
            return {}
        qs = qs.filter(client_id__in=allowed)

    profiles = list(qs.only("client_id", "flat_amount", "flat_period", "client__name"))
    if not profiles:
        return {}

    days = _window_days(time)

    # per_project fees only count when work actually happened in the window.
    project_cids = {p.client_id for p in profiles if p.flat_period == "per_project"}
    active_project_cids: set[int] = set()
    if project_cids:
        active_project_cids = set(
            Block.objects
            .filter(org=org, day__gte=time.start, day__lte=time.end,
                    client_id__in=project_cids)
            .values_list("client_id", flat=True)
            .distinct()
        )

    out: dict[int, dict] = {}
    for p in profiles:
        if p.flat_period == "per_project" and p.client_id not in active_project_cids:
            continue
        revenue = _prorate_flat_fee(to_float(p.flat_amount), p.flat_period or "monthly", days)
        if revenue <= 0:
            continue
        out[p.client_id] = {
            "name": p.client.name if p.client else f"Client {p.client_id}",
            "flat_amount": to_float(p.flat_amount),
            "period": p.flat_period or "monthly",
            "revenue": revenue,
        }
    return out


def flat_fee_revenue_for(org, scope: Scope, time: TimeRange) -> float:
    """Total pro-rated flat-fee revenue for the scope + window."""
    return round(sum(r["revenue"] for r in flat_fee_by_client(org, scope, time).values()), 2)


def flat_fee_client_ids(org) -> set[int]:
    """Client ids billed on a flat fee (any period). Used to keep flat-fee clients
    out of the hourly revenue estimate so the two don't double-count."""
    return set(
        ClientBillingProfile.objects
        .filter(org=org, billing_type="flat_fee")
        .values_list("client_id", flat=True)
    )


def non_billable_client_ids(org) -> set[int]:
    """Client ids explicitly marked non-billable. Excluded from revenue + leakage."""
    return set(
        ClientBillingProfile.objects
        .filter(org=org, billing_type="non_billable")
        .values_list("client_id", flat=True)
    )
