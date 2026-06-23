"""
Clear the safe personal/idle junk → committed non-billable. Same filter as the
shadow (clear personal/idle pattern + NO client hint). Re-derives the list at
run time (not a hardcoded ID list) so it can only ever touch matching junk.
"""
from datetime import date, timedelta
from tracker.models import Block
from django.utils import timezone

since = date(2026,6,23)-timedelta(days=14)
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True)

SAFE_JUNK = ('idle/uncategorized','calculator','crossword','breitbart','cnn.com',
    'foxnews','espn','youtube','netflix','facebook','twitter','reddit','instagram',
    'amazon.com','ebay','weather','spotify','new tab','untitled','sign in','log in','login')
CLIENT_HINTS = ('church','parish','reconciliation','tax','corp','inc','llc','1040',
    '1120','990','payroll','reimbursement','summary','client','invoice','return',
    'financ','budget','quickbooks','.xlsx','franciscan')

cleared=0; total_min=0
for b in qs:
    if (b.minutes or 0) < 2: continue
    t=(b.window_title or '').lower()
    if not (any(h in t for h in SAFE_JUNK) and not any(c in t for c in CLIENT_HINTS)):
        continue
    # Safety: must still have no client
    if b.client_id is not None:
        continue
    mins = b.minutes or 0
    b.category_hours = {'Personal/Non-Billable': round(mins/60.0, 4)}
    b.client = None
    b.is_billable = False
    b.categorized_by = 'correction'
    b.categorized_at = timezone.now()
    b.is_categorized = True
    b.classification_state = 'committed'
    b.save(force_update=True)
    cleared+=1; total_min+=mins

print("="*60)
print(f"Cleared {cleared} safe-junk blocks → non-billable ({total_min} min)")
print("="*60)
# verify what's left in pile
left = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed']).filter(minutes__gte=2).count()
print(f"Material pile remaining (>=2min): {left} blocks")
print("="*60)
