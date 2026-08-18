"""
Is the QuickBooks company-FILE capture actually working in the field?

READ-ONLY. Answers the one question that decides whether Stage 4.5 does
anything: can the agent read the open .qbw path off qbw.exe's handle table on
real machines, including files on a network share?

That question cannot be answered on a dev machine without QuickBooks, and it
cannot be answered by reading the code — psutil.open_files() may return
AccessDenied for a mapped drive, in which case the whole feature silently
no-ops (every path is deliberately fail-open). The only evidence is what the
agents actually report, which lands here in RawEvent.ctx.

Usage:
    python manage.py check_qb_capture --org 21
    python manage.py check_qb_capture --org 21 --days 3
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.models import Organization, RawEvent


class Command(BaseCommand):
    help = "Report whether agents are reporting QuickBooks company file paths (read-only)."

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True, help='org id or name')
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--samples', type=int, default=8)

    def handle(self, *args, **opts):
        val = opts['org']
        org = (Organization.objects.filter(id=int(val)).first() if str(val).isdigit()
               else Organization.objects.filter(name__icontains=val).first())
        if not org:
            raise CommandError(f'org not found: {val!r}')

        since = timezone.now() - timedelta(days=opts['days'])
        rows = list(RawEvent.objects
                    .filter(block__org=org, start_ts__gte=since,
                            app_name__istartswith='qbw')
                    .values_list('ctx', 'agent_version', 'hostname')[:200000])

        total = len(rows)
        self.stdout.write(f"\norg {org.id} {org.name!r} — QuickBooks events in the "
                          f"last {opts['days']}d: {total:,}")
        if not total:
            self.stdout.write(self.style.WARNING(
                "  No QuickBooks activity in this window — nothing to judge yet."))
            return

        with_path = with_open = 0
        paths = Counter()
        versions = Counter()
        reporting_hosts, qb_hosts = set(), set()

        for ctx, ver, host in rows:
            versions[ver or 'unknown'] += 1
            qb_hosts.add(host)
            if not isinstance(ctx, dict):
                continue
            if ctx.get('qb_open_files'):
                with_open += 1
                reporting_hosts.add(host)
            p = ctx.get('qb_company_path')
            if p:
                with_path += 1
                paths[p] += 1

        pct = 100.0 * with_open / total
        self.stdout.write(f"  carrying qb_open_files : {with_open:,}  ({pct:.1f}%)")
        self.stdout.write(f"  carrying qb_company_path: {with_path:,}  "
                          f"({100.0*with_path/total:.1f}%)")
        self.stdout.write(f"  machines seen doing QB  : {len(qb_hosts)}   "
                          f"of which reporting paths: {len(reporting_hosts)}")

        self.stdout.write("\n  agent versions doing QB work:")
        for v, n in versions.most_common(6):
            self.stdout.write(f"    {v:>12}  {n:,} events")

        if paths:
            self.stdout.write(self.style.SUCCESS(
                f"\n  WORKING — {len(paths)} distinct company file(s) seen:"))
            for p, n in paths.most_common(opts['samples']):
                self.stdout.write(f"    {n:6,}x  {p}")
            return

        # No paths. Distinguish "no new agent yet" from "the handle read failed".
        self.stdout.write(self.style.WARNING("\n  NO company file paths reported."))
        if all(str(v).startswith(('1.7.0', '1.7.1', '1.7.2', '1.7.3', '1.7.4',
                                  '1.7.5', '1.7.6', '1.7.7', '1.7.8', '1.7.9',
                                  '1.7.10', '1.7.11', '1.7.12', '1.7.13', 'unknown'))
               for v in versions):
            self.stdout.write(
                "  Every agent doing QB work predates the capture — expected.\n"
                "  Re-run once a machine with QuickBooks has updated to v1.7.14+.")
        else:
            self.stdout.write(self.style.ERROR(
                "  An agent at v1.7.14+ IS doing QuickBooks work and still reports\n"
                "  no path. That is the failure mode to chase: psutil.open_files()\n"
                "  is most likely being refused on the network share (Q:). Check the\n"
                "  agent log on that machine for '[FILE]' warnings."))
