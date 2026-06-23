"""
READ-ONLY SHADOW. For every uncategorized QuickBooks (and Excel/Word/Explorer
with a name) block in org 21 last 7 days, match its title against client
name + aliases. Show what we WOULD attribute, confidence, and the recoverable
total. Changes NOTHING. This is the proof before any classifier change.
"""
from datetime import date, timedelta
from collections import defaultdict
from tracker.models import Block, Client
import re

ORG, SINCE = 21, date(2026,6,22) - timedelta(days=7)

# Build client lookup: normalized name/alias -> (client_id, client_name, matched_on)
clients = list(Client.objects.filter(org_id=ORG, is_active=True))
def norm(s):
    return re.sub(r'[^a-z0-9 ]','', (s or '').lower()).strip()

# token sets for fuzzy containment
client_index = []  # (client, normalized_string, kind)
for c in clients:
    if c.name:
        client_index.append((c, norm(c.name), "name"))
    for a in (c.aliases or []):
        if a:
            client_index.append((c, norm(a), "alias"))

def match_title(title):
    """Return (client, confidence, matched_on, matched_str) best match or None."""
    nt = norm(title)
    if not nt or len(nt) < 3:
        return None
    best = None
    for c, cstr, kind in client_index:
        if not cstr or len(cstr) < 3:
            continue
        # exact containment of client name in title (strong)
        if cstr in nt:
            conf = 0.95 if kind == "name" else 0.90
            # longer match = more confident; penalize very short client strings
            if len(cstr) < 6:
                conf -= 0.15
            cand = (c, conf, kind, cstr)
            if best is None or cand[1] > best[1]:
                best = cand
    return best

# QBW + other client-bearing apps
APPS = ("qbw.exe","excel.exe","winword.exe","explorer","explorer.exe")
qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True, start__date__gte=SINCE,
                          is_categorized=False).exclude(classification_state="suppressed")

would_attribute = defaultdict(lambda: {"n":0,"min":0})
no_match = defaultdict(lambda: {"n":0,"min":0})
recover_min = 0
total_min = 0
samples = []

for b in qs:
    m = b.minutes or 0
    if m < 2:
        continue
    app = (b.app_name or "").lower()
    if app not in APPS:
        continue
    total_min += m
    res = match_title(b.window_title or "")
    if res:
        c, conf, kind, cstr = res
        would_attribute[c.name]["n"] += 1
        would_attribute[c.name]["min"] += m
        recover_min += m
        if len(samples) < 20:
            samples.append((b.id, m, conf, c.name, (b.window_title or "")[:40]))
    else:
        key = f"{(b.app_name or '?')} :: {(b.window_title or '')[:24]}"
        no_match[key]["n"] += 1
        no_match[key]["min"] += m

print("="*88)
print(f"SHADOW: QBW/Excel/Word/Explorer uncategorized → client-by-title match (org {ORG}, 7d)")
print("="*88)
print(f"Total material client-app uncategorized: {total_min//60}h{total_min%60}m")
print(f"WOULD attribute to a client: {recover_min//60}h{recover_min%60}m "
      f"({100*recover_min//max(total_min,1)}%)")
print("="*88)
print("WOULD-ATTRIBUTE by client (recoverable billable):")
for name, s in sorted(would_attribute.items(), key=lambda kv:-kv[1]["min"]):
    print(f"  {name[:40]:<40} {s['n']:>3} blks  {s['min']//60}h{s['min']%60:02d}m")
print("-"*88)
print("Sample matches [id | min | conf | client | title]:")
for s in samples:
    print(f"  {s[0]} | {s[1]:>3}m | {s[2]:.2f} | {s[3][:24]:<24} | {s[4]}")
print("="*88)
print("NO MATCH (would stay uncategorized / need other logic), top 15 by time:")
for key, s in sorted(no_match.items(), key=lambda kv:-kv[1]["min"])[:15]:
    print(f"  {key[:50]:<50} {s['n']:>3} blks  {s['min']//60}h{s['min']%60:02d}m")
print("="*88)
print("READ: 'would attribute' = recoverable billable hours if classifier matched")
print("title→client. Check the samples look RIGHT before we change classifier code.")
print("="*88)
