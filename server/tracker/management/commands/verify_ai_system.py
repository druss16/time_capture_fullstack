# tracker/management/commands/verify_ai_system.py
"""
Management command to verify AI classification and pattern learning.

Usage:
    python manage.py verify_ai_system
    python manage.py verify_ai_system --user danrussell
    python manage.py verify_ai_system --full-test
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta
from collections import defaultdict

from tracker.models import Block, UserWorkPattern, RawEvent
from tracker.services.pattern_learning import PatternLearningService

import logging

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Verify AI classification and pattern learning system'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Check specific user (username)',
        )
        parser.add_argument(
            '--full-test',
            action='store_true',
            help='Run full system test with AI calls',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days to analyze (default: 7)',
        )
    
    def handle(self, *args, **options):
        username = options.get('user')
        full_test = options.get('full_test')
        days = options.get('days')
        
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS('AI CLASSIFICATION & PATTERN LEARNING VERIFICATION'))
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write('')
        
        # Get user(s) to check
        if username:
            try:
                users = [User.objects.get(username=username)]
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
                return
        else:
            # Get all users with recent activity
            cutoff = timezone.now() - timedelta(days=days)
            user_ids = Block.objects.filter(
                start__gte=cutoff
            ).values_list('user_id', flat=True).distinct()
            
            users = User.objects.filter(id__in=user_ids)
        
        if not users:
            self.stdout.write(self.style.WARNING('No users with recent activity found'))
            return
        
        self.stdout.write(f"Analyzing {len(users)} user(s) over last {days} days...")
        self.stdout.write('')
        
        # Run checks for each user
        for user in users:
            self.check_user(user, days, full_test)
            self.stdout.write('')
    
    def check_user(self, user, days, full_test):
        """Check AI and pattern learning for a specific user"""
        
        cutoff = timezone.now() - timedelta(days=days)
        
        self.stdout.write(self.style.HTTP_INFO(f'USER: {user.username}'))
        self.stdout.write('-' * 80)
        
        # ============================================================================
        # 1. RAW EVENTS CHECK
        # ============================================================================
        
        self.stdout.write(self.style.WARNING('\n1. RAW EVENTS CHECK'))
        
        event_count = RawEvent.objects.filter(
            user=user,
            ts_utc__gte=cutoff
        ).count()
        
        recent_events = RawEvent.objects.filter(
            user=user,
            ts_utc__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        self.stdout.write(f"  ✓ Total events (last {days} days): {event_count}")
        self.stdout.write(f"  ✓ Recent events (last hour): {recent_events}")
        
        if event_count == 0:
            self.stdout.write(self.style.ERROR('  ✗ NO EVENTS FOUND - Agent may not be sending data'))
            return
        
        # ============================================================================
        # 2. BLOCK CREATION CHECK
        # ============================================================================
        
        self.stdout.write(self.style.WARNING('\n2. BLOCK CREATION CHECK'))
        
        block_count = Block.objects.filter(
            user=user,
            start__gte=cutoff
        ).count()
        
        recent_blocks = Block.objects.filter(
            user=user,
            start__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        self.stdout.write(f"  ✓ Total blocks (last {days} days): {block_count}")
        self.stdout.write(f"  ✓ Recent blocks (last hour): {recent_blocks}")
        
        if block_count == 0:
            self.stdout.write(self.style.ERROR('  ✗ NO BLOCKS FOUND - Compaction may not be running'))
            self.stdout.write('    → Check if Celery beat is running')
            self.stdout.write('    → Try: python manage.py compact_recent_events')
            return
        
        # Conversion ratio
        if event_count > 0:
            ratio = (block_count / event_count) * 100
            self.stdout.write(f"  ℹ Event→Block conversion: {ratio:.1f}%")
        
        # ============================================================================
        # 3. CATEGORIZATION STATUS
        # ============================================================================
        
        self.stdout.write(self.style.WARNING('\n3. CATEGORIZATION STATUS'))
        
        categorized = Block.objects.filter(
            user=user,
            start__gte=cutoff,
            is_categorized=True
        ).count()
        
        uncategorized = Block.objects.filter(
            user=user,
            start__gte=cutoff,
            is_categorized=False
        ).count()
        
        self.stdout.write(f"  ✓ Categorized blocks: {categorized}")
        self.stdout.write(f"  ✓ Uncategorized blocks: {uncategorized}")
        
        if block_count > 0:
            cat_rate = (categorized / block_count) * 100
            self.stdout.write(f"  ℹ Categorization rate: {cat_rate:.1f}%")
            
            if cat_rate < 50:
                self.stdout.write(self.style.WARNING(
                    '  ⚠ Low categorization rate - AI may need attention'
                ))
        
        # Breakdown by source
        by_source = Block.objects.filter(
            user=user,
            start__gte=cutoff,
            is_categorized=True
        ).values('categorized_by').annotate(count=Count('id'))
        
        if by_source:
            self.stdout.write('  Categorization sources:')
            for item in by_source:
                source = item['categorized_by'] or 'unknown'
                count = item['count']
                self.stdout.write(f"    - {source}: {count}")
        
        # ============================================================================
        # 4. PATTERN LEARNING CHECK
        # ============================================================================
        
        self.stdout.write(self.style.WARNING('\n4. PATTERN LEARNING CHECK'))
        
        patterns = UserWorkPattern.objects.filter(
            user=user
        )
        
        pattern_count = patterns.count()
        
        self.stdout.write(f"  ✓ Total learned patterns: {pattern_count}")
        
        if pattern_count == 0:
            self.stdout.write(self.style.WARNING(
                '  ⚠ NO PATTERNS LEARNED - System needs training data'
            ))
            self.stdout.write('    → Manually classify 5-10 blocks to start learning')
        else:
            # Show pattern breakdown
            by_type = defaultdict(int)
            for p in patterns:
                by_type[p.pattern_type] += 1
            
            self.stdout.write('  Pattern types:')
            for ptype, count in sorted(by_type.items()):
                self.stdout.write(f"    - {ptype}: {count}")
            
            # Show top patterns
            top_patterns = patterns.filter(
                confidence_score__gte=0.70,
                occurrence_count__gte=3
            ).order_by('-confidence_score')[:5]
            
            if top_patterns:
                self.stdout.write('  Top patterns (confidence ≥ 0.70):')
                for p in top_patterns:
                    client_name = p.client.name if p.client else 'no client'
                    category = p.category or 'no category'
                    self.stdout.write(
                        f"    - {p.pattern_type}: {p.pattern_key[:50]} "
                        f"→ {client_name}/{category} ({p.confidence_score:.2f})"
                    )
        
        # ============================================================================
        # 5. CLIENT DETECTION CHECK
        # ============================================================================
        
        self.stdout.write(self.style.WARNING('\n5. CLIENT DETECTION CHECK'))
        
        blocks_with_client = Block.objects.filter(
            user=user,
            start__gte=cutoff,
            client__isnull=False
        ).count()
        
        self.stdout.write(f"  ✓ Blocks with client assigned: {blocks_with_client}")
        
        if block_count > 0:
            client_rate = (blocks_with_client / block_count) * 100
            self.stdout.write(f"  ℹ Client assignment rate: {client_rate:.1f}%")
            
            if client_rate < 30:
                self.stdout.write(self.style.WARNING(
                    '  ⚠ Low client assignment rate - Check current client feature'
                ))
        
        # Show client distribution
        by_client = Block.objects.filter(
            user=user,
            start__gte=cutoff,
            client__isnull=False
        ).values('client__name').annotate(count=Count('id')).order_by('-count')[:5]
        
        if by_client:
            self.stdout.write('  Top clients:')
            for item in by_client:
                self.stdout.write(f"    - {item['client__name']}: {item['count']} blocks")
        
        # ============================================================================
        # 6. FULL TEST (if requested)
        # ============================================================================
        
        if full_test:
            self.run_full_test(user)
    
    def run_full_test(self, user):
        """Run a full AI classification test on recent blocks"""
        
        self.stdout.write(self.style.WARNING('\n6. FULL AI TEST (with OpenAI calls)'))
        
        import os
        if not os.getenv('OPENAI_API_KEY'):
            self.stdout.write(self.style.ERROR('  ✗ OPENAI_API_KEY not configured'))
            return
        
        # Get 5 recent uncategorized blocks
        test_blocks = Block.objects.filter(
            user=user,
            is_categorized=False,
            start__gte=timezone.now() - timedelta(days=1)
        ).order_by('-start')[:5]
        
        if not test_blocks:
            self.stdout.write('  ℹ No uncategorized blocks to test')
            return
        
        self.stdout.write(f'  Testing {len(test_blocks)} recent blocks...')
        
        for i, block in enumerate(test_blocks, 1):
            self.stdout.write(f'\n  Block {i}/{len(test_blocks)}:')
            self.stdout.write(f"    App: {block.app_name}")
            self.stdout.write(f"    Title: {block.window_title[:50]}...")
            
            # Check learned patterns
            patterns = PatternLearningService.get_patterns_for_block(block, user)
            
            if patterns:
                self.stdout.write('    Learned patterns:')
                for client_name, category, confidence in patterns:
                    self.stdout.write(
                        f"      → {client_name or 'no client'} / {category} "
                        f"({confidence:.2f})"
                    )
            else:
                self.stdout.write('    No patterns matched')
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('  ✓ Full test complete'))