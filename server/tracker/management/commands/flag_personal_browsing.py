"""
Flag unambiguously-personal web browsing as non-billable so it drops out of the
billable review pile (read-only dry-run by default).

Uses tracker.services.personal_browsing.is_personal_browsing — a surgical,
work-vetoed matcher (see that module). --apply commits matched blocks as
non-billable (client stays NULL, is_billable=False). Non-billable is the safe
under-bill direction; every write is stamped proposed_reasoning '[personal]'
so it is reversible and re-billable.

USAGE
-----
  python manage.py flag_personal_browsing --org 21 --start 2026-07-01 --end 2026-07-31
  python manage.py flag_personal_browsing --org 21 --start 2026-07-01 --end 2026-07-31 --apply
"""
from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tracker.models import Block, Organization
from tracker.services.personal_browsing import is_personal_browsing

MARK = "[personal] unambiguous personal browsing — auto non-billable"


class Command(BaseCommand):
    help = "Flag unambiguously-personal browsing as non-billable (read-only unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="org id or name")
        parser.add_argument("--start", required=True, help="YYYY-MM-DD")
        parser.add_argument("--end", required=True, help="YYYY-MM-DD")
        parser.add_argument("--apply", action="store_true",
                            help="Commit matched blocks as non-billable.")

    def _resolve_org(self, val):
        org = (Organization.objects.filter(id=int(val)).first() if str(val).isdigit()
               else Organization.objects.filter(name__icontains=val).first())
        if not org:
            raise CommandError(f"org not found: {val!r}")
        return org

    def handle(self, *args, **opts):
        org = self._resolve_org(opts["org"])
        start = dt.date.fromisoformat(opts["start"])
        end = dt.date.fromisoformat(opts["end"])

        q = (Block.objects
             .filter(org=org, client__isnull=True, approved=False,
                     day__gte=start, day__lte=end)
             .exclude(classification_state__in=["committed", "suppressed"]))
        targets = [b for b in q if is_personal_browsing(b.window_title, b.app_name)]

        total_min = sum((b.minutes or 0) for b in targets)
        self.stdout.write(
            f"\n=== Personal-browsing flag — org {org.id} ({org.name}) "
            f"{start}..{end} ===\n"
        )
        self.stdout.write(
            f"  {len(targets)} blocks / {total_min/60:.1f}h would be marked "
            f"non-billable:\n"
        )
        for b in sorted(targets, key=lambda b: -(b.minutes or 0))[:50]:
            self.stdout.write(
                f"    {(b.minutes or 0):>3}m  {(b.window_title or '')[:70]!r}  (blk {b.id})"
            )

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing written.\n"))
            return

        n = skipped = 0
        with transaction.atomic():
            for b in targets:
                if b.is_protected():
                    skipped += 1
                    continue
                b.is_billable = False
                b.is_categorized = True
                b.categorized_by = "ai"
                b.classification_state = "committed"
                b.state_changed_by = "rule"
                b.proposed_reasoning = MARK
                b.save(update_fields=[
                    "is_billable", "is_categorized", "categorized_by",
                    "classification_state", "state_changed_by", "proposed_reasoning",
                ])
                n += 1
        self.stdout.write(self.style.SUCCESS(
            f"\nMarked {n} blocks non-billable (committed); skipped {skipped} "
            f"protected. Reversible via proposed_reasoning startswith '[personal]'.\n"
        ))
