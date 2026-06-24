"""READ-ONLY. Find the QuickBooks 4m block that 'No Client' was clicked on.
Check: did it commit to non-billable? Does it have category_hours? Why isn't
the non-billable total reflecting it?"""
from datetime import date
from tracker.models import Block, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()

# The (Primary) QuickBooks Accountant Desktop Plus 2024 pending block(s)
print("="*72)
print("QuickBooks Accountant Desktop Plus blocks (no/null title-ish), wendy today:")
print("="*72)
qb = Block.objects.filter(
    user=wendy, day=DAY, deleted_at__isnull=True,
    window_title__icontains='QuickBooks Accountant Desktop Plus',
).order_by('-categorized_at')
for b in qb[:10]:
    print(f"  {b.id}: state={b.classification_state} min={b.minutes} "
          f"client={b.client_id} billable={b.is_billable}")
    print(f"     cat_hours={b.category_hours} by={b.categorized_by} "
          f"cat_at={b.categorized_at}")
    print(f"     title='{(b.window_title or '')[:45]}'")

# Recently modified (the No Client click would be most recent)
print("\n" + "="*72)
print("Most recently categorized blocks (the No Client click should be top):")
print("="*72)
recent = Block.objects.filter(
    user=wendy, day=DAY, deleted_at__isnull=True, categorized_by='correction',
).order_by('-categorized_at')[:5]
for b in recent:
    print(f"  {b.id}: state={b.classification_state} min={b.minutes} "
          f"client={b.client_id} billable={b.is_billable} "
          f"cat={list((b.category_hours or {}).keys())} at={b.categorized_at}")
    print(f"     '{(b.window_title or '')[:45]}'")

# Count non-billable total for wendy (what the footer should show)
print("\n" + "="*72)
print("Wendy's non-billable committed total today:")
nb = Block.objects.filter(
    user=wendy, day=DAY, deleted_at__isnull=True, classification_state='committed',
    is_billable=False,
)
total_nb = sum(b.minutes or 0 for b in nb)
print(f"  {nb.count()} non-billable committed blocks, {total_nb}m total")
