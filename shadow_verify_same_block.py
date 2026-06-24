"""READ-ONLY. Prove the 6 visible St James rows are all block 44733's events
(distinct window titles), confirming the '15m card' IS the confirmed 14m block."""
from datetime import date, datetime
from collections import defaultdict
from django.utils import timezone
from tracker.models import RawEvent, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()
start_utc = timezone.make_aware(datetime.combine(DAY, datetime.min.time()))
end_utc = timezone.make_aware(datetime.combine(DAY, datetime.max.time()))

# All of wendy's St James (114) events, grouped by window title
evs = RawEvent.objects.filter(
    user=wendy, start_ts__gte=start_utc, start_ts__lt=end_utc,
    block__client_id=114,
).select_related('block')

by_title = defaultdict(lambda: {'count':0, 'secs':0.0, 'block_ids':set()})
for e in evs:
    if not (e.start_ts and e.end_ts): continue
    t = (e.window_title or '(no title)')
    by_title[t]['count'] += 1
    by_title[t]['secs'] += (e.end_ts - e.start_ts).total_seconds()
    by_title[t]['block_ids'].add(e.block_id)

print("="*72)
print("Wendy's St James events grouped by window title (= the visible rows):")
print("="*72)
total = 0
for t, agg in sorted(by_title.items(), key=lambda x:-x[1]['secs']):
    mins = agg['secs']/60.0
    total += mins
    print(f"  {mins:4.1f}m  ({agg['count']:2d} ev)  block(s)={agg['block_ids']}  {t[:50]}")
print(f"\n  TOTAL: {total:.1f}m")
print("="*72)
print("CONCLUSION: if all rows show block_ids={44733}, the '15m card' IS the")
print("confirmed 14m block. The time is NOT missing — it's displayed, grouped")
print("by activity title. 'Should be 29m' double-counted the same block.")
