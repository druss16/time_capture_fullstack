from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from tracker.models import Block, Client, RawEvent, Organization
from tracker.services.compaction import compact_day, _filter_foreground_inside_meetings


class Command(BaseCommand):
    help = "Test meeting-supersedes-foreground filter"

    def handle(self, *args, **options):
        User = get_user_model()

        user = User.objects.filter(username__icontains='dan').first() or User.objects.first()
        self.stdout.write(f"\n✓ Testing as user: {user.username}\n")

        org = Organization.objects.first()
        TEST_HOST = 'meeting-supersede-test-SAFE-TO-DELETE'

        # Clean up prior test data
        Block.objects.filter(user=user, hostname=TEST_HOST).delete()
        RawEvent.objects.filter(user=user, hostname=TEST_HOST).delete()

        # Get or create test clients (use unique codes)
        client_a, _ = Client.objects.get_or_create(
            org=org, code='TESTCLNTA',
            defaults={'name': 'Test Client A', 'is_active': True},
        )
        client_b, _ = Client.objects.get_or_create(
            org=org, code='TESTCLNTB',
            defaults={'name': 'Test Client B', 'is_active': True},
        )

        today = timezone.localdate()
        base = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)

        # ──────────────────────────────────────────────────────────────
        # Create meeting block DIRECTLY (skip raw events / compactor)
        # We're testing the FILTER, not the compactor's client attribution
        # ──────────────────────────────────────────────────────────────
        meeting = Block.objects.create(
            user=user, hostname=TEST_HOST, org=org,
            day=today,
            start=base,
            end=base + timedelta(hours=1),
            minutes=60,
            app_name='Zoom Meeting',
            bundle_id='meeting:zoom',
            window_title='Client A Weekly Sync',
            client=client_a,  # ← THE KEY: meeting is attributed to Client A
            is_billable=True,
            billing_rate=Decimal('150.00'),
            is_categorized=True,
            categorized_by='meeting_detector',
            ai_category='Client Meeting',
            category_hours={'Client Meeting': 1.0},
            hints={'is_meeting': True, 'meeting_app': 'zoom'},
        )

        # Foreground block 1: fully inside meeting (should be suppressed)
        block_inside = Block.objects.create(
            user=user, hostname=TEST_HOST, org=org,
            day=today,
            start=base + timedelta(minutes=15),
            end=base + timedelta(minutes=45),
            minutes=30,
            app_name='Excel', window_title='Budget.xlsx',
            client=client_b,
            is_billable=True,
            billing_rate=Decimal('150.00'),
            categorized_by='ai',
            is_categorized=True,
            category_hours={'Bookkeeping': 0.5},
        )

        # Foreground block 2: partial overlap (should be LEFT ALONE)
        block_partial = Block.objects.create(
            user=user, hostname=TEST_HOST, org=org,
            day=today,
            start=base + timedelta(minutes=45),
            end=base + timedelta(minutes=75),
            minutes=30,
            app_name='Outlook', window_title='Email',
            client=client_b,
            is_billable=True,
            billing_rate=Decimal('150.00'),
            categorized_by='ai',
            is_categorized=True,
            category_hours={'Email': 0.5},
        )

        # Foreground block 3: no overlap (should be LEFT ALONE)
        block_outside = Block.objects.create(
            user=user, hostname=TEST_HOST, org=org,
            day=today,
            start=base + timedelta(minutes=90),
            end=base + timedelta(minutes=120),
            minutes=30,
            app_name='QuickBooks', window_title='Client B Ledger',
            client=client_b,
            is_billable=True,
            billing_rate=Decimal('150.00'),
            categorized_by='ai',
            is_categorized=True,
            category_hours={'Bookkeeping': 0.5},
        )

        # Foreground block 4: MANUAL categorization inside meeting (should be LEFT ALONE per rules)
        block_manual = Block.objects.create(
            user=user, hostname=TEST_HOST, org=org,
            day=today,
            start=base + timedelta(minutes=20),
            end=base + timedelta(minutes=30),
            minutes=10,
            app_name='Chrome', window_title='Something',
            client=client_b,
            is_billable=True,
            billing_rate=Decimal('150.00'),
            categorized_by='manual',  # ← user explicitly set this
            is_categorized=True,
            category_hours={'Research': 0.17},
        )

        self.stdout.write(f"✓ Created test fixtures:")
        self.stdout.write(f"  meeting  id={meeting.id}       10:00-11:00 Zoom (Client A)")
        self.stdout.write(f"  inside   id={block_inside.id}  10:15-10:45 Excel (Client B)")
        self.stdout.write(f"  partial  id={block_partial.id} 10:45-11:15 Outlook (Client B)")
        self.stdout.write(f"  outside  id={block_outside.id} 11:30-12:00 QuickBooks (Client B)")
        self.stdout.write(f"  manual   id={block_manual.id}  10:20-10:30 Chrome (manual, Client B)")

        # ──────────────────────────────────────────────────────────────
        # Run the filter directly (isolates the logic we're testing)
        # ──────────────────────────────────────────────────────────────
        self.stdout.write(f"\n─── Running _filter_foreground_inside_meetings() ───")
        suppressed_count = _filter_foreground_inside_meetings(user, today)
        self.stdout.write(f"✓ Filter returned: {suppressed_count} blocks suppressed")

        # Refetch blocks
        meeting.refresh_from_db()
        block_inside.refresh_from_db()
        block_partial.refresh_from_db()
        block_outside.refresh_from_db()
        block_manual.refresh_from_db()

        self.stdout.write(f"\n─── ASSERTIONS ───")
        passed, failed = 0, 0

        def check(label, cond):
            nonlocal passed, failed
            if cond:
                self.stdout.write(f"  ✓ {label}")
                passed += 1
            else:
                self.stdout.write(self.style.ERROR(f"  ❌ {label}"))
                failed += 1

        check("Meeting is still billable",               meeting.is_billable is True)
        check("Meeting is for Client A",                 meeting.client_id == client_a.id)
        check("INSIDE block marked non-billable",        block_inside.is_billable is False)
        check("INSIDE block billing_amount = 0",         block_inside.billing_amount == Decimal('0.00'))
        check("PARTIAL block still billable",            block_partial.is_billable is True)
        check("OUTSIDE block still billable",            block_outside.is_billable is True)
        check("MANUAL block still billable (user wins)", block_manual.is_billable is True)
        check("Filter returned count == 1",              suppressed_count == 1)

        self.stdout.write(f"\n─── RESULTS: {passed} passed, {failed} failed ───")

        # Cleanup
        Block.objects.filter(user=user, hostname=TEST_HOST).delete()
        RawEvent.objects.filter(user=user, hostname=TEST_HOST).delete()
        self.stdout.write(f"\n✓ Test data cleaned up")

        if failed == 0:
            self.stdout.write(self.style.SUCCESS("\n🎉 ALL CHECKS PASSED"))
        else:
            self.stdout.write(self.style.ERROR(f"\n⚠️  {failed} check(s) failed"))