"""READ-ONLY. Why does 41190 survive the stickiness guard when the other 11
cleared? Inspect its signals — the guard clears when ONLY agent_current_client
attests. Maybe 41190 has a second signal, or the moderate-signal trigger differs."""
from tracker.models import Block, Organization
from tracker.services.classification_service import ClassificationService

b = Block.objects.get(id=41190)
print("="*66)
print(f"Block 41190: {(b.window_title or '')[:50]}")
print(f"  stored client={b.client_id} billable={b.is_billable} state={b.classification_state}")
print(f"  STORED proposed_signals:")
for s in (getattr(b,'proposed_signals',None) or []):
    cid = (s.get('detail') or {}).get('client_id')
    print(f"    type={s.get('type'):28} str={s.get('strength')} client={cid}")
print("="*66)
org = Organization.objects.get(id=21)
d = ClassificationService(org=org, user=b.user).classify(b, skip_ai=True)
print(f"RECLASSIFY decision: client={d.client_id} billable={d.is_billable} state={d.recommended_state}")
print(f"  decision signals:")
for s in d.matched_signals:
    print(f"    type={s.type:28} str={s.strength:.2f} client={s.proposed_client_id}")
print("="*66)
# The guard clears only if the ONLY attesting signal is agent_current_client.
cid = d.client_id
if cid:
    attesting = [s for s in d.matched_signals if s.proposed_client_id == cid]
    print(f"Signals attesting to client {cid}: {[s.type for s in attesting]}")
    non_stick = [s for s in attesting if s.type != 'agent_current_client']
    print(f"Non-stickiness attesting: {[s.type for s in non_stick]}")
    if non_stick:
        print("→ Guard correctly does NOT fire: a non-stickiness signal attests.")
        print(f"  So 451 is backed by {non_stick[0].type}, not pure stickiness.")
        print("  This may be a LEGIT match, not the Mets pattern. Check the title.")
print("="*66)
