"""
SAFE auto-non-billable: ONLY blocks affirmatively matching a personal/system/
junk pattern. Does NOT trust the classifier's 'non-billable' default (that's
just matcher-failure and sweeps up real billable work). Affirmative-match only.
Hard EXCLUDE anything document/statement/return/email-about-person/payroll.
DRY_RUN=True by default.
"""
from datetime import date, timedelta
from tracker.models import Block
from django.utils import timezone

DRY_RUN = True

since = date(2026,6,23)-timedelta(days=14)

# Affirmative junk patterns — personal browsing, system chrome, idle.
JUNK = (
    'idle/uncategorized','calculator','crossword','breitbart','cnn.com','foxnews',
    'espn','milb.com','overall standings','youtube','netflix','facebook','twitter',
    'reddit','instagram','weather','spotify','gwen stefani','google search',
    'new tab','untitled','windows shell experience','timetracker',
    'support.taxwise.com','/mfa.aspx','sfs support','solution center',
    'new missed call','goodbye with',  # news headline fragment seen in pile
    '\\\\192.168',  # scanner network shares
    'quickbooks accountant desktop plus 2024',  # bare QB chrome, no company file
)
# If ANY of these appear, it is likely REAL WORK — never auto-commit.
WORK_HINTS = (
    '.pdf','.xlsx','statement','reconcil','return','1040','1120','990','fica',
    'payroll','reclass','invoice','tax return','church','parish','school','llc',
    'inc','corp','client','message (html)','re:','fw:','draft','financ','budget',
    'taberg','sdif','americu','blattner','lerch','nursery',  # specific client-ish tokens seen
)

qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True
    ).filter(minutes__gte=2)

todo=[]; skipped_worklike=[]
for b in qs:
    t=(b.window_title or '').lower()
    if not t.strip():   # blank title — leave for review, could be anything
        continue
    if any(w in t for w in WORK_HINTS):
        skipped_worklike.append((b.id,(b.window_title or '')[:40]))
        continue
    if any(j in t for j in JUNK):
        todo.append(b)

print("="*62)
print(f"STRICT junk (affirmative match, work-hints excluded): {len(todo)}")
print(f"DRY_RUN={DRY_RUN}")
print("="*62)
for b in todo[:40]:
    print(f"  commit nonbill: {b.id} | {(b.window_title or '')[:46]}")
print("-"*62)
print(f"Excluded as work-like (STAY for review): {len(skipped_worklike)} — sample:")
for bid,t in skipped_worklike[:12]:
    print(f"  KEEP: {bid} | {t}")
print("="*62)
if not DRY_RUN:
    n=0
    for b in todo:
        mins=b.minutes or 0
        b.category_hours={'Personal/Non-Billable': round(mins/60.0,4)}
        b.client=None; b.is_billable=False
        b.categorized_by='correction'; b.categorized_at=timezone.now()
        b.is_categorized=True; b.classification_state='committed'
        b.save(force_update=True); n+=1
    print(f"Committed {n} junk blocks non-billable.")
