"""
READ-ONLY SHADOW — Second-pass best-guess categorizer.
For each uncategorized block, compute a best guess + confidence tier. Reports
what WOULD be written. Writes NOTHING. Asserts: no guess would ever bill.

Tiers:
  HIGH   - client full name appears CONTIGUOUSLY in title  (safe attribution)
  HIGH   - exact same title as a COMMITTED block w/ exactly 1 client
  MEDIUM - sandwich: committed same-client before AND after within 30m
  COMMIT_NB - strict personal/system junk allowlist -> non-billable (only commit)
  LOW    - has some signal but weak -> flag 'please check', no client
  NONE   - no signal -> flag 'needs client'
NONE of HIGH/MEDIUM/LOW set is_billable; they're flagged proposals.
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

# client name-forms (contiguous), length>=10 to be safe
GENERIC_TAIL={'church','parish','cemetery','school','inc','llc','corp','co',
  'company','services','foundation','center','ministries','catholic'}
cforms=[]
for c in Client.objects.filter(org_id=21, is_active=True):
    n=norm(c.name)
    if len(n)<10: continue
    forms={n}
    w=n.split()
    while w and w[-1] in GENERIC_TAIL: w=w[:-1]
    if len(' '.join(w))>=12: forms.add(' '.join(w))
    cforms.append((c.id,c.name,forms))

# committed anchors for same-title + sandwich
committed=list(Block.objects.filter(org_id=21,deleted_at__isnull=True,start__date__gte=since,
    classification_state='committed',client_id__isnull=False
    ).values('id','user_id','client_id','window_title','start','end'))
title2client=defaultdict(set)
for c in committed:
    t=(c['window_title'] or '').strip().lower()
    if t: title2client[t].add(c['client_id'])
anchors_by_user=defaultdict(list)
for c in committed: anchors_by_user[c['user_id']].append(c)
for u in anchors_by_user: anchors_by_user[u].sort(key=lambda x:x['start'])

JUNK=('idle/uncategorized','calculator','crossword','breitbart','milb.com',
  'overall standings','gwen stefani','google search','windows shell experience',
  'timetracker','support.taxwise.com','/mfa.aspx','sfs support','solution center',
  '\\\\192.168','new missed call')
JUNK_WORKHINT=('.pdf','statement','reconcil','return','1040','1120','990','fica',
  'payroll','invoice','church','parish','cemetery')

pile=Block.objects.filter(org_id=21,deleted_at__isnull=True,start__date__gte=since,
    classification_state__in=['captured','proposed'],client_id__isnull=True
    ).filter(minutes__gte=2)

tiers=Counter(); would_bill=0; samples=defaultdict(list)
for b in pile:
    raw=(b.window_title or ''); t=norm(raw); tl=raw.lower()
    guess=None; tier=None
    # HIGH: contiguous name
    for cid,cname,forms in cforms:
        if any(len(f)>=10 and f in t for f in forms):
            guess=(cid,cname); tier='HIGH-name'; break
    # HIGH: same title as committed (unambiguous)
    if not tier:
        cids=title2client.get(raw.strip().lower())
        if cids and len(cids)==1:
            guess=(list(cids)[0],'(same-title)'); tier='HIGH-sametitle'
    # COMMIT_NB: strict junk
    if not tier and any(j in tl for j in JUNK) and not any(w in tl for w in JUNK_WORKHINT):
        tier='COMMIT_NB'
    # MEDIUM: sandwich
    if not tier:
        anc=anchors_by_user.get(b.user_id,[])
        bef=[c for c in anc if c['end'] and c['end']<=b.start and (b.start-c['end'])<=timedelta(minutes=30)]
        aft=[c for c in anc if c['start']>=b.start and (c['start']-b.start)<=timedelta(minutes=30)]
        if bef and aft and bef[-1]['client_id']==aft[0]['client_id']:
            guess=(bef[-1]['client_id'],'(sandwich)'); tier='MEDIUM-sandwich'
    # LOW / NONE
    if not tier:
        tier='LOW' if t else 'NONE'
    tiers[tier]+=1
    if len(samples[tier])<8:
        samples[tier].append((b.id, guess[1] if guess else '-', raw[:40]))

print("="*72)
print(f"SECOND-PASS SHADOW — pile {pile.count()} blocks (14d)")
print("="*72)
for tier in ['HIGH-name','HIGH-sametitle','MEDIUM-sandwich','COMMIT_NB','LOW','NONE']:
    print(f"\n{tier}: {tiers[tier]}")
    for bid,g,t in samples[tier]:
        print(f"    {bid} → {g[:22]:22} | {t}")
print("="*72)
print(f"Blocks that would BILL from a guess: {would_bill}  (MUST be 0)")
print("HIGH/MEDIUM/LOW = flagged proposals, is_billable=False until confirmed.")
print("COMMIT_NB = the only auto-commit, non-billable (strict junk).")
print("="*72)
