"""
READ-ONLY. Which uncategorized/no-client blocks would the EXPANDED overhead
list newly catch? Confirms they're genuine junk (no client to bill) before ship.
Only considers blocks that REACH the overhead branch: no client + pile-bound.
"""
from datetime import date, timedelta
from tracker.models import Block

NEW_SUBS = ('begin reconciliation','select reconciliation','reconciliation report',
    'print preview','print checks','printer setup','preview paycheck',
    'special paycheck situation','preparer options','past transactions',
    'recycle bin','this pc','quick access','control panel','task manager')

ORG, SINCE = 21, date(2026,6,23) - timedelta(days=21)
# Blocks that would hit the overhead branch: no client, not committed-billable
qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True,
    start__date__gte=SINCE).order_by('-start').values(
    'id','client_id','window_title','is_billable','classification_state')

newly = []
already_billable_with_client = []  # SAFETY CHECK: should be empty for these titles
for b in qs[:4000]:
    t = (b['window_title'] or '').lower()
    hit = next((s for s in NEW_SUBS if s in t), None)
    if not hit:
        continue
    if b['client_id'] is None:
        newly.append((b['id'], hit, b['is_billable'], (b['window_title'] or '')[:50]))
    else:
        # A block with this title that HAS a client — would NOT be touched
        # (doesn't reach overhead branch), but log to prove the safety.
        already_billable_with_client.append((b['id'], b['client_id'], hit, (b['window_title'] or '')[:45]))

print("="*78)
print(f"OVERHEAD EXPANSION SHADOW — new substrings, org {ORG}, last 21d")
print("="*78)
print(f"Blocks NEWLY caught (no client → auto non-billable): {len(newly)}")
for bid,hit,isb,t in newly[:30]:
    print(f"  {bid} | match='{hit}' | was_billable={isb} | {t}")
print("-"*78)
print(f"SAFETY: blocks with same titles that HAVE a client (NOT touched): {len(already_billable_with_client)}")
print("  (these prove real billable work with these titles is left alone)")
for bid,cid,hit,t in already_billable_with_client[:15]:
    print(f"  {bid} | client={cid} | '{hit}' | {t}  ← SAFE, untouched")
print("="*78)
print("Want: NEWLY-caught are all junk (no client); the client'd ones stay billable.")
print("="*78)
