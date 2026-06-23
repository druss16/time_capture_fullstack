"""
READ-ONLY. How much of the uncategorized pile can go ZERO-TOUCH (auto-default
to non-billable) with no ambiguity vs. needs-the-QB-ID-fix vs. genuinely-human.
The goal: maximize what needs NO user action.
"""
from datetime import date, timedelta
from collections import defaultdict
from tracker.models import Block

ORG, SINCE = 21, date(2026,6,22) - timedelta(days=7)
qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True, start__date__gte=SINCE,
                          is_categorized=False).exclude(classification_state="suppressed")

# Signatures that are ALWAYS non-billable overhead — safe to auto-default, no human.
OVERHEAD_TITLE = ("inbox","new tab","sign in","sign-in","login","log in","home",
                  "dashboard","settings","my account","payroll subscription",
                  "outlook","office","run powered by adp","accountedge",
                  "creative cloud","enter your phone","start","search")
OVERHEAD_APP = ("olk","")  # bare/no-app
# Personal browsing = non-billable
PERSONAL = ("monkey go happy","gwen stefani","sexually","trump","cbs","coaching",
            "michigan","nichols fresh market","flyer","after the pitt","reportedly")
# QB company files — the QB-ID-fixable bucket (real client work, needs exact ID)
QB_APPS = ("qbw.exe",)
# Idle/junk
JUNK_TITLE = ("","program manager","document2","missing client info","missing documents")

auto_overhead = defaultdict(lambda:{"n":0,"min":0})
auto_personal = defaultdict(lambda:{"n":0,"min":0})
qb_fixable = defaultdict(lambda:{"n":0,"min":0})
junk = defaultdict(lambda:{"n":0,"min":0})
human = defaultdict(lambda:{"n":0,"min":0})
tot = dict(overhead=0, personal=0, qb=0, junk=0, human=0)

for b in qs:
    m = b.minutes or 0
    if m < 2: continue
    app = (b.app_name or "").lower()
    title = (b.window_title or "").strip().lower()
    sig = f"{b.app_name} :: {(b.window_title or '')[:24]}"
    if app in QB_APPS and title not in ("","quickbooks accountant desktop plus 2024"," quickbooks accountant desktop plus 2024"):
        qb_fixable[sig]["min"]+=m; qb_fixable[sig]["n"]+=1; tot["qb"]+=m
    elif any(p in title for p in PERSONAL):
        auto_personal[sig]["min"]+=m; auto_personal[sig]["n"]+=1; tot["personal"]+=m
    elif any(o in title for o in OVERHEAD_TITLE) or app=="olk":
        auto_overhead[sig]["min"]+=m; auto_overhead[sig]["n"]+=1; tot["overhead"]+=m
    elif title in JUNK_TITLE or "explor" in app:
        junk[sig]["min"]+=m; junk[sig]["n"]+=1; tot["junk"]+=m
    else:
        human[sig]["min"]+=m; human[sig]["n"]+=1; tot["human"]+=m

def show(name, d, note):
    t = sum(v["min"] for v in d.values())
    print(f"\n{name}: {t//60}h{t%60}m  ({note})")
    for s,v in sorted(d.items(), key=lambda kv:-kv[1]["min"])[:8]:
        print(f"   {s[:46]:<46} {v['n']:>3} blks {v['min']//60}h{v['min']%60:02d}m")

print("="*84)
print(f"ZERO-TOUCH OPPORTUNITY, org {ORG}, 7d material pile")
print("="*84)
show("AUTO → NON-BILLABLE (overhead, zero human)", auto_overhead, "RULE, ship today")
show("AUTO → NON-BILLABLE (personal browsing)", auto_personal, "RULE, ship today")
show("SUPPRESS (idle/junk)", junk, "shell-idle filter")
show("QB-ID FIXABLE (real client work)", qb_fixable, "needs agent QB-company capture")
show("GENUINELY NEEDS HUMAN", human, "candidate-pick UI")
print("\n"+"="*84)
g=tot
print(f"SUMMARY of material pile:")
print(f"  Auto non-billable (overhead+personal): {(g['overhead']+g['personal'])//60}h{(g['overhead']+g['personal'])%60}m  ← ZERO TOUCH TODAY")
print(f"  Suppress idle/junk:                    {g['junk']//60}h{g['junk']%60}m  ← filter")
print(f"  QB-ID fixable (exact, agent fix):      {g['qb']//60}h{g['qb']%60}m  ← next project")
print(f"  Genuinely needs human pick:            {g['human']//60}h{g['human']%60}m  ← small")
print("="*84)
