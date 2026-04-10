# tracker/services/compaction.py
"""
Event-centric compaction - FIXED VERSION

FIXES:
1. Added auto_compact_all_active_users() - was missing, Celery task was failing
2. Use .update() instead of .save() to bypass Block protection when merging
3. 3-minute idle cap to match agent's MOUSE_IDLE_PAUSE_S
"""

from __future__ import annotations
from datetime import datetime, timedelta, date as date_type
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone
from django.contrib.auth import get_user_model

from tracker.models import Block, RawEvent, Client
from tracker.utils.blocks import is_idle_activity, get_current_client_for_user

import logging
logger = logging.getLogger(__name__)

User = get_user_model()

# Configuration
IDLE_CAP = timedelta(minutes=3)  # ✅ FIXED: Was 30, now 3 to match agent
MIN_BLOCK_MINUTES = 0.5
SESSION_GAP = timedelta(minutes=30)
AUTO_CATEGORIZE_THRESHOLD = 0.70


def _safe_device_id(device_id) -> int:
    if device_id is None:
        return 0
    try:
        return int(device_id)
    except (ValueError, TypeError):
        return 0


def _app_key(event_or_block) -> str:
    if isinstance(event_or_block, dict):
        return (event_or_block.get("app_name") or "").lower().strip()
    return (getattr(event_or_block, 'app_name', None) or "").lower().strip()


def _calculate_minutes_from_events(events_qs) -> int:
    """Calculate total minutes from events. SINGLE SOURCE OF TRUTH."""
    events = list(events_qs.order_by('ts_utc'))
    if not events:
        return 0
    
    total_seconds = 0
    for i, event in enumerate(events):
        if i + 1 < len(events):
            duration = (events[i + 1].ts_utc - event.ts_utc).total_seconds()
            duration = min(duration, IDLE_CAP.total_seconds())  # 3 min cap
        else:
            duration = 180  # 3 min for last event (was 300)
        total_seconds += duration
    
    return int(total_seconds / 60)


# =============================================================================
# AUTO-CATEGORIZATION PATTERNS
# =============================================================================
def auto_categorize_block(block: Block) -> bool:
    """
    Auto-categorize using industry-specific pattern matching.
    Returns True if categorized.
    """
    if block.is_categorized:
        return False
    
    # ✅ NEW: Get industry-specific patterns instead of hardcoded generic ones
    org = getattr(block, 'org', None)
    industry_type = 'general'
    if org:
        industry_type = getattr(org, 'industry_type', 'general') or 'general'
    
    from tracker.industry_categories import get_combined_tool_detection
    TOOL_PATTERNS = get_combined_tool_detection(industry_type)
    
    # Extract block context
    title = (block.window_title or block.title or "").lower()
    url = (block.url or "").lower()
    app_name = (block.app_name or "").lower()
    file_path = (block.file_path or "").lower()
    bundle_id = (block.bundle_id or "").lower()
    combined = f"{title} {url} {app_name} {file_path} {bundle_id}"
    
    hours = round((block.minutes or 0) / 60.0, 2)
    if hours <= 0:
        hours = 0.01
    
    best_match = None
    best_confidence = 0.0
    
    # ✅ NEW: Use industry-specific tool detection patterns
    for tool_name, patterns in TOOL_PATTERNS.items():
        confidence = 0.0
        
        # Check keywords
        for keyword in patterns.get('keywords', []):
            if keyword.lower() in combined:
                confidence = max(confidence, patterns.get('confidence', 0.85))
                break
        
        # Check domains
        for domain in patterns.get('domains', []):
            if domain.lower() in url:
                confidence = max(confidence, patterns.get('confidence', 0.85))
                break
        
        if confidence > best_confidence:
            best_confidence = confidence
            best_match = {
                'category': patterns.get('category', 'Uncategorized'),
                'confidence': confidence
            }
    
    if best_match and best_match['confidence'] >= AUTO_CATEGORIZE_THRESHOLD:
        try:
            block.category_hours = {best_match['category']: hours}
            block.is_categorized = True
            block.categorized_at = timezone.now()
            block.categorized_by = 'pattern'
            block.ai_confidence = best_match['confidence']
            block.ai_category = best_match['category']
            block.save(update_fields=[
                'category_hours', 'is_categorized', 'categorized_at',
                'categorized_by', 'ai_confidence', 'ai_category'
            ])
            logger.info(f"[AUTO-CAT] Block {block.id} ({block.app_name}) → {best_match['category']}")
            return True
        except Exception as e:
            logger.error(f"[AUTO-CAT] Failed: {e}")
    
    return False


