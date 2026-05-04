"""
tracker/management/commands/test_classification.py

Run the new ClassificationService against historical data and produce a
comparison report showing what TODAY'S classification said vs what the
NEW classifier would say.

This is the primary tool for Phase 2 (parallel run) tuning — but useful
in Phase 1 too, to validate Stage 0/1/8/9 against TL Wall data before we
build out Stages 2-7 and 10.

USAGE:
    # Test against a specific user for the last 14 days
    python manage.py test_classification --user wendy --days 14

    # Test against an entire org
    python manage.py test_classification --org-id 21 --days 7

    # Test a single block by id (debugging)
    python manage.py test_classification --block-id 3919

    # Output as CSV for analysis
    python manage.py test_classification --org-id 21 --days 7 --csv > report.csv

    # Show only disagreements
    python manage.py test_classification --org-id 21 --days 7 --disagreements-only

    # Verbose mode — show signals for every block
    python manage.py test_classification --block-id 3919 --verbose
"""

import csv
import sys
import logging
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Run the new ClassificationService against historical blocks and '
        'compare results to current classifications.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user', type=str, default=None,
            help='Username to test against (e.g., "wendy"). Tests just this user.',
        )
        parser.add_argument(
            '--user-id', type=int, default=None,
            help='User ID to test against. Alternative to --user.',
        )
        parser.add_argument(
            '--org-id', type=int, default=None,
            help='Organization ID to test against. Tests all users in the org.',
        )
        parser.add_argument(
            '--block-id', type=int, default=None,
            help='Specific block ID to test (overrides --user/--org/--days).',
        )
        parser.add_argument(
            '--days', type=int, default=7,
            help='Number of days back from today to include (default: 7).',
        )
        parser.add_argument(
            '--csv', action='store_true', default=False,
            help='Output as CSV instead of formatted table.',
        )
        parser.add_argument(
            '--disagreements-only', action='store_true', default=False,
            help='Only output blocks where new classifier disagrees with current.',
        )
        parser.add_argument(
            '--verbose', action='store_true', default=False,
            help='Show signals and reasoning for every block.',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Limit the number of blocks tested (default: no limit).',
        )

    def handle(self, *args, **options):
        # Lazy imports — avoid loading these at command-discovery time
        from tracker.models import Block, Organization
        from tracker.services.classification_service import ClassificationService

        # Resolve target blocks based on input args
        blocks = self._resolve_blocks(options)
        if not blocks:
            self.stdout.write(self.style.WARNING('No blocks matched the given criteria.'))
            return

        if options['limit']:
            blocks = blocks[:options['limit']]

        self.stdout.write(self.style.SUCCESS(
            f'Testing ClassificationService against {len(blocks)} blocks...'
        ))

        # Run classification on each block
        results = []
        service_cache = {}  # cache services by (org_id, user_id) tuple

        for block in blocks:
            cache_key = (block.org_id, block.user_id)
            if cache_key not in service_cache:
                service_cache[cache_key] = ClassificationService(org=block.org, user=block.user)
            service = service_cache[cache_key]

            try:
                decision = service.classify(block)
            except Exception as e:
                logger.exception(f'Error classifying block {block.id}')
                decision = None

            result = self._build_comparison(block, decision)
            results.append(result)

        # Filter to disagreements if requested
        if options['disagreements_only']:
            results = [r for r in results if not r['agreement']]
            self.stdout.write(self.style.NOTICE(
                f'Filtered to {len(results)} disagreements.'
            ))

        # Output
        if options['csv']:
            self._write_csv(results, options)
        else:
            self._write_formatted(results, options)

        # Summary stats
        self._print_summary(results)

    # -------------------------------------------------------------------------
    # Block resolution
    # -------------------------------------------------------------------------

    def _resolve_blocks(self, options):
        """Find blocks based on the input arguments."""
        from tracker.models import Block, Organization

        if options['block_id']:
            return list(Block.objects.filter(id=options['block_id']).select_related('org', 'user', 'client'))

        # Compute date range
        cutoff = timezone.now() - timedelta(days=options['days'])

        qs = Block.objects.filter(start__gte=cutoff).select_related('org', 'user', 'client')

        # Filter by user
        if options['user']:
            try:
                user = User.objects.get(username=options['user'])
                qs = qs.filter(user=user)
            except User.DoesNotExist:
                raise CommandError(f"No user found with username '{options['user']}'")
        elif options['user_id']:
            qs = qs.filter(user_id=options['user_id'])
        elif options['org_id']:
            qs = qs.filter(org_id=options['org_id'])
        else:
            raise CommandError(
                'Specify one of: --user, --user-id, --org-id, or --block-id'
            )

        return list(qs.order_by('start'))

    # -------------------------------------------------------------------------
    # Comparison logic
    # -------------------------------------------------------------------------

    def _build_comparison(self, block, decision):
        """
        Build a comparison row showing today's classification vs the new one.
        """
        # Today's classification (whatever's currently on the block)
        today_client = block.client.name if block.client else None
        today_category = ''
        if block.category_hours:
            today_category = max(block.category_hours.items(), key=lambda x: x[1])[0]

        # New classifier's decision
        if decision is None:
            new_client = '<ERROR>'
            new_category = '<ERROR>'
            new_state = '<ERROR>'
            new_confidence = 0.0
            new_signals = []
            new_reasoning = '<ERROR>'
            agreement = False
        else:
            # Resolve client name from id
            new_client = None
            if decision.client_id:
                from tracker.models import Client
                try:
                    new_client = Client.objects.get(id=decision.client_id).name
                except Client.DoesNotExist:
                    new_client = f'<missing client {decision.client_id}>'

            new_category = decision.category or ''
            new_state = decision.recommended_state
            new_confidence = decision.confidence
            new_signals = decision.signals_dicts()
            new_reasoning = decision.reasoning

            # Agreement = same client AND (same category OR new is captured/proposed without category)
            client_matches = (today_client == new_client) or (
                today_client is None and new_client is None
            )
            agreement = client_matches

        return {
            'block_id':       block.id,
            'username':       block.user.username if block.user else '?',
            'org_name':       block.org.name if block.org else '?',
            'start':          block.start.isoformat() if block.start else '',
            'minutes':        block.minutes or 0,
            'app':            (block.app_name or '')[:30],
            'title':          (block.window_title or block.title or '')[:80],
            'today_client':   today_client,
            'today_category': today_category,
            'today_state':    block.classification_state,
            'today_locked':   block.is_categorized,
            'new_client':     new_client,
            'new_category':   new_category,
            'new_state':      new_state,
            'new_confidence': round(new_confidence, 3),
            'new_signals':    new_signals,
            'new_reasoning':  new_reasoning,
            'agreement':      agreement,
        }

    # -------------------------------------------------------------------------
    # Output formatters
    # -------------------------------------------------------------------------

    def _write_csv(self, results, options):
        """Write results as CSV to stdout."""
        if not results:
            return

        writer = csv.writer(sys.stdout)

        # Header
        header = [
            'block_id', 'username', 'org', 'start', 'minutes', 'app', 'title',
            'today_client', 'today_category', 'today_state',
            'new_client', 'new_category', 'new_state', 'new_confidence',
            'agreement', 'new_reasoning',
        ]
        writer.writerow(header)

        for r in results:
            writer.writerow([
                r['block_id'], r['username'], r['org_name'], r['start'],
                r['minutes'], r['app'], r['title'],
                r['today_client'] or '', r['today_category'], r['today_state'],
                r['new_client'] or '', r['new_category'], r['new_state'], r['new_confidence'],
                'YES' if r['agreement'] else 'NO',
                r['new_reasoning'],
            ])

    def _write_formatted(self, results, options):
        """Write results as a formatted table."""
        for r in results:
            agreement_marker = self.style.SUCCESS('✓') if r['agreement'] else self.style.WARNING('✗')

            self.stdout.write('')
            self.stdout.write(f"{agreement_marker} Block #{r['block_id']} | {r['username']} | "
                              f"{r['minutes']}min | {r['app']}")
            self.stdout.write(f"  Title: {r['title']}")
            self.stdout.write(f"  TODAY: client={r['today_client']!r:30} cat={r['today_category']!r:20} state={r['today_state']!r}")
            self.stdout.write(f"  NEW:   client={r['new_client']!r:30} cat={r['new_category']!r:20} state={r['new_state']!r:10} conf={r['new_confidence']}")

            if r['new_reasoning']:
                self.stdout.write(f"  Reasoning: {r['new_reasoning']}")

            if options['verbose'] and r['new_signals']:
                self.stdout.write('  Signals:')
                for sig in r['new_signals']:
                    self.stdout.write(
                        f"    - [{sig['type']}] strength={sig['strength']:.2f} | {sig['evidence']}"
                    )

    def _print_summary(self, results):
        """Print summary stats at the end."""
        total = len(results)
        if total == 0:
            return

        agree = sum(1 for r in results if r['agreement'])
        disagree = total - agree

        # Breakdown by new state
        state_counts = {}
        for r in results:
            state_counts[r['new_state']] = state_counts.get(r['new_state'], 0) + 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('SUMMARY'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(f'Total blocks tested:    {total}')
        self.stdout.write(f'Agreement:              {agree} ({100*agree/total:.1f}%)')
        self.stdout.write(f'Disagreement:           {disagree} ({100*disagree/total:.1f}%)')
        self.stdout.write('')
        self.stdout.write('New classifier state breakdown:')
        for state, count in sorted(state_counts.items(), key=lambda x: -x[1]):
            self.stdout.write(f'  {state:>15}: {count:>5} ({100*count/total:.1f}%)')

        # Note about partial pipeline
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'NOTE: Stages 0/1/2/3/4/8/9/10 implemented. Stages 5/6/7 still TODO '
            '(URL domain matching covered by Stage 3, Calendar / Mail deferred '
            'to calendar/mail chunks). Disagreements often reflect '
            'classifier correctly rejecting bogus inherited attributions on '
            'idle/dialog blocks.'
        ))