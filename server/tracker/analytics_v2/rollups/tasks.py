"""
Celery tasks for analytics v2 rollups.

Add to celery.py beat_schedule (see README for full snippet):
  - tracker.v2_rollup_yesterday_client_daily   → daily 2:15am
  - tracker.v2_rollup_yesterday_staff_daily    → daily 2:30am
  - tracker.v2_snapshot_wip                    → hourly
  - tracker.v2_backfill_rollups                → on-demand only (not scheduled)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from tracker.models import (
    Block, Client, EmployeeCostRate, Invoice, Organization,
)

from ..types import to_float
from .models import ClientDailyRollup, StaffDailyRollup, WipSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client daily rollup
# ---------------------------------------------------------------------------

@shared_task(name="tracker.v2_rollup_yesterday_client_daily")
def rollup_yesterday_client_daily():
    """Nightly client rollup for yesterday."""
    yesterday = (timezone.now() - timedelta(days=1)).date()
    return rollup_client_daily_for_date(yesterday.isoformat())


@shared_task(name="tracker.v2_rollup_client_daily_for_date")
def rollup_client_daily_for_date(target_date_iso: str):
    """Roll up a specific date across all orgs."""
    target_date = date.fromisoformat(target_date_iso)
    
    for org in Organization.objects.all():
        try:
            _rollup_client_daily_for_org_date(org, target_date)
        except Exception as exc:
            logger.exception(
                "[v2-rollup] Client rollup failed org=%s date=%s: %s",
                org.id, target_date, exc,
            )
    return f"client_daily rolled up for {target_date}"


def _rollup_client_daily_for_org_date(org: Organization, target_date: date) -> int:
    """Recompute ClientDailyRollup rows for one org × one day. Returns rows written."""
    
    # Cost rates per user
    cost_rates: dict[int, float] = {}
    for cr in (EmployeeCostRate.objects
               .filter(organization=org, effective_date__lte=target_date)
               .order_by("user_id", "-effective_date")):
        if cr.user_id not in cost_rates:
            cost_rates[cr.user_id] = to_float(cr.cost_rate)
    default_cost = to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
    default_rate = to_float(getattr(org, "billing_rate_default", 0))
    
    # Aggregate blocks by client
    by_client: dict[int, dict] = defaultdict(lambda: {
        "total_minutes": 0, "billable_minutes": 0,
        "billing_amount": 0.0, "cost_amount": 0.0,
        "explicit_rate_amount": 0.0, "default_rate_amount": 0.0,
    })
    
    block_qs = Block.objects.filter(
        org=org, day=target_date, client__isnull=False,
    ).only("client_id", "minutes", "is_billable", "billing_amount",
           "billing_rate", "user_id")
    
    for b in block_qs:
        cid = b.client_id
        mins = to_float(b.minutes)
        hours = mins / 60.0
        amount = to_float(b.billing_amount)
        used_default = False
        if not amount:
            rate = to_float(b.billing_rate) or default_rate
            amount = hours * rate
            used_default = b.billing_rate is None
        else:
            used_default = b.billing_rate is None
        cost = hours * cost_rates.get(b.user_id, default_cost)
        
        by_client[cid]["total_minutes"] += int(mins)
        if b.is_billable:
            by_client[cid]["billable_minutes"] += int(mins)
            by_client[cid]["billing_amount"] += amount
            by_client[cid]["cost_amount"] += cost
            if used_default:
                by_client[cid]["default_rate_amount"] += amount
            else:
                by_client[cid]["explicit_rate_amount"] += amount
    
    # Invoices on this date (rare to invoice on a specific calendar day, but
    # this is how the dimension reduces; metrics that don't need invoiced
    # broken out by day will sum across the range)
    inv_by_client: dict[int, dict] = defaultdict(lambda: {"amount": 0.0, "hours": 0.0})
    for inv in (Invoice.objects
                .filter(org=org, invoice_date=target_date, client__isnull=False)
                .only("client_id", "amount", "hours_billed")
                ):
        inv_by_client[inv.client_id]["amount"] += to_float(inv.amount)
        inv_by_client[inv.client_id]["hours"] += to_float(inv.hours_billed)
    
    # UPSERT
    all_client_ids = set(by_client) | set(inv_by_client)
    written = 0
    with transaction.atomic():
        # Delete existing rows for this org/date so we can re-insert cleanly
        ClientDailyRollup.objects.filter(org=org, day=target_date).delete()
        
        new_rows = []
        for cid in all_client_ids:
            b = by_client.get(cid, {})
            i = inv_by_client.get(cid, {})
            new_rows.append(ClientDailyRollup(
                org=org,
                client_id=cid,
                day=target_date,
                total_minutes=b.get("total_minutes", 0),
                billable_minutes=b.get("billable_minutes", 0),
                billing_amount=Decimal(str(round(b.get("billing_amount", 0), 2))),
                cost_amount=Decimal(str(round(b.get("cost_amount", 0), 2))),
                invoiced_amount=Decimal(str(round(i.get("amount", 0), 2))),
                invoiced_hours=Decimal(str(round(i.get("hours", 0), 2))),
                explicit_rate_amount=Decimal(str(round(b.get("explicit_rate_amount", 0), 2))),
                default_rate_amount=Decimal(str(round(b.get("default_rate_amount", 0), 2))),
            ))
        ClientDailyRollup.objects.bulk_create(new_rows, batch_size=500)
        written = len(new_rows)
    
    logger.info("[v2-rollup] client_daily org=%s date=%s rows=%d",
                org.id, target_date, written)
    return written


# ---------------------------------------------------------------------------
# Staff daily rollup
# ---------------------------------------------------------------------------

@shared_task(name="tracker.v2_rollup_yesterday_staff_daily")
def rollup_yesterday_staff_daily():
    yesterday = (timezone.now() - timedelta(days=1)).date()
    return rollup_staff_daily_for_date(yesterday.isoformat())


@shared_task(name="tracker.v2_rollup_staff_daily_for_date")
def rollup_staff_daily_for_date(target_date_iso: str):
    target_date = date.fromisoformat(target_date_iso)
    for org in Organization.objects.all():
        try:
            _rollup_staff_daily_for_org_date(org, target_date)
        except Exception as exc:
            logger.exception("[v2-rollup] Staff rollup failed org=%s date=%s: %s",
                             org.id, target_date, exc)
    return f"staff_daily rolled up for {target_date}"


def _rollup_staff_daily_for_org_date(org: Organization, target_date: date) -> int:
    cost_rates: dict[int, float] = {}
    for cr in (EmployeeCostRate.objects
               .filter(organization=org, effective_date__lte=target_date)
               .order_by("user_id", "-effective_date")):
        if cr.user_id not in cost_rates:
            cost_rates[cr.user_id] = to_float(cr.cost_rate)
    default_cost = to_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
    default_rate = to_float(getattr(org, "billing_rate_default", 0))
    
    by_user: dict[int, dict] = defaultdict(lambda: {
        "total_minutes": 0, "billable_minutes": 0,
        "billing_amount": 0.0, "cost_amount": 0.0,
    })
    
    block_qs = Block.objects.filter(org=org, day=target_date).only(
        "user_id", "minutes", "is_billable", "billing_amount", "billing_rate"
    )
    
    for b in block_qs:
        uid = b.user_id
        mins = to_float(b.minutes)
        hours = mins / 60.0
        amount = to_float(b.billing_amount)
        if not amount:
            rate = to_float(b.billing_rate) or default_rate
            amount = hours * rate
        cost = hours * cost_rates.get(uid, default_cost)
        
        by_user[uid]["total_minutes"] += int(mins)
        if b.is_billable:
            by_user[uid]["billable_minutes"] += int(mins)
            by_user[uid]["billing_amount"] += amount
            by_user[uid]["cost_amount"] += cost
    
    written = 0
    with transaction.atomic():
        StaffDailyRollup.objects.filter(org=org, day=target_date).delete()
        new_rows = []
        for uid, d in by_user.items():
            new_rows.append(StaffDailyRollup(
                org=org, user_id=uid, day=target_date,
                total_minutes=d["total_minutes"],
                billable_minutes=d["billable_minutes"],
                billing_amount=Decimal(str(round(d["billing_amount"], 2))),
                cost_amount=Decimal(str(round(d["cost_amount"], 2))),
            ))
        StaffDailyRollup.objects.bulk_create(new_rows, batch_size=500)
        written = len(new_rows)
    
    logger.info("[v2-rollup] staff_daily org=%s date=%s rows=%d",
                org.id, target_date, written)
    return written


# ---------------------------------------------------------------------------
# WIP snapshot — hourly
# ---------------------------------------------------------------------------

@shared_task(name="tracker.v2_snapshot_wip")
def snapshot_wip_all_orgs():
    """Hourly WIP snapshot per org."""
    now = timezone.now()
    for org in Organization.objects.all():
        try:
            _snapshot_wip_for_org(org, now)
        except Exception as exc:
            logger.exception("[v2-rollup] WIP snapshot failed org=%s: %s", org.id, exc)
    return f"wip snapshot at {now}"


def _snapshot_wip_for_org(org: Organization, captured_at: datetime) -> WipSnapshot:
    qs = Block.objects.filter(
        org=org, approved=True, invoiced=False, is_billable=True,
    ).only("client_id", "minutes", "billing_amount", "billing_rate",
           "approved_at", "start")
    
    default_rate = to_float(getattr(org, "billing_rate_default", 0))
    bands = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    by_client: dict[int, float] = defaultdict(float)
    total = 0.0
    
    for b in qs:
        hours = to_float(b.minutes) / 60.0
        amount = to_float(b.billing_amount)
        if not amount:
            rate = to_float(b.billing_rate) or default_rate
            amount = hours * rate
        ref = b.approved_at or b.start
        if ref:
            if timezone.is_naive(ref):
                ref = timezone.make_aware(ref)
            age_days = max(0, (captured_at - ref).days)
        else:
            age_days = 0
        if age_days <= 30:
            bands["0_30"] += amount
        elif age_days <= 60:
            bands["31_60"] += amount
        elif age_days <= 90:
            bands["61_90"] += amount
        else:
            bands["90_plus"] += amount
        total += amount
        if b.client_id:
            by_client[b.client_id] += amount
    
    snap = WipSnapshot.objects.create(
        org=org,
        captured_at=captured_at,
        total=Decimal(str(round(total, 2))),
        aged_0_30=Decimal(str(round(bands["0_30"], 2))),
        aged_31_60=Decimal(str(round(bands["31_60"], 2))),
        aged_61_90=Decimal(str(round(bands["61_90"], 2))),
        aged_90_plus=Decimal(str(round(bands["90_plus"], 2))),
        by_client={str(cid): round(amt, 2) for cid, amt in by_client.items()},
    )
    
    # Retention — keep last 30 days of snapshots, prune the rest
    cutoff = captured_at - timedelta(days=30)
    deleted, _ = WipSnapshot.objects.filter(org=org, captured_at__lt=cutoff).delete()
    if deleted:
        logger.info("[v2-rollup] Pruned %d old WIP snapshots for org=%s", deleted, org.id)
    
    return snap


# ---------------------------------------------------------------------------
# Backfill (on-demand)
# ---------------------------------------------------------------------------

@shared_task(name="tracker.v2_backfill_rollups")
def backfill_rollups(org_id: int, start_date_iso: str, end_date_iso: str):
    """
    One-shot backfill for an org over a date range. Used when first deploying
    v2 or for an org that needs its rollups rebuilt.
    
    Run from a Django shell or management command:
        from tracker.analytics_v2.rollups.tasks import backfill_rollups
        backfill_rollups.delay(21, "2024-01-01", "2026-05-22")
    """
    start = date.fromisoformat(start_date_iso)
    end = date.fromisoformat(end_date_iso)
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return f"org {org_id} not found"
    
    cur = start
    client_total = 0
    staff_total = 0
    while cur <= end:
        client_total += _rollup_client_daily_for_org_date(org, cur)
        staff_total += _rollup_staff_daily_for_org_date(org, cur)
        cur += timedelta(days=1)
    return f"Backfilled org={org_id} {start}→{end}: {client_total} client rows, {staff_total} staff rows"
