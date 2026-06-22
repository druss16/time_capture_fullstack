"""
READ-ONLY pass 3. The NON-CIRCULAR accuracy test.

Pass 2 showed proposed_client == final_client 97% — but 92% of blocks were
categorized BY the ai, so that's mostly "the AI agrees with itself." The real
question: when a HUMAN touched the block, was the AI's proposal right?

We isolate human-touched blocks (categorized_by in manual/correction) and any
block that carries a recorded disagreement/correction, then check how often the
AI's proposed_client / proposed_category survived.

Run:
  docker compose exec -T api python manage.py shell < suggestion_quality3.py

Writes NOTHING.
"""
from collections import Counter
from datetime import timedelta
from django.utils import timezone
from tracker.models import Block

ORG_ID = 21
LOOKBACK_DAYS = 90   # widen — human corrections are rare, need more history
now = timezone.now()
since = now - timedelta(days=LOOKBACK_DAYS)

base = (Block.objects
        .filter(org_id=ORG_ID, is_categorized=True, deleted_at__isnull=True)
        .filter(start__gte=since))
total = base.count()
print("="*72)
print(f"Categorized blocks (org {ORG_ID}, {LOOKBACK_DAYS}d): {total}")
print("="*72)

by = Counter(base.values_list("categorized_by", flat=True))
print("categorized_by breakdown:")
for k, v in by.most_common():
    print(f"   {str(k):14s} {v:5d}  ({100*v/total:.0f}%)")
print("="*72)

# ---- HUMAN-TOUCHED blocks: the non-circular set ----
human = base.filter(categorized_by__in=["manual", "correction"])
hn = human.count()
print(f"HUMAN-TOUCHED blocks (manual + correction): {hn}")
if hn:
    # Of these, how many had a proposed_client, and did it survive?
    hp = human.exclude(proposed_client_id__isnull=True)
    hpn = hp.count()
    print(f"   ...of which had a proposed_client_id: {hpn}")
    if hpn:
        kept = 0; changed = 0
        change_samples = []
        for r in hp.values("id", "proposed_client_id", "client_id",
                           "proposed_category", "window_title", "proposed_confidence"):
            if r["proposed_client_id"] == r["client_id"]:
                kept += 1
            else:
                changed += 1
                if len(change_samples) < 15:
                    change_samples.append(r)
        print(f"   AI client KEPT by human:    {kept}/{hpn}  ({100*kept/hpn:.0f}%)")
        print(f"   AI client CHANGED by human: {changed}/{hpn}  ({100*changed/hpn:.0f}%)")
        print("   sample of CHANGED [proposed_cli -> final_cli | conf | title]:")
        for r in change_samples:
            t = (r["window_title"] or "")[:45]
            print(f"      {str(r['proposed_client_id']):>5} -> {str(r['client_id']):>5}"
                  f"  conf={r['proposed_confidence']}  {t}")
else:
    print("   (none — humans essentially never manually re-categorize)")
print("="*72)

# ---- Disagreement signals: blocks where AI disagreed with agent / was flagged ----
# These fields exist per the schema dump.
print("RECORDED DISAGREEMENTS (independent signal of AI being wrong):")
for fld in ["ai_disagrees_with_agent", "mail_disagrees_with_agent", "calendar_disagrees_with_agent"]:
    try:
        n = base.filter(**{fld: True}).count()
        print(f"   {fld:32s} True: {n}  ({100*n/total:.1f}%)")
    except Exception as e:
        print(f"   {fld}: (could not query: {e})")
print("="*72)

# ---- needs_review: how many categorized blocks are still flagged for review ----
try:
    nr = base.filter(needs_review=True).count()
    print(f"categorized blocks still needs_review=True: {nr}  ({100*nr/total:.0f}%)")
except Exception:
    pass

# ---- proposed_confidence distribution: is the AI well-calibrated? ----
print("-"*72)
print("proposed_confidence distribution (all categorized w/ a proposal):")
withc = base.exclude(proposed_confidence__isnull=True)
buckets = Counter()
for c in withc.values_list("proposed_confidence", flat=True):
    try:
        cf = float(c)
    except (TypeError, ValueError):
        buckets["non-numeric"] += 1; continue
    if cf >= 0.9: buckets["0.90-1.0"] += 1
    elif cf >= 0.8: buckets["0.80-0.89"] += 1
    elif cf >= 0.7: buckets["0.70-0.79"] += 1
    elif cf >= 0.5: buckets["0.50-0.69"] += 1
    else: buckets["<0.50"] += 1
for k in ["0.90-1.0","0.80-0.89","0.70-0.79","0.50-0.69","<0.50","non-numeric"]:
    if buckets.get(k):
        print(f"   {k:12s} {buckets[k]:5d}")
print("="*72)
print("DONE — paste whole output.")
print("="*72)
