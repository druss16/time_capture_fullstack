"""
WIP (Work In Progress) metrics — billable time captured but not yet invoiced.

WIP is NOT time-windowed the way other metrics are. WIP is a snapshot of
"as of now, what's sitting uninvoiced." For Pulse / dashboard views, the
time window is essentially ignored (or used only for "WIP that became 60+ days
during this window" type comparisons).

ACCRUAL LADDER
--------------
WIP used to be gated on `approved=True`, i.e. on a signed timesheet. That made
the number a lie at firms that don't run the approval workflow: org 21 had
$17k "WIP" and $143k of billable time sitting invisible behind the gate.

WIP now accrues the moment time is captured, tiered by how vetted it is:

    unreviewed  captured/proposed — real time, not yet confirmed in Daily Review
    confirmed   classification committed — client + category are settled
    approved    timesheet-signed on top of confirmed
    invoiced    relieved — leaves WIP entirely (see services/wip_relief.py)

Headline WIP = confirmed + approved. `unreviewed` is reported alongside as
pipeline so nobody thinks the rest of the money vanished. Suppressed blocks
are never WIP.

AGING BASIS
-----------
Aging runs from the *work date* (`day`), not `approved_at`. Aging from approval
made April work look two days old the moment a timesheet got signed, which is
exactly backwards: the firm's cash risk starts when the hour is worked.

This module is the single source of truth for "what is WIP and what is it
worth." The lens, the hourly snapshot task, and the insights engine all call
these helpers rather than rebuilding the filter — the four numbers must agree.
"""
from __future__ import annotations

from datetime import date

from django.db.models import Q, QuerySet
from django.utils import timezone

from tracker.models import Block, Organization

from ..types import MetricState, MetricValue, Scope, to_float
from .base import Metric, register_metric

# Blocks in these classification states are settled enough to bill.
COMMITTED_STATES = ("committed",)
# ...and these are real captured time that nobody has vetted yet.
UNREVIEWED_STATES = ("captured", "proposed")

# Tier keys accepted by wip_qs().
TIER_BILLABLE_READY = "billable_ready"   # confirmed + approved (headline WIP)
TIER_UNREVIEWED = "unreviewed"           # captured/proposed pipeline
TIER_ALL = "all"                         # both, for total-pipeline views


def apply_scope(qs: QuerySet, scope: Scope) -> QuerySet:
    """Scope-filter a queryset without needing a Metric instance in hand.

    Lenses and rollup tasks aren't Metrics but need the same dimension
    filtering; this saves them from instantiating a throwaway helper class.
    """
    return Metric()._apply_scope(qs, scope)


def wip_qs(org: Organization, scope: Scope | None = None,
           tier: str = TIER_BILLABLE_READY) -> QuerySet:
    """Uninvoiced billable blocks for this scope, at the given accrual tier."""
    qs = Block.objects.filter(org=org, invoiced=False, is_billable=True)

    if tier == TIER_BILLABLE_READY:
        qs = qs.filter(Q(classification_state__in=COMMITTED_STATES) | Q(approved=True))
    elif tier == TIER_UNREVIEWED:
        qs = qs.filter(classification_state__in=UNREVIEWED_STATES, approved=False)
    elif tier == TIER_ALL:
        qs = qs.exclude(classification_state="suppressed")
    else:
        raise ValueError(f"Unknown WIP tier: {tier!r}")

    if scope is not None:
        qs = apply_scope(qs, scope)
    return qs


# Fields every WIP walk needs. Keep in sync with block_amount/block_age_days.
WIP_FIELDS = ("minutes", "billing_amount", "billing_rate", "day", "start")


def block_amount(b, default_rate: float) -> float:
    """Resolve the dollar amount for a block, with default fallback."""
    amount = to_float(b.billing_amount)
    if amount:
        return amount
    hours = to_float(b.minutes) / 60.0
    rate = to_float(b.billing_rate) or default_rate
    return hours * rate


def block_age_days(b, today: date | None = None) -> int:
    """How long has this block been sitting unbilled, counted from the work date.

    `day` is the work date and is set on every real block. `start` is the
    fallback for the handful of blocks that predate it.
    """
    today = today or timezone.localdate()
    ref = b.day
    if ref is None and b.start:
        ref = timezone.localtime(b.start).date() if timezone.is_aware(b.start) else b.start.date()
    if ref is None:
        return 0
    return max(0, (today - ref).days)


def default_rate_for(org: Organization) -> float:
    return to_float(getattr(org, "billing_rate_default", 0))


