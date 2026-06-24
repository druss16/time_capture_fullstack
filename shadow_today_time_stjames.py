"""READ-ONLY. Does the committed 14m block (44733) actually flow into the
today_time dashboard payload for wendy's St James card? If it's committed in
DB but missing from the payload, that's the 'committed but invisible' bug."""
from datetime import date
from tracker.models import Block, User, Client

DAY = date(2026, 6, 23)
b = Block.objects.filter(id=44733).select_related('client','user').first()
print("block 44733:")
print(f"  user={b.user.username}  state={b.classification_state}  client={b.client.name if b.client_id else None}")
print(f"  minutes={b.minutes}  is_billable={b.is_billable}  category={getattr(b,'category',None)}")
print(f"  categorized_by={b.categorized_by}")
print(f"  day field={b.day}  start_ts={getattr(b,'start_ts',None)}  end_ts={getattr(b,'end_ts',None)}")

# Check the category field specifically — if category is None/empty, the
# today_time grouper may drop it or bucket it oddly.
print(f"\n  ⚠️ category value repr: {repr(getattr(b,'category',None))}")

# All committed St James blocks for wendy today, with their categories
sj = Client.objects.filter(name__icontains='James Church').first()
wendy = User.objects.filter(username='wendy').first()
print(f"\nWendy's committed St James (id={sj.id}) blocks today:")
rows = Block.objects.filter(
    day=DAY, user=wendy, client_id=sj.id, classification_state='committed',
    deleted_at__isnull=True,
)
for r in rows:
    print(f"  {r.id}: {r.minutes}m  cat={repr(getattr(r,'category',None))}  billable={r.is_billable}  '{(r.window_title or '')[:35]}'")

# Now simulate what today_time groups: does it require a non-null category?
print("\n" + "="*60)
print("If category is None on 44733, check whether today_time skips blocks")
print("with null category, or buckets them under a default. That determines")
print("whether the committed block shows in the card.")
print("="*60)
