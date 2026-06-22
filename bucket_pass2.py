"""
READ-ONLY second pass. Fixes two flaws in pass 1:
  1. Excludes idle/uncategorized blocks from the "attributed neighbor" set,
     so bucket (b) clean-adjacent-clue reflects REAL clients only.
  2. Dumps the actual bucket (a) name-in-title matches so we can eyeball
     precision before building a matcher on them. Flags suspicious short/common
     tokens separately.

Run:
  docker compose exec -T api python manage.py shell < bucket_pass2.py

Writes NOTHING.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from django.utils import timezone
from tracker.models import Block, Client

ORG_ID = 21
LOOKBACK_DAYS = 30
ADJACENCY_WINDOW_MIN = 30

# Names/categories that are NOT real clients — exclude from adjacency + treat as non-attributed
NON_CLIENT_NAMES = {
    "idle/uncategorized", "idle", "uncategorized", "personal/non-billable",
    "personal", "non-billable", "break", "lunch", "admin", "overhead",
    "internal", "__idle__",
}

JUNK_PATTERNS = [
    "log in", "login", "sign in", "sign-in", "phone code", "verification",
    "new tab", "region selection", "working...", "sharing link validation",
    "authenticator", "two-factor", "2fa", "mfa", "redirecting", "loading",
    "sign in to your account",
]
# NOTE: pulled "outlook"/"inbox"/"office" OUT of junk this pass — they were
# inflating (c). Outlook blocks now fall through to name-match / ambiguous.

now = timezone.now()
since = now - timedelta(days=LOOKBACK_DAYS)

qs = (Block.objects
      .filter(org_id=ORG_ID, is_categorized=False, deleted_at__isnull=True)
      .exclude(classification_state="suppressed")
      .filter(start__gte=since)
      .order_by("start"))

clients = list(Client.objects.filter(org_id=ORG_ID))

# Build token table, tagging each token with length so we can flag risky short ones
name_tokens = []  # (token, client_id, client_name, kind)
for c in clients:
    nm = (c.name or "").strip()
    if nm and nm.lower() not in NON_CLIENT_NAMES and len(nm) >= 4:
        name_tokens.append((nm.lower(), c.id, nm, "name"))
    code = (getattr(c, "code", None) or "").strip()
    if code and len(code) >= 3:
        name_tokens.append((code.lower(), c.id, nm or code, "code"))
    for a in (getattr(c, "aliases", None) or []):
        if isinstance(a, str) and len(a.strip()) >= 4:
            name_tokens.append((a.strip().lower(), c.id, nm, "alias"))

# Real-client attributed blocks only (exclude idle/personal categories)
attributed = []
for a in (Block.objects
          .filter(org_id=ORG_ID, deleted_at__isnull=True, client__isnull=False)
          .filter(start__gte=since)
          .values("id", "start", "end", "client_id", "client__name")):
    cn = (a["client__name"] or "").lower()
    if cn in NON_CLIENT_NAMES:
        continue
    attributed.append(a)

def title_of(b): return (b.window_title or "").strip()

def name_in_title(title):
    t = title.lower()
    hits = []
    for tok, cid, cname, kind in name_tokens:
        if tok in t:
            hits.append((tok, cname, kind))
    return hits

def is_junk(title):
    t = title.lower()
    return any(p in t for p in JUNK_PATTERNS)

def adjacent_client(b):
    lo = b.start - timedelta(minutes=ADJACENCY_WINDOW_MIN)
    hi = (b.end or b.start) + timedelta(minutes=ADJACENCY_WINDOW_MIN)
    near = {}
    for a in attributed:
        if a["id"] == b.id:
            continue
        if a["start"] <= hi and (a["end"] or a["start"]) >= lo:
            near[a["client_id"]] = a["client__name"]
    if len(near) == 1:
        return list(near.values())[0]
    return None

blocks = list(qs)
total = len(blocks)

b_name = b_clue = b_junk = b_ambig = 0
m_name = m_clue = m_junk = m_ambig = 0

name_samples = []          # clean-looking name matches
name_suspicious = []       # matched only via short token / code -> verify
token_hits = Counter()     # which tokens are doing the matching (spot junk tokens)
clue_samples = []

for b in blocks:
    title = title_of(b); mins = b.minutes or 0
    hits = name_in_title(title)
    if hits:
        b_name += 1; m_name += mins
        # record which tokens matched
        for tok, cname, kind in hits:
            token_hits[(tok, cname, kind)] += 1
        primary = hits[0]
        risky = (len(primary[0]) <= 5) or (primary[2] == "code")
        rec = (mins, primary[1], primary[0], primary[2], title[:60])
        if risky and len(name_suspicious) < 25:
            name_suspicious.append(rec)
        elif not risky and len(name_samples) < 25:
            name_samples.append(rec)
        continue
    if is_junk(title):
        b_junk += 1; m_junk += mins; continue
    cname = adjacent_client(b)
    if cname:
        b_clue += 1; m_clue += mins
        if len(clue_samples) < 12:
            clue_samples.append((mins, cname, title[:55]))
        continue
    b_ambig += 1; m_ambig += mins

def pct(n): return f"{(100*n/total):.0f}%" if total else "0%"
def hrs(m): return f"{m/60:.1f}h"

print("="*70)
print(f"ORG {ORG_ID} — PASS 2 (idle excluded from adjacency; outlook out of junk)")
print("="*70)
print(f"TOTAL uncategorized blocks: {total}")
print(f"  real-client attributed blocks for adjacency: {len(attributed)}")
print("-"*70)
print(f"(a) CLIENT NAME IN TITLE   {b_name:4d}  {pct(b_name):>4}   {hrs(m_name):>7}")
print(f"(b) CLEAN ADJACENT CLUE    {b_clue:4d}  {pct(b_clue):>4}   {hrs(m_clue):>7}")
print(f"(c) AUTH/CHROME JUNK       {b_junk:4d}  {pct(b_junk):>4}   {hrs(m_junk):>7}")
print(f"(d) GENUINELY AMBIGUOUS    {b_ambig:4d}  {pct(b_ambig):>4}   {hrs(m_ambig):>7}")
print("-"*70)
print("TOP MATCHING TOKENS in (a) [matches | token -> client | kind] — scan for junk:")
for (tok, cname, kind), cnt in token_hits.most_common(20):
    flag = "  <-- short/risky" if (len(tok) <= 5 or kind == "code") else ""
    print(f"   {cnt:4d}  '{tok}' -> {cname[:28]:28s} ({kind}){flag}")
print("-"*70)
print("CLEAN name-in-title samples [mins | client | token | kind | title]:")
for mins, cname, tok, kind, title in name_samples[:15]:
    print(f"   {mins:3d}m  {cname[:20]:20s}  '{tok}'({kind})  {title}")
print("-"*70)
print("SUSPICIOUS name matches (short token or code — VERIFY these):")
for mins, cname, tok, kind, title in name_suspicious[:15]:
    print(f"   {mins:3d}m  {cname[:20]:20s}  '{tok}'({kind})  {title}")
print("-"*70)
print("(b) clean-clue samples (should now be REAL clients, not idle):")
for mins, cname, title in clue_samples:
    print(f"   {mins:3d}m  {cname[:20]:20s}  {title}")
print("="*70)
