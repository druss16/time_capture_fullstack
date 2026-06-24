"""READ-ONLY. Find the ACTUAL block behind the 'Write Checks' pending row that
was confirmed — by its distinctive title. Is it 44733 or a DIFFERENT block?
And what's its current state?"""
from datetime import date
from tracker.models import Block, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()

print("="*72)
print("Blocks with 'Write Checks' in title (wendy, today):")
print("="*72)
wc = Block.objects.filter(user=wendy, day=DAY, window_title__icontains='Write Checks', deleted_at__isnull=True)
for b in wc:
    print(f"  block {b.id}: state={b.classification_state} min={b.minutes} "
          f"client={b.client_id} billable={b.is_billable} by={b.categorized_by}")
    print(f"    title: {b.window_title}")
    print(f"    cat_hours: {b.category_hours}")
    print(f"    start={getattr(b,'start',None)} end={getattr(b,'end',None)}")

print("\n" + "="*72)
print("Block 44733 full title (what the shadow grouped):")
b = Block.objects.filter(id=44733).first()
print(f"  44733 window_title: {b.window_title!r}")
print(f"  44733 state={b.classification_state} min={b.minutes} cat_hours={b.category_hours}")

print("\n" + "="*72)
print("ALL of wendy's St James (114) blocks today, EVERY state:")
print("="*72)
for x in Block.objects.filter(user=wendy, day=DAY, client_id=114, deleted_at__isnull=True).order_by('id'):
    print(f"  {x.id}: state={x.classification_state} min={x.minutes} billable={x.is_billable} "
          f"by={x.categorized_by} '{(x.window_title or '')[:45]}'")

# Also check: was the Write Checks block maybe RE-MERGED or its events moved?
print("\n" + "="*72)
print("Any St James blocks for wendy in OTHER states (proposed/suppressed/etc)?")
for x in Block.objects.filter(user=wendy, day=DAY, client_id=114).order_by('id'):
    print(f"  {x.id}: state={x.classification_state} deleted={x.deleted_at} min={x.minutes}")
