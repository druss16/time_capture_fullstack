"""
Create the draft timesheets that were never created.

`auto_submit_timesheets` only ever reads `status='draft'` rows, so a week that
has no Timesheet record at all is invisible to it forever — the time in it can
never be submitted, approved or billed by anyone. Org 21 accumulated 92 such
person-weeks (1,246h, 565h billable, ~$84.8k) while the weekly draft-creation
task was crashing, and its backfill never ran.

This creates the missing rows. It deliberately does NOT submit them:

  · auto_submit_timesheets only handles LAST week, so submitting older weeks is
    not something it would ever have done on its own.
  · submitting fires the approval workflow and, for owners, auto-approval and
    the Clio push (see Timesheet.submit). Ninety of those at once, unattended,
    against months-old time, is not a backfill — it is a billing event.

So this restores the rows, and a person sends their own weeks from the
outstanding-weeks banner on My Week, or a manager works the approval queue.

Usage:
    python manage.py backfill_missing_timesheets --org-id 21              # dry run
    python manage.py backfill_missing_timesheets --org-id 21 --weeks 26
    python manage.py backfill_missing_timesheets --org-id 21 --apply
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Create draft timesheets for past weeks that hold committed time but have no row."

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None, help='Limit to one org.')
        parser.add_argument('--weeks', type=int, default=12, help='How many completed weeks back (default 12).')
        parser.add_argument('--apply', action='store_true', help='Actually create the rows.')

    def handle(self, *args, **opts):
        from tracker.models import Organization, OrganizationMembership, Timesheet
        from tracker.services.billing_totals import committed_block_qs
        from tracker.views_reports import _day_bounds_utc

        orgs = Organization.objects.all()
        if opts['org_id']:
            orgs = orgs.filter(id=opts['org_id'])
            if not orgs.exists():
                raise CommandError(f"Org {opts['org_id']} not found")

        weeks_back = max(1, opts['weeks'])
        today = timezone.localdate()
        this_monday = today - timedelta(days=today.weekday())

        planned = []
        for org in orgs:
            have = {
                (t.user_id, t.week_start)
                for t in Timesheet.objects.filter(
                    org=org, week_start__gte=this_monday - timedelta(weeks=weeks_back))
            }
            members = list(
                OrganizationMembership.objects.filter(organization=org).select_related('user')
            )
            for i in range(1, weeks_back + 1):
                wk = this_monday - timedelta(weeks=i)
                start_utc, end_utc = _day_bounds_utc(wk, wk + timedelta(days=6))
                for m in members:
                    if (m.user_id, wk) in have:
                        continue
                    minutes = billable = 0
                    for b in committed_block_qs(org, start_utc, end_utc,
                                                user_id=m.user_id, can_see_all=False):
                        minutes += b.minutes or 0
                        if b.is_billable:
                            billable += b.minutes or 0
                    if minutes:
                        planned.append((org, m.user, wk, minutes, billable))

        mode = 'APPLY' if opts['apply'] else 'DRY RUN'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nMissing timesheets over {weeks_back} completed weeks — {mode}"))

        if not planned:
            self.stdout.write(self.style.SUCCESS("Nothing missing. ✅"))
            return

        per_user = Counter()
        per_week = Counter()
        tot_min = tot_bill = 0
        for org, user, wk, mins, bill in planned:
            per_user[f'{org.id}:{user.username}'] += mins
            per_week[wk] += 1
            tot_min += mins
            tot_bill += bill

        self.stdout.write(
            f"\n{len(planned)} person-weeks · {tot_min/60:.1f}h "
            f"({tot_bill/60:.1f}h billable)\n")
        self.stdout.write("Per person:")
        for who, mins in per_user.most_common():
            n = sum(1 for p in planned if f'{p[0].id}:{p[1].username}' == who)
            self.stdout.write(f"  {who:24s} {mins/60:7.1f}h across {n} weeks")

        self.stdout.write("\nPer week:")
        for wk in sorted(per_week):
            self.stdout.write(f"  {wk}  {per_week[wk]} people")

        if not opts['apply']:
            self.stdout.write(self.style.NOTICE(
                "\nDRY RUN — nothing written. Re-run with --apply to create the drafts.\n"
                "They are created as DRAFT and are not submitted: people send their own\n"
                "weeks from the My Week banner, or a manager works the approval queue."))
            return

        created = 0
        with transaction.atomic():
            for org, user, wk, _m, _b in planned:
                _ts, made = Timesheet.objects.get_or_create(
                    org=org, user=user, week_start=wk, defaults={'status': 'draft'})
                if made:
                    created += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nCreated {created} draft timesheets. None submitted."))
