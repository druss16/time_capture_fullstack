"""
Test the FIXED recategorize logic on ONE block (44390, a 1m Mets sibling).
Simulates what the endpoint now does — preserve duration, clear client to None.
Read state before, apply, verify, so we trust it before the 80m block / deploy.
NOTE: this WRITES to one block. Chosen: 44390 (1m, low risk, clearly mis-billed).
"""
from tracker.models import Block, Client
from django.utils import timezone

BID = 44390
b = Block.objects.get(id=BID)
print("="*60)
print(f"BEFORE: block {BID}")
print(f"  client_id={b.client_id} is_billable={b.is_billable}")
print(f"  category_hours={b.category_hours}")
print(f"  sum={sum((b.category_hours or {}).values()):.4f}h state={b.classification_state}")
print("="*60)

# Simulate the endpoint's NEW logic for a "move to No Client" (client_id=null)
def _is_nonbillable_category(category):
    return (category or '').strip().lower() in {'personal/non-billable','idle','uncategorized'}

new_category = 'Personal/Non-Billable'   # No-Client default
client_provided = True
new_client_id = None

existing_total = sum((b.category_hours or {}).values())
if existing_total <= 0:
    existing_total = (b.end - b.start).total_seconds()/3600 if b.end and b.start else 0
b.category_hours = {new_category: round(existing_total, 4)}
if client_provided:
    if new_client_id is None:
        b.client = None
        b.is_billable = False
b.categorized_by = 'correction'
b.categorized_at = timezone.now()
b.is_categorized = True
b.classification_state = 'committed'
b.save(force_update=True)

b.refresh_from_db()
print(f"AFTER: block {BID}")
print(f"  client_id={b.client_id} is_billable={b.is_billable}")
print(f"  category_hours={b.category_hours}")
print(f"  sum={sum((b.category_hours or {}).values()):.4f}h state={b.classification_state}")
print("="*60)
ok = (b.client_id is None and b.is_billable is False
      and abs(sum(b.category_hours.values()) - existing_total) < 0.001)
print("✓ PASS — duration preserved, client cleared, non-billable" if ok else "✗ CHECK FAILED")
print(f"  (duration kept at {existing_total:.4f}h, was NOT recomputed/lost)")
print("="*60)
