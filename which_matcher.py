"""
READ-ONLY. Stop guessing across 3 matchers. For the actual Mets block, dump
the EXACT signals and source so we know which matcher attributed it. Then test
whether the backend FIX A (already in the container) changes it on re-classify.
"""
from tracker.models import Block, Organization
from tracker.services.classification_service import ClassificationService

b = Block.objects.filter(org_id=21, window_title__icontains="Syracuse Mets").order_by('-start').first()
if not b:
    print("No Mets block found"); raise SystemExit

print("="*72)
print(f"Block {b.id}: {(b.window_title or '')[:60]}")
print(f"  CURRENT: client_id={b.client_id} state={b.classification_state} "
      f"billable={b.is_billable} categorized_by={b.categorized_by}")
print(f"  proposed_signals (what attributed it):")
for s in (getattr(b,'proposed_signals',None) or []):
    print(f"    - type={s.get('type')} strength={s.get('strength')} "
          f"client={s.get('detail',{}).get('client_id')}")
    print(f"      evidence: {s.get('evidence','')[:80]}")
print("="*72)

# Now RE-CLASSIFY with the backend FIX A live in the container
org = Organization.objects.get(id=21)
svc = ClassificationService(org=org, user=b.user)
decision = svc.classify(b, skip_ai=True)
print(f"RE-CLASSIFY with FIX A (backend), skip_ai=True:")
print(f"  decision client_id={decision.client_id} state={decision.recommended_state} "
      f"billable={decision.is_billable}")
print(f"  signals now:")
for s in decision.matched_signals:
    print(f"    - {s.type} str={s.strength:.2f} client={s.proposed_client_id} | {s.evidence[:60]}")
print("="*72)
if decision.client_id != 439:
    print("✓ FIX A changes it — backend no longer attributes to Transfiguration (439)")
else:
    print("✗ FIX A does NOT fix it — still attributes to 439. Bug is elsewhere")
    print("  (agent-side, or a different signal). Backend fix alone insufficient.")
print("="*72)
