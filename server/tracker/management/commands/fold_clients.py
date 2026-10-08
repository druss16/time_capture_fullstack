"""
Fold clients into a parent client: as projects under it, or as a plain merge of
duplicates. See tracker/services/client_conversion.py for what moves and what
stays.

Usage:
  # Dry run (default): does the whole thing in a transaction, reports, rolls back
  python manage.py fold_clients --org-id 7 --parent 100 --clients 101,102,103

  # Apply
  python manage.py fold_clients --org-id 7 --parent 100 --clients 101,102,103 --apply

  # Duplicates: merge, no project
  python manage.py fold_clients --org-id 7 --parent 100 --clients 104 --merge --apply

The folded clients are deactivated, not deleted. The days their time touched
have their client rollups rebuilt after an apply.
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.services.client_conversion import (
    MODE_MERGE, MODE_PROJECT, ConversionError, fold_clients,
)


def _hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}m"


class Command(BaseCommand):
    help = "Fold clients into a parent client as projects (or merge duplicates)."

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True)
        parser.add_argument("--parent", type=int, required=True,
                            help="Client id that receives everything.")
        parser.add_argument("--clients", required=True,
                            help="Comma-separated client ids to fold into the parent.")
        parser.add_argument("--merge", action="store_true",
                            help="Merge duplicates: move everything, make no project.")
        parser.add_argument("--apply", action="store_true",
                            help="Write. Without it the run is rolled back.")

    def handle(self, *args, **opts):
        try:
            ids = [int(x) for x in opts["clients"].split(",") if x.strip()]
        except ValueError:
            raise CommandError("--clients must be comma-separated integers")
        if not ids:
            raise CommandError("--clients is empty")
        mode = MODE_MERGE if opts["merge"] else MODE_PROJECT
        try:
            reports = fold_clients(opts["org_id"], opts["parent"], ids,
                                   mode=mode, apply=opts["apply"])
        except ConversionError as e:
            raise CommandError(str(e))

        w = self.stdout.write
        head = "APPLIED" if opts["apply"] else "DRY RUN (rolled back, nothing written)"
        if reports:
            w(f"{head}: {mode} into {reports[0].parent_id} {reports[0].parent_name!r}\n")
        total_blocks = total_min = 0
        for r in reports:
            total_blocks += r.block_count
            total_min += r.block_minutes
            w(f"{r.old_id} {r.old_name!r}")
            w(f"   blocks: {r.block_count} ({_hm(r.block_minutes)})")
            if r.project_id:
                w(f"   project: {r.project_id} {r.project_name!r} [{r.project_source}], "
                  f"given to {r.blocks_given_project} blocks")
            for name in r.moved_projects:
                w(f"   own project moved: {name}")
            for label, n in sorted(r.moved.items()):
                w(f"   moved {label}: {n}")
            for label, n in sorted(r.left_identity.items()):
                w(self.style.WARNING(f"   LEFT on old client (outside-system link, sort by hand) {label}: {n}"))
            for label, n in sorted(r.left_conflict.items()):
                w(self.style.WARNING(f"   LEFT on old client (parent already has one) {label}: {n}"))
            if r.aliases_left:
                w(f"   aliases left on old client: {r.aliases_left}")
            w("")
        days = set().union(*(r.days for r in reports)) if reports else set()
        w(f"{len(reports)} clients, {total_blocks} blocks, {_hm(total_min)}; "
          f"client rollups {'rebuilt' if opts['apply'] else 'to rebuild'} for {len(days)} days")
