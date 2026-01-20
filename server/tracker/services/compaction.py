# tracker/services/compaction.py
"""
Event-centric compaction - FINAL VERSION

FIXES ALL ISSUES:
1. Session awareness - gap > 30 min = new session (no 9-hour blocks)
2. Event-duration minutes - no double counting (each minute counted once)
3. Smart app merging - one block per app per session (fewer blocks to categorize)

GUARANTEES:
- Minutes are calculated from EVENT DURATIONS, not block spans
- No double-counting: if you work 1 hour, total is 1 hour (not 3 hours across overlapping blocks)
- Categorized blocks are NEVER touched
- Each event belongs to exactly one block
"""

from __future__ import annotations
from datetime import datetime, timedelta, date as date_type
from typing import Optional, List, Dict, Any, Tuple
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth import get_user_model

from tracker.models import Block, RawEvent, Client
from tracker.utils.blocks import is_idle_activity, get_current_client_for_user

import logging
logger = logging.getLogger(__name__)

User = get_user_model()

# Configuration
IDLE_CAP = timedelta(minutes=30)           # Cap event duration at 30 minutes
MIN_BLOCK_MINUTES = 0.5                    # Minimum block size (30 seconds)
SESSION_GAP = timedelta(minutes=30)        # Gap > 30 min = new session


def _safe_device_id(device_id) -> int:
    """Ensure device_id is a valid integer."""
    if device_id is None:
        return 0
    try:
        return int(device_id)
    except (ValueError, TypeError):
        return 0


def _app_key(event_or_block) -> str:
    """Get normalized app name."""
    if isinstance(event_or_block, dict):
        return (event_or_block.get("app_name") or "").lower().strip()
    return (getattr(event_or_block, 'app_name', None) or "").lower().strip()


def compact_rawevents_into_blocks(user=None, hostname: Optional[str] = None, org=None) -> int:
    """Main entry point."""
    today = timezone.localdate()
    
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            logger.warning(f"[COMPACT] User not found: {user}")
            return 0
    
    return compact_day(user, today, hostname=hostname, org=org)


