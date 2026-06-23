"""READ-ONLY. List the Mets blocks still mis-attributed to 439 (excluding the
one we just cleared, 44390). Confirms the batch target incl. the 80m block."""
from tracker.models import Block
mets = Block.objects.filter(org_id=21, window_title__icontains="Syracuse Mets",
    deleted_at__isnull=True, client_id=439).order_by('-start')
print("="*60)
print(f"Mets blocks STILL on client 439 (mis-billed): {mets.count()}")
total = 0
ids = []
for b in mets:
    h = sum((b.category_hours or {}).values()); total += h; ids.append(b.id)
    print(f"  id={b.id} {h*60:5.0f}m billable={b.is_billable} state={b.classification_state}")
print("="*60)
print(f"TOTAL still mis-billed: {total*60:.0f}m ({total:.2f}h)")
print(f"ID list for batch: {ids}")
print("="*60)
