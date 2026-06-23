"""
READ-ONLY SHADOW. Find blocks currently attributed to a client ONLY via weak
stale agent-stickiness (the Mets-class bug), now that the fix is deployed.
Re-classify each with the new code and show what WOULD change. No writes.
Discipline: shadow → one-block proof → scoped batch by explicit ID.
"""
from datetime import date, timedelta
from tracker.models import Block, Organization, Client

ORG = 21
org = Organization.objects.get(id=21)

# Same logic as the fast guard check: client attested ONLY by uncorroborated
# agent_current_client, with a clientless moderate signal present.
REAL = {'title_match_title_alias','title_match_file_path','title_match_domain',
        'file_path_structure','file_path_client_folder','mail','calendar',
        'learned_pattern','org_rule','tax_software','qb_company_file','agent_inference'}

qs = Block.objects.filter(org_id=ORG, deleted_at__isnull=True,
    client_id__isnull=False).order_by('-start').values(
    'id','client_id','window_title','proposed_signals','is_billable','start')

candidates = []
for b in qs[:3000]:
    cid = b['client_id']; sigs = b['proposed_signals'] or []
    attesting = [s for s in sigs if isinstance(s,dict)
                 and (s.get('detail') or {}).get('client_id')==cid]
    if not attesting: continue
    non_stick = [s for s in attesting if s.get('type')!='agent_current_client']
    corrob = any(s.get('type')=='agent_current_client' and (s.get('detail') or {}).get('corroborated')
                 for s in attesting)
    had_real = any(s.get('type') in REAL for s in attesting)
    if not non_stick and not corrob and not had_real:
        has_mod = any((s.get('strength') or 0)>=0.65 for s in sigs)
        if has_mod:
            candidates.append((b['id'], cid, b['is_billable'], (b['window_title'] or '')[:50], b['start']))

cmap = {c.id: c.name for c in Client.objects.filter(org_id=ORG)}
print("="*80)
print(f"METS-CLASS CLEANUP SHADOW — blocks attributed ONLY via stale stickiness")
print(f"  {len(candidates)} blocks would have their bad client cleared")
print("="*80)
bill = [c for c in candidates if c[2]]
print(f"  Of those, BILLABLE (actively mis-charging a client): {len(bill)}")
print("-"*80)
for bid,cid,isb,t,start in candidates[:40]:
    flag = "💰BILLABLE" if isb else "non-bill"
    print(f"  {bid} | {cmap.get(cid,cid)[:24]:24} | {flag:10} | {t}")
print("="*80)
print("These would be cleared to no-client (non-billable) on reclassify.")
print("Next: prove on ONE block, then batch by explicit ID list.")
print("="*80)
