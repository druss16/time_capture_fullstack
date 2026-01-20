"""
EMERGENCY FIX: Scan and fix all oversized blocks.

Run in Django shell:
    exec(open('fix_oversized_blocks.py').read())
"""

from django.db import transaction
from django.utils import timezone
from tracker.models import Block, RawEvent
from datetime import timedelta

# Find all blocks > 4 hours that are uncategorized
MAX_REASONABLE_MINUTES = 240  # 4 hours
SESSION_GAP_MINUTES = 30

oversized = Block.objects.filter(
    is_categorized=False,
    minutes__gt=MAX_REASONABLE_MINUTES
).order_by('-minutes')

print(f"Found {oversized.count()} oversized blocks (>{MAX_REASONABLE_MINUTES} min)")

fixed_count = 0
split_count = 0

for block in oversized:
    events = list(RawEvent.objects.filter(block=block).order_by('ts_utc'))
    
    if not events:
        print(f"  Block {block.id}: {block.minutes}min - NO EVENTS, deleting")
        block.delete()
        fixed_count += 1
        continue
    
    # Find sessions within this block
    sessions = []
    session_events = [events[0]]
    prev_ts = events[0].ts_utc
    
    for e in events[1:]:
        gap = (e.ts_utc - prev_ts).total_seconds() / 60
        if gap > SESSION_GAP_MINUTES:
            sessions.append(session_events)
            session_events = [e]
        else:
            session_events.append(e)
        prev_ts = e.ts_utc
    sessions.append(session_events)
    
    if len(sessions) == 1:
        # Single session but still too long - recalculate from events
        start = events[0].ts_utc
        end = events[-1].ts_utc + timedelta(minutes=5)
        new_minutes = int((end - start).total_seconds() / 60)
        
        if new_minutes > MAX_REASONABLE_MINUTES:
            # Still too long - cap it
            print(f"  Block {block.id}: {block.minutes}min → {new_minutes}min (capped, single session)")
            new_minutes = min(new_minutes, MAX_REASONABLE_MINUTES)
        
        block.start = start
        block.end = end
        block.minutes = new_minutes
        block.save()
        fixed_count += 1
        print(f"  Block {block.id}: {block.minutes}min → {new_minutes}min (recalculated)")
    else:
        # Multiple sessions - split the block
        print(f"  Block {block.id}: {block.minutes}min → splitting into {len(sessions)} blocks")
        
        with transaction.atomic():
            # Keep first session in original block
            first_events = sessions[0]
            start = first_events[0].ts_utc
            end = first_events[-1].ts_utc + timedelta(minutes=5)
            mins = int((end - start).total_seconds() / 60)
            
            block.start = start
            block.end = end
            block.minutes = mins
            block.save()
            print(f"    → Block {block.id}: {start.strftime('%H:%M')} - {end.strftime('%H:%M')} ({mins} min)")
            
            # Create new blocks for other sessions
            for session_events in sessions[1:]:
                start = session_events[0].ts_utc
                end = session_events[-1].ts_utc + timedelta(minutes=5)
                mins = int((end - start).total_seconds() / 60)
                
                new_block = Block.objects.create(
                    org=block.org,
                    user=block.user,
                    device_id=block.device_id,
                    hostname=block.hostname,
                    start=start,
                    end=end,
                    day=start.date(),
                    minutes=mins,
                    title=block.title,
                    window_title=block.window_title,
                    url=block.url,
                    file_path=block.file_path,
                    app_name=block.app_name,
                    bundle_id=block.bundle_id,
                    hints=block.hints or {},
                    client=block.client,
                    category_hours={},
                    is_categorized=False,
                    approved=False,
                )
                
                event_ids = [e.id for e in session_events]
                RawEvent.objects.filter(id__in=event_ids).update(block=new_block)
                
                print(f"    → NEW Block {new_block.id}: {start.strftime('%H:%M')} - {end.strftime('%H:%M')} ({mins} min)")
                split_count += 1
        
        fixed_count += 1

print(f"\n{'='*50}")
print(f"DONE: Fixed {fixed_count} blocks, created {split_count} new blocks from splits")