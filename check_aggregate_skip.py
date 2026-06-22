"""
READ-ONLY. Why does _aggregate show ~1h14m billable for Eileen when truth is 3h51m?
Tests BOTH hypotheses at once:
  H1: billable blocks skipped by category (_EXCLUDE_CATEGORIES, empty category_hours)
  H2: billable blocks dropped by the <2min materiality filter (_is_material)
"""
from datetime import date
from django.db.models import Q
from tracker.models import Block

ORG_ID, UID, DAY = 21, 48, date(2026, 6, 22)
EXCLUDE = {"idle", "uncategorized"}
ANOMALY = 6*60

def dom_cat(b):
    ch = b.category_hours
    return next(iter(ch.keys())) if isinstance(ch, dict) and ch else "Uncategorized"
def block_min(b):
    if b.start and b.end and (b.end-b.start).total_seconds()/60 > ANOMALY: return 0
    return max(0, b.minutes or 0)

q = Block.objects.filter(org_id=ORG_ID, user_id=UID, deleted_at__isnull=True,
    start__date=DAY).filter(Q(classification_state__in=["committed","proposed"]) | Q(is_categorized=True))

kept = cat_skip = immaterial_skip = 0
kept_m = cat_m = imm_m = 0
size_hist = {"<2min":0, "2-5min":0, "5min+":0}
for b in q:
    if not (b.is_billable and b.client_id):  # only billable-with-client
        continue
    m = block_min(b)
    if m <= 0: continue
    cat = dom_cat(b).lower()
    # replicate FIXED _aggregate logic:
    if cat in EXCLUDE and not (b.is_billable and b.client_id):
        cat_skip += 1; cat_m += m; continue
    if m < 2:  # materiality
        immaterial_skip += 1; imm_m += m
        size_hist["<2min"] += 1
        continue
    kept += 1; kept_m += m
    size_hist["2-5min" if m < 5 else "5min+"] += 1

print("="*72)
print("Eileen's BILLABLE-with-client blocks, Jun 22, under fixed _aggregate:")
print(f"  KEPT (counted as billable): {kept} blocks = {kept_m}m ({kept_m//60}h{kept_m%60}m)")
print(f"  SKIPPED by category rule:   {cat_skip} blocks = {cat_m}m")
print(f"  SKIPPED by <2min material:  {immaterial_skip} blocks = {imm_m}m ({imm_m//60}h{imm_m%60}m)")
print("-"*72)
print(f"  If KEPT ~= 1h14m, the rest is being dropped. Which bucket has it?")
print(f"  block size distribution of billable blocks: {size_hist}")
print("="*72)
print("VERDICT:")
if imm_m > cat_m and imm_m > 60:
    print(f"  -> MATERIALITY filter is eating {imm_m}m of billable time.")
    print("     today_time has no 2min filter; that's the divergence.")
elif cat_m > 60:
    print(f"  -> CATEGORY skip is eating {cat_m}m. The fix didn't take or cat check wrong.")
else:
    print("  -> Neither bucket explains it; the gap is elsewhere. Paste output.")
print("="*72)