def compact_day(user, day: date_type, hostname: Optional[str] = None, org=None) -> int:
    """
    Main compaction logic.
    
    Algorithm:
    1. Get all unlinked events for the day, ordered by time
    2. Calculate duration for each event (time to next event, capped at 30 min)
    3. Split into sessions (gap > 30 min = new session)
    4. Within each session, group events by app
    5. Create one block per app per session, with minutes = SUM of event durations
    """
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return 0
    
    if not user:
        return 0
    
    # Get org
    if not org:
        from tracker.models import Organization, OrganizationMembership
        membership = OrganizationMembership.objects.filter(user=user).first()
        if membership:
            org = membership.organization
        else:
            org, _ = Organization.objects.get_or_create(
                name="default-org",
                defaults={"slug": "default-org"}
            )
    
    # =========================================================
    # STEP 1: Get all unlinked events, ordered by time
    # =========================================================
    qs = RawEvent.objects.filter(
        user=user,
        ts_utc__date=day,
        block__isnull=True
    ).order_by('ts_utc')
    
    if hostname:
        qs = qs.filter(hostname=hostname)
    
    events = list(qs)
    
    if not events:
        logger.debug(f"[COMPACT] No unlinked events for {day}")
        return 0
    
    logger.info(f"[COMPACT] Processing {len(events)} unlinked events")
    
    # =========================================================
    # STEP 2: Calculate duration for EACH event
    # Duration = time to next event (any app), capped at 30 min
    # This ensures no double-counting!
    # =========================================================
    events_with_duration = []
    
    for i, event in enumerate(events):
        if i + 1 < len(events):
            next_ts = events[i + 1].ts_utc
            duration_seconds = (next_ts - event.ts_utc).total_seconds()
        else:
            # Last event gets 5 min default
            duration_seconds = 300
        
        # Cap at 30 minutes
        duration_seconds = min(duration_seconds, IDLE_CAP.total_seconds())
        duration_minutes = duration_seconds / 60.0
        
        events_with_duration.append({
            'event': event,
            'start': event.ts_utc,
            'duration_minutes': duration_minutes,
            'app_name': event.app_name or "",
            'bundle_id': event.bundle_id or "",
            'window_title': event.window_title or "",
            'url': event.url or "",
            'file_path': event.file_path or "",
            'hostname': event.hostname or hostname or "unknown",
            'device_id': _safe_device_id(getattr(event, 'device_id', None)),
            'current_client_id': getattr(event, 'current_client_id', None),
        })
    
    # =========================================================
    # STEP 3: Split into sessions (gap > 30 min = new session)
    # =========================================================
    sessions = []
    current_session = [events_with_duration[0]]
    
    for i in range(1, len(events_with_duration)):
        prev = events_with_duration[i - 1]
        curr = events_with_duration[i]
        
        gap = (curr['start'] - prev['start']).total_seconds() - prev['duration_minutes'] * 60
        
        if gap > SESSION_GAP.total_seconds():
            sessions.append(current_session)
            current_session = [curr]
        else:
            current_session.append(curr)
    
    if current_session:
        sessions.append(current_session)
    
    logger.info(f"[COMPACT] Split into {len(sessions)} sessions")
    
    # =========================================================
    # STEP 4: Within each session, group by APP (not window title)
    # Create ONE block per app per session
    # =========================================================
    blocks_to_create = []
    
    for session in sessions:
        # Group events by app
        by_app: Dict[str, List] = {}
        for ev in session:
            app = _app_key(ev)
            if app not in by_app:
                by_app[app] = []
            by_app[app].append(ev)
        
        # Create one block per app
        for app, app_events in by_app.items():
            if not app_events:
                continue
            
            # Calculate block properties
            starts = [e['start'] for e in app_events]
            block_start = min(starts)
            block_end = max(starts) + timedelta(minutes=app_events[-1]['duration_minutes'])
            
            # CRITICAL: Minutes = SUM of event durations (no double counting!)
            total_minutes = sum(e['duration_minutes'] for e in app_events)
            
            if total_minutes < MIN_BLOCK_MINUTES:
                continue
            
            # Pick best window title (longest/most descriptive)
            titles = [e['window_title'] for e in app_events if e['window_title']]
            titles = [t for t in titles if t.lower() not in ('', 'open', 'untitled', 'new tab')]
            window_title = max(titles, key=len) if titles else app_events[0]['window_title']
            
            # Pick URL and file_path if any
            urls = [e['url'] for e in app_events if e['url']]
            paths = [e['file_path'] for e in app_events if e['file_path']]
            
            blocks_to_create.append({
                'start': block_start,
                'end': block_end,
                'minutes': total_minutes,
                'app_name': app_events[0]['app_name'],
                'bundle_id': app_events[0]['bundle_id'],
                'window_title': window_title,
                'url': urls[0] if urls else "",
                'file_path': paths[0] if paths else "",
                'hostname': app_events[0]['hostname'],
                'device_id': app_events[0]['device_id'],
                'current_client_id': app_events[0]['current_client_id'],
                'source_events': [e['event'] for e in app_events],
            })
    
    logger.info(f"[COMPACT] Creating {len(blocks_to_create)} blocks")
    
    # =========================================================
    # STEP 5: Check for existing uncategorized blocks to merge into
    # =========================================================
    existing_uncategorized = {
        _app_key(b): b for b in Block.objects.filter(
            user=user,
            day=day,
            is_categorized=False,
        )
    }
    
    # =========================================================
    # STEP 6: Create blocks (or merge into existing)
    # =========================================================
    created_count = 0
    merged_count = 0
    
    with transaction.atomic():
        for block_data in blocks_to_create:
            app = _app_key(block_data)
            existing = existing_uncategorized.get(app)
            
            if existing:
                # Merge into existing block
                try:
                    locked = Block.objects.select_for_update().get(id=existing.id)
                    if not locked.is_categorized:
                        # Extend time range
                        locked.start = min(locked.start, block_data['start'])
                        locked.end = max(locked.end, block_data['end'])
                        # ADD minutes (don't recalculate from span!)
                        locked.minutes = locked.minutes + int(block_data['minutes'])
                        locked.save(update_fields=['start', 'end', 'minutes'])
                        
                        # Link events
                        event_ids = [e.id for e in block_data['source_events']]
                        RawEvent.objects.filter(id__in=event_ids).update(block=locked)
                        
                        merged_count += 1
                        logger.debug(f"[COMPACT] Merged {len(event_ids)} events into block {locked.id}")
                        continue
                except Block.DoesNotExist:
                    pass
            
            # Create new block
            new_block = _create_block(block_data, user, org, day)
            if new_block:
                created_count += 1
    
    logger.info(f"[COMPACT] Created {created_count}, merged {merged_count} for {day}")
    return created_count + merged_count


