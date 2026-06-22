"""
READ-ONLY FIRST. Find the 6.4h Explorer block (and ANY large Explorer/empty
block) for Terri that's still counting. The daily-review UI shows 'Explorer
(6.4h)' so it exists — find it regardless of date filtering.
"""
from datetime import datetime, timedelta, timezone as tz
from django.contrib.auth import get_user_model
from django.utils import timezone
from tracker.models import Block

User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()

# Wide window — 2 full days around Jun 22 to catch any date-boundary placement
start = timezone.make_aware(datetime(2026,6,21,0,0)).astimezone(tz.utc)
end   = timezone.make_aware(datetime(2026,6,24,0,0)).astimezone(tz.utc)

q = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                         start__gte=start, start__lt=end)

print("="*80)
print("Large Explorer / big blocks for Terri (any not-suppressed, >30min):")
print("="*80)
big = []
for b in q:
    if b.classification_state == "suppressed":
        continue
    m = b.minutes or 0
    app = (b.app_name or "").lower()
    if m >= 30 and ("explor" in app or not (b.window_title or "").strip() or "explor" in (b.window_title or "").lower()):
        big.append(b)

# Also: catch the single biggest block overall regardless of app
allbig = sorted([b for b in q if b.classification_state != "suppressed" and (b.minutes or 0) > 0],
                key=lambda b: -(b.minutes or 0))[:8]

print("Explorer/empty blocks >=30min:")
for b in big:
    st = b.start.astimezone() if b.start else None
    print(f"  id={b.id} | {st.strftime('%m-%d %H:%M') if st else '??'} | min={b.minutes} "
          f"({(b.minutes or 0)/60:.1f}h) | state={b.classification_state} | "
          f"app={b.app_name} | bill={b.is_billable} | client={b.client_id} | "
          f"title={(b.window_title or '(empty)')[:26]}")
print("-"*80)
print("Top 8 biggest non-suppressed blocks overall (any app):")
for b in allbig:
    st = b.start.astimezone() if b.start else None
    print(f"  id={b.id} | {st.strftime('%m-%d %H:%M') if st else '??'} | min={b.minutes} "
          f"({(b.minutes or 0)/60:.1f}h) | state={b.classification_state} | "
          f"app={b.app_name} | bill={b.is_billable} | "
          f"title={(b.window_title or '(empty)')[:26]}")
print("="*80)
