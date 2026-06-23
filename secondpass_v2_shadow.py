"""
READ-ONLY SHADOW v2 — retuned tiers.
FIX 1 HIGH-name: restore church matches. Match when a client name-form appears
  contiguously, floor lowered to 8 but REQUIRE the form to contain a
  distinctive (non-generic) token so 'assumption'/'pauls'/'johns' qualify but
  bare 'church' never does.
FIX 2 HIGH-sametitle: exclude GENERIC/chrome titles (reconciliation, preview
  paycheck, quickbooks desktop, etc.) so we don't propagate junk attributions.
FIX 3 sandwich: kept, marked LOUD flag.
Writes nothing. Still asserts zero billing.
"""
from datetime import date, timedelta
from tracker.models import Block, Client
from collections import defaultdict, Counter
import re

since = date(2026,6,23)-timedelta(days=14)
def norm(s):
    s=(s or '').lower(); s=re.sub(r'\bst\.?\s','saint ',s)
    s=s.replace("'","").replace("&"," and "); s=re.sub(r'[^a-z0-9 ]',' ',s)
    return re.sub(r'\s+',' ',s).strip()

GENERIC={'saint','church','catholic','parish','cemetery','school','inc','llc',
  'corp','co','company','services','foundation','center','ministries','the','and','of'}

# FIX 1: name-forms that contain >=1 distinctive token; floor 8
cforms=[]
for c in Client.objects.filter(org_id=21, is_active=True):
    n=norm(c.name)
    if len(n)<8: continue
    distinct=[t for t in n.split() if t not in GENERIC and len(t)>=4]
    if not distinct: continue   # name is all-generic → can't safely substring-match
    forms={n}
    w=n.split()
    while w and w[-1] in GENERIC: w=w[:-1]
    trimmed=' '.join(w)
    if len(trimmed)>=8 and any(t in distinct for t in w): forms.add(trimmed)
    cforms.append((c.id,c.name,forms,set(distinct)))

# committed anchors
committed=list(Block.objects.filter(org_id=21,deleted_at__isnull=True,start__date__gte=since,
    classification_state='committed',client_id__isnull=False
    ).values('id','user_id','client_id','window_title','start','end'))
title2client=defaultdict(set)
for c in committed:
    t=(c['window_title'] or '').strip().lower()
    if t: title2client[t].add(c['client_id'])
anchors=defaultdict(list)
for c in committed: anchors[c['user_id']].append(c)
for u in anchors: anchors[u].sort(key=lambda x:x['start'])

# FIX 2: generic titles that must NOT same-title-match
GENERIC_TITLE=('select reconciliation','begin reconciliation','reconciliation report',
  'preview paycheck','print checks','print preview','past transactions','preparer options',
  'quickbooks accountant desktop','(primary) quickbooks','(secondary) quickbooks',
  'special paycheck','missing client info','account spreadsheet','select reconciliation report')

JUNK=('idle/uncategorized','calculator','crossword','breitbart','milb.com','overall standings',
  'gwen stefani','google search','windows shell experience','timetracker','support.taxwise.com',
  '/mfa.aspx','sfs support','solution center','\\\\192.168','new missed call')
JUNK_WORKHINT=('.pdf','statement','reconcil','return','1040','1120','990','fica','payroll',
  'invoice','church','parish','cemetery')

pile=Block.objects.filter(org_id=21,deleted_at__isnull=True,start__date__gte=since,
    classification_state__in=['captured','proposed'],client_id__isnull=True).filter(minutes__gte=2)

tiers=Counter(); samples=defaultdict(list); would_bill=0
for b in pile:
    raw=(b.window_title or ''); t=norm(raw); tl=raw.lower(); tset=set(t.split())
    tier=None; guess=None
    # HIGH-name (contiguous form present AND its distinctive token in title)
    for cid,cname,forms,distinct in cforms:
        if any(len(f)>=8 and f in t for f in forms) and (distinct & tset):
            guess=(cid,cname); tier='HIGH-name'; break
    # HIGH-sametitle (skip generic titles)
    if not tier and not any(g in tl for g in GENERIC_TITLE):
        cids=title2client.get(raw.strip().lower())
        if cids and len(cids)==1:
            guess=(list(cids)[0],'(same-title)'); tier='HIGH-sametitle'
    # COMMIT_NB strict junk
    if not tier and any(j in tl for j in JUNK) and not any(w in tl for w in JUNK_WORKHINT):
        tier='COMMIT_NB'
    # MEDIUM sandwich
    if not tier:
        anc=anchors.get(b.user_id,[])
        bef=[c for c in anc if c['end'] and c['end']<=b.start and (b.start-c['end'])<=timedelta(minutes=30)]
        aft=[c for c in anc if c['start']>=b.start and (c['start']-b.start)<=timedelta(minutes=30)]
        if bef and aft and bef[-1]['client_id']==aft[0]['client_id']:
            guess=(bef[-1]['client_id'],'(sandwich)'); tier='MEDIUM-sandwich'
    if not tier: tier='LOW' if t else 'NONE'
    tiers[tier]+=1
    if len(samples[tier])<10: samples[tier].append((b.id, guess[1] if guess else '-', raw[:40]))

print("="*72)
print(f"SECOND-PASS v2 — pile {pile.count()}")
print("="*72)
for tier in ['HIGH-name','HIGH-sametitle','MEDIUM-sandwich','COMMIT_NB','LOW','NONE']:
    print(f"\n{tier}: {tiers[tier]}")
    for bid,g,t in samples[tier]:
        print(f"    {bid} → {g[:22]:22} | {t}")
print("="*72)
print(f"Would bill from a guess: {would_bill} (MUST be 0)")
print("="*72)
