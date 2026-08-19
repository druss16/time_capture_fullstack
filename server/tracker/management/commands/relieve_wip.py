"""
Apply synced invoices against uninvoiced WIP so WIP drains as the firm bills.

Dry run by default — nothing is written without --apply.

    python manage.py relieve_wip --org 21
    python manage.py relieve_wip --org 21 --since 2026-01-01 --apply

See tracker/services/wip_relief.py for the FIFO / period rules.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from tracker.models import Organization
from tracker.services.wip_relief import relieve_org


class Command(BaseCommand):
    help = "Apply invoices against uninvoiced WIP (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--org", type=int, help="Org ID. Omit for all orgs.")
        parser.add_argument("--since", type=str, default=None,
                            help="Only invoices dated on/after this ISO date.")
        parser.add_argument("--limit", type=int, default=None,
                            help="Cap invoices processed (useful for a first look).")
        parser.add_argument("--apply", action="store_true",
                            help="Actually write. Without it, nothing changes.")
        parser.add_argument("--verbose-rows", action="store_true",
                            help="Print one line per invoice.")

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
            report = relieve_org(org, dry_run=dry_run, since=since, limit=opts["limit"])
            if not report["invoices_seen"]:
                continue

            self.stdout.write(self.style.MIGRATE_HEADING(f"\norg {org.id} — {org.name}"))
            self.stdout.write(
                f"  invoices seen     {report['invoices_seen']}\n"
                f"  invoices applied  {report['invoices_applied']}\n"
                f"  blocks relieved   {report['blocks_relieved']}\n"
                f"  WIP relieved      ${report['wip_relieved']:,.2f}\n"
                f"  residual          ${report['residual_total']:,.2f}  "
                f"(+ billed above time on file, − wrote WIP down)"
            )
            if report["skipped"]:
                pairs = ", ".join(f"{k}={v}" for k, v in sorted(report["skipped"].items()))
                self.stdout.write(f"  skipped           {pairs}")

            if opts["verbose_rows"]:
                for d in report["details"]:
                    if d["skipped_reason"]:
                        self.stdout.write(
                            f"    - {d['invoice_number']:<20} {d['client_name'][:28]:<28} "
                            f"SKIP {d['skipped_reason']}"
                        )
                    else:
                        self.stdout.write(
                            f"    ✓ {d['invoice_number']:<20} {d['client_name'][:28]:<28} "
                            f"{d['mode']:<6} ${d['relieved_amount']:>10,.2f} "
                            f"{d['blocks']:>4} blocks  {d['oldest_day']}→{d['newest_day']}"
                        )

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run complete — nothing written."))
        else:
            self.stdout.write(self.style.SUCCESS("\nRelief applied."))
