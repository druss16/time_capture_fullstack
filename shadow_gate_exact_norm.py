"""READ-ONLY. Validate the 0.70 gate using the EXACT _normalize from
_alias_match_score (not the shadow's own). This confirms the threshold
against the real numbers the in-code gate will compute."""
import re
from difflib import SequenceMatcher
from tracker.models import Client

# EXACT copy of _normalize from _alias_match_score (lines ~1845-1855)
def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r'\bst\.?\s', 'saint ', s)
    s = re.sub(r'\bmt\.?\s', 'mount ', s)
    s = re.sub(r'\bft\.?\s', 'fort ', s)
    s = s.replace("'", "").replace("\u2019", "")
    s = re.sub(r'\b(\w{4,})s\b', r'\1', s)
    s = re.sub(r'[.,()&/\\|:;!?"*\u2013\u2014\-\[\]{}]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

title = "All Around Auto Repair and Sales Corp INC (70247783), Dashboard - Work - Microsoft Edge"
# pre_bracket = whole thing (no ' - [' bracket here)
raw_bracket = title.find(' - [')
pre_raw = title if raw_bracket < 0 else title[:raw_bracket]
pre_bracket = _normalize(pre_raw)
print(f"pre_bracket (code normalize): {pre_bracket!r}\n")

def gate_sim(alias):
    a = _normalize(alias)
    whole = SequenceMatcher(None, a, pre_bracket).ratio()
    lead = SequenceMatcher(None, a, pre_bracket[:len(a)+5]).ratio()
    return a, max(whole, lead), whole, lead

print(f"{'alias_n':<40} {'max':>6} {'whole':>6} {'lead':>6}  verdict")
print("-"*78)
test = []
for c in Client.objects.filter(is_active=True):
    forms = [c.name] + list(getattr(c,'aliases',[]) or [])
    best = 0.0; best_form=None
    for f in forms:
        a, mx, wh, ld = gate_sim(f)
        if mx > best: best, best_form, best_parts = mx, (f,a), (wh,ld)
    if best >= 0.50:
        test.append((best, c.id, c.name, best_form, best_parts))
for best, cid, name, bf, bp in sorted(test, reverse=True):
    verdict = "PASS (>=0.70)" if best >= 0.70 else "reject"
    print(f"{bf[1][:40]:<40} {best:6.3f} {bp[0]:6.3f} {bp[1]:6.3f}  {verdict}  id={cid} {name!r}")
print("-"*78)
print("Confirm: All Round Repair PASSES, CNY Coin rejects, nothing else falsely PASSES.")
