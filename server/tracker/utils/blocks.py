# tracker/utils/blocks.py
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional
from django.db import transaction
from django.utils import timezone
from tracker.models import Block, RawEvent, Client, KnownEntity, CurrentClient

# ============================================================================
# HELPER: Detect Communication/Meeting Apps
# ============================================================================
COMMUNICATION_APPS = {
    'zoom', 'zoom.us', 'zoomus',
    'microsoft teams', 'teams',
    'slack',
    'google meet', 'meet',
    'webex', 'cisco webex',
    'skype',
    'discord',
    'google chat',
    'ringcentral',
    'bluejeans',
    'goto meeting', 'gotomeeting',
}

COMMUNICATION_KEYWORDS = {
    'zoom meeting',
    'teams meeting',
    'google meet',
    'meeting with',
    'video call',
    'conference call',
    'meet.google.com',
    'zoom.us',
    'teams.microsoft.com',
    'slack call',
    'discord call',
}

def is_communication_activity(app_name=None, window_title=None, url=None):
    """
    Detect if activity is from a communication/meeting app.
    These should NEVER be marked as idle, even with low mouse activity.
    
    Args:
        app_name: Application name
        window_title: Window title text
        url: URL if available
    
    Returns:
        True if this is a communication app (meeting/call)
    """
    # Check app name
    if app_name:
        app_lower = app_name.lower()
        if any(comm_app in app_lower for comm_app in COMMUNICATION_APPS):
            return True
    
    # Check window title
    if window_title:
        title_lower = window_title.lower()
        if any(keyword in title_lower for keyword in COMMUNICATION_KEYWORDS):
            return True
    
    # Check URL
    if url:
        url_lower = url.lower()
        communication_domains = [
            'zoom.us',
            'meet.google.com',
            'teams.microsoft.com',
            'slack.com',
            'discord.com',
            'webex.com',
            'bluejeans.com',
            'gotomeeting.com',
        ]
        if any(domain in url_lower for domain in communication_domains):
            return True
    
    return False


# ============================================================================
# HELPER: Detect Idle Blocks
# ============================================================================
def is_idle_activity(app_name=None, bundle_id=None, window_title=None, url=None):
    """
    Detect if activity represents idle/AFK time.
    
    ✅ UPDATED: Never marks communication apps as idle (Zoom, Teams, Meet, etc.)
    
    Idle blocks should NEVER be assigned to a client.
    
    Args:
        app_name: Application name
        bundle_id: macOS bundle identifier
        window_title: Window title text
        url: URL if available
    
    Returns:
        True if this should be marked as idle
    """
    # ✅ CHECK COMMUNICATION FIRST - these are NEVER idle
    # People on video calls often don't move their mouse!
    if is_communication_activity(app_name, window_title, url):
        return False
    
    # Check bundle_id
    if bundle_id == "__idle__":
        return True
    
    # Check app_name
    if app_name and app_name.lower() in ("idle", "loginwindow", "screensaver", "screensaverengine"):
        return True
    
    # Check window_title
    if window_title:
        title_lower = window_title.strip().lower()
        idle_titles = {
            "uncategorized - idle",
            "idle/uncategorized",
            "idle",
            "uncategorized",
            "lock screen",
            "screen saver",
            "loginwindow"
        }
        if title_lower in idle_titles:
            return True
    
    return False


# ============================================================================
# HELPER: Get Current Client for User/Device
# ============================================================================
def get_current_client_for_user(user, device_id=None):
    """Get current client, but clear if stale (> 8 hours old)."""
    from django.utils import timezone
    from datetime import timedelta
    
    # Get the current client record
    current = UserCurrentClient.objects.filter(user=user).first()
    
    if not current or not current.client:
        return None
    
    # ✅ FIX: If set more than 8 hours ago, consider it stale
    STALE_HOURS = 8
    if current.updated_at:
        age = timezone.now() - current.updated_at
        if age > timedelta(hours=STALE_HOURS):
            # Clear stale client
            current.client = None
            current.save()
            return None
    
    return current.client


# --- basic client resolver ---
def resolve_client_from_known(org, block: Block) -> Optional[str]:
    """
    Prefer FK client name; else AI extracted; else KnownEntity lookup by keyword.
    Returns a client name (string) or None.
    """
    # If FK is already set
    if getattr(block, "client", None):
        return block.client.name

    # AI extracted (string)
    ai_client = getattr(block, "ai_extracted_client", None)
    if ai_client:
        return ai_client

    haystack = " ".join([
        block.title or "",
        block.window_title or "",
        block.url or "",
        block.file_path or "",
    ]).lower()

    # Known entities (client-level)
    for ke in KnownEntity.objects.filter(org=org, entity_type="client"):
        if ke.name.lower() in haystack or any(a.lower() in haystack for a in (ke.aliases or [])):
            return ke.name

    return None

