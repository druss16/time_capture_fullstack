"""
Run the REAL classify+apply path on ONE overhead block (43609) and show exactly
what state it lands in. This WRITES one block — but only one, and one we
shadow-approved. Proves the mechanism before touching the other 75.
"""
from tracker.models import Block, Organization
from tracker.services.classification_service import ClassificationService
from django.db import transaction

TEST_ID = 43609  # first overhead block from the shadow-approved set
org = Organization.objects.get(id=21)
b = Block.objects.get(id=TEST_ID)

print("="*70)
print(f"BEFORE — block {b.id}:")
print(f"  title: {(b.window_title or '')[:50]}")
print(f"  state={b.classification_state}  is_billable={b.is_billable}  "
      f"is_categorized={b.is_categorized}  category={b.category_hours}")
print("="*70)

svc = ClassificationService(org=org, user=b.user)
decision = svc.classify(b, skip_ai=True)

print("DECISION (not yet applied):")
print(f"  recommended_state={decision.recommended_state}")
print(f"  is_billable={decision.is_billable}  category={decision.category}")
sigs = [(s.type, round(s.strength,2)) for s in decision.matched_signals]
print(f"  signals={sigs}")
has_overhead = any(s.type=='overhead_auto_nonbillable' for s in decision.matched_signals)
print(f"  >>> carries overhead_auto_nonbillable signal: {has_overhead}")
print(f"  >>> would commit (recommended_state=='committed'): {decision.recommended_state=='committed'}")
print("="*70)

if decision.recommended_state == 'committed' and has_overhead:
    with transaction.atomic():
        svc.apply(b, decision, source='classifier')
    b.refresh_from_db()
    print(f"APPLIED. AFTER — block {b.id}:")
    print(f"  state={b.classification_state}  is_billable={b.is_billable}  "
          f"is_categorized={b.is_categorized}  category={b.category_hours}")
    print("  ✓ One block proven. If this looks right, run the other 75.")
else:
    print("NOT APPLIED — decision didn't commit as overhead. Stop and inspect;")
    print("the auto-commit logic isn't firing as expected on this block.")
print("="*70)
