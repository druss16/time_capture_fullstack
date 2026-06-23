"""
READ-ONLY. Shadow matched 0%. Find out why: are these churches CLIENTS at all?
And is the QBW title a truncated PREFIX of the client name (so 'name in title'
fails but 'title-prefix matches name' would work)?
"""
import re
from tracker.models import Client

ORG = 21
def norm(s): return re.sub(r'[^a-z0-9 ]','',(s or '').lower()).strip()

clients = list(Client.objects.filter(org_id=ORG, is_active=True))
print(f"Total active clients org {ORG}: {len(clients)}")
print("="*80)

# Do church/known titles exist as clients?
probes = ["franciscan","transfiguration","st. paul","st paul","annunciation",
          "church","parish","upstate","oswald"]
print("Clients whose name/alias contains probe words from the uncategorized titles:")
for p in probes:
    hits = [c for c in clients if p in norm(c.name) or any(p in norm(a) for a in (c.aliases or []))]
    if hits:
        for c in hits[:4]:
            print(f"  '{p}' → client {c.id}: {c.name!r}  aliases={c.aliases}")
    else:
        print(f"  '{p}' → NO CLIENT FOUND")
print("="*80)

# Now test BOTH match directions on the actual titles
titles = [
    "Franciscan Church of the Ass",
    "Transfiguration of Our Lord",
    "St. Paul's Church  - Qui",
    "The Church of the Annunc",
    "ERC Credits by Parish.xlsx",
]
print("Match-direction test on real titles:")
for t in titles:
    nt = norm(t)
    fwd = [c.name for c in clients if norm(c.name) and norm(c.name) in nt]   # name IN title
    rev = [c.name for c in clients if norm(c.name) and nt[:18] and nt[:18] in norm(c.name)]  # title-prefix in name
    # token overlap
    ttok = set(nt.split())
    tok = [(c.name, len(ttok & set(norm(c.name).split())))
           for c in clients if len(ttok & set(norm(c.name).split())) >= 2]
    tok.sort(key=lambda x:-x[1])
    print(f"\n  title={t!r}")
    print(f"    name-in-title: {fwd[:3] or 'none'}")
    print(f"    title-prefix-in-name: {rev[:3] or 'none'}")
    print(f"    2+ token overlap: {tok[:3] or 'none'}")
print("="*80)
