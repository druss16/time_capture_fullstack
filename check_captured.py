"""
Preview the CUMULATIVE hours-auto-captured trend for TL Wall.

This is immune to the review-ramp contamination that wrecks override/touch-free:
it just counts agent-captured material time, week by week, then accumulates.
Only-grows line = clean "look how much work you never had to do" story.

Shows both the per-week bars AND the running cumulative total.

    docker compose exec -T api python manage.py shell < check_captured.py
"""
from datetime import timedelta
from django.utils import timezone
from tracker.models import Block

ORG_ID = 21
MAX_PLAUSIBLE_MIN = 6 * 60   # mirror the report's anomaly guard
MATERIAL_MIN = 2

def block_min(b):
    span = None
    if b.start and b.end:
        span = (b.end - b.start).total_seconds() / 60.0
    if span is None:
        span = b.minutes or 0
    if span > MAX_PLAUSIBLE_MIN:
        return 0
    m = b.minutes or 0
    return m if m > 0 else 0

today = timezone.localdate()
this_monday = today - timedelta(days=today.weekday())

print("\n=== Hours auto-captured, last 8 weeks, org 21 ===")
print(f"  {'week of':<12} {'this week':>10} {'cumulative':>12}")
cum = 0.0
for w in range(8):
    ws = this_monday - timedelta(days=7 * (7 - w))
    we = ws + timedelta(days=7)
    mins = 0
    for b in Block.objects.filter(
        org_id=ORG_ID, deleted_at__isnull=True,
        start__date__gte=ws, start__date__lt=we,
    ).only("start", "end", "minutes"):
        m = block_min(b)
        if m >= MATERIAL_MIN:
            mins += m
    hrs = round(mins / 60, 1)
    cum = round(cum + hrs, 1)
    print(f"  {ws.isoformat():<12} {hrs:>9}h {cum:>11}h")

print("\n=== READ ===")
print("  'this week' = hours the agent captured that nobody typed.")
print("  'cumulative' = the running total — this is the line that only goes UP.")
print("  If cumulative climbs steadily, this is the success chart. Clean story,")
print("  no adoption contamination, no '% that needs explaining'.")
