"""READ-ONLY. The real opportunity: pile blocks whose title contains a CLIENT
NAME the matcher missed. Match each uncategorized title against the full client
list. Require a STRONG match: the client's distinctive (non-generic) tokens all
appear in the title, OR the full client name is a substring. Show which client.
This is safe attribution — the name is literally present, not a guess."""
from datetime import date, timedelta
from tracker.models import Block, Client
import re

since = date(2026,6,23)-timedelta(days=14)
clients = list(Client.objects.filter(org_id=21, is_active=True))

def norm(s):
    s=(s or '').lower()
    s=re.sub(r'\bst\.?\s','saint ',s)
    s=s.replace("'","").replace("&"," and ")
    return re.sub(r'[^a-z0-9 ]',' ',s)

DOMAIN={'saint','church','catholic','parish','the','and','of','inc','llc','corp',
  'co','company','tax','cemetery','school','foundation','center','services','ministries'}

# Pre-norm clients with distinctive tokens
cdata=[]
for c in clients:
    n=norm(c.name)
    toks=[t for t in n.split() if len(t)>=3 and t not in DOMAIN]
    cdata.append((c.id,c.name,n,set(toks)))

qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True
    ).filter(minutes__gte=2)

strong=[]   # full name substring OR all distinctive tokens present
for b in qs:
    tn=norm(b.window_title or '')
    if not tn.strip(): continue
    ttoks=set(tn.split())
    best=None
    for cid,cname,cn,ctoks in cdata:
        # full normalized name appears in title
        if len(cn)>=6 and cn in tn:
            best=(cid,cname,'full-name'); break
        # all distinctive tokens present (and at least 1 exists)
        if ctoks and ctoks.issubset(ttoks):
            best=(cid,cname,'all-tokens'); break
    if best:
        strong.append((b.id,best[1],best[2],(b.window_title or '')[:44]))

print("="*74)
print(f"Pile blocks (no client) whose TITLE contains a client name: {len(strong)}")
print("="*74)
for bid,cname,how,t in strong[:45]:
    print(f"  {bid} → {cname[:26]:26} [{how}] | {t}")
print("="*74)
print(f"These are billable work the matcher MISSED. Safe to attribute — name is")
print(f"in the title. This is the real auto-categorize opportunity.")
print("="*74)
