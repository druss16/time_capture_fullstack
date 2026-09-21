"""
Management command: how much email time has no mail evidence behind it?

Read-only. Writes nothing, touches no external API, reads no message content.

Usage:
  python manage.py mail_coverage --org 21
  python manage.py mail_coverage --org 21 --days 60 --users
  python manage.py mail_coverage --all-orgs

The 'gap' row is the ceiling on what reading additional mail folders could
buy. See tracker/services/mail_coverage.py for what each bucket means and why
the number is an upper bound rather than an estimate.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from tracker.models import Organization
from tracker.services.mail_coverage import (
    BUCKETS,
    BUCKET_LABELS,
    GAP,
    measure_org,
)


class Command(BaseCommand):
    help = "Report how much email-client time is attributed with no mail evidence."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None)
        parser.add_argument('--all-orgs', action='store_true')
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--users', action='store_true',
                            help='List the users carrying the most gap time')
        parser.add_argument('--top', type=int, default=10,
                            help='How many users to list under --users')

    def handle(self, *args, **opts):
        if opts['all_orgs']:
            org_ids = list(Organization.objects.values_list('id', flat=True))
        elif opts['org']:
            org_ids = [opts['org']]
        else:
            self.stderr.write('Specify --org N or --all-orgs')
            return

        for oid in org_ids:
            self._report(measure_org(oid, days=opts['days']), opts)

    def _report(self, r, opts):
        w = self.stdout.write
        h = lambda m: m / 60.0  # noqa: E731 — minutes to hours

        w('')
        w(f"=== org {r['org_id']} — mail evidence coverage, "
          f"{r['days']}d since {r['since']} ===")

        if not r['blocks']:
            w('  No email-client blocks in the window. Nothing to measure.')
            w('')
            return

        w(f"{r['blocks']} email-client blocks, {h(r['total_minutes']):.1f} h, "
          f"{r['mailboxes']} connected mailbox(es)")
        w('')

        for bucket in BUCKETS:
            w(f"  {BUCKET_LABELS[bucket]:48} "
              f"{r['counts'].get(bucket, 0):6d} blk  "
              f"{h(r['minutes'].get(bucket, 0.0)):8.1f} h  "
              f"{r['pct_of_all'].get(bucket, 0.0):5.1f}%")

        gap_hours = h(r['minutes'].get(GAP, 0.0))
        w('')
        w(f"  Ceiling on what more mail folders could buy: "
          f"{gap_hours:.1f} h over {r['days']}d "
          f"({r['pct_of_all'].get(GAP, 0.0):.1f}% of email time).")
        w('  Upper bound — Sent Items only reaches the subset of these where the')
        w('  user wrote to a client who had not written to them first.')

        if opts['users'] and r['per_user_gap']:
            self._user_table(r, opts, w, h)

        w('')

    def _user_table(self, r, opts, w, h):
        User = get_user_model()
        rows = sorted(
            r['per_user_gap'].items(),
            key=lambda kv: kv[1]['minutes'],
            reverse=True,
        )[:opts['top']]
        names = dict(
            User.objects
            .filter(id__in=[uid for uid, _ in rows])
            .values_list('id', 'username')
        )
        w('')
        w('  Gap time by user:')
        for uid, entry in rows:
            w(f"    {names.get(uid, f'user {uid}'):28} "
              f"{entry['blocks']:5d} blk  {h(entry['minutes']):7.1f} h")
