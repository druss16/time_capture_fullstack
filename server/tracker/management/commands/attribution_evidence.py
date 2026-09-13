"""
What is holding up the time you are about to bill?

    python manage.py attribution_evidence --org 21 --days 90
    python manage.py attribution_evidence --org 21 --days 90 --weakest

Read-only, whole-population. NOT an accuracy score — see
services/attribution_evidence for why that misreading is the dangerous one.
"""
from django.core.management.base import BaseCommand

from tracker.services.attribution_evidence import (
    BACKED_INDEPENDENT, BACKED_NONE, BACKED_PERSON, BACKED_TITLE,
    BUCKET_LABEL, evidence_report,
)


class Command(BaseCommand):
    help = "Evidence behind each client's settled, billable time."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--client', type=int, default=None)
        parser.add_argument('--all-time', action='store_true',
                            help='Include non-billable time too.')
        parser.add_argument('--weakest', action='store_true',
                            help='List the individual blocks with nothing behind them.')
        parser.add_argument('--clients', type=int, default=15)

    def handle(self, *a, **o):
        r = evidence_report(o['org'], days=o['days'], client_id=o['client'],
                            billable_only=not o['all_time'])
        h = lambda m: m / 60.0

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{r['total_blocks']} settled{'' if o['all_time'] else ' billable'} "
            f"blocks · {h(r['total_minutes']):.1f}h · last {o['days']} days"))

        pct = r['backed_pct']
        self.stdout.write(self.style.SUCCESS(
            f"  {pct:.1%} of that time can say why it belongs to its client"
            if pct is not None else "  no time in range"))
        self.stdout.write('')
        for k in (BACKED_PERSON, BACKED_INDEPENDENT, BACKED_TITLE, BACKED_NONE):
            v = r['totals'][k]
            self.stdout.write(
                f"   {h(v['minutes']):>7.1f}h  {v['blocks']:>5} blocks   {BUCKET_LABEL[k]}")

        self.stdout.write('\n  signals that ever corroborate:')
        for k, v in r['signal_counts'].items():
            self.stdout.write(f"      {v:>5}x  {k}")

        self.stdout.write('\n  where review time is worth most '
                          '(hours with nothing behind them):')
        for c in r['clients'][:o['clients']]:
            n = c['buckets'][BACKED_NONE]['minutes']
            if not n:
                continue
            self.stdout.write(
                f"   {h(n):>6.1f}h of {h(c['minutes']):>6.1f}h   {c['client_name'][:44]}")

        if o['weakest']:
            self.stdout.write('\n  individual blocks with nothing behind them:')
            for w in r['weakest']:
                self.stdout.write(
                    f"   {w['minutes']:>4}m  {w['date']}  {w['client_name'][:28]:<30}"
                    f" {w['window_title'][:54]}")

        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            "  This is evidence coverage, NOT accuracy. Unbacked time is usually\n"
            "  still correct — QuickBooks dialogs inherit the client from the\n"
            "  session, which is legitimate and invisible here. Read it as where\n"
            "  to spend review time, not as an error rate."))
