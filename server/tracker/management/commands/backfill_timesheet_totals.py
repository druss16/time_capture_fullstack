# tracker/management/commands/backfill_timesheet_totals.py
"""
Recompute the denormalized totals stored on Timesheet rows.

WHY
---
`Timesheet.recalculate_totals` used to aggregate `self.blocks.all()` with a bare
`is_billable=True`, so a timesheet's stored `billable_hours` counted suppressed
time, unconfirmed proposals, and time with no client attached. The approvals
list reads that stored field, so managers approved one number while Daily
Review, Reports and Analytics all showed another.

The calculation now applies the shared rules from `services.billing_totals`, but
that only fixes sheets recalculated from here on. Existing rows keep whatever
was stored when they were submitted. This command re-runs the (now correct)
calculation over them.

WHAT IT TOUCHES
---------------
Only the four derived fields — total_hours, billable_hours, non_billable_hours,
total_amount — plus updated_at, via `save(update_fields=...)`. Approval status,
approver, submitted/approved timestamps and every Block are untouched. The
values are derived from the linked blocks, so this is re-runnable and nothing is
destroyed: running it again on unchanged blocks is a no-op.

Draft timesheets are skipped by default — they get recalculated on submit
anyway, and rewriting an in-flight week just adds noise.

USAGE
-----
    # See what would change (default — this command does NOT write unless told)
    python manage.py backfill_timesheet_totals --org 21 --since 2026-07-01

    # Apply
    python manage.py backfill_timesheet_totals --org 21 --since 2026-07-01 --apply
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"
BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"


class Command(BaseCommand):
    help = "Recompute stored Timesheet totals using the shared billing rules."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True,
                            help="Org slug or id")
        parser.add_argument("--since", default=None,
                            help="Only weeks starting on/after YYYY-MM-DD")
        parser.add_argument("--until", default=None,
                            help="Only weeks starting on/before YYYY-MM-DD")
        parser.add_argument("--include-drafts", action="store_true",
                            help="Also recalculate draft timesheets")
        parser.add_argument("--apply", action="store_true",
                            help="Write the corrected totals. Without this the "
                                 "command only reports what would change.")

    def handle(self, *args, **opts):
        from tracker.models import Organization, Timesheet

        q = opts["org"]
        org = (Organization.objects.filter(slug=q).first()
               or (Organization.objects.filter(id=q).first() if str(q).isdigit() else None))
        if not org:
            raise CommandError(f"Org not found: {q}")

        qs = Timesheet.objects.filter(org=org)
        if not opts["include_drafts"]:
            qs = qs.exclude(status="draft")
        if opts["since"]:
            d = parse_date(opts["since"])
            if not d:
                raise CommandError(f"Bad --since: {opts['since']}")
            qs = qs.filter(week_start__gte=d)
        if opts["until"]:
            d = parse_date(opts["until"])
            if not d:
                raise CommandError(f"Bad --until: {opts['until']}")
            qs = qs.filter(week_start__lte=d)
        qs = qs.select_related("user").order_by("week_start", "user_id")

        mode = f"{RED}APPLY{RESET}" if opts["apply"] else f"{CYAN}DRY RUN{RESET}"
        print(f"  {BOLD}{org.name}{RESET} (id={org.id})   {qs.count()} timesheets   {mode}")
        if not opts["apply"]:
            print(f"  {DIM}nothing will be written — re-run with --apply{RESET}")
        print()

        changed = unchanged = 0
        d_total = d_billable = d_amount = 0.0

        for ts in qs:
            before = (
                float(ts.total_hours or 0),
                float(ts.billable_hours or 0),
                float(ts.total_amount or 0),
            )
            # Recompute in memory, then decide whether to persist.
            ts.recalculate_totals(commit=opts["apply"])
            after = (
                float(ts.total_hours or 0),
                float(ts.billable_hours or 0),
                float(ts.total_amount or 0),
            )

            if all(abs(a - b) < 0.005 for a, b in zip(before, after)):
                unchanged += 1
                continue

            changed += 1
            d_total += after[0] - before[0]
            d_billable += after[1] - before[1]
            d_amount += after[2] - before[2]
            name = ts.user.get_full_name() or ts.user.username
            print(f"  {ts.week_start}  {name[:22]:24} "
                  f"billable {before[1]:8.2f} → {after[1]:8.2f} "
                  f"({after[1] - before[1]:+7.2f} h)   "
                  f"amount ${before[2]:9,.0f} → ${after[2]:9,.0f}")

        print()
        print(f"  {BOLD}{changed} changed{RESET}, {unchanged} already correct")
        print(f"  billable hours  {d_billable:+9.2f}")
        print(f"  total hours     {d_total:+9.2f}")
        print(f"  amount          ${d_amount:+12,.2f}")
        if not opts["apply"]:
            print(f"\n  {CYAN}Dry run — nothing written.{RESET} Re-run with --apply to persist.")
        else:
            print(f"\n  {GREEN}Written.{RESET}")
