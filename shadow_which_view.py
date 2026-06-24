"""READ-ONLY. This card shows EMILY's 15m AND showed WENDY's 14m pending —
so it's a MERGED/multi-user view. Find which blocks a multi-user St James
aggregation includes, and whether 44733 (wendy, committed) is in or out."""
from datetime import date
from tracker.models import Block, User

DAY = date(2026, 6, 23)

# ALL St James (114) blocks today, ALL users — what an aggregated view would see
print("="*72)
print("ALL St James (114) blocks today, every user:")
print("="*72)
rows = Block.objects.filter(day=DAY, client_id=114, deleted_at__isnull=True).select_related('user')
total_committed = 0
for b in rows.order_by('user__username','id'):
    ch = sum((b.category_hours or {}).values())
    inc = "✓counts" if (b.classification_state=='committed' and b.is_billable) else "—"
    if b.classification_state=='committed' and b.is_billable:
        total_committed += (b.minutes or 0)
    print(f"  {b.id} | {b.user.username:8} | {b.classification_state:9} | "
          f"{b.minutes:3}m | billable={b.is_billable} | by={b.categorized_by} | "
          f"cat_hrs={ch} | {inc}")
print(f"\n  TOTAL committed+billable across ALL users: {total_committed}m")

# The 6 visible emily blocks — are they committed or proposed?
print("\n" + "="*72)
print("Emily's St James blocks (the visible 15m):")
emily = User.objects.filter(username='emily').first()
for b in Block.objects.filter(day=DAY, client_id=114, user=emily, deleted_at__isnull=True):
    print(f"  {b.id} | {b.classification_state} | {b.minutes}m | "
          f"cat_hrs={b.category_hours} | '{(b.window_title or '')[:35]}'")

# Is this maybe org-wide rollup? Check if there's impersonation context.
print("\n" + "="*72)
print("Wendy's 44733 specifically:")
b = Block.objects.filter(id=44733).first()
print(f"  state={b.classification_state} billable={b.is_billable} min={b.minutes} "
      f"cat_hrs={b.category_hours}")
print("  → If the card is org-aggregated, this SHOULD add 14m → 29m total.")
print("  → If per-user, this shows only on wendy's own review, not emily's.")
print("="*72)
