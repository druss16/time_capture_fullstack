"""
WIP relief — the drain side of work-in-progress.

WIP only means something if it goes down when the firm bills. Before this,
nothing in the product ever set `Block.invoiced=True` outside a demo seed: org
21 had 10,082 billable blocks and zero invoiced ones, so WIP aging was a ramp
that could only grow and realization could never be computed.

Firms don't map invoice line items back to individual time entries, and asking
them to would guarantee this never gets used. So relief is inferred from the
invoices that already sync in (QBO / Xero / CSV / manual):

  hourly clients      FIFO — the invoice relieves the OLDEST uninvoiced WIP for
                      that client, up to the invoice amount. Anything left over
                      is recorded as residual (billed more than the time on
                      file), not silently dropped.

  flat-fee/retainer   PERIOD — the invoice relieves ALL WIP for the client up
                      to the invoice date. Standard-rate WIP above the fee is a
                      write-down, which is the whole point of tracking WIP for a
                      flat-fee client: it tells you what the fee actually cost.

Every relief is idempotent (an Invoice carries `wip_relieved_at` once applied)
and auditable (each block records `relieving_invoice`).

Nothing here runs automatically without being switched on — `relieve_org` is
dry-run by default, the management command requires `--apply`, and the celery
task is gated on the org flag `wip_auto_relief`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from tracker.analytics_v2.metrics.wip import (
    TIER_BILLABLE_READY, WIP_FIELDS, block_amount, default_rate_for, wip_qs,
)
from tracker.models import Block, Client, Invoice, Organization

logger = logging.getLogger(__name__)

MODE_AMOUNT = "amount"
MODE_PERIOD = "period"

# In AMOUNT mode the last block usually doesn't land exactly on the invoice
# total. Take it if the remaining dollars cover at least this share of it —
# otherwise leave it in WIP for the next invoice.
PARTIAL_TAKE_RATIO = 0.5

# Statuses that don't relieve anything.
NON_RELIEVING_STATUSES = ("voided", "draft")


@dataclass
class InvoiceRelief:
    """What one invoice did (or would do) to WIP."""
    invoice_id: int
    invoice_number: str
    client_id: int | None
    client_name: str
    mode: str
    invoice_amount: float
    relieved_amount: float
    residual: float
    block_ids: list[int] = field(default_factory=list)
    oldest_day: date | None = None
    newest_day: date | None = None
    skipped_reason: str = ""

    @property
    def applied(self) -> bool:
        return not self.skipped_reason and bool(self.block_ids)

    def to_dict(self) -> dict:
        return {
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice_number,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "mode": self.mode,
            "invoice_amount": round(self.invoice_amount, 2),
            "relieved_amount": round(self.relieved_amount, 2),
            "residual": round(self.residual, 2),
            "blocks": len(self.block_ids),
            "oldest_day": self.oldest_day.isoformat() if self.oldest_day else None,
            "newest_day": self.newest_day.isoformat() if self.newest_day else None,
            "skipped_reason": self.skipped_reason,
        }


def relief_mode_for(client: Client | None) -> str:
    """Flat-fee/retainer clients relieve by period; everyone else by amount."""
    profile = getattr(client, "billing_profile", None)
    if profile is not None and profile.billing_type == "flat_fee":
        return MODE_PERIOD
    return MODE_AMOUNT


def _as_datetime(d: date) -> datetime:
    """Invoice dates are dates; Block.invoiced_at is a datetime."""
    dt = datetime.combine(d, time(12, 0))
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _last_relief_day(org: Organization, client: Client) -> date | None:
    """The most recent invoice date already applied against this client's WIP.

    PERIOD mode uses it as the lower bound so two flat-fee invoices in a row
    don't fight over the same blocks.
    """
    return (
        Invoice.objects.filter(org=org, client=client, wip_relieved_at__isnull=False)
        .order_by("-invoice_date")
        .values_list("invoice_date", flat=True)
        .first()
    )


def plan_relief(invoice: Invoice, *, org: Organization | None = None) -> InvoiceRelief:
    """Work out which blocks this invoice would relieve. Pure — writes nothing."""
    org = org or invoice.org
    client = invoice.client
    result = InvoiceRelief(
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        client_id=client.id if client else None,
        client_name=client.name if client else (invoice.client_name or "—"),
        mode="",
        invoice_amount=float(invoice.amount or 0),
        relieved_amount=0.0,
        residual=0.0,
    )

    if invoice.wip_relieved_at:
        result.skipped_reason = "already_relieved"
        return result
    if client is None:
        # Unlinked invoices are common on first CSV/QBO import. Surfaced in the
        # report so someone can map the customer, never guessed at.
        result.skipped_reason = "no_client_link"
        return result
    if (invoice.status or "") in NON_RELIEVING_STATUSES:
        result.skipped_reason = f"status_{invoice.status}"
        return result
    if not invoice.amount or invoice.amount <= 0:
        result.skipped_reason = "zero_amount"
        return result

    mode = relief_mode_for(client)
    result.mode = mode

    candidates = list(
        wip_qs(org, None, TIER_BILLABLE_READY)
        .filter(client=client, day__lte=invoice.invoice_date)
        .only("id", *WIP_FIELDS)
        .order_by("day", "id")
    )
    if mode == MODE_PERIOD:
        floor = _last_relief_day(org, client)
        if floor:
            candidates = [b for b in candidates if b.day and b.day > floor]

    if not candidates:
        result.skipped_reason = "no_wip_to_relieve"
        return result

    default = default_rate_for(org)
    relieved = 0.0

    if mode == MODE_PERIOD:
        # The fee covers the period regardless of hours — take everything.
        for b in candidates:
            relieved += block_amount(b, default)
            result.block_ids.append(b.id)
    else:
        remaining = float(invoice.amount)
        for b in candidates:
            amt = block_amount(b, default)
            if amt <= remaining:
                relieved += amt
                remaining -= amt
                result.block_ids.append(b.id)
                continue
            # Doesn't fit. Take it only if the invoice covers most of it.
            if amt > 0 and remaining >= amt * PARTIAL_TAKE_RATIO:
                relieved += amt
                result.block_ids.append(b.id)
            break

    if not result.block_ids:
        result.skipped_reason = "no_wip_to_relieve"
        return result

    days = [b.day for b in candidates if b.id in set(result.block_ids) and b.day]
    result.oldest_day = min(days) if days else None
    result.newest_day = max(days) if days else None
    result.relieved_amount = round(relieved, 2)
    result.residual = round(float(invoice.amount) - relieved, 2)
    return result


@transaction.atomic
def apply_relief(invoice: Invoice, plan: InvoiceRelief) -> InvoiceRelief:
    """Commit a plan: take the blocks out of WIP and stamp the invoice."""
    if not plan.applied:
        return plan

    # Re-filter on invoiced=False so a concurrent relief can't double-count.
    updated = Block.objects.filter(
        id__in=plan.block_ids, org=invoice.org, invoiced=False,
    ).update(
        invoiced=True,
        invoiced_at=_as_datetime(invoice.invoice_date),
        invoice_reference=invoice.invoice_number[:100],
        relieving_invoice=invoice,
    )

    invoice.wip_relieved_at = timezone.now()
    invoice.wip_relieved_amount = Decimal(str(plan.relieved_amount))
    invoice.wip_relief_residual = Decimal(str(plan.residual))
    invoice.wip_relief_mode = plan.mode
    invoice.save(update_fields=[
        "wip_relieved_at", "wip_relieved_amount", "wip_relief_residual",
        "wip_relief_mode", "updated_at",
    ])

    logger.info(
        "[wip-relief] org=%s invoice=%s client=%s mode=%s relieved $%.2f "
        "across %d blocks (residual $%.2f)",
        invoice.org_id, invoice.invoice_number, plan.client_name, plan.mode,
        plan.relieved_amount, updated, plan.residual,
    )
    return plan


def relieve_org(
    org: Organization,
    *,
    dry_run: bool = True,
    since: date | None = None,
    limit: int | None = None,
) -> dict:
    """Apply every unrelieved invoice for this org against its WIP, oldest first.

    Dry run by default — call with dry_run=False to actually drain.
    """
    qs = (
        Invoice.objects.filter(org=org, wip_relieved_at__isnull=True)
        .select_related("client", "client__billing_profile")
        .order_by("invoice_date", "id")
    )
    if since:
        qs = qs.filter(invoice_date__gte=since)
    if limit:
        qs = qs[:limit]

    plans: list[InvoiceRelief] = []
    for invoice in qs:
        plan = plan_relief(invoice, org=org)
        if plan.applied and not dry_run:
            apply_relief(invoice, plan)
        plans.append(plan)

    applied = [p for p in plans if p.applied]
    skipped: dict[str, int] = {}
    for p in plans:
        if p.skipped_reason:
            skipped[p.skipped_reason] = skipped.get(p.skipped_reason, 0) + 1

    return {
        "org_id": org.id,
        "dry_run": dry_run,
        "invoices_seen": len(plans),
        "invoices_applied": len(applied),
        "blocks_relieved": sum(len(p.block_ids) for p in applied),
        "wip_relieved": round(sum(p.relieved_amount for p in applied), 2),
        "residual_total": round(sum(p.residual for p in applied), 2),
        "skipped": skipped,
        "details": [p.to_dict() for p in plans],
    }
