"""
Attribute unattributed QuickBooks *chrome* blocks to the concurrently-open
company file's client (read-only dry-run by default).

The logic lives in tracker.services.qb_chrome_attribution (shared with the
nightly beat task tracker.tasks.attribute_qb_chrome_all). This command is the
manual / dry-run entry point with a human-readable report.

USAGE
-----
  python manage.py attribute_qb_chrome --org 21 --start 2026-07-01 --end 2026-07-31
  python manage.py attribute_qb_chrome --org 21 --start 2026-07-01 --end 2026-07-31 --sample 40
  python manage.py attribute_qb_chrome --org 21 --start 2026-07-01 --end 2026-07-31 --apply

--apply COMMITS the OVERLAP tier (billable) and PROPOSES the NEAR tier.
AMBIGUOUS/NONE are always left untouched. Every write is stamped
proposed_reasoning startswith '[qb-chrome]' and is reversible.
"""
from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from tracker.models import Client, Organization
from tracker.services.qb_chrome_attribution import (
    classify_targets, run_qb_chrome_attribution,
)


class Command(BaseCommand):
    help = ("Attribute unattributed QuickBooks chrome blocks to the concurrently-open "
            "company file's client (read-only unless --apply).")

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="org id or name")
        parser.add_argument("--start", required=True, help="YYYY-MM-DD")
        parser.add_argument("--end", required=True, help="YYYY-MM-DD")
        parser.add_argument("--gap", type=int, default=10,
                            help="NEAR tier: max minutes to nearest anchor (default 10).")
        parser.add_argument("--sample", type=int, default=25,
                            help="How many example attributions to print.")
        parser.add_argument("--apply", action="store_true",
                            help="COMMIT the OVERLAP tier (billable) and PROPOSE the NEAR "
                                 "tier. AMBIGUOUS/NONE untouched.")

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
        gap = opts["gap"]

        results = classify_targets(org, start, end, gap)
        client_name = {c.id: c.name for c in Client.objects.filter(org=org)}

        def mins(lst):
            return sum((b.minutes or 0) for b, _, _ in lst)

        n_targets = sum(len(v) for v in results.values())
        h_targets = sum(mins(v) for v in results.values()) / 60
        self.stdout.write(
            f"\n=== QB-chrome attribution — org {org.id} ({org.name}) "
            f"{start}..{end} ===\n"
        )
        self.stdout.write(f"  chrome targets: {n_targets}  ({h_targets:.1f}h)\n")
        for tier in ("OVERLAP", "NEAR", "AMBIGUOUS", "NONE"):
            lst = results[tier]
            self.stdout.write(f"  {tier:9s}: {len(lst):>4} blocks  {mins(lst)/60:>5.1f}h")

        inherit = results["OVERLAP"] + results["NEAR"]
        self.stdout.write(self.style.SUCCESS(
            f"\n  -> would attribute {len(inherit)} blocks / {mins(inherit)/60:.1f}h; "
            f"abstain on {len(results['AMBIGUOUS']) + len(results['NONE'])} "
            f"({(mins(results['AMBIGUOUS'])+mins(results['NONE']))/60:.1f}h)\n"
        ))

        self.stdout.write("  SAMPLE attributions (title -> inherited client):\n")
        for b, cid, why in inherit[: opts["sample"]]:
            self.stdout.write(
                f"    {b.start:%m-%d %H:%M} {(b.minutes or 0):>2}m  "
                f"{(b.window_title or '')[:38]!r:40}  ->  "
                f"{client_name.get(cid, cid)!r}  [{why}]  (blk {b.id})"
            )
        if results["AMBIGUOUS"]:
            self.stdout.write("\n  SAMPLE abstained (ambiguous — left in review):\n")
            for b, _, why in results["AMBIGUOUS"][:8]:
                self.stdout.write(
                    f"    {b.start:%m-%d %H:%M} {(b.minutes or 0):>2}m  "
                    f"{(b.window_title or '')[:38]!r:40}  [{why}]  (blk {b.id})"
                )

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing written.\n"))
            return

        stats = run_qb_chrome_attribution(org, start, end, gap, apply=True)
        self.stdout.write(self.style.SUCCESS(
            f"\nCommitted {stats['committed']} OVERLAP blocks (billable) and "
            f"proposed {stats['proposed']} NEAR blocks; skipped "
            f"{stats['skipped_protected']} protected. AMBIGUOUS/NONE untouched.\n"
            f"Reversible via proposed_reasoning startswith '[qb-chrome]'.\n"
        ))
