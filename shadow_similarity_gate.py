"""READ-ONLY. Test a WHOLE-NAME similarity gate vs the current token-overlap.
Goal: keep 'All Round Repair' match (good, ~same name), kill 'CNY Coin' match
(bad, shares only generic tokens). Uses difflib ratio on the client name vs the
best-matching contiguous span of the title."""
import re
from difflib import SequenceMatcher
from tracker.models import Client

title = "All Around Auto Repair and Sales Corp INC (70247783), Dashboard - Work - Microsoft Edge"
title_l = title.lower()

def norm(s):
    return ' '.join(re.findall(r'[a-z0-9]+', (s or '').lower()))

def best_span_ratio(client_name, title):
    """Highest SequenceMatcher ratio between the full client name and any
    window of the title of similar length. Approximates 'does this client
    name appear, even fuzzily, as a chunk of the title?'"""
    cn = norm(client_name)
    tl = norm(title)
    if not cn or not tl:
        return 0.0
    # whole-string ratio
    whole = SequenceMatcher(None, cn, tl).ratio()
    # also try matching against the leading chunk of the title the length of cn
    chunk = tl[:len(cn)+5]
    lead = SequenceMatcher(None, cn, chunk).ratio()
    return max(whole, lead)

candidates = [
    (154, "All Round Repair & Sales Corp"),
    (207, "CNY Coin & Silver, Inc."),
]
# also pull aliases for each
print("="*72)
print(f"TITLE: {title}")
print(f"  normalized: {norm(title)}")
print("="*72)
for cid, _ in candidates:
    c = Client.objects.filter(id=cid).first()
    if not c: 
        print(f"  client {cid} not found"); continue
    forms = [c.name] + list(getattr(c, 'aliases', []) or [])
    best = max(best_span_ratio(f, title) for f in forms)
    verdict = "KEEP (strong)" if best >= 0.70 else ("WEAK" if best >= 0.55 else "REJECT")
    print(f"\nclient {cid}: {c.name!r}")
    print(f"  forms: {forms}")
    print(f"  best whole-name similarity to title: {best:.3f}  → {verdict}")

print("\n" + "="*72)
print("Now scan ALL active clients: similarity to this same title.")
print("Anything >= 0.70 that ISN'T 'All Round Repair' is a concern.")
print("="*72)
rows = []
for c in Client.objects.filter(is_active=True):
    forms = [c.name] + list(getattr(c, 'aliases', []) or [])
    best = max((best_span_ratio(f, title) for f in forms), default=0.0)
    if best >= 0.55:
        rows.append((best, c.id, c.name))
for best, cid, name in sorted(rows, reverse=True):
    print(f"  {best:.3f}  id={cid}  {name!r}")
print("="*72)
print("READ: a 0.70 gate should KEEP All Round Repair (~0.8+) and REJECT")
print("CNY Coin (~0.2). If only All Round Repair clears 0.70, the gate works.")
