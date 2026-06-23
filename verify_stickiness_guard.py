"""
READ-ONLY. The 12 stickiness-only billing blocks — are they OLD (pre-fix) or
would the now-live guard still let them through? Re-classify each and check.
If all 12 are pre-fix and the guard now clears them, the forward-looking work
is DONE — we just clean up these 12 existing ones.
"""
from datetime import date, timedelta
from tracker.models import Block, Organization
from tracker.services.classification_service import ClassificationService

since = date(2026,6,23)-timedelta(days=14)
org = Organization.objects.get(id=21)
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state='proposed', is_billable=True, client_id__isnull=False)

stickiness_only = []
for b in qs:
    sigs = getattr(b,'proposed_signals',None) or []
    cid = b.client_id
    attesting = [s for s in sigs if isinstance(s,dict) and (s.get('detail') or {}).get('client_id')==cid]
    if attesting and all(s.get('type')=='agent_current_client' for s in attesting):
        stickiness_only.append(b)

print("="*70)
print(f"Stickiness-only billing blocks: {len(stickiness_only)}")
print("Re-classifying each with the LIVE guard to see if it now clears them:")
print("-"*70)
still_bills = []
for b in stickiness_only:
    svc = ClassificationService(org=org, user=b.user)
    d = svc.classify(b, skip_ai=True)
    status = "CLEARED ✓" if (d.client_id is None or not d.is_billable) else f"STILL BILLS 439? client={d.client_id}"
    if not (d.client_id is None or not d.is_billable):
        still_bills.append(b.id)
    print(f"  {b.id} | client={b.client_id} | reclassify→ {status} | {(b.window_title or '')[:35]}")
print("="*70)
if not still_bills:
    print("✓ Guard CLEARS all of them on reclassify. Forward-looking fix is DONE.")
    print(f"  Just clean up these {len(stickiness_only)} existing blocks (scoped batch).")
    print(f"  ID list: {[b.id for b in stickiness_only]}")
else:
    print(f"✗ {len(still_bills)} still bill after guard: {still_bills}")
    print("  Guard needs widening for these cases.")
print("="*70)
