"""READ-ONLY final check: the 11 blocks' current state, and confirm no
Mets-class (stickiness-only + billing) blocks remain in the 14d window."""
from datetime import date, timedelta
from tracker.models import Block

IDS = [44728, 44669, 44667, 44668, 44620, 44476, 44475, 44474, 44468, 44334, 44243]
print("Cleanup batch — final state of the 11:")
for bid in IDS:
    b = Block.objects.get(id=bid)
    print(f"  {bid}: client={b.client_id} billable={b.is_billable} state={b.classification_state} | {(b.window_title or '')[:30]}")

print("\nRemaining stickiness-only billing blocks in 14d:")
since = date(2026,6,23)-timedelta(days=14)
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state='proposed', is_billable=True, client_id__isnull=False)
n=0
for b in qs:
    sigs=getattr(b,'proposed_signals',None) or []; cid=b.client_id
    att=[s for s in sigs if isinstance(s,dict) and (s.get('detail') or {}).get('client_id')==cid]
    if att and all(s.get('type')=='agent_current_client' for s in att): n+=1
print(f"  count: {n}  (the legit org_rule/title ones like 41190/44669 are NOT counted)")
