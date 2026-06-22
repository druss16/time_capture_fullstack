"""
READ-ONLY. Ground-truth billable/total/uncategorized per user for one day,
computed the DAILY-REVIEW way (the source of truth per Dan). After applying the
reports_summary committed->proposed+committed fix, the dashboard's per-employee
numbers should match THIS table. Any row that doesn't match = a remaining
divergence between today_time and reports_summary to chase.

Counts billable as: is_billable=True AND client set, ANY classification_state
except suppressed (mirrors what today_time shows). Total = all non-suppressed,
non-anomalous blocks. Uncategorized = is_categorized=False, not suppressed, >=2min.

Run:
  docker compose exec -T api python manage.py shell < verify_dashboard_match.py
"""
from datetime import date
from collections import defaultdict
from tracker.models import Block

ORG_ID = 21
DAY = date(2026, 6, 22)
ANOMALY_MIN = 6 * 60

def hm(m):
    m = int(m or 0); return f"{m//60}h{m%60:02d}m"

q = (Block.objects.filter(org_id=ORG_ID, deleted_at__isnull=True, start__date=DAY)
     .exclude(classification_state="suppressed")
     .select_related("user", "client"))

def anomalous(b):
    if b.start and b.end:
        return (b.end - b.start).total_seconds()/60 > ANOMALY_MIN
    return (b.minutes or 0) > ANOMALY_MIN

agg = defaultdict(lambda: {"name":"", "total":0, "billable":0, "nonbill":0, "uncat":0})
for b in q:
    if anomalous(b):
        continue
    m = b.minutes or 0
    if m <= 0:
        continue
    u = agg[b.user_id]
    u["name"] = (b.user.get_full_name().strip() or b.user.username) if b.user_id else "?"
    u["total"] += m
    if not b.is_categorized:
        if m >= 2:
            u["uncat"] += m
        continue
    if b.is_billable and b.client_id:
        u["billable"] += m
    else:
        u["nonbill"] += m

print("="*90)
print(f"GROUND TRUTH (Daily-Review definition) — org {ORG_ID}, {DAY}")
print("="*90)
print(f"{'Employee':22s} {'Total':>8s} {'Billable':>9s} {'Non-bill':>9s} {'Uncat>=2m':>10s}")
print("-"*90)
tot=bil=nb=unc=0
for uid, u in sorted(agg.items(), key=lambda kv:-kv[1]["total"]):
    print(f"{u['name'][:22]:22s} {hm(u['total']):>8s} {hm(u['billable']):>9s} {hm(u['nonbill']):>9s} {hm(u['uncat']):>10s}")
    tot+=u["total"]; bil+=u["billable"]; nb+=u["nonbill"]; unc+=u["uncat"]
print("-"*90)
print(f"{'ORG TOTAL':22s} {hm(tot):>8s} {hm(bil):>9s} {hm(nb):>9s} {hm(unc):>10s}")
print("="*90)
print("After the fix, compare each row to the dashboard (period=day, same date).")
print("Matches = good. Mismatches = a remaining today_time vs reports_summary gap.")
