# tracker/utils/blocks.py
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional
from django.db import transaction
from django.utils import timezone
from tracker.models import Block, RawEvent, Client, KnownEntity

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

# --- very light compaction: RawEvent → Block (optional no-op) ---
def compact_rawevents_into_blocks(user: Optional[str], hostname: Optional[str], org) -> int:
    """
    Minimal “compaction” so your summary endpoint has Blocks to aggregate.
    This is intentionally simple and safe: it only creates a single Block for
    the most recent hour if none exist today.

    Returns number of blocks created.
    """
    if not user:
        return 0

    # If we already have at least one block today, skip
    today = timezone.localdate()
    exists = Block.objects.filter(user__username=user, day=today).exists()
    if exists:
        return 0

    # Find at least one recent RawEvent for this user/host in the last 90 minutes
    since = timezone.now() - timedelta(minutes=90)
    re_qs = RawEvent.objects.filter(ts_utc__gte=since, user__username=user)
    if hostname:
        re_qs = re_qs.filter(hostname=hostname)
    re_qs = re_qs.order_by("ts_utc")

    first = re_qs.first()
    last = re_qs.last()
    if not (first and last):
        return 0

    # Create one coarse block spanning the min..max of the window
    start_utc = first.ts_utc
    end_utc = last.ts_utc
    if end_utc <= start_utc:
        end_utc = start_utc + timedelta(minutes=5)

    from django.contrib.auth.models import User
    u = User.objects.get(username=user)

    with transaction.atomic():
        blk = Block.objects.create(
            org=org,
            user=u,
            hostname=hostname or "unknown",
            start=start_utc,
            end=end_utc,
            window_title=last.window_title or "",
            title=last.app_name or "",
            url=last.url or "",
            file_path=last.file_path or "",
            minutes=int((end_utc - start_utc).total_seconds() // 60),
            day=start_utc.astimezone(dt_timezone.utc).astimezone(timezone.get_current_timezone()).date(),
            category_hours={},  # let AI/signal fill later
        )
    return 1