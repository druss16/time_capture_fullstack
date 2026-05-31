"""
Auto-resolve obvious personal/non-billable blocks so they stop polluting
the Categorize review pile.

A block qualifies for auto-resolve if ALL of these are true:
  - is_categorized=False (still in the pile)
  - client_id=None (no client identified by ANY signal stage)
  - is_billable=False (classifier already marked as non-billable)
  - classification_state IN ('captured', 'proposed') (not yet user-confirmed)
  - state_changed_by NOT IN ('user', 'user_edit', 'correction')
  - minutes <= --max-minutes (default 5)

The minutes ceiling is a safety belt. Short blocks (≤5 min) are almost
always quick personal-browsing detours — news headlines, music sites,
shopping, calculator. Long blocks (>5 min) are more likely substantial
work that deserves user review even if the classifier can't identify
the client, because they might be billable activity that needs proper
attribution.

Resolved blocks get marked:
  - is_categorized=True
  - categorized_by='ai'
  - classification_state='committed'

User can still find them in unbilled / Personal Activity views and edit
if needed. The Categorize review pile no longer surfaces them.

Location: server/tracker/management/commands/auto_resolve_personal_blocks.py

Usage:
  # Dry run first
  python manage.py auto_resolve_personal_blocks --org-id 21 --dry-run

  # Commit
  python manage.py auto_resolve_personal_blocks --org-id 21

  # Tighter (only auto-resolve very short blocks)
  python manage.py auto_resolve_personal_blocks --org-id 21 --max-minutes 3 --dry-run

  # Wider (auto-resolve up to 10-min blocks — riskier)
  python manage.py auto_resolve_personal_blocks --org-id 21 --max-minutes 10 --dry-run

  # Look back further
  python manage.py auto_resolve_personal_blocks --org-id 21 --days 90 --dry-run

  # Limit to one user
  python manage.py auto_resolve_personal_blocks --org-id 21 --user-id 56
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.models import Block, Organization


class Command(BaseCommand):
    help = "Auto-resolve obvious non-billable blocks out of the review pile"

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, required=True)
        parser.add_argument(
            '--days', type=int, default=30,
            help='Look back N days (default 30)'
        )
        parser.add_argument(
            '--max-minutes', type=int, default=5,
            help='Only auto-resolve blocks <= this many minutes (default 5). '
                 'Longer blocks stay in review because they are more likely '
                 'to be substantial billable activity needing user attribution.'
        )
        parser.add_argument(
            '--user-id', type=int, default=None,
            help='Restrict to one user'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without writing'
        )

    def handle(self, *args, **opts):
        try:
            org = Organization.objects.get(pk=opts['org_id'])
        except Organization.DoesNotExist:
            raise CommandError(f"Org {opts['org_id']} not found")

        cutoff = timezone.localdate() - timedelta(days=opts['days'])
        max_minutes = opts['max_minutes']

        qs = Block.objects.filter(
            org=org,
            day__gte=cutoff,
            is_categorized=False,
            client__isnull=True,
            is_billable=False,
            classification_state__in=['captured', 'proposed'],
            minutes__lte=max_minutes,
        ).exclude(
            state_changed_by__in=['user', 'user_edit', 'correction'],
        )

        if opts.get('user_id'):
            qs = qs.filter(user_id=opts['user_id'])

        total_count = qs.count()
        if total_count == 0:
            self.stdout.write(
                f"\nNo blocks match the auto-resolve criteria for "
                f"{org.name} in the last {opts['days']} days "
                f"(max_minutes={max_minutes}). Nothing to do."
            )
            return

        # Per-user breakdown
        from django.db.models import Count, Sum
        per_user = qs.values(
            'user_id', 'user__username',
        ).annotate(
            block_count=Count('id'),
            total_minutes=Sum('minutes'),
        ).order_by('-block_count')

        self.stdout.write(
            f"\nFound {total_count} blocks to auto-resolve for {org.name} "
            f"(last {opts['days']} days, ≤{max_minutes}min each):\n"
        )
        for row in per_user:
            self.stdout.write(
                f"  user={row['user__username'] or row['user_id']}: "
                f"{row['block_count']} blocks, "
                f"{row['total_minutes'] or 0} min total"
            )

        # Show ALL blocks if total is small, sample otherwise
        sample_size = 30 if total_count <= 30 else 20
        self.stdout.write(
            f"\nBlocks that would be auto-resolved (showing {min(sample_size, total_count)} of {total_count}):"
        )
        for b in qs.order_by('-day', '-minutes')[:sample_size]:
            title = (b.window_title or '')[:65]
            self.stdout.write(
                f"  {b.pk} | {b.day} | {b.app_name:12s} | {b.minutes or 0:3d}m | {title}"
            )
        if total_count > sample_size:
            self.stdout.write(f"  ... and {total_count - sample_size} more")

        # Show what's STAYING in the pile (above max_minutes threshold)
        staying = Block.objects.filter(
            org=org,
            day__gte=cutoff,
            is_categorized=False,
            client__isnull=True,
            is_billable=False,
            classification_state__in=['captured', 'proposed'],
            minutes__gt=max_minutes,
        ).exclude(
            state_changed_by__in=['user', 'user_edit', 'correction'],
        )
        if opts.get('user_id'):
            staying = staying.filter(user_id=opts['user_id'])
        staying_count = staying.count()
        if staying_count:
            self.stdout.write(
                f"\nSTAYING in review pile ({staying_count} blocks >{max_minutes}min "
                f"— might be billable, needs user eyes):"
            )
            for b in staying.order_by('-minutes')[:20]:
                title = (b.window_title or '')[:65]
                self.stdout.write(
                    f"  {b.pk} | {b.day} | {b.app_name:12s} | {b.minutes or 0:3d}m | {title}"
                )

        if opts['dry_run']:
            self.stdout.write(
                "\nDry-run — no writes. Re-run without --dry-run to commit."
            )
            return

        # WRITE PHASE
        self.stdout.write("\nWriting...")
        now = timezone.now()
        updated = qs.update(
            is_categorized=True,
            categorized_at=now,
            categorized_by='ai',
            classification_state='committed',
            state_changed_by='classifier',
            state_changed_at=now,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Auto-resolved {updated} blocks. Hidden from Categorize "
                f"pile. {staying_count if 'staying_count' in dir() else 0} "
                f"longer blocks still in review for user attention.\n\n"
                f"Tell Wayne to refresh his Daily Review."
            )
        )