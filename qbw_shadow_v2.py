"""
READ-ONLY SHADOW v2. Token-overlap matcher with disambiguation.
For each uncategorized QBW/Office block, score every client by token overlap
between title and client name+aliases. Attribute ONLY when there's a clear
winner (top score high AND a gap to #2). Otherwise flag as AMBIGUOUS with the
top candidates — those become human-review quick-picks, not auto-attribution.
Changes nothing.
"""
from datetime import date, timedelta
from collections import defaultdict
from tracker.models import Block, Client
import re

ORG, SINCE = 21, date(2026,6,22) - timedelta(days=7)

STOP = {"the","of","and","inc","llc","corp","church","parish","co","company",
        "ltd","our","st","saint","-","&","quickbooks","accountant","desktop",
        "plus","2024","2025","primary","secondary","file","explorer","word",
        "excel","document","outlook","inbox"}

def toks(s):
    s = re.sub(r'[^a-z0-9 ]',' ',(s or '').lower())
    return {t for t in s.split() if t and t not in STOP and len(t) > 2}

clients = list(Client.objects.filter(org_id=ORG, is_active=True))
client_toks = []
for c in clients:
    strs = [c.name] + list(c.aliases or [])
    ct = set()
    for s in strs:
        ct |= toks(s)
    if ct:
        client_toks.append((c, ct))

def score_title(title):
    """Return ranked [(client, score, overlap_tokens)] by token overlap."""
    tt = toks(title)
    if not tt:
        return []
    scored = []
    for c, ct in client_toks:
        ov = tt & ct
        if ov:
            # score = overlap count, weighted by how much of the CLIENT name matched
            score = len(ov) + (len(ov)/max(len(ct),1))
            scored.append((c, round(score,2), ov))
    scored.sort(key=lambda x:-x[1])
    return scored

APPS = ("qbw.exe","excel.exe","winword.exe")
qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True, start__date__gte=SINCE,
                          is_categorized=False).exclude(classification_state="suppressed")

CLEAR, AMBIG, NOMATCH = [], [], []
clear_min = ambig_min = 0
for b in qs:
    m = b.minutes or 0
    if m < 2: continue
    if (b.app_name or "").lower() not in APPS: continue
    ranked = score_title(b.window_title or "")
    if not ranked:
        NOMATCH.append((b, m)); continue
    top = ranked[0]
    gap = top[1] - (ranked[1][1] if len(ranked) > 1 else 0)
    # CLEAR: top has >=2 overlap tokens AND a real gap to #2
    if len(top[2]) >= 2 and gap >= 1.0:
        CLEAR.append((b, m, top, gap)); clear_min += m
    else:
        AMBIG.append((b, m, ranked[:3])); ambig_min += m

print("="*92)
print(f"SHADOW v2 (token-overlap + disambiguation), org {ORG}, 7d, material QBW/Office")
print("="*92)
print(f"CLEAR auto-attributable: {len(CLEAR)} blocks = {clear_min//60}h{clear_min%60}m")
print(f"AMBIGUOUS (flag for human w/ candidates): {len(AMBIG)} blocks = {ambig_min//60}h{ambig_min%60}m")
print(f"NO MATCH: {len(NOMATCH)} blocks")
print("="*92)
print("CLEAR matches [min | client | gap | title]:")
for b, m, top, gap in sorted(CLEAR, key=lambda x:-x[1])[:20]:
    print(f"  {m:>3}m | {top[0].name[:30]:<30} | gap={gap:.1f} | {(b.window_title or '')[:34]}")
print("-"*92)
print("AMBIGUOUS [min | title → top candidates]:")
for b, m, cands in sorted(AMBIG, key=lambda x:-x[1])[:15]:
    cs = " / ".join(f"{c.name[:20]}({s})" for c,s,_ in cands)
    print(f"  {m:>3}m | {(b.window_title or '')[:30]:<30} → {cs}")
print("="*92)
print("READ: CLEAR = safe to auto-propose. AMBIGUOUS = show user the candidate")
print("buttons in Daily Review. Check CLEAR matches are actually RIGHT.")
print("="*92)
