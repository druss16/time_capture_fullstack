"""READ-ONLY. Replicate today_time's block query for wendy and see if 44733
is included. Then check each common filter that could exclude it."""
from datetime import date
from tracker.models import Block, User

DAY = date(2026, 6, 23)
wendy = User.objects.filter(username='wendy').first()
print(f"wendy id={wendy.id}, org={getattr(wendy,'organization_id',None)} / membership orgs:",
      list(wendy.memberships.values_list('organization_id', flat=True)) if hasattr(wendy,'memberships') else 'n/a')

b = Block.objects.filter(id=44733).first()
print(f"\n44733: user={b.user.username} user_id={b.user_id} day={b.day} "
      f"state={b.classification_state} client={b.client_id} billable={b.is_billable} "
      f"deleted={b.deleted_at} cat_hours={b.category_hours}")

# Common today_time filters — test each against 44733
print("\nFilter checks for 44733:")
print(f"  user == wendy?            {b.user_id == wendy.id}")
print(f"  day == {DAY}?             {b.day == DAY}")
print(f"  deleted_at is null?       {b.deleted_at is None}")
print(f"  has category_hours?       {bool(b.category_hours)}")
print(f"  minutes>0?                {(b.minutes or 0) > 0}")
print(f"  is_categorized?           {getattr(b,'is_categorized',None)}")
print(f"  classification_state:     {b.classification_state}")

# Does today_time maybe filter by is_billable, or exclude 'committed' via some
# state whitelist? Check what states the OTHER visible St James blocks have.
print("\nAll St James (114) blocks for wendy on this day:")
for x in Block.objects.filter(user=wendy, day=DAY, client_id=114, deleted_at__isnull=True):
    print(f"  {x.id}: state={x.classification_state} min={x.minutes} "
          f"cat_hours={x.category_hours} billable={x.is_billable} by={x.categorized_by}")

# Are the VISIBLE 15m blocks even wendy's? Check who owns them.
print("\nWho owns the visible '15m' St James blocks (Home/Make Deposits/etc)?")
for x in Block.objects.filter(day=DAY, client_id=114, deleted_at__isnull=True).exclude(id=44733)[:10]:
    print(f"  {x.id}: user={x.user.username} '{(x.window_title or '')[:40]}' "
          f"min={x.minutes} cat_hours={x.category_hours}")
