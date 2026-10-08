"""
Deactivate imported clients nobody works for: no projects, no time, no
timecard rows. See tracker/services/dormant_clients.py.

Usage:
  # Dry run (default): list what would be deactivated
  python manage.py prune_dormant_clients --org-id 7

  # Apply
  python manage.py prune_dormant_clients --org-id 7 --apply

  # Also deactivate clients that only have invoices
  python manage.py prune_dormant_clients --org-id 7 --include-invoiced --apply

Reversible: the output ends with the ids, and setting is_active=True on any of
them brings it back.
"""
from django.core.management.base import BaseCommand

from tracker.services.dormant_clients import deactivate, find_dormant_clients


class Command(BaseCommand):
    help = "Deactivate imported clients with no projects, no time and no timecard rows."

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True)
        parser.add_argument("--include-invoiced", action="store_true",
                            help="Also deactivate clients whose only activity is invoices.")
        parser.add_argument("--apply", action="store_true", help="Write. Without it nothing changes.")

    def handle(self, *args, **opts):
        org_id = opts["org_id"]
        dormant, kept = find_dormant_clients(org_id, include_invoiced=opts["include_invoiced"])
        w = self.stdout.write
        for d in dormant:
            inv = f"  ({d.invoices} invoices)" if d.invoices else ""
            w(f"   {d.client.pk:>6}  {d.client.imported_from:<10} {d.client.name}{inv}")
        if kept:
            w(f"\nKept, invoiced but no time ({len(kept)}; --include-invoiced to deactivate):")
            for d in kept:
                w(f"   {d.client.pk:>6}  {d.client.name}  ({d.invoices} invoices)")

        if opts["apply"]:
            n = deactivate([d.client for d in dormant])
            w(f"\nAPPLIED: deactivated {n} clients in org {org_id}")
        else:
            w(f"\nDRY RUN: {len(dormant)} clients in org {org_id} would be deactivated")
        if dormant:
            w("ids: " + ",".join(str(d.client.pk) for d in dormant))
