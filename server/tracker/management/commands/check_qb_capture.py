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
        probes = Counter()       # what the agent's own probe reported
        errors = Counter()
        env = Counter()          # security-context facts, when nothing worked
        share = Counter()        # what the share scan could see
        elev = Counter()         # is the agent elevated?
        recent = Counter()       # age of the freshest company file
        named = 0
        reporting_hosts, qb_hosts = set(), set()

        for ctx, ver, host in rows:
            versions[ver or 'unknown'] += 1
            qb_hosts.add(host)
            if not isinstance(ctx, dict):
                continue
            rep = ctx.get('qb_report')
            if isinstance(rep, dict):
                rd = rep.get('diag') or {}
                elev[f"agent_is_admin={rd.get('admin', '?')}"] += 1
                for item in (rep.get('recent') or [])[:1]:
                    try:
                        recent[f"freshest_file_age_seconds={int(item.get('age')):,}"] += 1
                    except Exception:
                        pass
                if rep.get('company'):
                    named += 1
            probe = ctx.get('qb_capture')
            if isinstance(probe, dict):
                probes[probe.get('src') or 'none'] += 1
                if probe.get('err') or probe.get('cmd_err') or probe.get('share_err'):
                    errors[f"handles={probe.get('err', '-')} "
                           f"cmdline={probe.get('cmd_err', '-')} "
                           f"share={probe.get('share_err', '-')}  "
                           f"(procs={probe.get('procs', '?')} "
                           f"handles={probe.get('handles', '?')} "
                           f"ini={probe.get('ini', '?')} "
                           f"reg={probe.get('reg', '?')} "
                           f"cmd={probe.get('cmd', '?')} "
                           f"share={probe.get('share', '?')})"] += 1
                # Did the share scan find the directory and the files at all?
                if 'sharedirs' in probe or 'sharefiles' in probe:
                    share[f"dirs={probe.get('sharedirs', '?')} "
                          f"files_seen={probe.get('sharefiles', '?')} "
                          f"name_candidates={probe.get('cands', '?')} "
                          f"picked={probe.get('share', '?')} "
                          f"freshest_min={probe.get('freshmin', '?')} "
                          f"gap_min={probe.get('gapmin', '?')}"] += 1
                # Security-context facts, only present when nothing worked.
                if 'me' in probe or 'qbuser' in probe:
                    env[f"agent_user={probe.get('me', '?')} "
                        f"qbw_user={probe.get('qbuser', '?')} "
                        f"agent_is_admin={probe.get('admin', '?')} "
                        f"ini_files_found={probe.get('inifiles', '?')} "
                        f"registry_key_exists={probe.get('regkey', '?')}"] += 1
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

        if probes:
            self.stdout.write("\n  what the agent's own probe reported:")
            for src, n in probes.most_common():
                label = {'handles': 'read from qbw.exe handle table',
                         'mru': 'read from QuickBooks recent-file list',
                         'cmdline': 'read from the qbw.exe command line',
                         'share': 'read from the file share (no process access)',
                         'none': 'found nothing'}.get(src, src)
                self.stdout.write(f"    {src:>8}  {n:,} events   ({label})")
        if errors:
            self.stdout.write("\n  probe errors (this is the actual cause):")
            for e, n in errors.most_common(5):
                self.stdout.write(f"    {n:6,}x  {e}")
        if elev:
            self.stdout.write("\n  agent elevation (decides if handles can ever work):")
            for e, n in elev.most_common(4):
                self.stdout.write(f"    {n:6,}x  {e}")
        if recent:
            self.stdout.write("\n  freshest company file on the share — THE deciding number:")
            for e, n in recent.most_common(8):
                self.stdout.write(f"    {n:6,}x  {e}")
            self.stdout.write(
                "    -> small values (seconds/minutes) mean the timestamps move and\n"
                "       this works. Uniformly huge values mean QuickBooks never\n"
                "       publishes a fresh timestamp and the share route is dead.")
        if named:
            self.stdout.write(f"\n  events whose title carried a company name: {named:,}")

        if share:
            self.stdout.write("\n  share scan (reads the drive, not the process):")
            for e, n in share.most_common(8):
                self.stdout.write(f"    {n:6,}x  {e}")
            self.stdout.write(
                "    -> name_candidates is how many files match the company in the\n"
                "       title; picked=1 means one led the rest clearly. freshest_min\n"
                "       is how old the best candidate's transaction log is: if that\n"
                "       stays huge while people are working, QuickBooks is not\n"
                "       flushing the log to the server and NO timing signal exists.")

        if env:
            self.stdout.write("\n  security context (agent vs QuickBooks):")
            for e, n in env.most_common(10):
                self.stdout.write(f"    {n:6,}x  {e}")
            self.stdout.write(
                "    -> same user + AccessDenied = QuickBooks is ELEVATED.\n"
                "       agent_is_admin=0 means the agent is NOT elevated even though\n"
                "       these users clearly can be — the scheduled task asks for\n"
                "       HighestAvailable, so it is not taking effect, and fixing that\n"
                "       is smaller than any new mechanism.")

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
        # Compare as version TUPLES. String prefixes are a trap here:
        # '1.7.14'.startswith('1.7.1') is True, so a prefix test reports the
        # first agent that actually HAS the feature as "too old" — exactly
        # backwards, and it hides the failure this command exists to catch.
        def _tuple(v):
            try:
                return tuple(int(x) for x in str(v).split('.')[:3])
            except (TypeError, ValueError):
                return (0, 0, 0)

        FIRST_WITH_CAPTURE = (1, 7, 14)
        capable = {v: n for v, n in versions.items()
                   if _tuple(v) >= FIRST_WITH_CAPTURE}
        if not capable:
            self.stdout.write(
                "  Every agent doing QB work predates v1.7.14 — expected.\n"
                "  Re-run once a machine with QuickBooks has updated.")
        else:
            n = sum(capable.values())
            self.stdout.write(self.style.ERROR(
                f"  {n:,} event(s) from agents at v1.7.14+ "
                f"({', '.join(sorted(capable))}) did QuickBooks work and reported\n"
                "  NO company file. The code is shipping but no mechanism can\n"
                "  see the path. Read the probe lines above for the cause; if\n"
                "  they are absent the agent predates the diagnostic (v1.7.15)."))
