"""
Diagnostic: does TL Wall actually have override-rate HISTORY to chart?

Run against the dev container (reads the live Neon DB via your normal settings):

    docker compose exec -T api python manage.py shell < check_override_history.py

It prints, for the last 8 ISO weeks, for org 21 (TL Wall):
  - ai_decisions  = blocks categorized_by='ai' + 'correction' (the denominator)
  - corrections   = blocks categorized_by='correction'        (overrides)
  - override_rate = corrections / ai_decisions

If 'corrections' is 0 across the board, the line chart has nothing to plot and
the honest move is to NOT show it yet. If there ARE corrections, the trend
endpoint will render a real line and we ship it.

Also prints the distinct categorized_by values present, so if corrections are
being stored under a DIFFERENT label than 'correction', we'll see it here and
can point the endpoint at the right value.
"""
from datetime import timedelta
from collections import Counter
from django.utils import timezone
from django.db.models import Count
from tracker.models import Block

ORG_ID = 21  # TL Wall Accounting

today = timezone.localdate()
# Monday of the current week
this_monday = today - timedelta(days=today.weekday())

print("\n=== categorized_by values present for org 21 (all time) ===")
vals = (
    Block.objects.filter(org_id=ORG_ID, deleted_at__isnull=True)
    .values_list("categorized_by", flat=True)
)
counter = Counter((v or "<null>") for v in vals)
for k, n in counter.most_common():
    print(f"  {k:<20} {n:>7}")

print("\n=== Weekly override history (last 8 weeks), org 21 ===")
print(f"  {'week of':<12} {'ai_decisions':>13} {'corrections':>12} {'override%':>10}")
any_corrections = False
for w in range(8):
    wk_start = this_monday - timedelta(days=7 * (7 - w))  # oldest → newest
    wk_end = wk_start + timedelta(days=7)
    qs = Block.objects.filter(
        org_id=ORG_ID,
        deleted_at__isnull=True,
        start__date__gte=wk_start,
        start__date__lt=wk_end,
    )
    cb = Counter(
        (b.categorized_by or "").lower()
        for b in qs.only("categorized_by")
    )
    ai_blocks = cb.get("ai", 0)
    corrections = cb.get("correction", 0)
    ai_decisions = ai_blocks + corrections
    rate = round(100 * corrections / ai_decisions, 1) if ai_decisions else 0.0
    if corrections:
        any_corrections = True
    print(f"  {wk_start.isoformat():<12} {ai_decisions:>13} {corrections:>12} {rate:>9}%")

print("\n=== VERDICT ===")
if any_corrections:
    print("  ✅ Corrections exist — the trend chart will plot a REAL line. Ship it.")
else:
    print("  ⚠️  No corrections recorded in the last 8 weeks.")
    print("     The override-rate chart would be flat at 0% — no story to tell yet.")
    print("     Either (a) nobody has corrected an AI guess, or (b) corrections are")
    print("     stored under a different categorized_by value (see the list above).")
