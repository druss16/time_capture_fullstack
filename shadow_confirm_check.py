"""READ-ONLY. Find the 14m 'St. James Church - Write Checks' block and show
its CURRENT state — did the Confirm actually commit it? Where did it land?"""
from datetime import date
from tracker.models import Block, Client

DAY = date(2026, 6, 23)

# Find the St James Write Checks block(s)
blocks = Block.objects.filter(
    day=DAY,
    window_title__icontains='Write Checks',
    deleted_at__isnull=True,
).select_related('client', 'proposed_client')

print("="*72)
print(f"'Write Checks' blocks on {DAY}: {blocks.count()}")
print("="*72)
for b in blocks:
    print(f"\nblock {b.id} | user={b.user.username}")
    print(f"  title: {(b.window_title or '')[:60]}")
    print(f"  minutes: {b.minutes}")
    print(f"  classification_state: {b.classification_state}")
    print(f"  client: {b.client.name if b.client_id else None} (id={b.client_id})")
    print(f"  proposed_client: {b.proposed_client.name if b.proposed_client_id else None} (id={b.proposed_client_id})")
    print(f"  is_billable: {b.is_billable}")
    print(f"  categorized_by: {b.categorized_by}")
    print(f"  category: {getattr(b,'category',None)}")

# What does St James (find its id) have committed today?
print("\n" + "="*72)
sj = Client.objects.filter(name__icontains='James Church').first()
if sj:
    print(f"St James Church = id {sj.id}")
    committed = Block.objects.filter(
        day=DAY, client_id=sj.id, classification_state='committed',
        deleted_at__isnull=True,
    )
    total = sum(b.minutes or 0 for b in committed)
    print(f"Committed blocks for St James today: {committed.count()}, total {total}m")
    for b in committed:
        print(f"   {b.id}: {b.minutes}m  billable={b.is_billable}  '{(b.window_title or '')[:40]}'")
print("="*72)
print("DIAGNOSIS:")
print(" - If the 14m block now shows classification_state=committed, client=St James,")
print("   is_billable=True → it DID commit; the billable total math or refresh is the bug.")
print(" - If it's still proposed → the Confirm didn't write through (handler/endpoint bug).")
print(" - If is_billable=False despite committed → the recategorize set it non-billable.")
