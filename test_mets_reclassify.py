"""
READ-ONLY (no apply). Does a fresh reclassify of the Mets block, with FIX A live,
now WANT to clear the bad 439 attribution? Shows the decision without writing.
If recommended client is None/not-439, the backend fix + FIX 7 resolve it on
the next real reclassify — no agent fix needed for the BACKEND to stop holding it.
"""
from tracker.models import Block, Organization
from tracker.services.classification_service import ClassificationService

b = Block.objects.filter(org_id=21, window_title__icontains="Syracuse Mets").order_by('-start').first()
org = Organization.objects.get(id=21)

# IMPORTANT: simulate a fresh classify where the agent stickiness is the only
# 439 signal. The decision's FINAL client tells us what apply() WOULD write.
svc = ClassificationService(org=org, user=b.user)
decision = svc.classify(b, skip_ai=True)

print("="*70)
print(f"Block {b.id} — what apply() WOULD do with backend fix live:")
print(f"  final client_id = {decision.client_id}")
print(f"  recommended_state = {decision.recommended_state}")
print(f"  is_billable = {decision.is_billable}")
print(f"  reasoning = {decision.reasoning[:120]}")
print("="*70)
if decision.client_id != 439:
    print("✓ Backend fix RESOLVES it: reclassify would clear the bad 439 attribution.")
    print("  → A scoped reclassify of affected blocks cleans them up. No agent")
    print("    fix strictly required to stop the BACKEND from holding Mets→439.")
    print("  → Agent fix still wanted so the agent stops SELECTING 439 live,")
    print("    but the billing-visible mis-attribution is fixed backend-side.")
else:
    print("✗ Still 439 — agent_current_client is holding it even post-fix.")
    print("  Need to clear stale agent client or fix agent matcher.")
print("="*70)
