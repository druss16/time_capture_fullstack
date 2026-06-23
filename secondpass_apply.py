"""
Second-pass categorizer — APPLY (DRY_RUN default).
Auto-commit non-billable: COMMIT_NB junk + affirmatively-personal LOW.
Flagged proposals (proposed, is_billable=False, NO commit):
  HIGH-name / HIGH-sametitle (confident), sandwich (please-check),
  work-like LOW (needs-client, no proposed client).
NOTHING auto-commits to a client (sibling-entity ambiguity).
Respects manual/correction blocks (never overwrites a human decision).
"""
from datetime import date, timedelta
from tracker.models import Block, Client
from collections import defaultdict, Counter
from django.utils import timezone
import re

DRY_RUN = True   # flip to False to write

since = date(2026,6,23)-timedelta(days=14)
def norm(s):
    s=(s or '').lower(); s=re.sub(r'\bst\.?\s','saint ',s)
    s=s.replace("'","").replace("&"," and "); s=re.sub(r'[^a-z0-9 ]',' ',s)
    return re.sub(r'\s+',' ',s).strip()
GENERIC={'saint','church','catholic','parish','cemetery','school','inc','llc','corp','co',
  'company','services','foundation','center','ministries','the','and','of'}

cforms=[]
for c in Client.objects.filter(org_id=21, is_active=True):
    n=norm(c.name)
    if len(n)<8: continue
    distinct=[t for t in n.split() if t not in GENERIC and len(t)>=4]
    if not distinct: continue
    forms={n}; w=n.split()
    while w and w[-1] in GENERIC: w=w[:-1]
    if len(' '.join(w))>=8 and any(t in distinct for t in w): forms.add(' '.join(w))
    cforms.append((c.id,c.name,forms,set(distinct)))

committed=list(Block.objects.filter(org_id=21,deleted_at__isnull=True,start__date__gte=since,
    classification_state='committed',client_id__isnull=False).values('window_title','client_id'))
title2client=defaultdict(set)
for c in committed:
    t=(c['window_title'] or '').strip().lower()
    if t: title2client[t].add(c['client_id'])

GENERIC_TITLE=('select reconciliation','begin reconciliation','reconciliation report',
  'preview paycheck','print checks','print preview','past transactions','preparer options',
  'quickbooks accountant desktop','(primary) quickbooks','(secondary) quickbooks',
  'special paycheck','missing client info','account spreadsheet','enter memorized','save print output')
JUNK=('idle/uncategorized','calculator','crossword','breitbart','milb.com','overall standings',
  'gwen stefani','google search','windows shell experience','timetracker','support.taxwise.com',
  '/mfa.aspx','sfs support','solution center','\\\\192.168','new missed call')
PERSONAL_LOW=('las vegas','espn','youtube','netflix','facebook','twitter','reddit','instagram',
  'weather','spotify','amazon.com','ebay','bing travel','flights from','train ticket','bus and train',
  'birthday parties','big don','sky city','maverik','custom portal','register','monkey go happy')
WORKHINT=('.pdf','.xlsx','statement','reconcil','return','1040','1120','990','fica','payroll',
  'invoice','church','parish','cemetery','reimbursement','tax','client','deposit','bank','escrow')

NONBILL_CAT='Personal/Non-Billable'
pile=Block.objects.filter(org_id=21,deleted_at__isnull=True,start__date__gte=since,
    classification_state__in=['captured','proposed'],client_id__isnull=True).filter(minutes__gte=2)

actions=Counter()
def classify(b):
    raw=(b.window_title or ''); t=norm(raw); tl=raw.lower(); tset=set(t.split())
    # commit junk
    if any(j in tl for j in JUNK) and not any(w in tl for w in WORKHINT):
        return ('COMMIT_NB',None,0.0)
    # HIGH-name proposal
    for cid,cname,forms,distinct in cforms:
        if any(len(f)>=8 and f in t for f in forms) and (distinct & tset):
            return ('PROP_HIGH',cid,0.85)
    # HIGH-sametitle (non-generic)
    if not any(g in tl for g in GENERIC_TITLE):
        cids=title2client.get(raw.strip().lower())
        if cids and len(cids)==1: return ('PROP_HIGH',list(cids)[0],0.85)
    # affirmatively personal LOW → commit nonbill
    if any(p in tl for p in PERSONAL_LOW) and not any(w in tl for w in WORKHINT):
        return ('COMMIT_NB',None,0.0)
    # work-like → needs-client flag
    if any(w in tl for w in WORKHINT):
        return ('PROP_NEEDS',None,0.30)
    if not t.strip():
        return ('NONE',None,0.0)
    return ('PROP_NEEDS',None,0.20)

samples=defaultdict(list)
for b in pile:
    act,cid,conf=classify(b)
    actions[act]+=1
    if len(samples[act])<6: samples[act].append((b.id,cid,(b.window_title or '')[:38]))
    if not DRY_RUN:
        if b.categorized_by in ('manual','correction'): continue
        if act=='COMMIT_NB':
            mins=b.minutes or 0
            b.category_hours={NONBILL_CAT:round(mins/60.0,4)}; b.client=None; b.is_billable=False
            b.categorized_by='correction'; b.categorized_at=timezone.now()
            b.is_categorized=True; b.classification_state='committed'; b.save(force_update=True)
        elif act in ('PROP_HIGH','PROP_NEEDS'):
            b.proposed_client_id=cid; b.proposed_confidence=conf
            b.proposed_reasoning=('second-pass: name in title' if act=='PROP_HIGH' else 'second-pass: needs client')
            b.is_billable=False; b.classification_state='proposed'; b.save(force_update=True)

print("="*64)
print(f"SECOND-PASS APPLY  DRY_RUN={DRY_RUN}  pile={pile.count()}")
print("="*64)
for a in ['COMMIT_NB','PROP_HIGH','PROP_NEEDS','NONE']:
    print(f"\n{a}: {actions[a]}")
    for bid,cid,t in samples[a]:
        print(f"    {bid} → client={cid} | {t}")
print("="*64)
print("COMMIT_NB → committed non-billable. PROP_* → proposed+flagged, is_billable=False.")
print("No client guess auto-commits. Flip DRY_RUN=False to write.")
print("="*64)