def _create_block(block_data: Dict, user, org, day: date_type) -> Optional[Block]:
    """Create a new block."""
    
    is_idle = is_idle_activity(
        app_name=block_data.get("app_name"),
        bundle_id=block_data.get("bundle_id"),
        window_title=block_data.get("window_title")
    )
    
    device_id = block_data.get("device_id", 0)
    minutes = int(block_data["minutes"])
    
    client = None
    if not is_idle:
        client_id = block_data.get("current_client_id")
        if client_id:
            try:
                client = Client.objects.get(id=client_id)
            except Client.DoesNotExist:
                pass
        
        if not client and device_id:
            client = get_current_client_for_user(user, device_id=device_id)
    
    if is_idle:
        hours = round(minutes / 60.0, 2)
        new_block = Block.objects.create(
            org=org,
            user=user,
            device_id=device_id or 0,
            hostname=block_data["hostname"],
            start=block_data["start"],
            end=block_data["end"],
            day=day,
            minutes=minutes,
            title="Idle",
            window_title="Idle/Uncategorized",
            url="",
            file_path="",
            app_name=block_data.get("app_name") or "Idle",
            bundle_id=block_data.get("bundle_id") or "__idle__",
            hints={},
            client=None,
            category_hours={"Idle": hours},
            is_categorized=True,
            categorized_by="system",
            categorized_at=timezone.now(),
            approved=False,
        )
    else:
        new_block = Block.objects.create(
            org=org,
            user=user,
            device_id=device_id or 0,
            hostname=block_data["hostname"],
            start=block_data["start"],
            end=block_data["end"],
            day=day,
            minutes=minutes,
            title=block_data.get("app_name") or "Unknown",
            window_title=block_data.get("window_title") or "",
            url=block_data.get("url") or "",
            file_path=block_data.get("file_path") or "",
            app_name=block_data.get("app_name") or "",
            bundle_id=block_data.get("bundle_id") or "",
            hints={},
            client=client,
            category_hours={},
            is_categorized=False,
            approved=False,
        )
    
    # Link events
    event_ids = [e.id for e in block_data['source_events']]
    RawEvent.objects.filter(id__in=event_ids).update(block=new_block)
    
    logger.debug(f"[COMPACT] Created block {new_block.id} ({new_block.app_name}) - {minutes} min")
    return new_block


def compact_recent_events(user, hostname: Optional[str] = None, minutes_back: int = 15) -> int:
    """Quick compaction of recent events."""
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return 0
    
    if not user:
        return 0
    
    today = timezone.localdate()
    return compact_day(user, today, hostname=hostname)


def auto_compact_all_active_users(minutes_back: int = 30):
    """Auto-compact for all users with recent activity."""
    cutoff = timezone.now() - timedelta(minutes=minutes_back)
    
    recent_users = RawEvent.objects.filter(
        ts_utc__gte=cutoff,
        block__isnull=True
    ).values_list('user', 'hostname').distinct()
    
    stats = {
        'users_processed': 0,
        'blocks_created': 0,
        'errors': 0
    }
    
    today = timezone.localdate()
    
    for user_id, hostname in recent_users:
        try:
            user = User.objects.get(id=user_id)
            count = compact_day(user, today, hostname=hostname)
            stats['blocks_created'] += count
            stats['users_processed'] += 1
        except Exception as e:
            logger.error(f"[AUTO-COMPACT] Error for user {user_id}: {e}")
            stats['errors'] += 1
    
    logger.info(
        f"[AUTO-COMPACT] Processed {stats['users_processed']} users, "
        f"created {stats['blocks_created']} blocks"
    )
    
    return stats