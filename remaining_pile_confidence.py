"""
READ-ONLY. The overhead is cleared; what's LEFT in the pile? For each remaining
material uncategorized block, show what the AI/signals propose and at what
confidence. Question: is there confident-but-not-auto-applied work we could
auto-commit NOW, or is the remainder all genuinely-needs-a-human?
"""
from datetime import date, timedelta
from collections import defaultdict
from tracker.models import Block

ORG, SINCE = 21, date(2026,6,23) - timedelta(days=7)
qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True, start__date__gte=SINCE,
                          is_categorized=False).exclude(classification_state="suppressed")

buckets = defaultdict(lambda: {"n":0,"min":0})
has_client_prop = 0
confident_client = []   # AI proposes a client at >=0.80 but block still uncategorized
for b in qs:
    m = b.minutes or 0
    if m < 2: continue
    conf = b.proposed_confidence or 0
    pc = b.proposed_client_id
    if pc is not None:
        has_client_prop += 1
        if conf >= 0.80:
            confident_client.append((b.id, m, conf, pc, (b.window_title or '')[:40]))
    # bucket by confidence band
    if conf >= 0.90: band = ">=0.90"
    elif conf >= 0.80: band = "0.80-0.90"
    elif conf >= 0.65: band = "0.65-0.80"
    elif conf >= 0.50: band = "0.50-0.65"
    else: band = "<0.50"
    buckets[band]["n"] += 1; buckets[band]["min"] += m

tot = sum(v["n"] for v in buckets.values())
totm = sum(v["min"] for v in buckets.values())
print("="*72)
print(f"REMAINING material uncategorized pile (org {ORG}, 7d): {tot} blocks, {totm//60}h{totm%60}m")
print(f"  blocks where AI proposes a CLIENT: {has_client_prop}")
print(f"  of those, confident (>=0.80): {len(confident_client)}")
print("="*72)
print("By confidence band:")
for band in (">=0.90","0.80-0.90","0.65-0.80","0.50-0.65","<0.50"):
    v = buckets[band]
    print(f"  {band:<12} {v['n']:>4} blocks  {v['min']//60}h{v['min']%60:02d}m")
print("="*72)
if confident_client:
    print("CONFIDENT client proposals NOT auto-applied (the available win):")
    for bid,m,c,pc,t in confident_client[:20]:
        print(f"  {bid} | {m:>3}m | conf={c:.2f} | client={pc} | {t}")
else:
    print("No confident (>=0.80) client proposals sitting unapplied.")
    print("→ remainder is genuinely low-confidence; needs Step 2 (QB-ID) or human.")
print("="*72)
