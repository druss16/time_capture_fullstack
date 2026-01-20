# tracker/services/compaction.py
"""
Event-centric compaction with cross-run block merging:
- Each RawEvent has a `block` FK (null until processed)
- Compaction ONLY processes events where block__isnull=True
- NEW: Events are merged into EXISTING uncategorized blocks when possible
- Events are linked to their block when created
- Categorized blocks are NEVER touched

GUARANTEES:
1. No duplicates - each event belongs to exactly one block
2. No double-counting - events with block!=null are ignored
3. No flip-flopping - categorized blocks never change
4. NEW: Minimal blocks - adjacent same-activity blocks are merged
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
IDLE_CAP = timedelta(minutes=30)       # Cap long gaps to 30 minutes
MIN_BLOCK = timedelta(seconds=30)      # Drop tiny blips under 30 seconds
COALESCE_GAP = timedelta(seconds=5)    # Merge blocks if gap < 5 seconds
MERGE_GAP = timedelta(minutes=5)       # Merge with existing blocks if gap < 5 minutes


def _safe_device_id(device_id) -> int:
    """Ensure device_id is a valid integer. Returns 0 for invalid values."""
    if device_id is None:
        return 0
    try:
        return int(device_id)
    except (ValueError, TypeError):
        return 0


def _block_signature(block_or_dict) -> Tuple[str, str, str]:
    """
    Create a signature tuple for matching blocks.
    Works with both Block objects and dicts.
    """
    if isinstance(block_or_dict, dict):
        return (
            (block_or_dict.get("app_name") or "").lower().strip(),
            (block_or_dict.get("bundle_id") or "").lower().strip(),
            (block_or_dict.get("window_title") or "").lower().strip(),
        )
    else:
        return (
            (getattr(block_or_dict, 'app_name', None) or "").lower().strip(),
            (getattr(block_or_dict, 'bundle_id', None) or "").lower().strip(),
            (getattr(block_or_dict, 'window_title', None) or "").lower().strip(),
        )


def compact_rawevents_into_blocks(user=None, hostname: Optional[str] = None, org=None) -> int:
    """
    Main entry point - called by ai_suggestions_today and other views.
    Compacts today's unlinked events into blocks.
    """
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
    Event-centric compaction with cross-run block merging.
    
    Key principles:
    1. Only process events where block__isnull=True
    2. Merge into existing uncategorized blocks when possible
    3. Never touch categorized blocks
    4. Consolidate duplicate blocks at the end
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
    # STEP 1: Get ONLY unlinked events (never processed before)
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
        # Still run consolidation in case there are duplicate blocks
        consolidated = consolidate_uncategorized_blocks(user, day, hostname, org)
        return consolidated
    
    logger.info(f"[COMPACT] Found {len(events)} unlinked events to process")
    
    # =========================================================
    # STEP 2: Build raw blocks using duration-to-next-event
    # =========================================================
    raw_blocks = []
    
    for i, event in enumerate(events):
        start = event.ts_utc
        
        # Duration = time until next event (capped at IDLE_CAP)
        if i + 1 < len(events):
            next_ts = events[i + 1].ts_utc
        else:
            next_ts = start + timedelta(minutes=10)
        
        dur = max(timedelta(0), min(next_ts - start, IDLE_CAP))
        
        if dur < MIN_BLOCK:
            continue
        
        end = start + dur
        
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
            "device_id": _safe_device_id(getattr(event, 'device_id', None)),
            "current_client_id": getattr(event, 'current_client_id', None),
            "ctx": getattr(event, 'ctx', {}),
            "source_events": [event],
        })
    
    if not raw_blocks:
        logger.info(f"[COMPACT] No blocks to create (all events too short)")
        # Still run consolidation
        consolidated = consolidate_uncategorized_blocks(user, day, hostname, org)
        return consolidated
    
    # =========================================================
    # STEP 3: Coalesce adjacent identical activities (within this batch)
    # =========================================================
    coalesced = []
    
    for block in raw_blocks:
        if coalesced and _can_coalesce(coalesced[-1], block):
            coalesced[-1]["end"] = block["end"]
            coalesced[-1]["minutes"] += block["minutes"]
            coalesced[-1]["source_events"].extend(block["source_events"])
        else:
            coalesced.append(block)
    
    logger.info(f"[COMPACT] Coalesced {len(raw_blocks)} → {len(coalesced)} blocks (within batch)")
    
    # =========================================================
    # STEP 4: Get existing UNCATEGORIZED blocks for merging
    # =========================================================
    existing_uncategorized = list(Block.objects.filter(
        user=user,
        day=day,
        is_categorized=False,
    ).order_by('start'))
    
    if hostname:
        existing_uncategorized = [b for b in existing_uncategorized if b.hostname == hostname]
    
    # Build signature map for quick lookup
    existing_by_sig: Dict[Tuple, List[Block]] = {}
    for eb in existing_uncategorized:
        sig = _block_signature(eb)
        if sig not in existing_by_sig:
            existing_by_sig[sig] = []
        existing_by_sig[sig].append(eb)
    
    logger.info(f"[COMPACT] Found {len(existing_uncategorized)} existing uncategorized blocks to potentially merge into")
    
    # =========================================================
    # STEP 5: Try to merge new blocks into existing ones
    # =========================================================
    blocks_to_create = []
    merged_count = 0
    
    with transaction.atomic():
        for block_data in coalesced:
            sig = _block_signature(block_data)
            matching_existing = existing_by_sig.get(sig, [])
            
            merged = False
            
            for existing in matching_existing:
                # Check if adjacent or overlapping (within MERGE_GAP)
                gap_after_existing = (block_data["start"] - existing.end).total_seconds()
                gap_before_existing = (existing.start - block_data["end"]).total_seconds()
                
                # Merge if: new block is within 5 minutes before or after existing
                # OR if they overlap
                can_merge = (
                    -300 <= gap_after_existing <= MERGE_GAP.total_seconds() or  # New starts near/after existing end
                    -300 <= gap_before_existing <= MERGE_GAP.total_seconds() or  # New ends near/before existing start
                    (block_data["start"] <= existing.end and block_data["end"] >= existing.start)  # Overlap
                )
                
                if can_merge:
                    # Extend existing block
                    new_start = min(existing.start, block_data["start"])
                    new_end = max(existing.end, block_data["end"])
                    new_minutes = int((new_end - new_start).total_seconds() / 60)
                    
                    # Lock and update
                    existing_locked = Block.objects.select_for_update().get(id=existing.id)
                    
                    # Double-check it's still uncategorized
                    if existing_locked.is_categorized:
                        continue
                    
                    existing_locked.start = new_start
                    existing_locked.end = new_end
                    existing_locked.minutes = new_minutes
                    existing_locked.save(update_fields=['start', 'end', 'minutes'])
                    
                    # Link events to this existing block
                    event_ids = [e.id for e in block_data["source_events"]]
                    RawEvent.objects.filter(id__in=event_ids).update(block=existing_locked)
                    
                    # Update our local reference too
                    existing.start = new_start
                    existing.end = new_end
                    existing.minutes = new_minutes
                    
                    logger.info(f"[COMPACT] ✅ Extended existing block {existing.id} with {len(event_ids)} events → now {new_minutes} min")
                    merged = True
                    merged_count += 1
                    break
            
            if not merged:
                blocks_to_create.append(block_data)
    
    logger.info(f"[COMPACT] Merged {merged_count} blocks into existing, {len(blocks_to_create)} new to create")
    
    # =========================================================
    # STEP 6: Create remaining blocks
    # =========================================================
    created_count = 0
    
    with transaction.atomic():
        for block_data in blocks_to_create:
            is_idle = is_idle_activity(
                app_name=block_data.get("app_name"),
                bundle_id=block_data.get("bundle_id"),
                window_title=block_data.get("window_title")
            )
            
            device_id = block_data.get("device_id", 0)
            
            # Get client
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
            
            # Create the block
            if is_idle:
                hours = round(int(block_data["minutes"]) / 60.0, 2)
                new_block = Block.objects.create(
                    org=org,
                    user=user,
                    device_id=device_id or 0,
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
                new_block = Block.objects.create(
                    org=org,
                    user=user,
                    device_id=device_id or 0,
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
            
            # Link source events to this block
            event_ids = [e.id for e in block_data["source_events"]]
            RawEvent.objects.filter(id__in=event_ids).update(block=new_block)
            
            created_count += 1
            logger.debug(f"[COMPACT] Created block {new_block.id} ({new_block.title}) from {len(event_ids)} events")
    
    logger.info(f"[COMPACT] Created {created_count} new blocks for {day}")
    
    # =========================================================
    # STEP 7: Consolidate any remaining duplicate blocks
    # =========================================================
    consolidated = consolidate_uncategorized_blocks(user, day, hostname, org)
    
    return created_count + merged_count


def consolidate_uncategorized_blocks(user, day: date_type, hostname: Optional[str], org) -> int:
    """
    Post-compaction cleanup: merge any uncategorized blocks that have the same
    signature and are adjacent/overlapping.
    
    This handles blocks created by previous compaction runs that should have
    been merged but weren't.
    """
    # Get all uncategorized blocks for today
    qs = Block.objects.filter(
        user=user,
        day=day,
        is_categorized=False,
    ).order_by('start')
    
    if hostname:
        qs = qs.filter(hostname=hostname)
    
    blocks = list(qs)
    
    if len(blocks) < 2:
        return 0
    
    logger.info(f"[CONSOLIDATE] Checking {len(blocks)} uncategorized blocks for duplicates")
    
    # Group by signature
    by_sig: Dict[Tuple, List[Block]] = {}
    for b in blocks:
        sig = _block_signature(b)
        if sig not in by_sig:
            by_sig[sig] = []
        by_sig[sig].append(b)
    
    merged_count = 0
    blocks_to_delete = []
    
    with transaction.atomic():
        for sig, sig_blocks in by_sig.items():
            if len(sig_blocks) < 2:
                continue
            
            # Sort by start time
            sig_blocks.sort(key=lambda b: b.start)
            
            # Find adjacent/overlapping blocks to merge
            i = 0
            while i < len(sig_blocks) - 1:
                current = sig_blocks[i]
                next_block = sig_blocks[i + 1]
                
                # Check if adjacent/overlapping
                gap_seconds = (next_block.start - current.end).total_seconds()
                
                # Merge if gap < 5 minutes OR overlapping
                if gap_seconds <= MERGE_GAP.total_seconds():
                    # Lock both blocks
                    try:
                        current_locked = Block.objects.select_for_update().get(id=current.id)
                        next_locked = Block.objects.select_for_update().get(id=next_block.id)
                        
                        # Double-check neither is categorized
                        if current_locked.is_categorized or next_locked.is_categorized:
                            i += 1
                            continue
                        
                        # Merge next into current
                        new_start = min(current_locked.start, next_locked.start)
                        new_end = max(current_locked.end, next_locked.end)
                        new_minutes = int((new_end - new_start).total_seconds() / 60)
                        
                        current_locked.start = new_start
                        current_locked.end = new_end
                        current_locked.minutes = new_minutes
                        current_locked.save(update_fields=['start', 'end', 'minutes'])
                        
                        # Move events from next to current
                        RawEvent.objects.filter(block=next_locked).update(block=current_locked)
                        
                        # Mark next for deletion
                        blocks_to_delete.append(next_locked.id)
                        
                        # Update local references
                        current.start = new_start
                        current.end = new_end
                        current.minutes = new_minutes
                        
                        # Remove next from list
                        sig_blocks.pop(i + 1)
                        
                        merged_count += 1
                        logger.info(f"[CONSOLIDATE] ✅ Merged block {next_locked.id} into {current_locked.id} → now {new_minutes} min")
                        
                        # Don't increment i - check if we can merge more into current
                        
                    except Block.DoesNotExist:
                        i += 1
                else:
                    i += 1
        
        # Delete merged blocks
        if blocks_to_delete:
            Block.objects.filter(id__in=blocks_to_delete).delete()
            logger.info(f"[CONSOLIDATE] Deleted {len(blocks_to_delete)} merged blocks")
    
    if merged_count > 0:
        logger.info(f"[CONSOLIDATE] Merged {merged_count} duplicate blocks")
    
    return merged_count


def _can_coalesce(block1: Dict[str, Any], block2: Dict[str, Any]) -> bool:
    """
    Check if two blocks can be merged (within same compaction batch).
    Only merge if same app, same window, and gap < 5 seconds.
    """
    if not all([
        block1["app_name"] == block2["app_name"],
        block1["bundle_id"] == block2["bundle_id"],
        block1["window_title"] == block2["window_title"],
    ]):
        return False
    
    gap = block2["start"] - block1["end"]
    if gap > COALESCE_GAP:
        return False
    
    return True


def compact_recent_events(user, hostname: Optional[str] = None, minutes_back: int = 15) -> int:
    """
    Quick compaction of recent events.
    Called after event ingestion for real-time block creation.
    """
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
    """
    Auto-compact for all users with recent activity.
    Run this from a cron job or celery task.
    """
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


# =========================================================
# ONE-TIME CLEANUP: Run this to fix existing duplicate blocks
# =========================================================
def cleanup_duplicate_blocks_for_user(username: str, days_back: int = 7):
    """
    One-time cleanup script to consolidate duplicate blocks.
    Run this after deploying the fix to clean up existing duplicates.
    
    Usage:
        from tracker.services.compaction import cleanup_duplicate_blocks_for_user
        cleanup_duplicate_blocks_for_user('dan', days_back=7)
    """
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        logger.error(f"User not found: {username}")
        return
    
    from tracker.models import Organization, OrganizationMembership
    membership = OrganizationMembership.objects.filter(user=user).first()
    org = membership.organization if membership else None
    
    today = timezone.localdate()
    total_merged = 0
    
    for i in range(days_back):
        day = today - timedelta(days=i)
        merged = consolidate_uncategorized_blocks(user, day, None, org)
        total_merged += merged
        if merged > 0:
            logger.info(f"[CLEANUP] {day}: Merged {merged} duplicate blocks")
    
    logger.info(f"[CLEANUP] Total merged: {total_merged} blocks over {days_back} days")
    return total_merged