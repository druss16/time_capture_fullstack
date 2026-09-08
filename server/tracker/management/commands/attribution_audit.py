"""
Management command: how much booked time is backed by evidence?

Read-only. Scores every attributed block of the window against the client
roster and reports what share of the time carries a word that actually
distinguishes the client it was booked to from its look-alike siblings.

Usage:
  python manage.py attribution_audit --org 21
  python manage.py attribution_audit --org 21 --days 90 --names
  python manage.py attribution_audit --all-orgs --days 30

See tracker/services/attribution_audit.py for what the buckets mean.
"""
from django.core.management.base import BaseCommand

from tracker.models import Organization
from tracker.services.attribution_audit import (
    AMBIGUOUS,
    BUCKET_LABELS,
    NO_EVIDENCE,
    RESOLVED,
    SINGULAR,
    audit_org,
)


class Command(BaseCommand):
    help = "Report how much attributed time is backed by distinguishing evidence."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None)
        parser.add_argument('--all-orgs', action='store_true')
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--names', action='store_true',
                            help='List client name/alias forms that cannot exclude another client')
        parser.add_argument('--top', type=int, default=15,
                            help='How many worst-offender clients to list')

    def handle(self, *args, **opts):
        if opts['all_orgs']:
            org_ids = list(Organization.objects.values_list('id', flat=True))
        elif opts['org']:
            org_ids = [opts['org']]
        else:
            self.stderr.write('Specify --org N or --all-orgs')
            return

        for oid in org_ids:
            self._report(audit_org(oid, days=opts['days']), opts)

    def _report(self, r, opts):
        w = self.stdout.write
        h = lambda m: m / 60.0  # noqa: E731 — minutes to hours

        w('')
        w(f"=== org {r['org_id']} — attribution evidence, "
          f"{r['days']}d since {r['since']} ===")
        w(f"{r['blocks']} attributed blocks, {h(r['total_minutes']):.1f} h, "
          f"{r['clients']} active clients")
        w('')
        for bucket in (SINGULAR, RESOLVED, AMBIGUOUS, NO_EVIDENCE):
            mins = r['minutes'].get(bucket, 0)
            w(f"  {BUCKET_LABELS[bucket]:48} "
              f"{r['counts'].get(bucket, 0):6d} blk  {h(mins):8.1f} h  "
              f"{r['pct_of_all'].get(bucket, 0.0):5.1f}%")

        w('')
        w('  Among blocks whose text names a look-alike group:')
        for bucket in (RESOLVED, AMBIGUOUS, NO_EVIDENCE):
            w(f"    {BUCKET_LABELS[bucket]:46} {r['pct_of_lookalikes'][bucket]:5.1f}%")

        w('')
        w(f"  {h(r['unresolved_minutes']):.1f} h across {r['unresolved_blocks']} blocks "
          f"is booked to a look-alike client with nothing in the text to prove it.")
        w(f"  {r['committed_without_evidence']} of those blocks are already COMMITTED "
          f"— nothing ever asked a human.")
        w(f"  Grouped into work sessions, {r['session_decisions']} human picks "
          f"would settle all of it (~{r['session_decisions'] / max(1, r['days']):.1f}/day firm-wide).")

        worst = sorted(
            ((cid, sum(b.values())) for cid, b in r['per_client'].items()),
            key=lambda kv: -kv[1],
        )[:opts['top']]
        if worst:
            w('')
            w('  Worst clients by un-evidenced minutes:')
            for cid, mins in worst:
                buckets = r['per_client'][cid]
                name = r['by_id'][cid].name if cid in r['by_id'] else f'client {cid}'
                w(f"    {mins:6d}m  [{cid}] {name[:44]:44} "
                  f"(ambiguous {buckets.get(AMBIGUOUS, 0)}m, "
                  f"no-evidence {buckets.get(NO_EVIDENCE, 0)}m)")

        forms = r['ambiguous_name_forms']
        if forms:
            w('')
            w(f"  {len(forms)} clients have a name or alias that cannot exclude another "
              f"client.")
            w('  Renaming these is the highest-leverage fix — one rename settles a '
              'whole group:')
            if not opts['names']:
                w('  (re-run with --names for the full list)')
            shown = sorted(forms.items(),
                           key=lambda kv: -sum(r['per_client'].get(kv[0], {}).values()))
            for cid, entries in (shown if opts['names'] else shown[:5]):
                name = r['by_id'][cid].name if cid in r['by_id'] else f'client {cid}'
                w(f"    [{cid}] {name}")
                for form, clashes in entries[:3]:
                    other_id, other_form, kind = clashes[0]
                    other_name = (r['by_id'][other_id].name
                                  if other_id in r['by_id'] else f'client {other_id}')
                    extra = (f" (+{len(clashes) - 1} more)" if len(clashes) > 1 else '')
                    w(f'        "{form}" also fits [{other_id}] {other_name} '
                      f'as "{other_form}" ({kind}){extra}')
