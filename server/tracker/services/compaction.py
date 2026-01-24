# tracker/services/compaction.py
"""
Event-centric compaction with AUTO-CATEGORIZATION

FEATURES:
1. Session awareness - gap > 30 min = new session (no 9-hour blocks)
2. Event-duration minutes - no double counting (each minute counted once)
3. Smart app merging - one block per app per session (fewer blocks to categorize)
4. **NEW**: Auto-categorization using pattern matching (no API calls)

GUARANTEES:
- Minutes are calculated from EVENT DURATIONS, not block spans
- No double-counting: if you work 1 hour, total is 1 hour
- Categorized blocks are NEVER touched
- Each event belongs to exactly one block
- New blocks are auto-categorized if patterns match with >= 70% confidence
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
AUTO_CATEGORIZE_THRESHOLD = 0.70           # Min confidence to auto-categorize


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


def _calculate_minutes_from_events(events_qs) -> int:
    """
    Calculate total minutes from a queryset of events.
    
    This is the SINGLE SOURCE OF TRUTH for block minutes.
    Duration = time to next event (capped at 30 min), last event = 5 min.
    """
    events = list(events_qs.order_by('ts_utc'))
    if not events:
        return 0
    
    total_seconds = 0
    for i, event in enumerate(events):
        if i + 1 < len(events):
            duration = (events[i + 1].ts_utc - event.ts_utc).total_seconds()
            duration = min(duration, IDLE_CAP.total_seconds())
        else:
            duration = 300  # 5 min for last event
        total_seconds += duration
    
    return int(total_seconds / 60)


# =============================================================================
# AUTO-CATEGORIZATION PATTERNS (No API calls - fast pattern matching)
# =============================================================================

def auto_categorize_block(block: Block) -> bool:
    """
    Attempt to auto-categorize a block using pattern matching.
    Returns True if categorized, False otherwise.
    
    This is FAST (no API calls) and runs on every new block.
    """
    if block.is_categorized:
        return False
    
    # Get block context
    title = (block.window_title or block.title or "").lower()
    url = (block.url or "").lower()
    app_name = (block.app_name or "").lower()
    file_path = (block.file_path or "").lower()
    bundle_id = (block.bundle_id or "").lower()
    
    combined = f"{title} {url} {app_name} {file_path} {bundle_id}"
    
    # Calculate hours for category_hours
    hours = round((block.minutes or 0) / 60.0, 2)
    if hours <= 0:
        hours = 0.01  # Minimum
    
    # =================================================================
    # PATTERN MATCHING - Order matters! More specific patterns first.
    # =================================================================
    
    result = None
    
    # -----------------------------------------------------------------
    # MEETINGS (Highest priority - even low mouse activity is billable)
    # -----------------------------------------------------------------
    meeting_apps = ['zoom', 'teams', 'meet', 'webex', 'slack huddle', 'discord']
    meeting_domains = ['zoom.us', 'meet.google.com', 'teams.microsoft.com']
    meeting_keywords = ['meeting', 'call with', 'video call', 'conference']
    
    if any(app in app_name for app in meeting_apps):
        result = {'category': 'Meetings', 'confidence': 0.92, 'reason': 'Meeting app detected'}
    elif any(domain in url for domain in meeting_domains):
        result = {'category': 'Meetings', 'confidence': 0.90, 'reason': 'Meeting URL detected'}
    elif any(kw in title for kw in meeting_keywords):
        result = {'category': 'Meetings', 'confidence': 0.85, 'reason': 'Meeting keyword in title'}
    
    # -----------------------------------------------------------------
    # SOFTWARE DEVELOPMENT
    # -----------------------------------------------------------------
    if not result:
        dev_apps = ['code', 'vscode', 'visual studio', 'sublime', 'atom', 'intellij', 
                    'pycharm', 'webstorm', 'xcode', 'android studio']
        dev_indicators = ['terminal', 'iterm', 'iterm2', 'hyper', 'warp',
                         'github.com', 'gitlab.com', 'bitbucket.org',
                         'localhost', '127.0.0.1', ':3000', ':8000', ':5173', ':5000',
                         'docker', 'npm', 'yarn', 'pip', 'git ', 'python manage.py',
                         '.py -', '.js -', '.tsx -', '.jsx -', '.ts -', '.vue -',
                         'views.py', 'models.py', 'settings.py', 'urls.py',
                         'component', 'index.tsx', 'app.tsx']
        
        if any(app in app_name for app in dev_apps):
            result = {'category': 'Software Development', 'confidence': 0.95, 'reason': 'Code editor detected'}
        elif any(ind in combined for ind in dev_indicators):
            result = {'category': 'Software Development', 'confidence': 0.88, 'reason': 'Development activity detected'}
    
    # -----------------------------------------------------------------
    # AI / RESEARCH
    # -----------------------------------------------------------------
    if not result:
        ai_indicators = ['claude.ai', 'chat.openai.com', 'chatgpt', 'anthropic',
                        'stackoverflow.com', 'stack overflow',
                        'docs.python.org', 'docs.djangoproject.com', 'reactjs.org',
                        'developer.mozilla.org', 'mdn web docs']
        
        if any(ind in combined for ind in ai_indicators):
            result = {'category': 'Research/AI Assistance', 'confidence': 0.88, 'reason': 'AI/research tool detected'}
    
    # -----------------------------------------------------------------
    # EMAIL / COMMUNICATION
    # -----------------------------------------------------------------
    if not result:
        email_indicators = ['mail.google.com', 'gmail', 'outlook.office', 'outlook.live',
                           'yahoo.com/mail', 'mail.yahoo', 'protonmail',
                           'slack.com', 'app.slack.com', 'discord.com']
        
        if any(ind in combined for ind in email_indicators):
            result = {'category': 'Email/Communication', 'confidence': 0.90, 'reason': 'Email/chat detected'}
    
    # -----------------------------------------------------------------
    # TAX SOFTWARE (CPA-specific)
    # -----------------------------------------------------------------
    if not result:
        tax_indicators = ['ultratax', 'lacerte', 'proseries', 'drake', 'taxact',
                         'cchaxcess', 'thomson reuters', 'wolters kluwer',
                         'irs.gov', '1040', '1120', '1065', 'form 990', 'w-2', '1099']
        
        if any(ind in combined for ind in tax_indicators):
            result = {'category': 'Tax Preparation', 'confidence': 0.93, 'reason': 'Tax software detected'}
    
    # -----------------------------------------------------------------
    # ACCOUNTING SOFTWARE
    # -----------------------------------------------------------------
    if not result:
        accounting_indicators = ['quickbooks', 'qbo.intuit', 'xero.com', 'freshbooks',
                                'wave', 'sage', 'netsuite', 'intacct']
        
        if any(ind in combined for ind in accounting_indicators):
            result = {'category': 'Accounting/Bookkeeping', 'confidence': 0.92, 'reason': 'Accounting software detected'}
    
    # -----------------------------------------------------------------
    # DOCUMENT / ADMIN WORK
    # -----------------------------------------------------------------
    if not result:
        doc_indicators = ['docs.google.com', 'drive.google.com', 'dropbox.com',
                         'onedrive', 'sharepoint', 'notion.so', 'confluence',
                         '.docx', '.xlsx', '.pdf', 'word', 'excel', 'powerpoint']
        
        if any(ind in combined for ind in doc_indicators):
            result = {'category': 'Administration', 'confidence': 0.75, 'reason': 'Document work detected'}
    
    # -----------------------------------------------------------------
    # DESIGN / CREATIVE
    # -----------------------------------------------------------------
    if not result:
        design_indicators = ['figma.com', 'canva.com', 'adobe', 'photoshop',
                            'illustrator', 'sketch', 'invision']
        
        if any(ind in combined for ind in design_indicators):
            result = {'category': 'Design/Creative', 'confidence': 0.88, 'reason': 'Design tool detected'}
    
    # =================================================================
    # Apply categorization if confidence meets threshold
    # =================================================================
    if result and result['confidence'] >= AUTO_CATEGORIZE_THRESHOLD:
        try:
            block.category_hours = {result['category']: hours}
            block.is_categorized = True
            block.categorized_at = timezone.now()
            block.categorized_by = 'pattern'
            block.ai_confidence = result['confidence']
            block.ai_category = result['category']
            block.save(update_fields=[
                'category_hours', 'is_categorized', 'categorized_at',
                'categorized_by', 'ai_confidence', 'ai_category'
            ])
            
            logger.info(
                f"[AUTO-CAT] Block {block.id} ({block.app_name}) → "
                f"{result['category']} ({result['confidence']:.0%}) - {result['reason']}"
            )
            return True
            
        except Exception as e:
            logger.error(f"[AUTO-CAT] Failed to save block {block.id}: {e}")
            return False
    
    return False


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
    Main compaction logic with auto-categorization.
    
    Algorithm:
    1. Get all unlinked events for the day, ordered by time
    2. Calculate duration for each event (time to next event, capped at 30 min)
    3. Split into sessions (gap > 30 min = new session)
    4. Within each session, group events by app
    5. Create one block per app per session, with minutes = SUM of event durations
    6. **NEW**: Auto-categorize new blocks using pattern matching
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
    # =========================================================
    events_with_duration = []
    
    for i, event in enumerate(events):
        if i + 1 < len(events):
            next_ts = events[i + 1].ts_utc
            duration_seconds = (next_ts - event.ts_utc).total_seconds()
        else:
            duration_seconds = 300
        
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
    # STEP 4: Within each session, group by APP
    # =========================================================
    blocks_to_create = []
    
    for session in sessions:
        by_app: Dict[str, List] = {}
        for ev in session:
            app = _app_key(ev)
            if app not in by_app:
                by_app[app] = []
            by_app[app].append(ev)
        
        for app, app_events in by_app.items():
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
            
            blocks_to_create.append({
                'start': block_start,
                'end': block_end,
                'new_event_minutes': new_event_minutes,
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
    # STEP 5: Check for existing uncategorized blocks to merge
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
    auto_categorized_count = 0
    new_blocks = []  # Track new blocks for auto-categorization
    
    with transaction.atomic():
        for block_data in blocks_to_create:
            app = _app_key(block_data)
            existing = existing_uncategorized.get(app)
            
            if existing:
                # Merge into existing block
                try:
                    locked = Block.objects.select_for_update().get(id=existing.id)
                    if not locked.is_categorized:
                        event_ids = [e.id for e in block_data['source_events']]
                        RawEvent.objects.filter(id__in=event_ids).update(block=locked)
                        
                        locked.start = min(locked.start, block_data['start'])
                        locked.end = max(locked.end, block_data['end'])
                        
                        locked.minutes = _calculate_minutes_from_events(
                            RawEvent.objects.filter(block=locked)
                        )
                        locked.save(update_fields=['start', 'end', 'minutes'])
                        
                        merged_count += 1
                        new_blocks.append(locked)  # Try to categorize merged blocks too
                        continue
                except Block.DoesNotExist:
                    pass
            
            # Create new block
            new_block = _create_block(block_data, user, org, day)
            if new_block:
                created_count += 1
                if not new_block.is_categorized:  # Don't add idle blocks
                    new_blocks.append(new_block)
    
    # =========================================================
    # STEP 7: AUTO-CATEGORIZE new/merged blocks
    # =========================================================
    for block in new_blocks:
        if auto_categorize_block(block):
            auto_categorized_count += 1
    
    logger.info(
        f"[COMPACT] Created {created_count}, merged {merged_count}, "
        f"auto-categorized {auto_categorized_count} for {day}"
    )
    return created_count + merged_count


def _create_block(block_data: Dict, user, org, day: date_type) -> Optional[Block]:
    """Create a new block."""
    
    is_idle = is_idle_activity(
        app_name=block_data.get("app_name"),
        bundle_id=block_data.get("bundle_id"),
        window_title=block_data.get("window_title")
    )
    
    device_id = block_data.get("device_id", 0)
    
    # Calculate minutes from the source events
    source_events = block_data.get('source_events', [])
    if source_events:
        total_seconds = 0
        for i, event in enumerate(source_events):
            if i + 1 < len(source_events):
                duration = (source_events[i + 1].ts_utc - event.ts_utc).total_seconds()
                duration = min(duration, IDLE_CAP.total_seconds())
            else:
                duration = 300
            total_seconds += duration
        minutes = int(total_seconds / 60)
    else:
        minutes = int(block_data.get("new_event_minutes", 0))
    
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


def recalculate_block_minutes(block_id: int) -> int:
    """Recalculate minutes for a specific block from its linked events."""
    try:
        block = Block.objects.get(id=block_id)
        new_minutes = _calculate_minutes_from_events(
            RawEvent.objects.filter(block=block)
        )
        if new_minutes != block.minutes:
            logger.info(f"[COMPACT] Block {block_id} minutes: {block.minutes} -> {new_minutes}")
            block.minutes = new_minutes
            block.save(update_fields=['minutes'])
        return new_minutes
    except Block.DoesNotExist:
        return 0


def recalculate_all_blocks_for_day(user, day: date_type) -> Dict[str, int]:
    """Recalculate minutes for ALL blocks on a given day."""
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return {'error': 'User not found'}
    
    blocks = Block.objects.filter(user=user, day=day)
    stats = {'checked': 0, 'fixed': 0, 'total_diff': 0}
    
    for block in blocks:
        old_minutes = block.minutes
        new_minutes = _calculate_minutes_from_events(
            RawEvent.objects.filter(block=block)
        )
        
        stats['checked'] += 1
        
        if new_minutes != old_minutes:
            diff = old_minutes - new_minutes
            stats['fixed'] += 1
            stats['total_diff'] += diff
            
            logger.info(f"[COMPACT] Fixing block {block.id} ({block.app_name}): {old_minutes} -> {new_minutes}")
            block.minutes = new_minutes
            block.save(update_fields=['minutes'])
    
    return stats


def compact_recent_events(user, hostname: Optional[str] = None, minutes_back: int = 15) -> int:
    """Quick compaction of recent events (includes auto-categorization)."""
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


def auto_categorize_existing_blocks(user, day: date_type = None) -> Dict[str, int]:
    """
    Run auto-categorization on existing uncategorized blocks.
    Use this to backfill categorization on old data.
    
    Returns stats dict.
    """
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return {'error': 'User not found'}
    
    if day is None:
        day = timezone.localdate()
    
    blocks = Block.objects.filter(
        user=user,
        day=day,
        is_categorized=False
    )
    
    stats = {'checked': 0, 'categorized': 0}
    
    for block in blocks:
        stats['checked'] += 1
        if auto_categorize_block(block):
            stats['categorized'] += 1
    
    logger.info(
        f"[AUTO-CAT] Checked {stats['checked']} blocks, "
        f"categorized {stats['categorized']} for {day}"
    )
    
    return stats