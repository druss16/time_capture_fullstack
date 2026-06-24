"""READ-ONLY. Replicate today_time's event rollup for wendy and report what
lands under St James (114). Specifically: do block 44733's 35 events
contribute minutes to the St James card, or are they dropped somewhere?"""
from datetime import date, datetime
from collections import defaultdict
from django.utils import timezone
from tracker.models import RawEvent, Block, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()
start_utc = timezone.make_aware(datetime.combine(DAY, datetime.min.time()))
end_utc = timezone.make_aware(datetime.combine(DAY, datetime.max.time()))

events = list(RawEvent.objects.filter(
    user=wendy, start_ts__gte=start_utc, start_ts__lt=end_utc,
).exclude(block__classification_state='suppressed').select_related('block','block__client').order_by('start_ts'))

deleted_block_ids = set(Block.objects.filter(user=wendy, deleted_at__isnull=False).values_list('id', flat=True))

# Roll up minutes by (client_id, category), tracking block 44733 specifically
by_client_cat = defaultdict(float)
b44733_minutes = 0.0
b44733_events_counted = 0
b44733_zero_dur = 0
for event in events:
    if not (event.start_ts and event.end_ts):
        if event.block_id == 44733: b44733_zero_dur += 1
        continue
    dur = (event.end_ts - event.start_ts).total_seconds()
    if dur <= 0:
        if event.block_id == 44733: b44733_zero_dur += 1
        continue
    block = event.block
    if block and block.id in deleted_block_ids:
        block = None
    if block:
        cid = block.client_id
        ch = block.category_hours if isinstance(block.category_hours, dict) else {}
        cat = (list(ch.keys())[0] if ch else 'Uncategorized')
    else:
        cid, cat = None, 'Uncategorized'
    by_client_cat[(cid, cat)] += dur/60.0
    if event.block_id == 44733:
        b44733_minutes += dur/60.0
        b44733_events_counted += 1

print("="*72)
print("St James (114) rollup for wendy today:")
print("="*72)
for (cid, cat), mins in sorted(by_client_cat.items(), key=lambda x:-x[1]):
    if cid == 114:
        print(f"  client 114 / {cat}: {mins:.1f}m")
print(f"\nBlock 44733 specifically:")
print(f"  events counted into rollup: {b44733_events_counted}")
print(f"  minutes contributed:        {b44733_minutes:.1f}m")
print(f"  events with zero/null dur:   {b44733_zero_dur}")
print("="*72)
print("If 44733 contributes ~14m to client 114, the ROLLUP is fine and the")
print("bug is in STEP 3 dedup (blocks_seen) or the frontend. If it contributes")
print("0m, the events are being dropped here — and we'll see why.")
