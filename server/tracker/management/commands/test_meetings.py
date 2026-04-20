from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from tracker.models import RawEvent, Block
from tracker.services.compaction import compact_day


class Command(BaseCommand):
    help = "Test meeting block extraction end-to-end"

    def handle(self, *args, **options):
        User = get_user_model()

        user = User.objects.filter(username__icontains='dan').first()
        if not user:
            user = User.objects.first()
        self.stdout.write(f"\n✓ Testing as user: {user.username} (id={user.id})")

        TEST_HOST = 'meeting-test-host-SAFE-TO-DELETE'

        old_events = RawEvent.objects.filter(user=user, hostname=TEST_HOST).count()
        old_blocks = Block.objects.filter(user=user, hostname=TEST_HOST).count()
        if old_events or old_blocks:
            self.stdout.write(f"✓ Cleaning up {old_events} events, {old_blocks} blocks from prior runs")
            RawEvent.objects.filter(user=user, hostname=TEST_HOST).delete()
            Block.objects.filter(user=user, hostname=TEST_HOST).delete()

        now = timezone.now()
        meeting_start = now - timedelta(minutes=30)
        meeting_end = now - timedelta(minutes=15)

        RawEvent.objects.create(
            user=user, hostname=TEST_HOST, ts_utc=meeting_start,
            app_name='Meeting', bundle_id='meeting:zoom',
            window_title='TEST Meeting - Varacchi 1040 Review',
            url='', file_path='',
        )
        RawEvent.objects.create(
            user=user, hostname=TEST_HOST, ts_utc=meeting_end,
            app_name='Meeting-End', bundle_id='meeting:zoom',
            window_title='', url='', file_path='',
        )
        self.stdout.write(f"✓ Injected meeting: {meeting_start.strftime('%H:%M:%S')} → {meeting_end.strftime('%H:%M:%S')}")
        self.stdout.write(f"  Expected duration: 15 min")

        self.stdout.write(f"\n─── Running compact_day() ───")
        result = compact_day(user, timezone.localdate(), hostname=TEST_HOST)
        self.stdout.write(f"✓ compact_day returned: {result}")

        self.stdout.write(f"\n─── BLOCKS CREATED ───")
        blocks = list(Block.objects.filter(user=user, hostname=TEST_HOST).order_by('start'))

        if not blocks:
            self.stdout.write(self.style.ERROR("❌ FAIL: No blocks created."))
        else:
            for b in blocks:
                self.stdout.write(f"\n  Block {b.id}:")
                self.stdout.write(f"    App name:      {b.app_name}")
                self.stdout.write(f"    Bundle ID:     {b.bundle_id}")
                self.stdout.write(f"    Window title:  {b.window_title}")
                self.stdout.write(f"    Start:         {b.start.strftime('%H:%M:%S')}")
                self.stdout.write(f"    End:           {b.end.strftime('%H:%M:%S')}")
                self.stdout.write(f"    Duration:      {b.minutes} min")
                self.stdout.write(f"    Client:        {b.client.name if b.client else '(unattributed)'}")
                self.stdout.write(f"    Category:      {b.category_hours}")
                self.stdout.write(f"    Locked:        {b.is_categorized}")
                self.stdout.write(f"    Billable:      {b.is_billable}")
                self.stdout.write(f"    Billing rate:  ${b.billing_rate}")
                self.stdout.write(f"    Billing amt:   ${b.billing_amount}")
                self.stdout.write(f"    Hints:         {b.hints}")

        self.stdout.write(f"\n─── ASSERTIONS ───")
        passed, failed = 0, 0

        def check(label, condition):
            nonlocal passed, failed
            if condition:
                self.stdout.write(f"  ✓ {label}")
                passed += 1
            else:
                self.stdout.write(self.style.ERROR(f"  ❌ {label}"))
                failed += 1

        if blocks:
            b = blocks[0]
            check("Exactly 1 block created", len(blocks) == 1)
            check("Bundle ID starts with 'meeting:'", b.bundle_id.startswith('meeting:'))
            check("Bundle ID is 'meeting:zoom'", b.bundle_id == 'meeting:zoom')
            check("App name mentions 'Zoom' and 'Meeting'", 'Zoom' in (b.app_name or '') and 'Meeting' in (b.app_name or ''))
            check("Duration is 15 min", b.minutes == 15)
            check("Category is 'Client Meeting'", 'Client Meeting' in (b.category_hours or {}))
            check("Block is locked", b.is_categorized is True)
            check("Block is billable", b.is_billable is True)
            check("categorized_by = 'meeting_detector'", b.categorized_by == 'meeting_detector')
            check("hints['is_meeting'] = True", (b.hints or {}).get('is_meeting') is True)
            check("hints['meeting_app'] = 'zoom'", (b.hints or {}).get('meeting_app') == 'zoom')
        else:
            failed = 1

        self.stdout.write(f"\n─── RESULTS: {passed} passed, {failed} failed ───")

        self.stdout.write(f"\n─── CLEANING UP TEST DATA ───")
        RawEvent.objects.filter(user=user, hostname=TEST_HOST).delete()
        Block.objects.filter(user=user, hostname=TEST_HOST).delete()
        self.stdout.write("✓ Done.")

        if failed == 0:
            self.stdout.write(self.style.SUCCESS("\n🎉 ALL CHECKS PASSED"))
        else:
            self.stdout.write(self.style.ERROR(f"\n⚠️  {failed} check(s) failed"))