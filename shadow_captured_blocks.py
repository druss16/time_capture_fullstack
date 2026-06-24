"""READ-ONLY. Inspect wendy's 'captured' blocks — what are they, do they have
a client, a category, how do they differ from committed/proposed? This tells
us how 'stay in card but needs confirmation' should render."""
from datetime import date
from tracker.models import Block, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()

caps = Block.objects.filter(user=wendy, day=DAY, classification_state='captured', deleted_at__isnull=True).select_related('client','proposed_client')
print(f"wendy 'captured' blocks: {caps.count()}")
print("="*72)
for b in caps:
    print(f"  block {b.id}: {b.minutes}m")
    print(f"    client:          {b.client.name if b.client_id else None}")
    print(f"    proposed_client: {b.proposed_client.name if b.proposed_client_id else None}")
    print(f"    category_hours:  {b.category_hours}")
    print(f"    is_billable:     {b.is_billable}")
    print(f"    is_categorized:  {getattr(b,'is_categorized',None)}")
    print(f"    categorized_by:  {b.categorized_by}")
    print(f"    title:           {(b.window_title or '')[:50]}")
    print()

# How do committed differ? sample one
print("="*72)
print("For contrast — a committed block:")
c = Block.objects.filter(user=wendy, day=DAY, classification_state='committed', client_id__isnull=False, deleted_at__isnull=True).first()
if c:
    print(f"  {c.id}: client={c.client.name if c.client_id else None} "
          f"cat_hours={c.category_hours} billable={c.is_billable} "
          f"is_categorized={getattr(c,'is_categorized',None)} by={c.categorized_by}")

print("\n" + "="*72)
print("QUESTION: do captured blocks have a client/category already, or are they")
print("blank (truly uncategorized)? That determines how 'needs confirmation in")
print("the card' should look — confirm an existing guess, or assign from scratch.")
