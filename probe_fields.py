"""
READ-ONLY. Before building the accuracy query, find what fields capture:
  - the AI's suggestion (proposed_client_id / proposed_category / proposed_confidence)
  - what the block ended up as (client_id / category_hours / is_billable)
  - whether a human touched it (categorized_by, classification_state, audit)
so we can measure 'AI suggestion vs final human choice' for real.
"""
from tracker.models import Block
import django.db.models as m

# List all field names on Block so we know what's available
fields = [f.name for f in Block._meta.get_fields()]
print("="*70)
print("Block fields available:")
print("="*70)
interesting = [f for f in fields if any(k in f.lower() for k in
              ("propos","confiden","categor","client","billable","state","source","ai","suggest"))]
for f in sorted(interesting):
    print(f"  {f}")
print("="*70)

# Sample a few org-21 blocks that have a proposed_confidence to see the shape
from datetime import date, timedelta
recent = date(2026,6,22) - timedelta(days=14)
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=recent)
print(f"Org-21 blocks last 14 days: {qs.count()}")

# How many have a usable confidence signal?
def has(attr):
    try:
        return qs.exclude(**{attr: None}).count()
    except Exception:
        return "n/a"
for attr in ("proposed_confidence","proposed_client_id","proposed_category","categorized_by"):
    print(f"  non-null {attr}: {has(attr)}")
print("="*70)

# Peek at one fully-populated example
ex = qs.exclude(proposed_confidence=None).exclude(client_id=None).first()
if ex:
    print("Example block with proposal + final client:")
    for a in ("id","proposed_client_id","client_id","proposed_confidence",
              "proposed_category","is_billable","classification_state","categorized_by"):
        print(f"  {a} = {getattr(ex, a, '(none)')}")
    print(f"  category_hours = {ex.category_hours}")
print("="*70)
