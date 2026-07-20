"""
One-time backfill: mark every Internal-client block non-billable.

Internal firm work is tracked under clients named "Internal" or "Internal - <x>"
(e.g. "Internal - Tax", "Internal - Accounting"). Those blocks should never bill.
Going forward Block.save enforces this, but existing rows created before that may
still carry is_billable=True (and a non-zero billing_amount). This command fixes
them so reports, the weekly timesheet, and invoicing all agree.

Matches the shared predicate tracker.industry_categories.is_internal_client_name:
exactly "Internal" or "Internal - <x>" — a real client like "Internal Revenue
Service" is NOT swept in.

Dry-run by default. Use --apply to write. --org-id to scope to one org.

Usage:
  python manage.py mark_internal_nonbillable                 # dry-run, all orgs
  python manage.py mark_internal_nonbillable --org-id 21     # dry-run, org 21
  python manage.py mark_internal_nonbillable --apply         # write, all orgs
  python manage.py mark_internal_nonbillable --org-id 21 --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum, Count

from tracker.models import Block, Client


class Command(BaseCommand):
    help = "Mark all Internal-client blocks non-billable (is_billable=False, billing_amount=0)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write changes (default: dry-run).")
        parser.add_argument("--org-id", type=int, default=None,
                            help="Limit to a single org.")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        org_id = opts["org_id"]

        # DB-side match for the is_internal_client_name predicate: exactly
        # "Internal" OR "Internal - <x>".
        client_q = Q(name__iexact="Internal") | Q(name__istartswith="Internal -")
        clients = Client.objects.filter(client_q)
        if org_id:
            clients = clients.filter(org_id=org_id)
        internal = list(clients.values("id", "name", "org_id"))
        internal_ids = [c["id"] for c in internal]

        if not internal_ids:
            self.stdout.write("No Internal clients found for the given scope.")
            return

        self.stdout.write(f"Internal clients in scope ({len(internal_ids)}):")
        for c in internal:
            self.stdout.write(f"  - id={c['id']} org={c['org_id']} {c['name']!r}")

        # Blocks currently marked billable under an Internal client.
        qs = Block.objects.filter(
            client_id__in=internal_ids,
            is_billable=True,
            deleted_at__isnull=True,
        )
        if org_id:
            qs = qs.filter(org_id=org_id)

        agg = qs.aggregate(
            n=Count("id"),
            minutes=Sum("minutes"),
            amount=Sum("billing_amount"),
        )
        n = agg["n"] or 0
        minutes = agg["minutes"] or 0
        amount = agg["amount"] or Decimal("0.00")

        self.stdout.write("")
        self.stdout.write(
            f"Affected blocks: {n}  |  {minutes} min ({minutes/60:.1f} h)  |  "
            f"billing_amount to zero: {amount}"
        )
        # Per-client breakdown so invoice-touching rows get eyeballed.
        by_client = (qs.values("client__name")
                       .annotate(n=Count("id"), minutes=Sum("minutes"))
                       .order_by("-minutes"))
        for row in by_client:
            self.stdout.write(
                f"    {row['client__name']!r}: {row['n']} blocks, "
                f"{row['minutes'] or 0} min"
            )

        if n == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        if not apply:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "DRY RUN — no changes written. Re-run with --apply to commit."
            ))
            return

        updated = qs.update(is_billable=False, billing_amount=Decimal("0.00"))
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Applied: set is_billable=False + billing_amount=0 on {updated} block(s)."
        ))
