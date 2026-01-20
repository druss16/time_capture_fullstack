# tracker/services/compaction.py
"""
Event-centric compaction with SESSION-AWARE merging.

KEY RULES:
1. Gap > 30 minutes = DIFFERENT SESSION (never merge across)
2. Same app + overlapping/adjacent time (< 2 min gap) = merge
3. Minutes are ALWAYS calculated from (end - start), never added
4. Categorized blocks are NEVER touched

GUARANTEES:
- No 9-hour blocks from 30 minutes of work
- No duplicate blocks for same activity
- No flip-flopping of categorized blocks
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
IDLE_CAP = timedelta(minutes=30)           # Cap duration to next event
MIN_BLOCK = timedelta(seconds=30)          # Drop events shorter than this
SESSION_GAP = timedelta(minutes=30)        # Gap > 30 min = new session (NEVER merge across)
MERGE_GAP = timedelta(minutes=2)           # Merge blocks if gap < 2 min (within same session)


def _safe_device_id(device_id) -> int:
    """Ensure device_id is a valid integer."""
    if device_id is None:
        return 0
    try:
        return int(device_id)
    except (ValueError, TypeError):
        return 0


def _app_key(block_or_dict) -> str:
    """Get normalized app name for grouping."""
    if isinstance(block_or_dict, dict):
        return (block_or_dict.get("app_name") or "").lower().strip()
    return (getattr(block_or_dict, 'app_name', None) or "").lower().strip()


def compact_rawevents_into_blocks(user=None, hostname: Optional[str] = None, org=None) -> int:
    """Main entry point - compacts today's unlinked events into blocks."""
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
    Event-centric compaction with session-aware merging.
    """
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            logger.warning(f"[COMPACT] User not found: {user}")
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
    # STEP 1: Get unlinked events
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
    
    logger.info(f"[COMPACT] Found {len(events)} unlinked events to process")
    
    # =========================================================
    # STEP 2: Group events into SESSIONS (gap > 30 min = new session)
    # =========================================================
    sessions = _split_into_sessions(events)
    logger.info(f"[COMPACT] Split into {len(sessions)} sessions")
    
    # =========================================================
    # STEP 3: Within each session, build blocks by app
    # =========================================================
    all_blocks = []
    
    for session_events in sessions:
        session_blocks = _build_session_blocks(session_events, hostname)
        all_blocks.extend(session_blocks)
    
    logger.info(f"[COMPACT] Built {len(all_blocks)} blocks from sessions")
    
    if not all_blocks:
        return 0
    
    # =========================================================
    # STEP 4: Try to merge into existing uncategorized blocks
    # =========================================================
    existing_uncategorized = list(Block.objects.filter(
        user=user,
        day=day,
        is_categorized=False,
    ).order_by('start'))
    
    if hostname:
        existing_uncategorized = [b for b in existing_uncategorized if b.hostname == hostname]
    
    blocks_to_create = []
    merged_count = 0
    
    with transaction.atomic():
        for block_data in all_blocks:
            merged = _try_merge_into_existing(block_data, existing_uncategorized)
            
            if merged:
                merged_count += 1
            else:
                blocks_to_create.append(block_data)
    
    logger.info(f"[COMPACT] Merged {merged_count} into existing, {len(blocks_to_create)} new")
    
    # =========================================================
    # STEP 5: Create new blocks
    # =========================================================
    created_count = 0
    
    with transaction.atomic():
        for block_data in blocks_to_create:
            new_block = _create_block(block_data, user, org, day)
            if new_block:
                created_count += 1
    
    logger.info(f"[COMPACT] Created {created_count} new blocks for {day}")
    
    return created_count + merged_count


def _split_into_sessions(events: List) -> List[List]:
    """
    Split events into sessions based on time gaps.
    Gap > 30 minutes = new session.
    """
    if not events:
        return []
    
    sessions = []
    current_session = [events[0]]
    prev_ts = events[0].ts_utc
    
    for event in events[1:]:
        gap = (event.ts_utc - prev_ts).total_seconds()
        
        if gap > SESSION_GAP.total_seconds():
            # Big gap - start new session
            sessions.append(current_session)
            current_session = [event]
        else:
            current_session.append(event)
        
        prev_ts = event.ts_utc
    
    if current_session:
        sessions.append(current_session)
    
    return sessions


def _build_session_blocks(events: List, hostname: Optional[str]) -> List[Dict]:
    """
    Build blocks from events within a single session.
    Groups consecutive same-app events together.
    """
    if not events:
        return []
    
    blocks = []
    
    # Group consecutive events by app
    current_app = _app_key_from_event(events[0])
    current_events = [events[0]]
    
    for event in events[1:]:
        app = _app_key_from_event(event)
        gap = (event.ts_utc - current_events[-1].ts_utc).total_seconds()
        
        # Same app AND gap < 2 minutes = continue block
        if app == current_app and gap <= MERGE_GAP.total_seconds():
            current_events.append(event)
        else:
            # Different app or gap too big - finalize current block
            block = _events_to_block(current_events, hostname)
            if block:
                blocks.append(block)
            
            current_app = app
            current_events = [event]
    
    # Don't forget last block
    if current_events:
        block = _events_to_block(current_events, hostname)
        if block:
            blocks.append(block)
    
    return blocks


def _app_key_from_event(event) -> str:
    """Get app key from event."""
    return (event.app_name or "").lower().strip()


def _events_to_block(events: List, hostname: Optional[str]) -> Optional[Dict]:
    """Convert a list of events into a block dict."""
    if not events:
        return None
    
    start = events[0].ts_utc
    
    # End = last event + duration to next (capped)
    # For simplicity, use last event + 5 minutes or time to next
    if len(events) == 1:
        end = start + timedelta(minutes=5)
    else:
        # Use the span of events + small buffer
        end = events[-1].ts_utc + timedelta(minutes=5)
    
    # Calculate actual minutes from time range
    minutes = (end - start).total_seconds() / 60.0
    
    if minutes < 0.5:  # Less than 30 seconds
        return None
    
    # Pick the most descriptive window title
    titles = [e.window_title for e in events if e.window_title]
    titles = [t for t in titles if t.lower() not in ('', 'open', 'untitled', 'new tab')]
    window_title = max(titles, key=len) if titles else (events[0].window_title or "")
    
    # Pick URL if any
    urls = [e.url for e in events if e.url]
    url = urls[0] if urls else ""
    
    # Pick file_path if any
    paths = [e.file_path for e in events if e.file_path]
    file_path = paths[0] if paths else ""
    
    return {
        "start": start,
        "end": end,
        "minutes": minutes,
        "app_name": events[0].app_name or "",
        "bundle_id": events[0].bundle_id or "",
        "window_title": window_title,
        "url": url,
        "file_path": file_path,
        "hostname": events[0].hostname or hostname or "unknown",
        "device_id": _safe_device_id(getattr(events[0], 'device_id', None)),
        "current_client_id": getattr(events[0], 'current_client_id', None),
        "ctx": getattr(events[0], 'ctx', {}) or {},
        "source_events": events,
    }


def _try_merge_into_existing(block_data: Dict, existing_blocks: List[Block]) -> bool:
    """
    Try to merge block_data into an existing uncategorized block.
    Only merges if:
    1. Same app
    2. Time ranges overlap OR gap < 2 minutes
    3. NOT separated by a session gap (> 30 min)
    """
    app = _app_key(block_data)
    block_start = block_data["start"]
    block_end = block_data["end"]
    
    for existing in existing_blocks:
        if existing.is_categorized:
            continue
        
        if _app_key(existing) != app:
            continue
        
        # Check time relationship
        # Gap = time between blocks (negative = overlap)
        if block_start > existing.end:
            gap_seconds = (block_start - existing.end).total_seconds()
        elif block_end < existing.start:
            gap_seconds = (existing.start - block_end).total_seconds()
        else:
            gap_seconds = 0  # Overlapping
        
        # Only merge if gap < 2 minutes (and definitely not > 30 min)
        if gap_seconds <= MERGE_GAP.total_seconds():
            # Merge!
            try:
                with transaction.atomic():
                    locked = Block.objects.select_for_update().get(id=existing.id)
                    
                    if locked.is_categorized:
                        continue
                    
                    # Calculate new time range
                    new_start = min(locked.start, block_start)
                    new_end = max(locked.end, block_end)
                    new_minutes = int((new_end - new_start).total_seconds() / 60)
                    
                    # Sanity check - don't create blocks > 4 hours
                    if new_minutes > 240:
                        logger.warning(f"[COMPACT] Refusing to create {new_minutes}min block - too long")
                        continue
                    
                    locked.start = new_start
                    locked.end = new_end
                    locked.minutes = new_minutes
                    
                    # Keep better window title
                    if len(block_data.get("window_title", "")) > len(locked.window_title or ""):
                        locked.window_title = block_data["window_title"]
                    
                    locked.save(update_fields=['start', 'end', 'minutes', 'window_title'])
                    
                    # Link events
                    event_ids = [e.id for e in block_data["source_events"]]
                    RawEvent.objects.filter(id__in=event_ids).update(block=locked)
                    
                    # Update local reference
                    existing.start = new_start
                    existing.end = new_end
                    existing.minutes = new_minutes
                    
                    logger.debug(f"[COMPACT] Merged into block {locked.id} → {new_minutes} min")
                    return True
                    
            except Block.DoesNotExist:
                continue
    
    return False


def _create_block(block_data: Dict, user, org, day: date_type) -> Optional[Block]:
    """Create a new block from block_data."""
    
    is_idle = is_idle_activity(
        app_name=block_data.get("app_name"),
        bundle_id=block_data.get("bundle_id"),
        window_title=block_data.get("window_title")
    )
    
    device_id = block_data.get("device_id", 0)
    minutes = int(block_data["minutes"])
    
    # Sanity check
    if minutes > 240:
        logger.warning(f"[COMPACT] Refusing to create {minutes}min block - too long")
        return None
    
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
            hints=block_data.get("ctx") or {},
            client=client,
            category_hours={},
            is_categorized=False,
            approved=False,
        )
    
    # Link events
    event_ids = [e.id for e in block_data["source_events"]]
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