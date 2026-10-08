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

  # Every org: one line each, worst first. Read-only; --apply needs --org-id.
  python manage.py prune_dormant_clients --all-orgs

Reversible: the output ends with the ids, and setting is_active=True on any of
them brings it back.
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.services.dormant_clients import deactivate, dormant_counts_by_org, find_dormant_clients


class Command(BaseCommand):
    help = "Deactivate imported clients with no projects, no time and no timecard rows."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--org-id", type=int)
        target.add_argument("--all-orgs", action="store_true",
                            help="Summary for every org. Read-only.")
        parser.add_argument("--include-invoiced", action="store_true",
                            help="Also deactivate clients whose only activity is invoices.")
        parser.add_argument("--apply", action="store_true", help="Write. Without it nothing changes.")

    def handle(self, *args, **opts):
        if opts["all_orgs"]:
            if opts["apply"]:
                raise CommandError("--apply works one org at a time: use --org-id")
            return self._all_orgs()
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

    def _all_orgs(self):
        from tracker.models import Organization
        counts = dormant_counts_by_org()
        names = dict(Organization.objects.values_list('id', 'name'))
        rows = sorted(((c['dormant'], c['active'], org_id) for org_id, c in counts.items()
                       if c['dormant']), reverse=True)
        w = self.stdout.write
        if not rows:
            w("No org has dormant clients.")
            return
        w(f"{'org':>5}  {'idle':>5} / {'active':<6} name")
        for dormant, active, org_id in rows:
            w(f"{org_id:>5}  {dormant:>5} / {active:<6} {names.get(org_id, '?')}")
        w(f"\n{sum(r[0] for r in rows)} dormant clients across {len(rows)} orgs. "
          "Inspect one with --org-id N; nothing was written.")
