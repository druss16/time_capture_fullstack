# tracker/services/compaction.py
"""
Improved compaction service that:
1. Uses duration-to-next-event logic (more accurate)
2. Caps idle gaps (lunch breaks don't create 60-min blocks)
3. Coalesces adjacent identical activities
4. Respects immutability (doesn't touch categorized blocks)
"""

from __future__ import annotations
from datetime import datetime, timedelta, date as date_type
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from tracker.models import Block, RawEvent, Client, CurrentClient
from tracker.utils.blocks import is_idle_activity, get_current_client_for_user

import logging
logger = logging.getLogger(__name__)

User = get_user_model()

# Configuration
IDLE_CAP = timedelta(minutes=30)   # Cap long gaps (e.g., lunch) to 30 minutes
MIN_BLOCK = timedelta(seconds=30)  # Drop tiny blips under 30 seconds
COALESCE_GAP = timedelta(seconds=5)  # Merge blocks if gap < 5 seconds


def compact_day(user, day: date_type, hostname: Optional[str] = None, org=None) -> int:
    """
    Build blocks from raw events for a specific day.
    Uses duration-to-next-event logic for accurate time tracking.
    
    Args:
        user: User instance or username
        day: date object for the day to compact
        hostname: Optional hostname filter
        org: Organization Group
    
    Returns:
        Number of blocks created
    """
    # Normalize user
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            logger.warning(f"[COMPACT] User not found: {user}")
            return 0
    
    if not user:
        return 0
    
    # Get org if not provided
    # Get org if not provided
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
    
    logger.info(f"[COMPACT] Processing {day} for {user.username}")
    
    # ✅ Step 1: Get all raw events for the day
    qs = RawEvent.objects.filter(
        user=user,
        ts_utc__date=day
    ).order_by('ts_utc')
    
    if hostname:
        qs = qs.filter(hostname=hostname)
    
    events = list(qs)
    
    if not events:
        logger.debug(f"[COMPACT] No events found for {day}")
        return 0
    
    logger.info(f"[COMPACT] Found {len(events)} events for {day}")
    
    # ✅ Step 2: Check for existing categorized blocks (DON'T DELETE THESE!)
    existing_blocks = Block.objects.filter(
        user=user,
        day=day
    )
    
    if hostname:
        existing_blocks = existing_blocks.filter(hostname=hostname)
    
    categorized_blocks = []
    uncategorized_blocks = []
    categorized_time_ranges = []
    
    for b in existing_blocks:
        if b.is_categorized:
            categorized_blocks.append(b)
            if b.start and b.end:
                categorized_time_ranges.append((b.start, b.end))
        else:
            uncategorized_blocks.append(b)
    
    # Delete ONLY uncategorized blocks (safe to recreate)
    if uncategorized_blocks:
        uncategorized_ids = [b.id for b in uncategorized_blocks]
        Block.objects.filter(id__in=uncategorized_ids).delete()
        logger.info(f"[COMPACT] Deleted {len(uncategorized_ids)} uncategorized blocks")
    
    logger.info(f"[COMPACT] Protected {len(categorized_blocks)} categorized blocks")
    
    # ✅ Step 3: Build raw blocks using duration-to-next-event logic
    raw_blocks = []
    
    for i, event in enumerate(events):
        start = event.ts_utc
        
        # Duration = time until next event (or now if this is the last event)
        if i + 1 < len(events):
            next_ts = events[i + 1].ts_utc
        else:
            # Last event of the day - cap at 10 minutes
            next_ts = start + timedelta(minutes=10)
        
        # Calculate duration with idle cap
        dur = max(timedelta(0), min(next_ts - start, IDLE_CAP))
        
        # Skip tiny blips
        if dur < MIN_BLOCK:
            continue
        
        end = start + dur
        
        # Check if this overlaps with a categorized block
        overlaps = False
        for cat_start, cat_end in categorized_time_ranges:
            if start < cat_end and end > cat_start:
                overlaps = True
                break
        
        if overlaps:
            continue  # Skip events that overlap with categorized blocks
        
        raw_blocks.append({
            "start": start,
            "end": end,
            "minutes": dur.total_seconds() / 60.0,
            "app_name": event.app_name or "",
            "bundle_id": event.bundle_id or "",
            "window_title": event.window_title or "",
            "url": event.url or "",
            "file_path": event.file_path or "",
            "hostname": event.hostname or hostname or "unknown",
            "device_id": getattr(event, 'device_id', 'unknown'),
            "current_client_id": getattr(event, 'current_client_id', None),
            "ctx": getattr(event, 'ctx', {}),
        })
    
    if not raw_blocks:
        logger.info(f"[COMPACT] No blocks to create (all overlapped with categorized blocks)")
        return 0
    
    # ✅ Step 4: Coalesce adjacent identical activities
    coalesced = []
    
    for block in raw_blocks:
        if coalesced and _can_coalesce(coalesced[-1], block):
            # Merge with previous block
            coalesced[-1]["end"] = block["end"]
            coalesced[-1]["minutes"] += block["minutes"]
        else:
            # Start new block
            coalesced.append(block)
    
    logger.info(f"[COMPACT] Coalesced {len(raw_blocks)} raw blocks → {len(coalesced)} final blocks")
    
    # ✅ Step 5: Create Block records
    created_count = 0
    
    with transaction.atomic():
        for block_data in coalesced:
            # Check if this is idle activity
            is_idle = is_idle_activity(
                app_name=block_data.get("app_name"),
                bundle_id=block_data.get("bundle_id"),
                window_title=block_data.get("window_title")
            )
            
            # Get client (only for non-idle blocks)
            client = None
            if not is_idle:
                client_id = block_data.get("current_client_id")
                if client_id:
                    try:
                        client = Client.objects.get(id=client_id)
                    except Client.DoesNotExist:
                        pass
                
                # Fallback: Get current client for user
                if not client:
                    client = get_current_client_for_user(
                        user,
                        device_id=block_data.get("device_id")
                    )
            
            # Create block
            # Auto-categorize idle blocks
            if is_idle:
                hours = round(int(block_data["minutes"]) / 60.0, 2)
                Block.objects.create(
                    org=org,
                    user=user,
                    device_id=block_data["device_id"],
                    hostname=block_data["hostname"],
                    start=block_data["start"],
                    end=block_data["end"],
                    day=day,
                    minutes=int(block_data["minutes"]),
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
                Block.objects.create(
                    org=org,
                    user=user,
                    device_id=block_data["device_id"],
                    hostname=block_data["hostname"],
                    start=block_data["start"],
                    end=block_data["end"],
                    day=day,
                    minutes=int(block_data["minutes"]),
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
            
            created_count += 1
    
    logger.info(f"[COMPACT] Created {created_count} new blocks for {day}")
    
    return created_count


def _can_coalesce(block1: Dict[str, Any], block2: Dict[str, Any]) -> bool:
    """
    Check if two blocks can be merged.
    
    Criteria:
    - Same app_name, bundle_id, window_title
    - Gap between blocks < 5 seconds
    """
    # Check signature match
    if not all([
        block1["app_name"] == block2["app_name"],
        block1["bundle_id"] == block2["bundle_id"],
        block1["window_title"] == block2["window_title"],
    ]):
        return False
    
    # Check time gap
    gap = block2["start"] - block1["end"]
    if gap > COALESCE_GAP:
        return False
    
    return True


def compact_recent_events(user, hostname: Optional[str] = None, minutes_back: int = 15) -> int:
    """
    Quick compaction of recent events (last 15 minutes).
    Called after raw events are ingested to create blocks immediately.
    
    Args:
        user: User instance or username
        hostname: Optional hostname filter
        minutes_back: How far back to look (default 15 minutes)
    
    Returns:
        Number of blocks created/updated
    """
    # Normalize user
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return 0
    
    if not user:
        return 0
    
    # Get today's date
    today = timezone.localdate()
    
    # Compact today
    return compact_day(user, today, hostname=hostname)


# ============================================================================
# BACKGROUND TASK: Auto-compact for all active users
# ============================================================================

def auto_compact_all_active_users(minutes_back: int = 30):
    """
    Auto-compact recent events for all users who have activity in the last N minutes.
    Called by Celery beat every 10 minutes.
    
    Returns:
        Dict with stats
    """
    from django.utils import timezone
    
    cutoff = timezone.now() - timedelta(minutes=minutes_back)
    
    # Find users with recent activity
    recent_users = RawEvent.objects.filter(
        ts_utc__gte=cutoff
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
    
    logger.info(f"[AUTO-COMPACT] Processed {stats['users_processed']} users, created {stats['blocks_created']} blocks")
    
    return stats