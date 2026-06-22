"""
READ-ONLY analysis of org 21's uncategorized blocks.
Buckets the pile into the three populations that determine the redesign:
  (a) client name sits in the title  -> mechanical win (name matching)
  (b) clean single adjacent client   -> the "likely X" chip fires
  (c) pure auth/chrome/overhead      -> "mark overhead" / suppress
  (d) genuinely ambiguous            -> manual review, no shortcut

Run:
  docker compose exec api python manage.py shell < bucket_uncategorized.py

Writes NOTHING. Pure SELECTs.
"""
from datetime import timedelta
from django.utils import timezone
from tracker.models import Block, Client

ORG_ID = 21
LOOKBACK_DAYS = 30
ADJACENCY_WINDOW_MIN = 30   # how close an adjacent attributed block must be to count as a "clue"

# auth / chrome / navigation noise patterns (lowercased substring match)
JUNK_PATTERNS = [
    "log in", "login", "sign in", "sign-in", "phone code", "verification",
    "new tab", "region selection", "working...", "sharing link validation",
    "authenticator", "two-factor", "2fa", "mfa", "redirecting", "loading",
    "sign in to your account", "office", "outlook", "inbox",
]

now = timezone.now()
since = now - timedelta(days=LOOKBACK_DAYS)

# Uncategorized = not categorized, not suppressed, not deleted (mirrors Categorize tab)
qs = (Block.objects
      .filter(org_id=ORG_ID, is_categorized=False, deleted_at__isnull=True)
      .exclude(classification_state="suppressed")
      .filter(start__gte=since)
      .order_by("start"))

# Build client name/code/alias vocabulary for title-match test
clients = list(Client.objects.filter(org_id=ORG_ID))
name_tokens = []
for c in clients:
    if c.name and len(c.name) >= 4:
        name_tokens.append((c.name.lower(), c.id, c.name))
    if getattr(c, "code", None) and len(c.code) >= 3:
        name_tokens.append((c.code.lower(), c.id, c.name))
    for a in (getattr(c, "aliases", None) or []):
        if isinstance(a, str) and len(a) >= 4:
            name_tokens.append((a.lower(), c.id, c.name))

# Index attributed blocks by time for adjacency lookup
attributed = list(Block.objects
                  .filter(org_id=ORG_ID, deleted_at__isnull=True, client__isnull=False)
                  .filter(start__gte=since)
                  .values("id", "start", "end", "client_id", "client__name")
                  .order_by("start"))

def title_of(b):
    return (b.window_title or "").strip()

def has_client_name_in_title(title):
    t = title.lower()
    for tok, cid, cname in name_tokens:
        if tok in t:
            return cname
    return None

def is_junk(title):
    t = title.lower()
    return any(p in t for p in JUNK_PATTERNS)

def adjacent_client(b):
    """Return (client_name, n_distinct_clients_in_window). Clue is 'clean' only if exactly 1."""
    lo = b.start - timedelta(minutes=ADJACENCY_WINDOW_MIN)
    hi = (b.end or b.start) + timedelta(minutes=ADJACENCY_WINDOW_MIN)
    near = set()
    name = None
    for a in attributed:
        if a["id"] == b.id:
            continue
        if a["start"] <= hi and (a["end"] or a["start"]) >= lo:
            near.add(a["client_id"])
            name = a["client__name"]
    if len(near) == 1:
        return name, 1
    return None, len(near)

blocks = list(qs)
total = len(blocks)

b_name = 0          # (a) name in title
b_clue = 0          # (b) clean single adjacent client
b_junk = 0          # (c) auth/chrome junk
b_ambig = 0         # (d) nothing
mins_name = mins_clue = mins_junk = mins_ambig = 0

# precedence: name-in-title > junk > clean-clue > ambiguous
# (name match is the strongest/cheapest; junk should be suppressed regardless of a stray clue)
sample_clue = []
for b in blocks:
    title = title_of(b)
    mins = b.minutes or 0
    nm = has_client_name_in_title(title)
    if nm:
        b_name += 1; mins_name += mins; continue
    if is_junk(title):
        b_junk += 1; mins_junk += mins; continue
    cname, ndist = adjacent_client(b)
    if cname:
        b_clue += 1; mins_clue += mins
        if len(sample_clue) < 8:
            sample_clue.append((title[:50], cname, mins))
        continue
    b_ambig += 1; mins_ambig += mins

def pct(n): return f"{(100*n/total):.0f}%" if total else "0%"
def hrs(m): return f"{m/60:.1f}h"

print("="*64)
print(f"ORG {ORG_ID} — uncategorized blocks, last {LOOKBACK_DAYS} days")
print("="*64)
print(f"TOTAL uncategorized blocks: {total}")
print(f"  total clients in vocab: {len(clients)}  ({len(name_tokens)} match tokens)")
print(f"  attributed blocks for adjacency: {len(attributed)}")
print("-"*64)
print(f"(a) CLIENT NAME IN TITLE   {b_name:4d}  {pct(b_name):>4}   {hrs(mins_name):>7}")
print(f"(b) CLEAN ADJACENT CLUE    {b_clue:4d}  {pct(b_clue):>4}   {hrs(mins_clue):>7}   <- blue 'likely X' chip fires here")
print(f"(c) AUTH/CHROME JUNK       {b_junk:4d}  {pct(b_junk):>4}   {hrs(mins_junk):>7}   <- 'overhead' / suppress")
print(f"(d) GENUINELY AMBIGUOUS    {b_ambig:4d}  {pct(b_ambig):>4}   {hrs(mins_ambig):>7}   <- manual, no shortcut")
print("-"*64)
print("sample of (b) clean-clue blocks [title -> adjacent client, mins]:")
for t, c, m in sample_clue:
    print(f"   {m:3d}m  {c:22s}  {t}")
print("="*64)