# --- lightweight task/category inference ---
TASK_KEYWORDS = [
    ("Email/Communication", [r"gmail|outlook|inbox|mail", r"reply|respond|compose|email"]),
    ("Meetings/Calls",      [r"zoom|meet\.google\.com|teams\.microsoft|calendar", r"meeting|call|standup"]),
    ("File Organization",   [r"finder|onedrive|dropbox|box", r"rename|organize|upload|move file"]),
    ("Research",            [r"google\.com|bing\.com|duckduckgo", r"search|docs|whitepaper|reference"]),
    ("Bookkeeping",         [r"quickbooks|xero|sage|netsuite", r"ledger|recon|invoice|bill|payables|receivables"]),
    ("Tax Prep",            [r"lacerte|proseries|drake|ultratax|proconnect|tax", r"return|1040|1120|k-1|w-2|1099"]),
]

def infer_task_for_block(block: Block) -> str:
    """
    Use AI category if present; otherwise keyword heuristics.
    """
    if getattr(block, "ai_category", None):
        return block.ai_category

    text = " ".join([
        block.title or "",
        block.window_title or "",
        block.url or "",
        block.file_path or "",
    ]).lower()

    for label, patterns in TASK_KEYWORDS:
        hits = 0
        for pat in patterns:
            if re.search(pat, text):
                hits += 1
        if hits >= 1:
            return label

    return "Uncategorized"

# ============================================================================
# UPDATED COMPACTION WITH CURRENT CLIENT SUPPORT
# ============================================================================
def compact_rawevents_into_blocks(
    user: Optional[str], 
    hostname: Optional[str], 
    org,
    device_id: Optional[str] = None,
    **kwargs  # Accept extra args for compatibility
) -> int:
    """
    Minimal "compaction" that creates blocks from raw events.
    NOW: Automatically applies current client from CurrentClient table.
    
    ✅ UPDATED: Never marks communication apps (Zoom, Teams, Meet) as idle
    
    Args:
        user: Username or User instance
        hostname: Device hostname
        org: Organization Group
        device_id: Optional device ID for client lookup
    
    Returns:
        Number of blocks created
    """
    if not user:
        return 0

    from django.contrib.auth.models import User
    
    # Normalize user to User instance
    user_obj = user if isinstance(user, User) else None
    if not user_obj:
        try:
            user_obj = User.objects.get(username=user)
        except User.DoesNotExist:
            return 0

    # If we already have at least one block today, skip
    today = timezone.localdate()
    exists = Block.objects.filter(user=user_obj, day=today).exists()
    if exists:
        return 0

    # Find at least one recent RawEvent for this user/host in the last 90 minutes
    since = timezone.now() - timedelta(minutes=90)
    re_qs = RawEvent.objects.filter(ts_utc__gte=since, user=user_obj)
    if hostname:
        re_qs = re_qs.filter(hostname=hostname)
    re_qs = re_qs.order_by("ts_utc")

    first = re_qs.first()
    last = re_qs.last()
    if not (first and last):
        return 0

    # ✅ GET CURRENT CLIENT FOR THIS USER/DEVICE
    # BUT: Don't assign client to idle blocks!
    current_client = None
    
    # Check if this is idle activity (✅ now passes url parameter)
    is_idle = is_idle_activity(
        app_name=last.app_name,
        bundle_id=last.bundle_id,
        window_title=last.window_title,
        url=last.url  # ✅ Added: Pass URL for meeting detection
    )
    
    # Only get current client for NON-IDLE blocks
    if not is_idle:
        current_client = get_current_client_for_user(user_obj, device_id)
        
        # If no device-specific client, check event ctx for hints
        if not current_client and hasattr(last, 'ctx') and last.ctx:
            client_id = last.ctx.get('_current_client_id')
            if client_id:
                try:
                    current_client = Client.objects.get(id=client_id)
                except Client.DoesNotExist:
                    pass

    # Create one coarse block spanning the min..max of the window
    start_utc = first.ts_utc
    end_utc = last.ts_utc
    if end_utc <= start_utc:
        end_utc = start_utc + timedelta(minutes=5)

    with transaction.atomic():
        blk = Block.objects.create(
            org=org,
            user=user_obj,
            hostname=hostname or "unknown",
            device_id=device_id or getattr(last, 'device_id', 'unknown'),
            start=start_utc,
            end=end_utc,
            window_title=last.window_title or "",
            title=last.app_name or "",
            url=last.url or "",
            file_path=last.file_path or "",
            minutes=int((end_utc - start_utc).total_seconds() // 60),
            day=start_utc.astimezone(dt_timezone.utc).astimezone(timezone.get_current_timezone()).date(),
            category_hours={},
            # ✅ AUTO-ASSIGN CURRENT CLIENT
            client=current_client,
        )
    
    return 1


# ============================================================================
# HELPER: Apply Current Client to Recent Blocks
# ============================================================================
def apply_current_client_to_recent_blocks(
    user,
    client: Client,
    minutes_back: int = 15,
    device_id: Optional[str] = None
) -> int:
    """
    Retroactively assign current client to recent unassigned blocks.
    Called when user switches clients to catch recent activity.
    
    Args:
        user: User instance
        client: Client to assign
        minutes_back: How far back to look (default 15 minutes)
        device_id: Optional device filter
    
    Returns:
        Number of blocks updated
    """
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(minutes=minutes_back)
    
    qs = Block.objects.filter(
        user=user,
        start__gte=cutoff,
        client__isnull=True  # Only unassigned blocks
    )
    
    if device_id:
        qs = qs.filter(device_id=device_id)
    
    count = qs.update(client=client)
    return count