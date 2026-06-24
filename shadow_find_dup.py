"""READ-ONLY. Find the duplicate created by the recent move (non-billable →
Accounting/Bookkeeping). Look for blocks with same user+title+day appearing
more than once, especially recently modified."""
from datetime import date, timedelta
from collections import defaultdict
from django.utils import timezone
from tracker.models import Block, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()

# Most recently modified blocks (the move just happened)
print("="*72)
print("wendy's 10 most recently modified blocks today:")
print("="*72)
recent = Block.objects.filter(user=wendy, day=DAY, deleted_at__isnull=True).order_by('-categorized_at','-id')[:10]
for b in recent:
    print(f"  {b.id}: state={b.classification_state} min={b.minutes} "
          f"cat={list((b.category_hours or {}).keys())} client={b.client_id} "
          f"by={b.categorized_by} at={b.categorized_at} '{(b.window_title or '')[:30]}'")

# Find same-title duplicates today
print("\n" + "="*72)
print("Potential duplicates (same title appearing in 2+ blocks today):")
print("="*72)
by_title = defaultdict(list)
for b in Block.objects.filter(user=wendy, day=DAY, deleted_at__isnull=True):
    t = (b.window_title or '').strip()
    if t:
        by_title[t].append(b)
for t, blocks in by_title.items():
    if len(blocks) > 1:
        # only show if they overlap in time (true dup, not legit re-visit)
        print(f"\n  '{t[:45]}' — {len(blocks)} blocks:")
        for b in sorted(blocks, key=lambda x:x.id):
            print(f"     {b.id}: state={b.classification_state} min={b.minutes} "
                  f"cat={list((b.category_hours or {}).keys())} "
                  f"start={getattr(b,'start',None)} by={b.categorized_by}")