# =============================================================================
# ✅ FIX #1: This function was MISSING - Celery was failing silently!
# =============================================================================

def auto_compact_all_active_users(minutes_back: int = 30) -> Dict[str, int]:
    """
    Auto-compact recent events for ALL active users.
    Called by Celery beat every 5 minutes.
    
    Args:
        minutes_back: How far back to look for unlinked events (default 30 min)
    
    Returns:
        Dict with stats: users_processed, blocks_created, errors
    """
    stats = {
        'users_processed': 0,
        'blocks_created': 0,
        'errors': 0,
    }
    
    # Find all users with unlinked events in the last N minutes
    cutoff = timezone.now() - timedelta(minutes=minutes_back)
    
    users_with_events = RawEvent.objects.filter(
        ts_utc__gte=cutoff,
        block__isnull=True
    ).values('user').annotate(count=Count('id')).filter(count__gt=0)
    
    logger.info(f"[AUTO-COMPACT] Found {len(users_with_events)} users with unlinked events")
    
    for user_data in users_with_events:
        user_id = user_data['user']
        event_count = user_data['count']
        
        try:
            user = User.objects.get(id=user_id)
            logger.info(f"[AUTO-COMPACT] Processing {user.username}: {event_count} events")
            
            # Compact today's events for this user
            today = timezone.localdate()
            result = compact_day(user, today)
            
            stats['users_processed'] += 1
            stats['blocks_created'] += result
            
        except User.DoesNotExist:
            logger.warning(f"[AUTO-COMPACT] User {user_id} not found")
            stats['errors'] += 1
        except Exception as e:
            logger.error(f"[AUTO-COMPACT] Error for user {user_id}: {e}", exc_info=True)
            stats['errors'] += 1
    
    logger.info(
        f"[AUTO-COMPACT] Complete: {stats['users_processed']} users, "
        f"{stats['blocks_created']} blocks, {stats['errors']} errors"
    )
    
    return stats


def compact_rawevents_into_blocks(user=None, hostname: Optional[str] = None, org=None) -> int:
    """Main entry point."""
    today = timezone.localdate()
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return 0
    return compact_day(user, today, hostname=hostname, org=org)


