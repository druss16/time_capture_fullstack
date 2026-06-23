"""READ-ONLY v2. Same idea, but MUCH stricter to kill the 'New School→new',
'St James→headline' false matches (the Mets pattern). Rules:
 - require >=2 distinctive tokens present, OR full client-name substring, OR
   one LONG (>=6 char) distinctive token that's not a common English word.
 - reject single short/common-token matches outright."""
from datetime import date, timedelta
from tracker.models import Block, Client
import re

since = date(2026,6,23)-timedelta(days=14)
clients = list(Client.objects.filter(org_id=21, is_active=True))

def norm(s):
    s=(s or '').lower(); s=re.sub(r'\bst\.?\s','saint ',s)
    s=s.replace("'","").replace("&"," and ")
    return re.sub(r'[^a-z0-9 ]',' ',s)

DOMAIN={'saint','church','catholic','parish','the','and','of','inc','llc','corp',
  'co','company','tax','cemetery','school','foundation','center','services','ministries'}
# Common English words that must NEVER be the sole basis of a match
COMMON={'new','old','first','second','main','south','north','east','west','city',
  'town','county','american','national','general','home','park','grand','great',
  'mary','marys','james','john','johns','paul','pauls','james','ann','anns'}  # bare given-names too weak alone

cdata=[]
for c in clients:
    n=norm(c.name)
    toks=[t for t in n.split() if len(t)>=3 and t not in DOMAIN]
    cdata.append((c.id,c.name,n,toks))

qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True
    ).filter(minutes__gte=2)

safe=[]; rejected=[]
for b in qs:
    tn=norm(b.window_title or '')
    if not tn.strip(): continue
    ttoks=set(tn.split())
    match=None
    for cid,cname,cn,toks in cdata:
        if len(cn)>=10 and cn in tn:   # full name substring (long) = rock solid
            match=(cid,cname,'FULL-NAME'); break
        present=[t for t in toks if t in ttoks]
        distinctive_present=[t for t in present if t not in COMMON]
        # need >=2 present AND at least one non-common, OR one long(>=7) non-common token
        if len(present)>=2 and distinctive_present:
            match=(cid,cname,f'{len(present)}tok'); break
        if any(len(t)>=7 and t not in COMMON for t in present):
            match=(cid,cname,'long-tok'); break
    if match:
        safe.append((b.id,match[1],match[2],(b.window_title or '')[:42]))
    else:
        # log titles that the loose version would have matched but we now reject
        pass

print("="*74)
print(f"STRICT v2 — safe client-in-title matches: {len(safe)}")
print("="*74)
for bid,cname,how,t in safe[:50]:
    print(f"  {bid} → {cname[:24]:24} [{how:9}] | {t}")
print("="*74)
print("Check: NO 'New School→travel/game', NO 'St James→headline'. Only real")
print("church/cemetery/client work with the name actually present.")
print("="*74)
