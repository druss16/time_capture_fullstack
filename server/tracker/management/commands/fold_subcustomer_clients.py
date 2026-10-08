"""
Find clients that are really a company's project and fold them into it.

A QuickBooks Online import used to make a client of every sub-customer, beside
the project QuickBooks Time had already filed under the company. The import no
longer does that; this cleans up what it left.

Two ways to find them:

  twins (default)  an active client with the same name as an active project
                   under exactly one other client. Needs no QuickBooks access,
                   so it runs anywhere. Only clients imported from QuickBooks,
                   unless --any-source.
  qbo              ask QuickBooks Online which customers are sub-customers.
                   Needs the firm's live connection: run it on Render.

Usage:
  # Every org, dry run: what would be folded
  python manage.py fold_subcustomer_clients

  # One org, apply
  python manage.py fold_subcustomer_clients --org-id 7 --apply

  # From QuickBooks itself (Render shell)
  python manage.py fold_subcustomer_clients --org-id 7 --source qbo

Folding is fold_clients' project mode: time moves to the company under the
project, the client is deactivated (never deleted). A dry run rolls back.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from tracker.services.client_conversion import (
    ConversionError, find_project_twins, find_qbo_subcustomer_clients, fold_clients,
)


class Command(BaseCommand):
    help = "Fold clients that are really a company's project into that company."

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int)
        parser.add_argument("--source", choices=["twins", "qbo"], default="twins")
        parser.add_argument("--any-source", action="store_true",
                            help="twins: consider clients from any source, not just QuickBooks.")
        parser.add_argument("--apply", action="store_true",
                            help="Write. Without it every fold is rolled back.")

    def handle(self, *args, **opts):
        if opts["source"] == "qbo":
            if not opts["org_id"]:
                raise CommandError("--source qbo needs --org-id")
            try:
                twins = find_qbo_subcustomer_clients(opts["org_id"])
            except ConversionError as e:
                raise CommandError(str(e))
        else:
            twins = find_project_twins(opts["org_id"], any_source=opts["any_source"])

        w = self.stdout.write
        if not twins:
            w("Nothing to fold.")
            return

        groups = defaultdict(list)
        for t in twins:
            groups[(t.org_id, t.parent.pk)].append(t)

        head = "APPLIED" if opts["apply"] else "DRY RUN (rolled back, nothing written)"
        w(f"{head}: {len(twins)} clients into {len(groups)} companies "
          f"across {len({k[0] for k in groups})} orgs\n")
        total_blocks = total_min = 0
        for (org_id, parent_id), items in sorted(groups.items()):
            parent = items[0].parent
            w(f"org {org_id} · {parent_id} {parent.name!r}")
            try:
                reports = fold_clients(org_id, parent_id, [t.client.pk for t in items], apply=opts["apply"])
            except ConversionError as e:
                # One bad company must not stop the rest; nothing of it was written.
                w(self.style.WARNING(f"   SKIPPED: {e}"))
                w("")
                continue
            for r in reports:
                total_blocks += r.block_count
                total_min += r.block_minutes
                extra = []
                if r.block_count:
                    extra.append(f"{r.block_count} blocks, {r.block_minutes // 60}h{r.block_minutes % 60:02d}m")
                if r.left_identity or r.left_conflict:
                    left = {**r.left_identity, **r.left_conflict}
                    extra.append("left: " + ", ".join(f"{k} {v}" for k, v in sorted(left.items())))
                w(f"   {r.old_id} {r.old_name!r} -> project {r.project_id} [{r.project_source}]"
                  + (f"  ({'; '.join(extra)})" if extra else ""))
            w("")
        w(f"{len(twins)} clients, {total_blocks} blocks, {total_min // 60}h{total_min % 60:02d}m moved")