def compact_day(user, day: date_type, hostname: Optional[str] = None, org=None) -> int:
    """
    Main compaction logic - FIXED to prevent duplicates and separate by client.
    
    KEY CHANGES:
    1. Group by app AND client (not just app)
    2. Don't merge blocks with different clients
    3. Use .update() instead of .save() to bypass Block protection
    """
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return 0
    
    if not user:
        return 0
    
    if not org:
        from tracker.models import Organization, OrganizationMembership
        membership = OrganizationMembership.objects.filter(user=user).first()
        if membership:
            org = membership.organization
        else:
            org, _ = Organization.objects.get_or_create(
                name="default-org", defaults={"slug": "default-org"}
            )
    
    # Get unlinked events
    qs = RawEvent.objects.filter(
        user=user,
        ts_utc__date=day,
        block__isnull=True
    ).order_by('ts_utc')
    
    if hostname:
        qs = qs.filter(hostname=hostname)
    
    events = list(qs)
    if not events:
        return 0
    
    logger.info(f"[COMPACT] Processing {len(events)} unlinked events for {user.username}")
    
    # Calculate durations
    events_with_duration = []
    for i, event in enumerate(events):
        if i + 1 < len(events):
            duration = (events[i + 1].ts_utc - event.ts_utc).total_seconds()
        else:
            duration = 180  # 3 min for last event
        duration = min(duration, IDLE_CAP.total_seconds())  # 3 min cap
        
        events_with_duration.append({
            'event': event,
            'start': event.ts_utc,
            'duration_minutes': duration / 60.0,
            'app_name': event.app_name or "",
            'bundle_id': event.bundle_id or "",
            'window_title': event.window_title or "",
            'url': event.url or "",
            'file_path': event.file_path or "",
            'hostname': event.hostname or hostname or "unknown",
            'device_id': _safe_device_id(getattr(event, 'device_id', None)),
            'current_client_id': getattr(event, 'current_client_id', None),
        })
    
    # Split into sessions
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
    
    # ✅ FIX: Group by app AND client within each session
    blocks_to_create = []
    for session in sessions:
        by_app_client: Dict[str, List] = {}
        for ev in session:
            app = _app_key(ev)
            client_id = ev.get('current_client_id') or 0
            key = f"{app}|{client_id}"  # Group by app AND client
            if key not in by_app_client:
                by_app_client[key] = []
            by_app_client[key].append(ev)
        
        for key, app_events in by_app_client.items():
            if not app_events:
                continue
             
            starts = [e['start'] for e in app_events]
            block_start = min(starts)
            block_end = max(starts) + timedelta(minutes=app_events[-1]['duration_minutes'])
            new_event_minutes = sum(e['duration_minutes'] for e in app_events)
            
            if new_event_minutes < MIN_BLOCK_MINUTES:
                continue
            
            titles = [e['window_title'] for e in app_events if e['window_title']]
            titles = [t for t in titles if t.lower() not in ('', 'open', 'untitled', 'new tab')]
            window_title = max(titles, key=len) if titles else app_events[0]['window_title']
            
            urls = [e['url'] for e in app_events if e['url']]
            paths = [e['file_path'] for e in app_events if e['file_path']]
            
            # Get the client_id (all events in this group have same client)
            client_id = app_events[0].get('current_client_id')
            
            blocks_to_create.append({
                'start': block_start,
                'end': block_end,
                'app_name': app_events[0]['app_name'],
                'bundle_id': app_events[0]['bundle_id'],
                'window_title': window_title,
                'url': urls[0] if urls else "",
                'file_path': paths[0] if paths else "",
                'hostname': app_events[0]['hostname'],
                'device_id': app_events[0]['device_id'],
                'current_client_id': client_id,
                'source_events': [e['event'] for e in app_events],
            })
    
    # Get ALL existing blocks for this day
    existing_blocks = list(Block.objects.filter(
        user=user,
        day=day,
    ).order_by('start'))
    
    # ✅ FIX: Build lookup by app AND client
    existing_by_app_client = {}
    for b in existing_blocks:
        app = _app_key(b)
        client_id = b.client_id or 0
        key = f"{app}|{client_id}"
        if key not in existing_by_app_client:
            existing_by_app_client[key] = []
        existing_by_app_client[key].append(b)
    
    created_count = 0
    merged_count = 0
    blocks_to_categorize = []
    
    with transaction.atomic():
        for block_data in blocks_to_create:
            app = _app_key(block_data)
            new_start = block_data['start']
            new_end = block_data['end']
            new_client_id = block_data.get('current_client_id') or 0
            key = f"{app}|{new_client_id}"
            
            # Find an existing block to merge into (same app AND same client)
            merge_target = None
            
            for existing in existing_by_app_client.get(key, []):
                gap_to_existing = (new_start - existing.end).total_seconds() if existing.end else float('inf')
                gap_from_existing = (existing.start - new_end).total_seconds() if existing.start else float('inf')
                
                if gap_to_existing < SESSION_GAP.total_seconds() or gap_from_existing < SESSION_GAP.total_seconds():
                    merge_target = existing
                    break
                
                if existing.start and existing.end:
                    if new_start >= existing.start and new_start <= existing.end:
                        merge_target = existing
                        break
            
            if merge_target:
                try:
                    locked = Block.objects.select_for_update().get(id=merge_target.id)
                    
                    # Link events to this block
                    event_ids = [e.id for e in block_data['source_events']]
                    RawEvent.objects.filter(id__in=event_ids).update(block=locked)
                    
                    # Calculate new values
                    updated_start = min(locked.start, new_start)
                    updated_end = max(locked.end, new_end)
                    updated_minutes = _calculate_minutes_from_events(
                        RawEvent.objects.filter(block=locked)
                    )
                    
                    # Build update dict
                    update_fields = {
                        'start': updated_start,
                        'end': updated_end,
                        'minutes': updated_minutes,
                    }

                    # ✅ ADD THIS — recalculate billing_amount when minutes change
                    if locked.billing_rate and updated_minutes:
                        update_fields['billing_amount'] = round((updated_minutes / 60) * float(locked.billing_rate), 2)
                    
                    # If categorized, update category_hours
                    if locked.is_categorized and locked.category_hours:
                        category = list(locked.category_hours.keys())[0]
                        update_fields['category_hours'] = {category: round(updated_minutes / 60.0, 2)}
                    
                    # Use .update() to bypass Block.save() protection
                    Block.objects.filter(id=locked.id).update(**update_fields)
                    
                    merged_count += 1
                    logger.debug(f"[COMPACT] Merged into block {locked.id} ({locked.app_name})")
                    continue
                    
                except Block.DoesNotExist:
                    pass
            
            # CREATE new block
            new_block = _create_block(block_data, user, org, day)
            if new_block:
                created_count += 1
                if not new_block.is_categorized:
                    blocks_to_categorize.append(new_block)
                
                # Add to lookup for future merges in this run
                if key not in existing_by_app_client:
                    existing_by_app_client[key] = []
                existing_by_app_client[key].append(new_block)
    
    # Auto-categorize new blocks
    auto_cat_count = 0
    for block in blocks_to_categorize:
        if auto_categorize_block(block):
            auto_cat_count += 1
    
    logger.info(f"[COMPACT] Created {created_count}, merged {merged_count}, auto-cat {auto_cat_count}")
    return created_count + merged_count

