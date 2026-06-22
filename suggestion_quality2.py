"""
READ-ONLY pass 2. Fixes the crash (no `category` field exists) and inspects the
REAL shape of category storage before measuring anything.

Key facts already known from prior run:
  - 92% of categorized blocks were done by `ai`
  - category lives in: ai_category, proposed_category, category_hours (shape unknown)
  - client suggestion lives in: proposed_client_id / ai_proposed_client_id

Run:
  docker compose exec -T api python manage.py shell < suggestion_quality2.py

Writes NOTHING.
"""
from collections import Counter
from datetime import timedelta
from django.utils import timezone
from tracker.models import Block

ORG_ID = 21
LOOKBACK_DAYS = 45
now = timezone.now()
since = now - timedelta(days=LOOKBACK_DAYS)

catd = (Block.objects
        .filter(org_id=ORG_ID, is_categorized=True, deleted_at__isnull=True)
        .filter(start__gte=since))
total = catd.count()
print("="*72)
print(f"Categorized blocks (org {ORG_ID}, {LOOKBACK_DAYS}d): {total}")
print("="*72)

# ---- 1. Inspect 5 real rows to see the actual data shape ----
print("SAMPLE ROWS — raw values so we see the true shape:")
sample = catd.values(
    "id", "ai_category", "proposed_category", "category_hours",
    "task_type_id", "client_id", "is_billable", "categorized_by",
    "ai_confidence", "proposed_confidence", "proposed_client_id",
)[:5]
for r in sample:
    print("-"*72)
    for k, v in r.items():
        sv = str(v)
        if len(sv) > 80: sv = sv[:80] + "…"
        print(f"   {k:22s} = {sv}")
print("="*72)

# ---- 2. ai_category distribution (what the AI actually outputs) ----
print("ai_category distribution (top 20):")
ac = Counter()
for v in catd.values_list("ai_category", flat=True):
    ac[(v or "(null)")] += 1
for k, c in ac.most_common(20):
    print(f"   {str(k)[:40]:40s} {c:5d}  ({100*c/total:.0f}%)")
print("="*72)

# ---- 3. proposed_category distribution ----
print("proposed_category distribution (top 20):")
pc = Counter()
for v in catd.values_list("proposed_category", flat=True):
    pc[(v or "(null)")] += 1
for k, c in pc.most_common(20):
    print(f"   {str(k)[:40]:40s} {c:5d}  ({100*c/total:.0f}%)")
print("="*72)

# ---- 4. agreement between proposed_category and ai_category ----
print("AGREEMENT: proposed_category vs ai_category")
both = catd.exclude(proposed_category__isnull=True).exclude(proposed_category="") \
           .exclude(ai_category__isnull=True).exclude(ai_category="")
nb = both.count()
if nb:
    m = 0
    mism = Counter()
    for r in both.values("proposed_category", "ai_category")[:8000]:
        a = (r["proposed_category"] or "").strip().lower()
        b = (r["ai_category"] or "").strip().lower()
        if a == b: m += 1
        else: mism[(a, b)] += 1
    ck = min(nb, 8000)
    print(f"   rows w/ both: {nb}  checked {ck}")
    print(f"   match: {100*m/ck:.0f}%  ({m}/{ck})")
    print("   top divergences [proposed -> ai_category : count]:")
    for (a, b), c in mism.most_common(12):
        print(f"      {a[:26]:26s} -> {b[:26]:26s}  {c}")
else:
    print("   not enough rows with both fields populated.")
print("="*72)

# ---- 5. how often is a category 'Personal/Non-Billable'-ish? (the complaint) ----
print("How many categorized blocks landed NON-BILLABLE / personal-ish?")
nonbill = catd.filter(is_billable=False).count()
print(f"   is_billable=False: {nonbill}/{total}  ({100*nonbill/total:.0f}%)")
print("   ai_category values that look personal/idle:")
personalish = {k: v for k, v in ac.items()
               if any(w in str(k).lower() for w in ("personal","idle","uncategor","non-bill"))}
for k, v in sorted(personalish.items(), key=lambda x:-x[1]):
    print(f"      {str(k)[:40]:40s} {v:5d}  ({100*v/total:.0f}%)")
print("="*72)

# ---- 6. client suggestion behavior ----
print("CLIENT SUGGESTION: proposed_client_id vs final client_id")
pcli = catd.exclude(proposed_client_id__isnull=True)
npc = pcli.count()
print(f"   blocks with a proposed_client_id: {npc}  ({100*npc/total:.0f}%)")
if npc:
    agree = 0
    for r in pcli.values("proposed_client_id", "client_id")[:8000]:
        if r["proposed_client_id"] == r["client_id"]:
            agree += 1
    ck = min(npc, 8000)
    print(f"   proposed == final client: {agree}/{ck}  ({100*agree/ck:.0f}%)")
print("="*72)
print("DONE — paste whole output.")
print("="*72)
