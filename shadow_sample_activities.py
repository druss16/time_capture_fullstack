"""READ-ONLY. What sample_activities strings does today_time produce for the
two Print Checks blocks? If their representative titles DIFFER, siblingBlockIds
won't match them, so recategorizing one misses the other → the 'split'."""
from datetime import date, datetime
from collections import defaultdict
from django.utils import timezone
from tracker.models import RawEvent, Block, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()

# Mimic how today_time derives the activity title per block.
# It groups events; the row title comes from event window_title.
for bid in [44763, 44767]:
    b = Block.objects.filter(id=bid).first()
    print(f"block {bid}: cat={list((b.category_hours or {}).keys())} min={b.minutes}")
    evs = RawEvent.objects.filter(block_id=bid)
    titles = defaultdict(float)
    for e in evs:
        if e.start_ts and e.end_ts:
            titles[(e.window_title or '')] += (e.end_ts-e.start_ts).total_seconds()
    for t, s in sorted(titles.items(), key=lambda x:-x[1]):
        print(f"    '{t}'  {s/60:.1f}m")
    print(f"  → dominant title (likely the row label): "
          f"'{max(titles.items(), key=lambda x:x[1])[0] if titles else None}'")
    print()

print("="*72)
print("If the two blocks' DOMINANT titles differ (e.g. 'Print Checks' vs")
print("'Print Checks - Confirmation'), they render as SEPARATE rows and")
print("siblingBlockIds can't link them → moving one leaves the other = 'split'.")
print("If SAME title, they should group and move together — bug is elsewhere.")
