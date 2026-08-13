"""Shared Block-queryset helpers for analytics.

`exclude_idle` drops idle / lock-screen blocks. The agent records idle time as
"Idle/Uncategorized" (app_name "Idle") and lock-screen time (app_name "Lockapp")
blocks — they're captured but they are NOT active working time, so they must not
sit in the utilization "tracked" denominator (or they deflate every ratio).
"""
from __future__ import annotations

from django.db.models import Q

# App names / task-type names that represent idle or away-from-desk time.
IDLE_APP_NAMES = ("idle", "lockapp")
IDLE_TASK_TYPE_NAMES = ("idle",)


def exclude_idle(qs):
    """Return `qs` without idle / lock-screen blocks."""
    q = Q()
    for name in IDLE_APP_NAMES:
        q |= Q(app_name__iexact=name)
    for name in IDLE_TASK_TYPE_NAMES:
        q |= Q(task_type__name__iexact=name)
    return qs.exclude(q)


def billable_effort_client_ids(org) -> set[int]:
    """Clients flagged 'count as billable for utilization' — work that IS
    productive/billable effort (e.g. UltraTax parked under Internal-Tax) but
    isn't invoiced through the system. Counts in the utilization numerator; does
    NOT touch billing/export."""
    from tracker.models import ClientBillingProfile

    return set(
        ClientBillingProfile.objects
        .filter(org=org, counts_billable_utilization=True)
        .values_list("client_id", flat=True)
    )


def utilization_excluded_client_ids(org) -> set[int]:
    """Clients whose time is NOT counted in utilization at all: flat-fee /
    retainer clients, non-billable clients, and the firm's internal-work clients.
    Billable-effort clients (see above) are NOT excluded — their time counts as
    billable instead."""
    from .metrics.revenue_sources import flat_fee_client_ids, non_billable_client_ids
    from tracker.industry_categories import is_internal_client_name
    from tracker.models import Client

    ids: set[int] = set(flat_fee_client_ids(org)) | set(non_billable_client_ids(org))
    for cid, name in Client.objects.filter(org=org).values_list("id", "name"):
        if is_internal_client_name(name or ""):
            ids.add(cid)
    # Billable-effort clients count as billable — don't exclude them.
    return ids - billable_effort_client_ids(org)


def billable_q(org):
    """Q for blocks that count as BILLABLE in utilization: normally-billable
    blocks, PLUS any block on a billable-effort client."""
    q = Q(is_billable=True)
    eff = billable_effort_client_ids(org)
    if eff:
        q |= Q(client_id__in=eff)
    return q


def working_qs(qs, org):
    """Hourly-engagement working time only: drops idle/lock AND flat-fee /
    non-billable / internal-client blocks. Used as the consistent basis for
    utilization so numerator, denominator, and the Tracked/Total tiles agree."""
    qs = exclude_idle(qs)
    excluded = utilization_excluded_client_ids(org)
    if excluded:
        qs = qs.exclude(client_id__in=excluded)
    return qs
