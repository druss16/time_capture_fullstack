"""READ-ONLY. Measure 3 recovery mechanisms on the uncategorized pile:
 1. SAME-TITLE: pile block's exact title matches a COMMITTED block w/ a client → safe
 2. SANDWICH: pile block sits between two committed blocks (same user) with the
    SAME client, within 30 min → temporal guess (flag, don't auto-bill)
 3. OBVIOUS NON-BILLABLE: no client + proposed_category non-billable → safe commit
No writes."""
from datetime import date, timedelta
from tracker.models import Block
from collections import defaultdict

since = date(2026,6,23)-timedelta(days=14)

# Committed blocks with a client (the "known" anchors)
committed = list(Block.objects.filter(org_id=21, deleted_at__isnull=True,
    start__date__gte=since, classification_state='committed', client_id__isnull=False
    ).values('id','user_id','client_id','window_title','start','end'))

# Pile = uncategorized, no client, material
pile = list(Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True
    ).filter(minutes__gte=2).values('id','user_id','window_title','start','proposed_category'))

# 1. Same-title map (committed title -> client)
title_to_client = {}
for c in committed:
    t=(c['window_title'] or '').strip().lower()
    if t: title_to_client.setdefault(t, set()).add(c['client_id'])
same_title=[]
for p in pile:
    t=(p['window_title'] or '').strip().lower()
    cids = title_to_client.get(t)
    if cids and len(cids)==1:  # unambiguous: title only ever maps to ONE client
        same_title.append((p['id'], list(cids)[0], (p['window_title'] or '')[:40]))

# 3. Obvious non-billable
NONBILL_CATS={'personal/non-billable','idle','uncategorized'}
obvious_nb=[p['id'] for p in pile if (p['proposed_category'] or '').lower() in NONBILL_CATS]

# 2. Sandwich (cheap approx): committed-before and committed-after same client within 30m
by_user=defaultdict(list)
for c in committed: by_user[c['user_id']].append(c)
for u in by_user: by_user[u].sort(key=lambda x:x['start'])
sandwich=[]
for p in pile:
    anchors=by_user.get(p['user_id'],[])
    before=[c for c in anchors if c['end'] and c['end']<=p['start'] and (p['start']-c['end'])<=timedelta(minutes=30)]
    after=[c for c in anchors if c['start']>=p['start'] and (c['start']-p['start'])<=timedelta(minutes=30)]
    if before and after:
        bc=before[-1]['client_id']; ac=after[0]['client_id']
        if bc==ac:
            sandwich.append((p['id'], bc, (p['window_title'] or '')[:36]))

print("="*68)
print(f"PILE: {len(pile)} blocks")
print("="*68)
print(f"1. SAME-TITLE as committed (unambiguous→1 client) [SAFE]: {len(same_title)}")
for bid,cid,t in same_title[:12]: print(f"     {bid} → client {cid} | {t}")
print(f"\n3. OBVIOUS non-billable (no client+nonbill cat) [SAFE]: {len(obvious_nb)}")
print(f"\n2. SANDWICH (between same-client committed, 30m) [FLAG ONLY]: {len(sandwich)}")
for bid,cid,t in sandwich[:12]: print(f"     {bid} → guess client {cid} | {t}")
print("="*68)
