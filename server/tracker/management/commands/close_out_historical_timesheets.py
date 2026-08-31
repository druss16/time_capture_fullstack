"""
Close out every completed week before last week, so the queue starts empty.

TL Wall never submitted anything by hand and the weekly draft-creation task was
down for months, so their history is a mess of three shapes: weeks approved
normally, weeks sitting as drafts nobody sent, and weeks with no Timesheet row
at all (invisible to auto_submit_timesheets, which only reads status='draft').
Roughly 1,250 hours across 92 person-weeks had no route to approval.

This settles all of it in one pass: create the missing rows, attach the blocks,
recalculate the totals, and mark the week approved.

WHY IT DOES NOT CALL submit()/approve():

  · submit() fires notify_timesheet_submitted — ~92 emails to managers about
    months-old weeks nobody is going to read.
  · _queue_clio_push only checks the org's clio_push_trigger, NOT whether a
    Clio integration exists. Org 21 has none (verified: zero Integration rows,
    zero timesheets ever pushed) but its trigger is 'approve', so approving
    through the normal path would enqueue ~92 doomed push tasks and stamp
    clio_push_status on every row.

Neither is dangerous. Both are noise on a slate that is supposed to be clean.
So the status is written directly. This is a data migration, not 92 workflow
events, and it is only correct BECAUSE nothing downstream is connected — do not
reuse this on an org with a live billing integration.

Blocks are still linked exactly as submit() links them, because that FK is what
the approval queue and the reports read.

    python manage.py close_out_historical_timesheets --org-id 21            # dry run
    python manage.py close_out_historical_timesheets --org-id 21 --apply
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

# Weeks in these states are already settled; leave them alone.
DONE = ('approved', 'locked')
CLOSING_NOTE = 'Closed out in bulk — historical backfill, never routed for approval'


class Command(BaseCommand):
    help = "Approve every completed week before last week, creating missing timesheets first."

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--weeks', type=int, default=0,
                            help='Limit to the N most recent completed weeks (0 = all history).')

    def handle(self, *args, **opts):
        from tracker.models import (
            Block, Integration, Organization, OrganizationMembership, Timesheet,
        )
        from tracker.services.billing_totals import committed_block_qs
        from tracker.views_reports import _day_bounds_utc

        try:
            org = Organization.objects.get(id=opts['org_id'])
        except Organization.DoesNotExist:
            raise CommandError(f"Org {opts['org_id']} not found")

        # Refuse outright if anything downstream is live — approving months of
        # history would be a billing event, not bookkeeping.
        live = Integration.objects.filter(organization=org, is_connected=True)
        if live.exists():
            raise CommandError(
                f"Org {org.id} has a connected integration "
                f"({', '.join(i.provider for i in live)}). This command bypasses the "
                f"approval workflow and its push hooks, so it must not run here."
            )

        today = timezone.localdate()
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)      # left alone on purpose

        members = list(OrganizationMembership.objects
                       .filter(organization=org).select_related('user'))
        existing = {(t.user_id, t.week_start): t
                    for t in Timesheet.objects.filter(org=org)}

        first = (Block.objects.filter(org=org, deleted_at__isnull=True)
                 .order_by('start').first())
        if not first:
            self.stdout.write(self.style.SUCCESS("No blocks in this org."))
            return
        earliest = first.start.date()
        earliest -= timedelta(days=earliest.weekday())
        if opts['weeks']:
            earliest = max(earliest, last_monday - timedelta(weeks=opts['weeks']))

        plan = []
        wk = earliest
        while wk < last_monday:                             # strictly BEFORE last week
            s_utc, e_utc = _day_bounds_utc(wk, wk + timedelta(days=6))
            for m in members:
                ts = existing.get((m.user_id, wk))
                if ts and ts.status in DONE:
                    continue
                minutes = billable = 0
                for b in committed_block_qs(org, s_utc, e_utc,
                                            user_id=m.user_id, can_see_all=False):
                    minutes += b.minutes or 0
                    if b.is_billable:
                        billable += b.minutes or 0
                if minutes:
                    plan.append({
                        'user': m.user, 'week': wk, 'ts': ts,
                        'minutes': minutes, 'billable': billable,
                        'state': ts.status if ts else 'missing',
                    })
            wk += timedelta(days=7)

        mode = 'APPLY' if opts['apply'] else 'DRY RUN'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nClose out {org.name} — weeks before {last_monday} — {mode}"))
        if not plan:
            self.stdout.write(self.style.SUCCESS("Nothing to close out. ✅"))
            return

        by_state = Counter(p['state'] for p in plan)
        tot = sum(p['minutes'] for p in plan)
        bil = sum(p['billable'] for p in plan)
        self.stdout.write(
            f"\n{len(plan)} person-weeks · {tot/60:.1f}h ({bil/60:.1f}h billable)")
        self.stdout.write(f"  by current state: {dict(by_state)}")
        self.stdout.write(f"  week range: {plan[0]['week']} .. {plan[-1]['week']}")
        self.stdout.write(f"  UNTOUCHED: week of {last_monday} (auto-submits Tuesday) "
                          f"and the current week")

        per_user = Counter()
        for p in plan:
            per_user[p['user'].username] += p['minutes']
        self.stdout.write("\nPer person:")
        for u, mins in per_user.most_common():
            n = sum(1 for p in plan if p['user'].username == u)
            self.stdout.write(f"  {u.ljust(12)} {mins/60:7.1f}h across {n} weeks")

        if not opts['apply']:
            self.stdout.write(self.style.NOTICE(
                "\nDRY RUN — nothing written. Re-run with --apply.\n"
                "On apply each week is: created if missing, blocks attached, totals\n"
                "recalculated, then marked approved directly — no notification email\n"
                "and no Clio push queued."))
            return

        now = timezone.now()
        created = closed = linked = 0
        with transaction.atomic():
            for p in plan:
                ts = p['ts']
                if ts is None:
                    ts = Timesheet.objects.create(
                        org=org, user=p['user'], week_start=p['week'], status='draft')
                    created += 1
                s_utc, e_utc = _day_bounds_utc(p['week'], p['week'] + timedelta(days=6))
                linked += (Block.objects
                           .filter(org=org, user=p['user'], deleted_at__isnull=True,
                                   start__gte=s_utc, start__lt=e_utc, timesheet__isnull=True)
                           .update(timesheet=ts))
                ts.recalculate_totals()
                # Direct write: no submit(), no approve(), so no mail and no push.
                Timesheet.objects.filter(id=ts.id).update(
                    status='approved',
                    submitted_at=ts.submitted_at or now,
                    approved_at=now,
                    auto_submitted=True,
                    submitted_notes=CLOSING_NOTE,
                )
                closed += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nClosed {closed} person-weeks ({created} timesheets created, "
            f"{linked} blocks attached). No emails sent, no pushes queued."))
