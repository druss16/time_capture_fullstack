"""READ-ONLY. Why did 'All Around Auto Repair' get proposed to CNY Coin & Silver?
Inspect the block's signals/reasoning and check whether 'All Around Auto Repair'
exists as its own client (which would make CNY Coin the wrong guess)."""
from tracker.models import Block, Client, User

# The two All Around Auto Repair blocks from the screenshot (ids 44xxx range, 1m each)
# Find them by title for the user/day:
from datetime import date
u = User.objects.filter(username='wayne').first() or User.objects.filter(username='stephen').first()
print("user:", u.username if u else None)

blocks = Block.objects.filter(
    window_title__icontains='All Around Auto Repair',
    classification_state='proposed',
    deleted_at__isnull=True,
).select_related('proposed_client', 'client').order_by('-day')[:10]

print("="*72)
print(f"'All Around Auto Repair' proposed blocks: {blocks.count()}")
print("="*72)
for b in blocks:
    print(f"\nblock {b.id} | day={b.day} | user={b.user.username}")
    print(f"  title: {(b.window_title or '')[:70]}")
    print(f"  proposed_client: {b.proposed_client.name if b.proposed_client_id else None} (id={b.proposed_client_id})")
    print(f"  proposed_confidence: {getattr(b,'proposed_confidence',None)}")
    print(f"  proposed_reasoning: {(getattr(b,'proposed_reasoning','') or '')[:200]}")
    print(f"  current_client_id (agent): {getattr(b,'current_client_id',None)}")

# Is 'All Around Auto Repair' a real client?
print("\n" + "="*72)
print("Clients matching 'Auto Repair' or 'All Around':")
for c in Client.objects.filter(name__icontains='Auto Repair'):
    print(f"  id={c.id}  {c.name}  active={c.is_active}")
for c in Client.objects.filter(name__icontains='All Around'):
    print(f"  id={c.id}  {c.name}  active={c.is_active}")
print("\nClients matching 'CNY Coin' / 'Central Ny Coin':")
for c in Client.objects.filter(name__icontains='Coin'):
    print(f"  id={c.id}  {c.name}  active={c.is_active}  aliases={getattr(c,'aliases',None)}")
print("="*72)
