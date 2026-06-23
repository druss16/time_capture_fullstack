"""
Auto-commit Bucket 3: pile blocks with NO client AND classifier's best category
is non-billable. SAFE (can't mis-bill; non-billable is the safe direction).
Re-derives list at runtime. Excludes anything with a client hint as belt-and-suspenders.
SET DRY_RUN=False to apply.
"""
from datetime import date, timedelta
from tracker.models import Block
from django.utils import timezone

DRY_RUN = True   # <-- flip to False to apply

since = date(2026,6,23)-timedelta(days=14)
NONBILL={'personal/non-billable','idle','uncategorized'}
CLIENT_HINTS=('church','parish','franciscan','ascension','sacred heart','st mary',
    'st marys','reconciliation','1040','1120','990')  # extra caution

qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True
    ).filter(minutes__gte=2)

todo=[]
for b in qs:
    cat=(getattr(b,'proposed_category','') or '').lower()
    if cat not in NONBILL: continue
    t=(b.window_title or '').lower()
    if any(h in t for h in CLIENT_HINTS):   # skip anything client-ish, stays for review
        continue
    todo.append(b)

print("="*60)
print(f"Bucket 3 — no-client non-billable, no client hint: {len(todo)} blocks")
print(f"DRY_RUN={DRY_RUN}")
print("="*60)
if DRY_RUN:
    for b in todo[:30]:
        print(f"  WOULD commit nonbill: {b.id} | {(b.window_title or '')[:45]}")
    print(f"  ... ({len(todo)} total)")
else:
    n=0
    for b in todo:
        mins=b.minutes or 0
        b.category_hours={'Personal/Non-Billable': round(mins/60.0,4)}
        b.client=None; b.is_billable=False
        b.categorized_by='correction'; b.categorized_at=timezone.now()
        b.is_categorized=True; b.classification_state='committed'
        b.save(force_update=True); n+=1
    print(f"  Committed {n} blocks non-billable.")
    left=Block.objects.filter(org_id=21,deleted_at__isnull=True,start__date__gte=since,
        classification_state__in=['captured','proposed']).filter(minutes__gte=2).count()
    print(f"  Material pile remaining: {left}")
print("="*60)
