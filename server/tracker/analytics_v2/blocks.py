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


def utilization_excluded_client_ids(org) -> set[int]:
    """Clients whose time is NOT hourly-billable work, so it shouldn't sit in
    the utilization numerator or denominator: flat-fee / retainer clients,
    non-billable clients, and the firm's internal-work clients. Retainer work is
    measured in Profitability (flat-fee revenue), not hourly utilization."""
    from .metrics.revenue_sources import flat_fee_client_ids, non_billable_client_ids
    from tracker.industry_categories import is_internal_client_name
    from tracker.models import Client

    ids: set[int] = set(flat_fee_client_ids(org)) | set(non_billable_client_ids(org))
    for cid, name in Client.objects.filter(org=org).values_list("id", "name"):
        if is_internal_client_name(name or ""):
            ids.add(cid)
    return ids


def working_qs(qs, org):
    """Hourly-engagement working time only: drops idle/lock AND flat-fee /
    non-billable / internal-client blocks. Used as the consistent basis for
    utilization so numerator, denominator, and the Tracked/Total tiles agree."""
    qs = exclude_idle(qs)
    excluded = utilization_excluded_client_ids(org)
    if excluded:
        qs = qs.exclude(client_id__in=excluded)
    return qs
