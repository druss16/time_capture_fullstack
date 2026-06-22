"""
READ-ONLY. Dashboard shows Terri 9h19m non-billable. User says ~8h is overnight.
But the 19 overnight Explorer blocks are already suppressed. So either the
dashboard is stale, OR there are MORE overnight blocks we didn't catch.
Dump EVERY non-suppressed block contributing to her non-billable, sorted by
hour, flagging anything between midnight and 7am.
"""
from datetime import date
from django.contrib.auth import get_user_model
from tracker.models import Block

User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()
DAY = date(2026,6,22)

q = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                         start__date=DAY).exclude(classification_state="suppressed").order_by("start")

print("="*80)
print("ALL non-suppressed blocks for Terri, by time. ⚠️ = overnight (00:00-07:00)")
print("="*80)
overnight_min = 0
day_min = 0
overnight_ids = []
for b in q:
    if (b.minutes or 0) <= 0:
        continue
    st = b.start.astimezone() if b.start else None
    hr = st.hour if st else 99
    is_overnight = 0 <= hr < 7
    flag = "⚠️ " if is_overnight else "   "
    bill = "BILL" if b.is_billable else "non "
    if is_overnight:
        overnight_min += b.minutes or 0
        overnight_ids.append(b.id)
    else:
        day_min += b.minutes or 0
    print(f"{flag}id={b.id} | {st.strftime('%H:%M') if st else '??'} | min={b.minutes:>4} | "
          f"{bill} | {(b.app_name or '?')[:12]:12} | state={b.classification_state:9} | "
          f"{(b.window_title or '(empty)')[:30]}")

print("="*80)
print(f"OVERNIGHT (00:00-07:00) still showing: {overnight_min}m ({overnight_min//60}h{overnight_min%60}m)")
print(f"   overnight IDs not yet suppressed: {overnight_ids}")
print(f"DAYTIME (07:00+): {day_min}m ({day_min//60}h{day_min%60}m)")
print("="*80)
# Also report what state the known-19 are in, to detect staleness
KNOWN19 = [43481,43485,43482,43483,43484,43486,43487,43489,43488,43490,
           43491,43493,43492,43494,43497,43496,43499,43498,43531]
from collections import Counter
s = Block.objects.filter(id__in=KNOWN19).values_list("classification_state", flat=True)
print("Known-19 overnight Explorer state:", dict(Counter(s)))
print("If they're 'suppressed' but dashboard still shows ~8h overnight non-bill,")
print("the dashboard is STALE — hard-refresh, don't delete more.")
print("="*80)
