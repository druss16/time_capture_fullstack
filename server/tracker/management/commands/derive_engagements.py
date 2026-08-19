"""
Group captured time into engagements, budget them from history, and refresh the
shadow phase inference.

Dry run by default — nothing is written without --apply.

    python manage.py derive_engagements --org 21
    python manage.py derive_engagements --org 21 --since 2026-01-01 --apply
    python manage.py derive_engagements --org 21 --agreement   # inference vs people

See tracker/services/engagements.py and tracker/services/phase_inference.py.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from tracker.models import Organization
from tracker.services.engagements import assign_engagements, derive_budgets
from tracker.services.phase_inference import agreement_report, refresh_inferred_phases


class Command(BaseCommand):
    help = "Derive engagements + budgets from captured time (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--org", type=int, help="Org ID. Omit for all orgs.")
        parser.add_argument("--since", type=str, default=None,
                            help="Only assign blocks dated on/after this ISO date.")
        parser.add_argument("--limit", type=int, default=None,
                            help="Cap blocks scanned during assignment.")
        parser.add_argument("--apply", action="store_true", help="Actually write.")
        parser.add_argument("--skip-budgets", action="store_true",
                            help="Assign blocks only; leave budgets alone.")
        parser.add_argument("--skip-inference", action="store_true",
                            help="Skip the shadow phase inference pass.")
        parser.add_argument("--agreement", action="store_true",
                            help="Print how well inferred phases match preparers.")

    def handle(self, *args, **opts):
        since = None
        if opts["since"]:
            try:
                since = date.fromisoformat(opts["since"])
            except ValueError:
                raise CommandError(f"--since must be ISO (YYYY-MM-DD), got {opts['since']!r}")

        orgs = (
            Organization.objects.filter(id=opts["org"])
            if opts["org"] else Organization.objects.all()
        )
        if opts["org"] and not orgs.exists():
            raise CommandError(f"No org with id {opts['org']}")

        dry_run = not opts["apply"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes. Add --apply to commit.\n"))

        for org in orgs:
            header_written = False

            def header():
                nonlocal header_written
                if not header_written:
                    self.stdout.write(self.style.MIGRATE_HEADING(f"\norg {org.id} — {org.name}"))
                    header_written = True

            assigned = assign_engagements(org, since=since, dry_run=dry_run,
                                          limit=opts["limit"])
            if assigned["blocks_assigned"] or assigned["engagements_created"]:
                header()
                self.stdout.write(
                    f"  engagements created  {assigned['engagements_created']}\n"
                    f"  blocks assigned      {assigned['blocks_assigned']}\n"
                    f"  blocks skipped       {assigned['blocks_skipped']}  "
                    f"(no client, no date, or not an auto-derived service)"
                )

            if not opts["skip_budgets"]:
                budgets = derive_budgets(org, dry_run=dry_run)
                if budgets["actions"]:
                    header()
                    pairs = ", ".join(f"{k}={v}" for k, v in sorted(budgets["actions"].items()))
                    self.stdout.write(f"  budgets              {pairs}")

            if not opts["skip_inference"]:
                inferred = refresh_inferred_phases(org, dry_run=dry_run)
                if inferred["counts"]:
                    header()
                    pairs = ", ".join(f"{k}={v}" for k, v in sorted(inferred["counts"].items()))
                    self.stdout.write(f"  inferred phases      {pairs}")

            if opts["agreement"]:
                report = agreement_report(org)
                header()
                if not report["compared"]:
                    self.stdout.write("  agreement            no engagement has both a "
                                      "set phase and an inferred one yet")
                else:
                    self.stdout.write(
                        f"  agreement            {report['exact_pct']}% exact, "
                        f"{report['within_one_pct']}% within one phase "
                        f"(n={report['compared']})"
                    )
                    for pair, n in list(report["confusion"].items())[:5]:
                        self.stdout.write(f"      {pair:<28} {n}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run complete — nothing written."))
        else:
            self.stdout.write(self.style.SUCCESS("\nDone."))
