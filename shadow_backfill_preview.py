"""DRY-RUN PREVIEW (read-only). Find committed blocks whose category_hours
sums to 0 but which have real minutes — these are the blocks broken by the
pre-fix recategorize bug. Shows what a backfill WOULD write. Changes nothing."""
from datetime import date, timedelta
from tracker.models import Block

# Look back a couple weeks across all orgs; adjust if needed
since = date.today() - timedelta(days=14)

broken = []
qs = Block.objects.filter(
    classification_state='committed',
    categorized_by='correction',     # confirmed via the inline card / manual
    deleted_at__isnull=True,
    day__gte=since,
)
for b in qs:
    ch_sum = sum((b.category_hours or {}).values())
    if ch_sum == 0 and (b.minutes or 0) > 0:
        broken.append(b)

print("="*72)
print(f"BROKEN blocks (committed, category_hours=0, minutes>0) since {since}: {len(broken)}")
print("="*72)
for b in broken:
    cat = list((b.category_hours or {}).keys())[0] if b.category_hours else '(empty)'
    would = round((b.minutes or 0)/60.0, 4)
    print(f"  {b.id} | {b.day} | {b.user.username} | {b.minutes}m | "
          f"client={b.client.name if b.client_id else 'None'} | "
          f"cat_hours={b.category_hours!r} → would write {{{cat!r}: {would}}}")
print("="*72)
print(f"TOTAL hidden minutes: {sum(b.minutes or 0 for b in broken)}")
print("If this list looks right, say 'apply backfill' and I'll write the")
print("non-dry-run version that rewrites category_hours = {existing_cat: minutes/60}.")
print("="*72)
