"""
Fill Block.project from matter numbers in captured filenames and titles.

    python manage.py attribute_matters --org-id 17
    python manage.py attribute_matters --org-id 17 --days 90 --apply

Dry-run by default. This decides which client gets billed for an hour, so look
at the split before committing: a run that is mostly sole-matter inferences
means the firm is not putting matter numbers in filenames, and that inference
is only safe while each client has exactly one matter.
"""

from django.core.management.base import BaseCommand

from tracker.models import Organization
from tracker.services.matter_attribution import attribute_matters_for_org


class Command(BaseCommand):
    help = 'Attribute captured blocks to matters via matter number or sole-matter fallback.'

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None,
                            help='Limit to one org. Default: every org with matter mappings.')
        parser.add_argument('--days', type=int, default=30,
                            help='How far back to look. Default 30.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Cap blocks scanned, for a quick look.')
        parser.add_argument('--apply', action='store_true',
                            help='Write the attributions. Without this, nothing is saved.')

    def handle(self, *args, **opts):
        dry_run = not opts['apply']
        orgs = (
            Organization.objects.filter(id=opts['org_id'])
            if opts['org_id'] else Organization.objects.all()
        )

        totals = {'scanned': 0, 'by_number': 0, 'by_sole_matter': 0, 'unmatched': 0}
        for org in orgs:
            stats = attribute_matters_for_org(
                org, days=opts['days'], dry_run=dry_run, limit=opts['limit'],
            )
            if not stats['matters']:
                continue  # no practice-management sync — nothing to attribute against
            for k in totals:
                totals[k] += stats.get(k, 0)
            self.stdout.write(
                f"org {org.id} {org.name[:28]:30s} "
                f"matters={stats['matters']:4d} scanned={stats['scanned']:5d} "
                f"by_number={stats['by_number']:4d} sole={stats['by_sole_matter']:4d} "
                f"unmatched={stats['unmatched']:5d}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\n{'DRY RUN — nothing written' if dry_run else 'APPLIED'}: "
            f"scanned={totals['scanned']} by_number={totals['by_number']} "
            f"sole_matter={totals['by_sole_matter']} unmatched={totals['unmatched']}"
        ))
        if dry_run:
            self.stdout.write('Re-run with --apply to write these attributions.')
