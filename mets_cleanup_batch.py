"""
Scoped batch cleanup of the 11 remaining mis-billed Mets blocks.
Uses the SAME logic validated on block 44390: clear client to None,
mark Personal/Non-Billable, preserve duration, commit so classifier won't
re-attribute. Explicit ID list — NO blanket update. (Rule-17 discipline.)
"""
from tracker.models import Block
from django.utils import timezone

IDS = [44481, 44467, 44465, 44462, 44460, 44458, 44457, 44454, 44455, 44440, 44371]

print("="*60)
print(f"Clearing {len(IDS)} mis-billed Mets blocks → No Client / Non-Billable")
print("="*60)
cleared = 0
errors = 0
total_min = 0
for bid in IDS:
    try:
        b = Block.objects.get(id=bid, org_id=21, deleted_at__isnull=True)
        # Safety: only touch blocks still on 439 (don't clobber if already moved)
        if b.client_id != 439:
            print(f"  {bid}: SKIP (already client={b.client_id}, not 439)")
            continue
        existing_total = sum((b.category_hours or {}).values())
        if existing_total <= 0:
            existing_total = (b.end - b.start).total_seconds()/3600 if b.end and b.start else 0
        b.category_hours = {'Personal/Non-Billable': round(existing_total, 4)}
        b.client = None
        b.is_billable = False
        b.categorized_by = 'correction'
        b.categorized_at = timezone.now()
        b.is_categorized = True
        b.classification_state = 'committed'
        b.save(force_update=True)
        cleared += 1
        total_min += existing_total * 60
        print(f"  {bid}: ✓ cleared ({existing_total*60:.0f}m)")
    except Block.DoesNotExist:
        print(f"  {bid}: NOT FOUND"); errors += 1
    except Exception as e:
        print(f"  {bid}: ERROR {e}"); errors += 1
print("="*60)
print(f"Cleared {cleared}/{len(IDS)} blocks, {total_min:.0f}m removed from client 439")
print(f"Errors: {errors}")
print("="*60)

# Verify nothing left on 439
remaining = Block.objects.filter(org_id=21, window_title__icontains="Syracuse Mets",
    deleted_at__isnull=True, client_id=439).count()
print(f"Mets blocks STILL on 439 after cleanup: {remaining}  (want 0)")
print("="*60)
