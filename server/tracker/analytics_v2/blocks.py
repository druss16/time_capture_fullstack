"""Shared Block-queryset helpers for analytics.

BASIS
-----
Analytics reports CONFIRMED time — the same set Daily Review, Reports, Billing
and the Clio push count, defined once in `tracker.services.billing_totals`.
Analytics used to read raw blocks (`is_billable=True` and nothing else), which
counted suppressed time a human had explicitly killed, unconfirmed `proposed`
re-attributions, never-reviewed `captured` blocks, and time with no client at
all. On org 21's Q3 2026 that overstated revenue by 82.5 h / $6,191 (13.4%)
against the firm's own Daily Review screen. `confirmed_qs` is the fix; every
period metric composes it, so the dashboards can't drift apart again.

WIP is the deliberate exception: it has its own accrual ladder (unreviewed →
confirmed → approved → invoiced) and must keep counting unreviewed time as a
named tier, so it applies the hygiene half of the rules only. See metrics/wip.py.

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


def confirmed_qs(qs):
    """Restrict to confirmed, live time — the analytics basis.

    Thin pass-through to `services.billing_totals.apply_confirmed_rules` so the
    definition of "confirmed" is stated in exactly one place. Analytics windows
    on `day` while Daily Review windows on the UTC `start`, which is why the
    rule is shared as a queryset transform rather than a whole query."""
    from tracker.services.billing_totals import apply_confirmed_rules
    return apply_confirmed_rules(qs)


def billable_q(org):
    """Q for blocks that count as BILLABLE: the canonical billing rule (marked
    billable AND has a client AND not internal work), PLUS any block on a
    billable-effort client.

    The client requirement is what keeps unattributed time out of revenue —
    org 21 was carrying 489 clientless blocks (76.5 h) as billable."""
    from tracker.services.billing_totals import billable_block_q
    q = billable_block_q(org)
    eff = billable_effort_client_ids(org)
    if eff:
        q |= Q(client_id__in=eff)
    return q


def working_qs(qs, org):
    """Hourly-engagement working time only: drops idle/lock AND flat-fee /
    non-billable / internal-client blocks. Used as the consistent basis for
    utilization so numerator, denominator, and the Tracked/Total tiles agree."""
    qs = confirmed_qs(exclude_idle(qs))
    excluded = utilization_excluded_client_ids(org)
    if excluded:
        qs = qs.exclude(client_id__in=excluded)
    return qs
