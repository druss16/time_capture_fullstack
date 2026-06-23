"""
Final cleanup: clear the 11 confirmed stickiness-only mis-billed blocks.
EXCLUDES 41190 (legit org_rule attribution). Reclassifies each through the
LIVE pipeline + applies — the guard clears the bad client, same proven path.
Explicit ID list, only touches blocks whose reclassify says client should clear.
"""
from tracker.models import Block, Organization
from tracker.services.classification_service import ClassificationService

IDS = [44728, 44669, 44667, 44668, 44620, 44476, 44475, 44474, 44468, 44334, 44243]
org = Organization.objects.get(id=21)

print("="*64)
print(f"Clearing {len(IDS)} stickiness-only mis-billed blocks (excl. 41190 legit)")
print("="*64)
cleared = 0; skipped = 0
for bid in IDS:
    try:
        b = Block.objects.get(id=bid, org_id=21, deleted_at__isnull=True)
        svc = ClassificationService(org=org, user=b.user)
        d = svc.classify(b, skip_ai=True)
        if d.client_id is None or not d.is_billable:
            svc.apply(b, d, source='classifier')
            b.refresh_from_db()
            print(f"  {bid}: ✓ cleared → client={b.client_id} billable={b.is_billable}")
            cleared += 1
        else:
            print(f"  {bid}: SKIP — reclassify still attributes client={d.client_id} (not stickiness-only)")
            skipped += 1
    except Exception as e:
        print(f"  {bid}: ERROR {e}")
print("="*64)
print(f"Cleared {cleared}, skipped {skipped}")
print("="*64)
