"""READ-ONLY before/after shadow for the alias-matcher fix.

Bug: 'repair'/'sales' are not in DOMAIN_COMMON_WORDS, so client
'All Round Repair & Sales Corp' (154) matches the unrelated title
'All Around Auto Repair and Sales Corp INC' on tokens repair+sales+round.

This shadow does NOT change anything. It:
  1. For the 9 known-bad blocks, re-runs the CURRENT matcher and prints score.
  2. Simulates the candidate fix (add business-generic words to the common set)
     and prints what the score WOULD be.
  3. Scans ALL proposed/committed blocks from the last 14 days and reports any
     CURRENTLY-matching alias hit that the fix would BREAK (so we see collateral
     damage before applying).
"""
from datetime import date, timedelta
from django.utils import timezone
from tracker.models import Block, Client
from tracker.services.classification_service import ClassificationService as CS

# --- candidate additions (business-generic words that shouldn't be distinctive) ---
CANDIDATE_EXTRA = {'repair', 'sales', 'auto', 'rentals', 'rental', 'supply', 'supplies'}

KNOWN_BAD = [44755, 44573, 44565, 44569, 44561, 44575, 44237, 44238, 41240]

def distinctive_after(tokens, common):
    return [t for t in tokens if t not in common]

print("="*72)
print("PART 1 — current distinctive tokens for client 154 vs candidate")
print("="*72)
c154 = Client.objects.filter(id=154).first()
if c154:
    import re
    name_toks = [t for t in re.findall(r'[a-z0-9]+', (c154.name or '').lower())]
    cur_common = CS.__dict__.get('DOMAIN_COMMON_WORDS') or None
    # DOMAIN_COMMON_WORDS is module-level; import it
    from tracker.services import classification_service as csm
    DCW = csm.DOMAIN_COMMON_WORDS
    print(f"client 154 name: {c154.name!r}  tokens={name_toks}")
    print(f"  CURRENT distinctive: {distinctive_after(name_toks, DCW)}")
    print(f"  WITH FIX  distinctive: {distinctive_after(name_toks, DCW | CANDIDATE_EXTRA)}")
    print(f"  aliases: {getattr(c154,'aliases',None)}")

print("\n" + "="*72)
print("PART 2 — the 9 known-bad blocks: current proposed match")
print("="*72)
for bid in KNOWN_BAD:
    b = Block.objects.filter(id=bid).select_related('proposed_client').first()
    if not b:
        print(f"  {bid}: not found"); continue
    print(f"  {bid}: '{(b.window_title or '')[:45]}' → "
          f"{b.proposed_client.name if b.proposed_client_id else 'None'} "
          f"(conf {getattr(b,'proposed_confidence',0)})")

print("\n" + "="*72)
print("PART 3 — COLLATERAL CHECK: which real clients contain candidate words?")
print("  (these are the clients whose matching could be AFFECTED by the fix)")
print("="*72)
import re
for c in Client.objects.filter(is_active=True):
    toks = set(re.findall(r'[a-z0-9]+', (c.name or '').lower()))
    hit = toks & CANDIDATE_EXTRA
    if hit:
        from tracker.services import classification_service as csm
        DCW = csm.DOMAIN_COMMON_WORDS
        name_toks = re.findall(r'[a-z0-9]+', (c.name or '').lower())
        cur_d = distinctive_after(name_toks, DCW)
        fix_d = distinctive_after(name_toks, DCW | CANDIDATE_EXTRA)
        flag = "  <-- LOSES ALL DISTINCTIVE TOKENS!" if not fix_d else ""
        print(f"  id={c.id} {c.name!r} contains {hit}")
        print(f"       current distinctive={cur_d}  with-fix={fix_d}{flag}")
print("="*72)
print("READ: any client flagged 'LOSES ALL DISTINCTIVE TOKENS' would stop")
print("matching under the fix — those are the ones to protect. If none, fix is safe.")
print("="*72)