def _resolve_billing_rate(org, user, client_id, task_type_id=None):
    from decimal import Decimal
    from django.db.models import Q

    default = getattr(org, 'billing_rate_default', None) or Decimal('0')

    if not org:
        return default

    try:
        from tracker.models import BillingRate
    except ImportError:
        return default

    qs = BillingRate.objects.filter(org=org).order_by("-effective_date")
    uid = getattr(user, 'id', None)

    filters = []
    if uid and client_id and task_type_id:
        filters.append(Q(user_id=uid, client_id=client_id, task_type_id=task_type_id))
    if uid and client_id:
        filters.append(Q(user_id=uid, client_id=client_id, task_type__isnull=True))
    if client_id and task_type_id:
        filters.append(Q(user_id__isnull=True, client_id=client_id, task_type_id=task_type_id))
    if client_id:
        filters.append(Q(user_id__isnull=True, client_id=client_id, task_type__isnull=True))
    if uid:
        filters.append(Q(user_id=uid, client__isnull=True, task_type__isnull=True))

    for f in filters:
        match = qs.filter(f).first()
        if match:
            return match.rate

    return default

def _create_block(block_data: Dict, user, org, day: date_type) -> Optional[Block]:
    """Create a new block - checks work patterns BEFORE defaulting to idle."""
    
    # Extract context for pattern matching
    app_name = (block_data.get("app_name") or "").lower()
    bundle_id = (block_data.get("bundle_id") or "").lower()
    window_title = (block_data.get("window_title") or "").lower()
    url = (block_data.get("url") or "").lower()
    file_path = (block_data.get("file_path") or "").lower()
    
    # =========================================================================
    # ✅ FIX: Check work patterns FIRST before marking as idle
    # This prevents Claude.ai, GitHub, etc. from being marked as idle
    # =========================================================================
    
    # Domains that should NEVER be marked as idle (active work tools)
    NEVER_IDLE_DOMAINS = {
        'claude.ai', 'chat.openai.com', 'chatgpt.com',  # AI assistants
        'github.com', 'gitlab.com', 'bitbucket.org',     # Code repos
        'stackoverflow.com', 'docs.python.org',          # Research
        'localhost', '127.0.0.1',                         # Local dev
        'figma.com', 'canva.com',                         # Design tools
        'notion.so', 'docs.google.com',                   # Docs
        'slack.com', 'teams.microsoft.com',               # Communication
        'zoom.us', 'meet.google.com',                     # Meetings
        'qbo.intuit.com', 'quickbooks.intuit.com',        # Accounting
        'cchaxcess.com', 'irs.gov',                       # Tax
    }
    
    # Apps that should NEVER be marked as idle
    NEVER_IDLE_APPS = {
        'code', 'vscode', 'visual studio', 'sublime', 'sublime_text',
        'pycharm', 'intellij', 'webstorm', 'xcode', 'android studio',
        'terminal', 'iterm', 'iterm2', 'warp', 'hyper',
        'figma', 'sketch', 'photoshop',
        'zoom', 'teams', 'slack',
    }
    
    # Check if this matches a work pattern
    is_work_pattern = False
    
    # Check URL domains
    for domain in NEVER_IDLE_DOMAINS:
        if domain in url:
            is_work_pattern = True
            break
    
    # Check app names
    if not is_work_pattern:
        for app in NEVER_IDLE_APPS:
            if app in app_name:
                is_work_pattern = True
                break
    
    # Only check idle detection if no work pattern matched
    if is_work_pattern:
        is_idle = False
    else:
        is_idle = is_idle_activity(
            app_name=block_data.get("app_name"),
            bundle_id=block_data.get("bundle_id"),
            window_title=block_data.get("window_title")
        )
    
    # =========================================================================
    # Rest of function unchanged
    # =========================================================================
    
    device_id = block_data.get("device_id", 0)
    source_events = block_data.get('source_events', [])
    
    if source_events:
        total_seconds = 0
        for i, event in enumerate(source_events):
            if i + 1 < len(source_events):
                duration = (source_events[i + 1].ts_utc - event.ts_utc).total_seconds()
                duration = min(duration, IDLE_CAP.total_seconds())
            else:
                duration = 180  # 3 min for last event
            total_seconds += duration
        minutes = int(total_seconds / 60)
    else:
        minutes = 3  # fallback
    
    # Get client for ALL blocks (including idle)
    client = None
    client_id = block_data.get("current_client_id")
    if client_id:
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            pass
    if not client and device_id:
        client = get_current_client_for_user(user, device_id=device_id)

    # ✅ Calculate billing rate and amount for new blocks
    client_id_for_rate = block_data.get("current_client_id")
    task_type_id_for_rate = block_data.get("task_type_id")  # None for now, set when task types are tracked
    billing_rate = _resolve_billing_rate(org, user, client_id_for_rate, task_type_id_for_rate)
    billing_amount = round((minutes / 60) * float(billing_rate), 2)
    
    if is_idle:
        client = None  # ← ADD THIS
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
            client=client,
            category_hours={"Idle": hours},
            is_categorized=True,
            categorized_by="system",
            categorized_at=timezone.now(),
            approved=False,
            is_billable=False,
            billing_rate=billing_rate,
            billing_amount=0,
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
            is_billable=True,
            billing_rate=billing_rate,
            billing_amount=billing_amount,
        )
    
    # Link events
    event_ids = [e.id for e in block_data['source_events']]
    RawEvent.objects.filter(id__in=event_ids).update(block=new_block)
    
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


