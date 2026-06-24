"""READ-ONLY. Just show block 44733's complete current state — no theory."""
from tracker.models import Block

b = Block.objects.filter(id=44733).first()
if not b:
    print("44733 not found"); raise SystemExit
print("block 44733 — CURRENT STATE:")
print(f"  user:                {b.user.username}")
print(f"  day:                 {b.day}")
print(f"  minutes:             {b.minutes!r}")
print(f"  category_hours:      {b.category_hours!r}")
print(f"  sum(cat_hours):      {sum((b.category_hours or {}).values())}")
print(f"  classification_state:{b.classification_state}")
print(f"  client:              {b.client.name if b.client_id else None} (id={b.client_id})")
print(f"  is_billable:         {b.is_billable}")
print(f"  is_categorized:      {getattr(b,'is_categorized',None)}")
print(f"  categorized_by:      {b.categorized_by}")
print(f"  deleted_at:          {b.deleted_at}")
print(f"  window_title:        {(b.window_title or '')[:60]}")

# Why didn't backfill catch it? Check each filter condition:
print("\nBackfill filter check (why it found 0):")
print(f"  committed?           {b.classification_state == 'committed'}")
print(f"  categorized_by=correction? {b.categorized_by == 'correction'}")
print(f"  cat_hours sums to 0? {sum((b.category_hours or {}).values()) == 0}")
print(f"  minutes > 0?         {(b.minutes or 0) > 0}")
print(f"  not deleted?         {b.deleted_at is None}")

# Would it show in today_time? today_time groups by category_hours keys.
ch = b.category_hours or {}
print(f"\n  today_time would bucket under: {list(ch.keys())[0] if ch else '(NOTHING — empty category_hours)'}")
print(f"  hours contributed to billable: {sum(ch.values())}")
