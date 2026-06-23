"""
READ-ONLY. Show exactly which uncategorized blocks the overhead auto-nonbillable
rule WOULD catch. Confirm they're all true overhead (no billable client emails
sneaking in) before we change the classifier.
"""
from datetime import date, timedelta
from tracker.models import Block

ORG, SINCE = 21, date(2026,6,22) - timedelta(days=7)

AUTO_TITLE = ('inbox','new tab','sign in','sign-in','log in','login',
              'enter your phone','creative cloud desktop','payroll subscription')
AUTO_APPS = ('olk',)

qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True, start__date__gte=SINCE,
                          is_categorized=False).exclude(classification_state="suppressed")

caught, total_min = [], 0
# also surface anything that LOOKS like it might be billable but matches (safety)
risky = []
for b in qs:
    m = b.minutes or 0
    if m < 2: continue
    t = (b.window_title or "").lower()
    a = (b.app_name or "").lower()
    hit = any(s in t for s in AUTO_TITLE) or a in AUTO_APPS
    if not hit: continue
    caught.append((b, m)); total_min += m
    # risky = has a client already, or title has RE:/FW: (real correspondence)
    if b.client_id or "re:" in t or "fw:" in t or "review" in t:
        risky.append((b, m))

print("="*80)
print(f"Blocks the overhead rule WOULD auto-commit as non-billable (org {ORG}, 7d):")
print(f"  count: {len(caught)}  total: {total_min//60}h{total_min%60}m")
print("="*80)
for b, m in sorted(caught, key=lambda x:-x[1])[:30]:
    print(f"  {m:>3}m | client={b.client_id} | {(b.app_name or '?')[:10]:10} | "
          f"{(b.window_title or '(empty)')[:46]}")
print("="*80)
print(f"⚠️  RISKY matches (have a client OR look like real correspondence): {len(risky)}")
for b, m in risky:
    print(f"  {m:>3}m | client={b.client_id} | {(b.window_title or '')[:50]}")
print("  ^ if this list is non-empty, the rule is too broad — tighten before shipping.")
print("="*80)

# Verify how commit-vs-propose is decided: find the threshold/gate
import subprocess, os
base = "/app/tracker" if os.path.isdir("/app/tracker") else "tracker"
def grep(p):
    try: return subprocess.run(["grep","-rn",p,base+"/services/classification_service.py"],
                               capture_output=True,text=True,timeout=20).stdout.strip()
    except Exception as e: return f"(err {e})"
print("How does a decision become 'committed' vs 'proposed'? (the gate):")
for pat in ("recommended_state =","recommended_state=","= 'committed'","'proposed'","AUTO_COMMIT","auto_commit","strength >="):
    h = grep(pat)
    if h:
        print(f"\n[{pat}]")
        print(h[:900])
print("="*80)
