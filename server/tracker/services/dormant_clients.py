"""
Clients nobody works for: imported from an accounting system, never given a
project, never given a minute of time.

The QuickBooks connect link imports every active customer, and QuickBooks Time
makes a client of every customer that is linked to QuickBooks. A marketing firm
with 25-30 real clients ended up with 412: card processors ("Visa
Cardholder-3"), payment rails ("Stripe Sales"), one-off individuals and
"Sample Customer". Every one of them sits in the client list the agent matches
window titles against.

Deactivating them is reversible (is_active=True brings one back) and a sync
does not reactivate them: neither sync touches an existing client's is_active.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Q

from tracker.industry_categories import is_internal_client_name
from tracker.models import Block, Client, Invoice, Project, TimecardEntry

IMPORT_SOURCES = ('quickbooks', 'qb_time')


@dataclass
class Dormant:
    client: Client
    invoices: int


def find_dormant_clients(org_id: int, *, include_invoiced: bool = False) -> tuple[list[Dormant], list[Dormant]]:
    """(to_deactivate, kept_for_invoices) for one org.

    Dormant: active, imported from QuickBooks / QuickBooks Time, not an Internal
    bucket, and with no block (in any state, as booked or proposed), no project
    (active or not) and no timecard row. A client with invoices is a real
    customer even if no one tracks time for it, so it is kept unless
    include_invoiced.
    """
    candidates = (Client.objects
                  .filter(org_id=org_id, is_active=True, imported_from__in=IMPORT_SOURCES)
                  .order_by('name'))
    busy = set(Block.objects.filter(org_id=org_id).filter(
        Q(client__isnull=False) | Q(proposed_client__isnull=False)
    ).values_list('client_id', 'proposed_client_id').distinct().iterator())
    busy_ids = {cid for pair in busy for cid in pair if cid}
    busy_ids |= set(Project.objects.filter(org_id=org_id).values_list('client_id', flat=True))
    busy_ids |= set(TimecardEntry.objects.filter(client__org_id=org_id)
                    .values_list('client_id', flat=True))
    invoices = dict(Invoice.objects.filter(client__org_id=org_id).values('client_id')
                    .annotate(n=Count('id')).values_list('client_id', 'n'))

    out, kept = [], []
    for c in candidates:
        if c.pk in busy_ids or is_internal_client_name(c.name):
            continue
        d = Dormant(c, invoices.get(c.pk, 0))
        (kept if d.invoices and not include_invoiced else out).append(d)
    return out, kept


def deactivate(clients: list[Client]) -> int:
    """Deactivate without save(): no signals, nothing reclassified."""
    return Client.objects.filter(pk__in=[c.pk for c in clients], is_active=True).update(is_active=False)
