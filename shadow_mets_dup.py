"""READ-ONLY. The 'Syracuse Mets Transaction' shows as 10m Email AND 1m
Personal under Transfiguration. Find the block(s) and trace why its events
split across two categories in the rollup."""
from datetime import date
from collections import defaultdict
from tracker.models import Block, RawEvent, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()

print("="*72)
print("Blocks with 'Mets Transaction' in title (wendy today):")
print("="*72)
blocks = Block.objects.filter(user=wendy, day=DAY, window_title__icontains='Mets Transaction', deleted_at__isnull=True).select_related('client')
for b in blocks:
    print(f"  block {b.id}: state={b.classification_state} min={b.minutes} "
          f"client={b.client.name if b.client_id else None}")
    print(f"    category_hours: {b.category_hours}")
    print(f"    by={b.categorized_by} billable={b.is_billable}")
    print(f"    start={getattr(b,'start',None)} end={getattr(b,'end',None)}")
    # events for this block — what titles/categories?
    evs = RawEvent.objects.filter(block=b)
    print(f"    {evs.count()} events:")
    by_t = defaultdict(int)
    for e in evs:
        by_t[(e.window_title or '')[:40]] += 1
    for t,c in by_t.items():
        print(f"       {c}x  '{t}'")
    print()

# Is there a block with this title in Email AND another in Personal?
print("="*72)
print("Same-title blocks split by category:")
by_cat = defaultdict(list)
for b in blocks:
    cat = list((b.category_hours or {}).keys())[0] if b.category_hours else 'none'
    by_cat[cat].append(b.id)
for cat, ids in by_cat.items():
    print(f"  {cat}: blocks {ids}")
print("\nIf ONE block's events span two categories → rollup bug.")
print("If TWO blocks (one Email, one Personal) same title → move created a dup.")
