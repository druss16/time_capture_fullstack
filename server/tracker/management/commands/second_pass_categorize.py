"""
Management command: run the automated second-pass categorizer.

Place at: server/tracker/management/commands/second_pass_categorize.py

Usage:
  python manage.py second_pass_categorize --org 21          # dry run (default)
  python manage.py second_pass_categorize --org 21 --apply  # write
  python manage.py second_pass_categorize --all-orgs --apply --days 14
"""
from django.core.management.base import BaseCommand
from tracker.models import Organization
from tracker.services.second_pass import run_second_pass


class Command(BaseCommand):
    help = "Second-pass categorize uncategorized blocks (junk->non-billable, client guesses->flagged proposals)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None)
        parser.add_argument('--all-orgs', action='store_true')
        parser.add_argument('--days', type=int, default=14)
        parser.add_argument('--apply', action='store_true', help='Write changes (default is dry run)')

    def handle(self, *args, **opts):
        dry = not opts['apply']
        if opts['all_orgs']:
            org_ids = list(Organization.objects.values_list('id', flat=True))
        elif opts['org']:
            org_ids = [opts['org']]
        else:
            self.stderr.write("Specify --org N or --all-orgs")
            return

        for oid in org_ids:
            s = run_second_pass(oid, days=opts['days'], dry_run=dry)
            mode = 'DRY-RUN' if dry else 'APPLIED'
            self.stdout.write(
                f"[{mode}] org {oid}: "
                f"commit_nb={s['commit_nb']} propose_high={s['propose_high']} "
                f"propose_needs={s['propose_needs']} skip={s['skip']} billed={s['billed']}"
            )
            if s['billed']:
                self.stderr.write(f"  WARNING org {oid}: {s['billed']} blocks billed from a guess — investigate!")