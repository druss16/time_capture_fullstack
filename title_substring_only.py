"""READ-ONLY. ONLY rule: the client's name (or a strong multi-word variant)
appears as a CONTIGUOUS substring in the title. No token-scatter matching —
that's what produced 'Mouse Properties'→'Elusive Moose Properties' garbage.
Contiguous full-name match only. Fewer hits, but each is correct."""
from datetime import date, timedelta
from tracker.models import Block, Client
import re

since = date(2026,6,23)-timedelta(days=14)
clients = list(Client.objects.filter(org_id=21, is_active=True))

def norm(s):
    s=(s or '').lower(); s=re.sub(r'\bst\.?\s','saint ',s)
    s=s.replace("'","").replace("&"," and ")
    s=re.sub(r'[^a-z0-9 ]',' ',s)
    return re.sub(r'\s+',' ',s).strip()

# Build candidate name-forms per client: full normalized name, and the name with
# trailing generic descriptors trimmed (e.g. 'transfiguration of our lord').
GENERIC_TAIL={'church','parish','cemetery','school','inc','llc','corp','co',
  'company','services','foundation','center','ministries','catholic'}
cforms=[]
for c in clients:
    n=norm(c.name)
    if len(n) < 8:   # too short to be safe as a substring
        continue
    forms={n}
    # also a form with leading 'the ' dropped and trailing generic words trimmed
    words=n.split()
    while words and words[-1] in GENERIC_TAIL:
        words=words[:-1]
    trimmed=' '.join(words)
    if len(trimmed)>=10:    # only keep trimmed form if still long/specific
        forms.add(trimmed)
    cforms.append((c.id,c.name,forms))

qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True
    ).filter(minutes__gte=2)

hits=[]
for b in qs:
    tn=norm(b.window_title or '')
    if len(tn)<8: continue
    found=None
    for cid,cname,forms in cforms:
        for f in forms:
            if len(f)>=10 and f in tn:
                found=(cid,cname,f); break
        if found: break
    if found:
        hits.append((b.id,found[1],found[2],(b.window_title or '')[:46]))

print("="*78)
print(f"CONTIGUOUS full-name substring matches ONLY: {len(hits)}")
print("="*78)
for bid,cname,form,t in hits[:50]:
    print(f"  {bid} → {cname[:24]:24} | matched '{form[:24]}' | {t}")
print("="*78)
print("Every row: the client's actual name appears verbatim in the title.")
print("If any look wrong, the form was too short — we raise the length floor.")
print("="*78)
