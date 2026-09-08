"""
Management command: is the agent managing to read the QuickBooks company file?

QuickBooks Desktop puts the COMPANY NAME in the window title, and a firm with 30
parishes has a dozen files whose company name reads "St. Mary's Church". Only
the FILE NAME is specific. Several mechanisms try to get it, each blocked in a
different way, and the failures are silent — the agent just reports nothing and
the classifier falls back to guessing between siblings.

So the agent ships a diagnostic with every QuickBooks event, and this reads it
back. It answers one question: which mechanism, if any, is working right now.

  python manage.py qb_capture_status --org 21
  python manage.py qb_capture_status --org 21 --days 7

Nothing here writes.
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import RawEvent


def _verdict(diag):
    """Translate the diag counters into the one sentence that matters."""
    mru = diag.get('mru', 'absent')
    names = diag.get('mrunames', 'absent')

    if diag.get('handles'):
        return 'WORKING — reading QuickBooks\' open file handles directly'
    if diag.get('cmd'):
        return 'WORKING — the company file is on the QuickBooks command line'
    if mru == 'absent':
        return ('OLD AGENT — this build predates the file-dialog reader; '
                'tag a release')
    if mru == -1:
        return ('NO REGISTRY KEY — QuickBooks is not using a shell file dialog, '
                'so this approach cannot work here')
    if not names:
        return (f'KEY FOUND ({mru} entries) but no filenames decoded — the '
                f'reader needs fixing, the idea is sound')
    return f'WORKING — {names} company filenames captured from the Open dialog'


class Command(BaseCommand):
    help = "Report whether the agent can read the open QuickBooks company file."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--days', type=int, default=2)
        parser.add_argument('--limit', type=int, default=8000,
                            help='Max events to sample')

    def handle(self, *args, **opts):
        since = timezone.now() - timedelta(days=opts['days'])
        rows = (RawEvent.objects
                .filter(block__org_id=opts['org'],
                        app_name__istartswith='qbw',
                        start_ts__gte=since)
                .values_list('ctx')[:opts['limit']])

        shapes = Counter()
        sampled = 0
        for (ctx,) in rows:
            if not isinstance(ctx, dict):
                continue
            diag = (ctx.get('qb_report') or {}).get('diag') or {}
            if not diag:
                continue
            sampled += 1
            shapes[(
                diag.get('mru', 'absent'),
                diag.get('mrunames', 'absent'),
                diag.get('handles', 0),
                diag.get('cmd', 0),
                diag.get('err'),
                diag.get('mru_err'),
            )] += 1

        w = self.stdout.write
        w(f"\norg {opts['org']} — QuickBooks events carrying a diagnostic "
          f"in the last {opts['days']}d: {sampled}")
        if not sampled:
            w('\nNo QuickBooks activity sampled. Either nobody used QuickBooks '
              'in the window, or no agent is reporting.')
            return

        w('')
        for shape, n in shapes.most_common(8):
            mru, names, handles, cmd, err, mru_err = shape
            diag = {'mru': mru, 'mrunames': names, 'handles': handles,
                    'cmd': cmd, 'err': err, 'mru_err': mru_err}
            pct = 100.0 * n / sampled
            w(f"  {n:6d} events ({pct:5.1f}%)")
            w(f"      mru={mru}  mrunames={names}  handles={handles}  cmd={cmd}"
              + (f"  err={err}" if err else '')
              + (f"  mru_err={mru_err}" if mru_err else ''))
            w(f"      -> {_verdict(diag)}")
            w('')
