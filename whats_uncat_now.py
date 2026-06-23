"""READ-ONLY. What's actually still uncategorized? Break the pile down by
WHY it's uncategorized so we know the right action for each slice."""
from datetime import date, timedelta
from tracker.models import Block
from collections import Counter

since = date(2026,6,23)-timedelta(days=14)
# "Uncategorized" = captured state OR no category, material (>=2min), in window
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'])

total=0; total_min=0
by_state=Counter(); by_signal=Counter()
no_client_no_cat=[]; has_proposed_client=[]; junk_titles=[]

JUNK_HINTS=('inbox','login','sign in','new tab','print preview','begin reconciliation',
  'reconciliation','past transactions','preview paycheck','print checks','preparer options',
  'this pc','quick access','recycle bin','document','untitled','explorer','- excel','- word')

for b in qs:
    mins = (b.minutes or 0)
    if mins < 2:  # material only
        continue
    total+=1; total_min+=mins
    by_state[b.classification_state]+=1
    t=(b.window_title or '').lower()
    has_cat = bool(b.category_hours)
    pcid = getattr(b,'proposed_client_id',None)
    if pcid:
        has_proposed_client.append(b.id)
    elif any(h in t for h in JUNK_HINTS):
        junk_titles.append((b.id,(b.window_title or '')[:40]))
    else:
        no_client_no_cat.append((b.id,(b.window_title or '')[:40]))

print("="*68)
print(f"UNCATEGORIZED PILE (material >=2min, 14d): {total} blocks, {total_min} min")
print("="*68)
print("By state:", dict(by_state))
print("-"*68)
print(f"A) Has a PROPOSED client (could auto-prefill/confirm): {len(has_proposed_client)}")
print(f"B) Junk/overhead titles (could auto-suppress/non-bill): {len(junk_titles)}")
print(f"C) No client, no junk match (genuinely needs signal):  {len(no_client_no_cat)}")
print("="*68)
print("Sample B (junk — candidates to auto-handle):")
for bid,t in junk_titles[:15]: print(f"  {bid} | {t}")
print("-"*68)
print("Sample C (real-looking, no signal):")
for bid,t in no_client_no_cat[:15]: print(f"  {bid} | {t}")
print("="*68)
