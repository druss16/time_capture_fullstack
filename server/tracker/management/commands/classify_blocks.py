from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from tracker.models import Block
from tracker.services.classify_block import classify_block

class Command(BaseCommand):
    help = "Re-classify Blocks using current AI logic."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7,
                            help="Reclassify Blocks from last N days (default 7).")

    def handle(self, *args, **opts):
        days = opts["days"]
        since = timezone.now().date() - timedelta(days=days)
        qs = Block.objects.filter(day__gte=since)

        self.stdout.write(f"🔍 Reclassifying {qs.count()} blocks from last {days} days…")
        for i, b in enumerate(qs, start=1):
            try:
                classify_block(b)
                if i % 20 == 0:
                    self.stdout.write(f"  → processed {i}…")
            except Exception as e:
                self.stderr.write(f"Error on {b.id}: {e}")
        self.stdout.write("✅ Done.")