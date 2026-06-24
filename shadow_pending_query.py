"""READ-ONLY. Does the proposed_inline query (what feeds the PENDING section)
actually include committed block 44867? Replicate the exact query from views.py."""
from datetime import date
from tracker.models import Block, User

DAY = date(2026,6,23)
terri = User.objects.filter(username='terri').first()

# Exact proposed_inline query from views.py ~4611
pi = Block.objects.filter(
    user=terri, day=DAY, classification_state='proposed',
    deleted_at__isnull=True,
).exclude(categorized_by__in=['manual', 'correction']).select_related('proposed_client')

print("="*72)
print(f"proposed_inline query for terri: {pi.count()} blocks")
print("="*72)
found_44867 = False
for b in pi:
    r = getattr(b,'proposed_reasoning','') or ''
    if 'second-pass' not in r and not b.proposed_client_id:
        continue
    if b.id == 44867: found_44867 = True
    print(f"  {b.id}: state={b.classification_state} '{(b.window_title or '')[:40]}' "
          f"proposed={b.proposed_client_id} by={b.categorized_by}")

print(f"\nIs committed block 44867 in the proposed_inline query? {found_44867}")
print(f"  (It should be FALSE — 44867 is committed, not proposed.)")

# 44867 current state
b = Block.objects.filter(id=44867).first()
print(f"\n44867 actual state: {b.classification_state} by={b.categorized_by} "
      f"client={b.client_id} proposed_client={b.proposed_client_id}")
print(f"  → If state=committed but it shows in pending UI, the frontend has")
print(f"    STALE data (committed after page load). Hard refresh fixes it.")
print(f"  → If proposed_inline query returns it, there's a real query bug.")
