"""READ-ONLY. Does block 44733 have RawEvents with valid start_ts? If not,
the event-based today_time path (filters start_ts__gte/lt) can't see it,
which is why the committed 14m never shows in wendy's card."""
from datetime import date, datetime
from django.utils import timezone
from tracker.models import Block, RawEvent

b = Block.objects.filter(id=44733).first()
print(f"block 44733: start_ts={getattr(b,'start_ts',None)} end_ts={getattr(b,'end_ts',None)} "
      f"start={getattr(b,'start',None)} end={getattr(b,'end',None)} minutes={b.minutes}")

# RawEvents linked to this block
evs = RawEvent.objects.filter(block=b)
print(f"\nRawEvents for 44733: {evs.count()}")
for e in evs[:20]:
    print(f"  ev {e.id}: start_ts={getattr(e,'start_ts',None)} end_ts={getattr(e,'end_ts',None)} "
          f"ts_utc={getattr(e,'ts_utc',None)} day={getattr(e,'day',None)}")

# What would the event-based query see for wendy today?
DAY = date(2026,6,23)
start_utc = timezone.make_aware(datetime.combine(DAY, datetime.min.time()))
end_utc = timezone.make_aware(datetime.combine(DAY, datetime.max.time()))
from tracker.models import User
wendy = User.objects.filter(username='wendy').first()
ev_in_range = RawEvent.objects.filter(
    user=wendy, start_ts__gte=start_utc, start_ts__lt=end_utc,
)
print(f"\nWendy RawEvents in start_ts range today: {ev_in_range.count()}")
# How many are linked to St James committed block 44733?
linked = ev_in_range.filter(block=b).count()
print(f"  ...linked to block 44733: {linked}")

# St James events specifically
sj_ev = ev_in_range.filter(block__client_id=114)
print(f"  ...St James (114) events in range: {sj_ev.count()}")

print("\nDIAGNOSIS:")
if evs.count() == 0:
    print("  ✗ 44733 has NO RawEvents → event-based today_time can't render it.")
    print("    The block exists but its time lives only in category_hours/minutes,")
    print("    not in timestamped events. Event-path view drops it.")
elif getattr(b,'start_ts',None) is None:
    print("  ✗ 44733 has events but block.start_ts is None → if today_time filters")
    print("    blocks by start_ts, it's excluded.")
