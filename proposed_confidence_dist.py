"""
READ-ONLY. The 919 proposed+billable+client blocks — what's their confidence
and what signal backs them? This tells us where to draw the 'safe to bill as
proposed' vs 'must confirm first' line. We do NOT change anything.
"""
from datetime import date, timedelta
from tracker.models import Block
from collections import Counter

since = date(2026,6,23)-timedelta(days=14)
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state='proposed', is_billable=True, client_id__isnull=False)

conf_buckets = Counter()
signal_types = Counter()
weak_stickiness_only = 0
for b in qs:
    c = float(getattr(b,'proposed_confidence',0) or 0)
    bucket = ('0.90+' if c>=0.90 else '0.80-0.89' if c>=0.80 else
              '0.70-0.79' if c>=0.70 else '0.60-0.69' if c>=0.60 else '<0.60')
    conf_buckets[bucket]+=1
    sigs = getattr(b,'proposed_signals',None) or []
    cid = b.client_id
    attesting = [s for s in sigs if isinstance(s,dict) and (s.get('detail') or {}).get('client_id')==cid]
    types = {s.get('type') for s in attesting}
    for t in types: signal_types[t]+=1
    # weak = ONLY agent_current_client attests (the Mets pattern)
    if attesting and all(s.get('type')=='agent_current_client' for s in attesting):
        weak_stickiness_only += 1

print("="*70)
print(f"919-ish proposed+billable+client blocks — confidence distribution")
print("="*70)
for b in ['0.90+','0.80-0.89','0.70-0.79','0.60-0.69','<0.60']:
    print(f"  conf {b:10}: {conf_buckets[b]}")
print("-"*70)
print("Signal types backing the client attribution (top):")
for t,n in signal_types.most_common(12):
    print(f"  {t:32} {n}")
print("-"*70)
print(f"⚠️  attributed ONLY by weak agent stickiness (Mets-type, unsafe): {weak_stickiness_only}")
print("="*70)
print("Line-drawing: blocks backed by strong signals (file_path, qb_company,")
print("exact title, mail/cal) are probably-correct → safe to bill as proposed.")
print("Stickiness-only / fuzzy-only → should require confirmation before billing.")
print("="*70)
