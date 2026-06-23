"""
READ-ONLY. Past 7 days only. Split uncategorized pile by the 2-min materiality
line. Question: is the 'huge' pile mostly sub-2min noise (already excluded from
KPIs) or real material blocks that need automation?
"""
from datetime import date, timedelta
from collections import defaultdict
from tracker.models import Block

ORG = 21
SINCE = date(2026,6,22) - timedelta(days=7)
qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True, start__date__gte=SINCE,
                          is_categorized=False).exclude(classification_state="suppressed")

n_total = under2_n = mat_n = 0
under2_min = mat_min = 0
mat_has_client = 0
mat_sig = defaultdict(lambda: {"n":0,"min":0,"has_client":0})

for b in qs:
    m = b.minutes or 0
    n_total += 1
    if m < 2:
        under2_n += 1; under2_min += m
    else:
        mat_n += 1; mat_min += m
        if b.proposed_client_id is not None:
            mat_has_client += 1
        app = (b.app_name or "?").strip()
        head = (b.window_title or "").strip().split(" - ")[0][:28] or "(no title)"
        s = mat_sig[f"{app} :: {head}"]
        s["n"] += 1; s["min"] += m
        if b.proposed_client_id is not None: s["has_client"] += 1

print("="*84)
print(f"UNCATEGORIZED PILE, org {ORG}, PAST 7 DAYS (since {SINCE}):")
print("="*84)
print(f"  Total uncategorized blocks: {n_total}")
print(f"  UNDER 2min (immaterial, already excluded from KPIs): "
      f"{under2_n} blocks = {under2_min//60}h{under2_min%60}m")
print(f"  >= 2min (MATERIAL — the real pile): "
      f"{mat_n} blocks = {mat_min//60}h{mat_min%60}m")
print(f"     of those, {mat_has_client} have an AI proposed client")
print("="*84)
print("MATERIAL (>=2min) uncategorized by signature — THIS is what to automate:")
print("-"*84)
print(f"{'Signature':<46}{'blks':>6}{'time':>9}{'prop_cli':>9}")
print("-"*84)
for key, s in sorted(mat_sig.items(), key=lambda kv:-kv[1]["min"])[:25]:
    print(f"  {key[:44]:<44}{s['n']:>6}{s['min']//60:>5}h{s['min']%60:02d}m{s['has_client']:>8}")
print("="*84)
GENERIC=("inbox","new tab","outlook","calendar","sign in","home","dashboard",
         "(no title)","search","settings","login","start","teams","sharepoint","onedrive")
gen=sum(s["min"] for k,s in mat_sig.items() if any(g in k.lower() for g in GENERIC))
print(f"Material pile that's generic/overhead: ~{gen//60}h{gen%60}m of {mat_min//60}h{mat_min%60}m "
      f"({100*gen//max(mat_min,1)}%)")
print("="*84)