def wip_total_value(org: Organization, scope: Scope | None = None,
                    tier: str = TIER_BILLABLE_READY) -> float:
    """Total dollar value of the WIP tier."""
    default = default_rate_for(org)
    return round(sum(
        block_amount(b, default)
        for b in wip_qs(org, scope, tier).only(*WIP_FIELDS)
    ), 2)


def _realizable_secondary(org, scope, time, gross_total, metric_self) -> dict | None:
    """Return KPI secondary fields for realizable WIP, or None when we can't
    compute a trustworthy realization rate (no invoices → don't fake a haircut).

    realizable = gross WIP × (dollar realization % / 100). Only applied when
    realization is invoice-backed and below 100% (a discount worth showing)."""
    try:
        from .realization import RealizationDollarMetric
        r = RealizationDollarMetric().compute(org, scope, time)
    except Exception:
        return None
    if r.state != MetricState.READY or r.value is None:
        return None
    rate = to_float(r.value)
    if rate <= 0 or rate >= 100:
        return None
    return {
        "secondary_value": round(gross_total * rate / 100.0, 2),
        "secondary_label": f"Realizable at {rate:.0f}% realization",
        "secondary_format": "currency_0dp",
    }


@register_metric("wip_total")
class WipTotalMetric(Metric):
    label = "WIP Total"
    format = "currency_0dp"
    tooltip = (
        "Dollar value of confirmed billable time that hasn't been invoiced yet. "
        "Accrues as time is captured — it does not wait for timesheet approval."
    )
    valid_scopes = ("firm", "client", "staff", "composite")
    delta_good_when = "down"  # Lower WIP = faster billing = better cash flow

    def compute(self, org, scope, time):
        # time is ignored for WIP — it's a "now" snapshot
        total = wip_total_value(org, scope, TIER_BILLABLE_READY)
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)

        # Realizable WIP: standard-rate WIP is optimistic — historically the firm
        # only collects `realization%` of what it books. Surface a realizable
        # value (WIP × historical realization) so the number isn't overstated.
        # Only when we have real invoice-backed realization; otherwise show gross.
        secondary = _realizable_secondary(org, scope, time, total, self)
        if secondary:
            return MetricValue(value=total, **secondary)
        return MetricValue(value=total)


@register_metric("wip_unreviewed")
class WipUnreviewedMetric(Metric):
    label = "Unreviewed Pipeline"
    format = "currency_0dp"
    tooltip = (
        "Captured billable time that hasn't been confirmed in Daily Review yet. "
        "Real work and real money — it just isn't vetted enough to bill."
    )
    valid_scopes = ("firm", "client", "staff", "composite")
    delta_good_when = "down"  # A growing unreviewed pile = review backlog

    def compute(self, org, scope, time):
        total = wip_total_value(org, scope, TIER_UNREVIEWED)
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        count = wip_qs(org, scope, TIER_UNREVIEWED).count()
        return MetricValue(
            value=total,
            secondary_value=count,
            secondary_label=f"{count:,} block{'' if count == 1 else 's'} awaiting review",
            secondary_format="integer",
        )


@register_metric("wip_aged_60_plus")
class WipAged60PlusMetric(Metric):
    label = "WIP Aged 60+"
    format = "currency_0dp"
    tooltip = (
        "WIP whose work date is 60+ days back. Risk of write-off — prioritize billing."
    )
    valid_scopes = ("firm", "client", "staff", "composite")
    delta_good_when = "down"

    def compute(self, org, scope, time):
        today = timezone.localdate()
        default = default_rate_for(org)
        total = 0.0
        for b in wip_qs(org, scope, TIER_BILLABLE_READY).only(*WIP_FIELDS):
            if block_age_days(b, today) >= 60:
                total += block_amount(b, default)
        if total == 0:
            return MetricValue(state=MetricState.EMPTY)
        return MetricValue(value=round(total, 2))


def compute_wip_aging_bands(org, scope=None, metric_self=None,
                            tier: str = TIER_BILLABLE_READY) -> dict:
    """
    Return the aging breakdown for the wip_aging chart. Used by the
    wip lens and the insights engine. Not a Metric itself — chart helper.

    `metric_self` is accepted and ignored; it exists so older callers that
    passed a scope-helper object keep working.
    """
    today = timezone.localdate()
    default = default_rate_for(org)
    bands = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}

    for b in wip_qs(org, scope, tier).only(*WIP_FIELDS):
        age = block_age_days(b, today)
        amt = block_amount(b, default)
        if age <= 30:
            bands["0_30"] += amt
        elif age <= 60:
            bands["31_60"] += amt
        elif age <= 90:
            bands["61_90"] += amt
        else:
            bands["90_plus"] += amt

    return {k: round(v, 2) for k, v in bands.items()}
