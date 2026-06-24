"""
Preview the TOUCH-FREE rate trend for TL Wall before we build a chart on it.

Touch-free = a block the agent captured + the AI/rules classified, that NO human
edited. "Touched" = categorized_by in {manual, correction} (a person typed or
corrected it). Everything classified by the automation (ai/pattern/learned/
deterministic/meeting_detector/tax_software) and never corrected = touch-free.

We compute it as:  touch_free / classified_total   per week, last 8 weeks.

Run:
    docker compose exec -T api python manage.py shell < check_touchfree.py
"""
from datetime import timedelta
from collections import Counter
from django.utils import timezone
from tracker.models import Block

ORG_ID = 21

# Same source buckets the report treats as "automation did it":
AUTOMATED = {"ai", "pattern", "learned", "deterministic", "meeting_detector", "tax_software"}
# A human touched it:
TOUCHED   = {"manual", "correction"}
# Ignore admin/bulk + unclassified entirely (not part of the success ratio):
IGNORE    = {"system", "import", ""}

today = timezone.localdate()
this_monday = today - timedelta(days=today.weekday())

print("\n=== Touch-free rate, last 8 weeks, org 21 ===")
print(f"  {'week of':<12} {'touch_free':>10} {'touched':>8} {'classified':>11} {'touch-free%':>12}")
prev = None
for w in range(8):
    ws = this_monday - timedelta(days=7 * (7 - w))   # oldest → newest
    we = ws + timedelta(days=7)
    cb = Counter(
        (b.categorized_by or "").lower()
        for b in Block.objects.filter(
            org_id=ORG_ID, deleted_at__isnull=True,
            start__date__gte=ws, start__date__lt=we,
        ).only("categorized_by")
    )
    touch_free = sum(cb.get(k, 0) for k in AUTOMATED)
    touched    = sum(cb.get(k, 0) for k in TOUCHED)
    classified = touch_free + touched      # exclude system/import/null
    rate = round(100 * touch_free / classified, 1) if classified else None
    arrow = ""
    if rate is not None and prev is not None:
        arrow = "↑" if rate > prev else "↓" if rate < prev else "→"
    prev = rate if rate is not None else prev
    rate_s = "—" if rate is None else f"{rate}%"
    print(f"  {ws.isoformat():<12} {touch_free:>10} {touched:>8} {classified:>11} {rate_s:>11} {arrow}")

print("\n=== READ ===")
print("  If the touch-free% column climbs left→right, this is your success line.")
print("  If it's flat near 100% the whole time, it's true but boring (no story yet).")
print("  If it FALLS, that's the same adoption effect as override — more review =")
print("  more touches early on — and we'd frame it as 'settling in', not regress.")
