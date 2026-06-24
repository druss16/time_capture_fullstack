"""READ-ONLY. Run AFTER applying the gate edit. Re-scores the 9 known blocks
through the LIVE (now-patched) _alias_match_score to confirm:
  - All Round Repair (154/763) still scores > 0  (KEEP — same company)
  - CNY Coin (207) now scores 0.0 on these titles (REJECT — garbage killed)
Also spot-checks a few contiguous matches still work (Tiers 1/2 unaffected)."""
from tracker.services.classification_service import ClassificationService as CS
from tracker.models import Client

title = "All Around Auto Repair and Sales Corp INC (70247783), Dashboard - Work - Microsoft Edge"

print("="*72)
print("GATE VERIFICATION — _alias_match_score on the Auto Repair title")
print("="*72)
for cid in [154, 763, 207]:
    c = Client.objects.filter(id=cid).first()
    if not c: 
        print(f"  {cid}: not found"); continue
    forms = [c.name] + list(getattr(c,'aliases',[]) or [])
    best = max((CS._alias_match_score(f, title) for f in forms), default=0.0)
    tag = "KEEP" if best > 0 else "REJECTED (gate killed it)"
    print(f"  id={cid} {c.name!r:35} → score {best:.3f}  {tag}")

print("\n" + "="*72)
print("REGRESSION — contiguous Tier 1/2 matches must STILL score high")
print("="*72)
# A few contiguous-name titles that SHOULD still match strongly:
checks = [
    (154, "All Round Repair & Sales Corp - QuickBooks Accountant Desktop"),
    (76,  "All Saints Church - QuickBooks - [Write Checks]"),
]
for cid, t in checks:
    c = Client.objects.filter(id=cid).first()
    if not c: continue
    forms = [c.name] + list(getattr(c,'aliases',[]) or [])
    best = max((CS._alias_match_score(f, t) for f in forms), default=0.0)
    ok = "OK (contiguous still strong)" if best >= 0.85 else "!! REGRESSION — check gate"
    print(f"  id={cid} {c.name!r:25} vs own title → {best:.3f}  {ok}")
print("="*72)
print("PASS CRITERIA: 154/763 > 0, 207 == 0.0, both contiguous checks >= 0.85")
