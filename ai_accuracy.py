"""
READ-ONLY. AI suggestion accuracy by confidence band, org 21, last 14 days.

Ground truth = blocks a HUMAN confirmed/changed (categorized_by='manual' or
'correction', or state_changed_by a real user). For those we KNOW the right
answer, so we can measure: did proposed_client match the final client?

Outputs a table → tells us the safe auto-apply threshold.
"""
from datetime import date, timedelta
from collections import defaultdict
from tracker.models import Block

ORG, SINCE = 21, date(2026,6,22) - timedelta(days=14)

qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True,
                          start__date__gte=SINCE).exclude(classification_state="suppressed")

# Bands
BANDS = [(0.90,1.01,"≥0.90"),(0.80,0.90,"0.80-0.90"),(0.65,0.80,"0.65-0.80"),
         (0.50,0.65,"0.50-0.65"),(0.0,0.50,"<0.50")]
def band(c):
    for lo,hi,lbl in BANDS:
        if lo <= c < hi: return lbl
    return "?"

# A block is "human-verified" if a person set/changed its category.
HUMAN_SOURCES = {"manual","correction","user"}
def is_human_verified(b):
    cb = (b.categorized_by or "").lower()
    scb = (b.state_changed_by or "").lower() if hasattr(b,'state_changed_by') else ""
    return cb in HUMAN_SOURCES or scb in HUMAN_SOURCES or b.classification_state == "committed"

stats = defaultdict(lambda: {"n":0,"client_match":0,"has_prop_client":0,
                             "total":0,"verified":0})

all_by_band = defaultdict(int)
for b in qs:
    c = b.proposed_confidence
    if c is None:
        continue
    lbl = band(c)
    all_by_band[lbl] += 1
    if not is_human_verified(b):
        continue  # only measure accuracy where we know truth
    s = stats[lbl]
    s["verified"] += 1
    # client accuracy: did AI's proposed client survive to final?
    if b.proposed_client_id is not None:
        s["has_prop_client"] += 1
        if b.proposed_client_id == b.client_id:
            s["client_match"] += 1

print("="*86)
print(f"AI CLIENT-SUGGESTION ACCURACY by confidence (org {ORG}, last 14d, human-verified blocks)")
print("="*86)
print(f"{'Band':<12}{'All blks':>9}{'Verified':>10}{'AI proposed client':>20}{'Matched final':>16}{'Accuracy':>10}")
print("-"*86)
for lo,hi,lbl in BANDS:
    s = stats[lbl]
    allc = all_by_band[lbl]
    acc = (100*s["client_match"]/s["has_prop_client"]) if s["has_prop_client"] else 0
    print(f"{lbl:<12}{allc:>9}{s['verified']:>10}{s['has_prop_client']:>20}{s['client_match']:>16}{acc:>9.1f}%")
print("="*86)
print("READ: 'Accuracy' = of human-verified blocks where AI proposed a client,")
print("how often the AI's client == the final client. High accuracy band = safe")
print("to auto-apply. The 'All blks' column shows the volume you'd auto-clear.")
print("="*86)

# Bonus: how many CURRENTLY-uncategorized blocks sit in each high band right now?
print("Currently-uncategorized blocks (is_categorized=False) by band — the")
print("auto-apply OPPORTUNITY (what we could clear from the pile):")
print("-"*86)
unc = qs.filter(is_categorized=False)
opp = defaultdict(lambda: {"n":0,"min":0,"has_client":0})
for b in unc:
    c = b.proposed_confidence
    if c is None: continue
    lbl = band(c)
    opp[lbl]["n"] += 1
    opp[lbl]["min"] += (b.minutes or 0)
    if b.proposed_client_id is not None:
        opp[lbl]["has_client"] += 1
for lo,hi,lbl in BANDS:
    o = opp[lbl]
    print(f"  {lbl:<12} {o['n']:>5} blocks  {o['min']//60:>3}h{o['min']%60:02d}m  "
          f"({o['has_client']} have a proposed client)")
print("="*86)