def auto_categorize_existing_blocks(user, day: date_type = None) -> Dict[str, int]:
    """Backfill auto-categorization on existing uncategorized blocks."""
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return {'error': 'User not found'}
    
    if day is None:
        day = timezone.localdate()
    
    blocks = Block.objects.filter(user=user, day=day, is_categorized=False)
    stats = {'checked': 0, 'categorized': 0}
    
    for block in blocks:
        stats['checked'] += 1
        if auto_categorize_block(block):
            stats['categorized'] += 1
    
    logger.info(f"[AUTO-CAT] Checked {stats['checked']}, categorized {stats['categorized']}")
    return stats


def recalculate_block_minutes(block_id: int) -> int:
    """Recalculate minutes for a specific block."""
    try:
        block = Block.objects.get(id=block_id)
        new_minutes = _calculate_minutes_from_events(RawEvent.objects.filter(block=block))
        if new_minutes != block.minutes:
            Block.objects.filter(id=block_id).update(minutes=new_minutes)
        return new_minutes
    except Block.DoesNotExist:
        return 0


# =============================================================================
# CLEANUP FUNCTIONS
# =============================================================================

def cleanup_duplicate_blocks(user, day: date_type = None, dry_run: bool = True) -> Dict[str, int]:
    """Find and remove duplicate blocks."""
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return {'error': 'User not found'}
    
    if day is None:
        day = timezone.localdate()
    
    blocks = list(Block.objects.filter(user=user, day=day).order_by('start'))
    
    to_delete = []
    checked = set()
    
    for i, b1 in enumerate(blocks):
        if b1.id in checked:
            continue
        
        for b2 in blocks[i+1:]:
            if b2.id in checked:
                continue
            
            if _app_key(b1) != _app_key(b2):
                continue
            
            if not (b1.start and b1.end and b2.start and b2.end):
                continue
            
            overlap_start = max(b1.start, b2.start)
            overlap_end = min(b1.end, b2.end)
            
            if overlap_start >= overlap_end:
                continue
            
            overlap_seconds = (overlap_end - overlap_start).total_seconds()
            b1_seconds = (b1.end - b1.start).total_seconds()
            b2_seconds = (b2.end - b2.start).total_seconds()
            
            smaller_seconds = min(b1_seconds, b2_seconds)
            if smaller_seconds > 0 and (overlap_seconds / smaller_seconds) > 0.8:
                b1_events = RawEvent.objects.filter(block=b1).count()
                b2_events = RawEvent.objects.filter(block=b2).count()
                
                if b1_events > b2_events:
                    victim = b2
                elif b2_events > b1_events:
                    victim = b1
                elif b1.minutes >= b2.minutes:
                    victim = b2
                else:
                    victim = b1
                
                to_delete.append(victim)
                checked.add(victim.id)
                logger.info(f"[CLEANUP] Duplicate: {victim.app_name} block {victim.id}")
    
    stats = {'checked': len(blocks), 'duplicates': len(to_delete), 'deleted': 0}
    
    if not dry_run:
        for block in to_delete:
            app = _app_key(block)
            survivor = Block.objects.filter(
                user=user, day=day
            ).exclude(id=block.id).filter(
                app_name__iexact=block.app_name
            ).first()
            
            if survivor:
                RawEvent.objects.filter(block=block).update(block=survivor)
                new_minutes = _calculate_minutes_from_events(
                    RawEvent.objects.filter(block=survivor)
                )
                Block.objects.filter(id=survivor.id).update(minutes=new_minutes)
            
            block.delete()
            stats['deleted'] += 1
    
    logger.info(f"[CLEANUP] {stats}")
    return stats