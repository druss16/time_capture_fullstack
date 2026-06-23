"""
READ-ONLY SHADOW. Show exactly which existing uncategorized overhead blocks the
cleanup WOULD reclassify to committed non-billable. Confirm the set matches the
78 we expect and nothing billable is in it. Writes NOTHING.
"""
from datetime import date, timedelta
from tracker.models import Block

ORG, SINCE = 21, date(2026,6,22) - timedelta(days=7)

AUTO_TITLE = ('inbox','new tab','sign in','sign-in','log in','login',
              'enter your phone','creative cloud desktop','payroll subscription')
AUTO_APPS = ('olk',)

qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True, start__date__gte=SINCE,
                          is_categorized=False).exclude(classification_state="suppressed")

would_change, risky = [], []
tmin = 0
for b in qs:
    m = b.minutes or 0
    if m < 2: continue
    t = (b.window_title or "").lower()
    a = (b.app_name or "").lower()
    if not (any(s in t for s in AUTO_TITLE) or a in AUTO_APPS):
        continue
    would_change.append(b); tmin += m
    # safety: anything with a client, or correspondence-looking, is RISKY
    if b.client_id or "re:" in t or "fw:" in t or "review" in t:
        risky.append(b)

print("="*78)
print(f"CLEANUP SHADOW — blocks that WOULD become committed non-billable:")
print(f"  count: {len(would_change)}   total: {tmin//60}h{tmin%60}m")
print(f"  RISKY (client set or correspondence-looking): {len(risky)}")
print("="*78)
print("Block IDs (the exact scoped set the cleanup would touch):")
ids = [b.id for b in would_change]
print(ids)
print("="*78)
if risky:
    print("⚠️ RISKY — DO NOT auto-commit these, inspect first:")
    for b in risky:
        print(f"  {b.id} | client={b.client_id} | {(b.window_title or '')[:50]}")
else:
    print("✓ No risky blocks. Set is clean — safe to reclassify this exact ID list.")
print("="*78)
print("Current state breakdown of the set (sanity):")
from collections import Counter
print("  ", dict(Counter(b.classification_state for b in would_change)))
print("  ", dict(Counter((b.is_billable, b.is_categorized) for b in would_change)))
print("="*78)
