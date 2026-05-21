# tracker/services/compaction.py
"""
Event-centric compaction — v1.3.39 (content-split).

KEY CHANGE FROM v1.3.38
=======================
Compaction now groups events by (app, client, content_bucket) instead of
just (app, client). This prevents personal browsing (Fox News, social
media) from being merged into the same Block as legitimate work that
happens to share the same app/client/session.

Block 11005 example (Wayne, 11:39-13:00 Internal-Tax Edge):
  Before: 1 Block containing CS login + Onvio + Fox News + Sonia Citron
          (all merged because app=Msedge, client=Internal-Tax matched)
  After:  Multiple Blocks split by content type:
            - work bucket: CS login + Onvio events
            - personal bucket: Fox News + Sonia Citron events

Pure-personal blocks also drop the client attribution (high-confidence
news/social browsing was never for any client; the agent's selection
was just stale state).

UNCHANGED FROM v1.3.38
======================
Dual interval timestamps, meeting extraction, idle filter, foreground
filter, auto-categorization, cleanup paths.

KEY INVARIANTS
==============
- Compaction is idempotent: re-running on the same events produces the
  same blocks (modulo race with newly-arriving events).
- SESSION_GAP defines block boundaries — gaps larger than this start a new
  block. Gap is measured as next.start_ts - prev.end_ts (true gap).
- The 0 <= gap < SESSION_GAP guard prevents negative-gap merges
  (block 10594 fix preserved).
"""

from __future__ import annotations
from datetime import datetime, timedelta, date as date_type
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone
from django.contrib.auth import get_user_model
from decimal import Decimal

from tracker.models import Block, RawEvent, Client
from tracker.utils.blocks import is_idle_activity, get_current_client_for_user
from tracker.utils.content_classifier import (
    classify_event_content,
    is_high_confidence_personal,
)

import logging
logger = logging.getLogger(__name__)

User = get_user_model()

# Configuration
# IDLE_CAP — DEPRECATED in v1.3.38. Events carry real intervals; no more
# capping needed. Kept as a no-op constant so any external imports don't
# break.
IDLE_CAP = timedelta(minutes=10)  # DEPRECATED — unused

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
    """
    Sum real interval durations across events.
    Overlapping events deduplicated via interval union to prevent double-counting.
    """
    events = list(events_qs.order_by("start_ts"))
    if not events:
        return 0

    intervals = sorted((e.start_ts, e.end_ts) for e in events)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    total_seconds = sum((end - start).total_seconds() for start, end in merged)
    return int(total_seconds / 60)


def _calculate_minutes_for_events_list(events: list) -> int:
    """Same as above but for a Python list of RawEvent objects (no queryset)."""
    if not events:
        return 0
    intervals = sorted((e.start_ts, e.end_ts) for e in events)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    total_seconds = sum((end - start).total_seconds() for start, end in merged)
    return max(1, int(total_seconds / 60))


def _content_identifier(window_title: str, file_path: str, url: str) -> str:
    """
    Universal content identifier for compaction grouping. Returns a
    stable string identifying WHAT the user is working on, independent
    of the agent's current_client_id (which can be stale).

    Priority order:
      1. file_path basename (most reliable — actual file the user opened)
      2. URL host + path prefix (web-based work)
      3. Window title's "file part" (extracted from common app patterns)
      4. Empty string (no signal — fall back to existing grouping)

    Used as a grouping dimension so that when the user switches between
    files/sites/documents, compaction creates separate blocks even when
    the agent's client_id is stale.
    """
    import os

    # Priority 1: file_path basename — most reliable signal
    if file_path:
        normalized = file_path.replace("\\", "/")
        basename = os.path.basename(normalized)
        if basename and len(basename) >= 3:
            # Strip common extensions for stable grouping
            # (.xlsx vs .xlsm shouldn't split the same workbook)
            name, ext = os.path.splitext(basename)
            return f"file={name.lower()}"

    # Priority 2: URL — for web-based work
    if url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url if "://" in url else f"http://{url}")
            host = (parsed.hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                # Use host + first path segment for stability
                # (so /clients/123/dashboard and /clients/123/billing group together,
                #  but /clients/456/dashboard is separate)
                path_parts = [p for p in (parsed.path or "").split("/") if p]
                if path_parts:
                    return f"url={host}/{path_parts[0]}"
                return f"url={host}"
        except Exception:
            pass

    # Priority 3: Parse "file part" from common window title patterns
    # Pattern: "{file_part}  - {app_name}" or "{file_part} - {app_name}"
    if window_title:
        # Look for common app suffix markers
        APP_SUFFIX_MARKERS = (
            " - QuickBooks",
            " - Excel",
            " - Word",
            " - PowerPoint",
            " - Adobe Acrobat",
            " - Acrobat Reader",
            " - Outlook",
            " - UltraTax",
            " - Lacerte",
            " - ProSeries",
            " - Drake",
            " - TaxWise",
            " - CCH",
            " - Onvio",
            " - Karbon",
        )
        for marker in APP_SUFFIX_MARKERS:
            if marker in window_title:
                file_part = window_title.split(marker, 1)[0].strip()
                # Strip QB-style screen brackets
                bracket_pos = file_part.rfind(" - [")
                if bracket_pos > 0:
                    file_part = file_part[:bracket_pos].strip()
                # Strip mode markers
                for mode in ("(Primary)", "(Secondary)", "[Compatibility Mode]",
                             "- Compatibility Mode", "[Read-Only]", "[Protected View]"):
                    file_part = file_part.replace(mode, "").strip()
                if file_part and len(file_part) >= 3:
                    return f"title={file_part.lower()}"
                break

    return ""

# =============================================================================
# Meeting extraction (unchanged from v1.3.37 — already interval-aware)
# =============================================================================

def _extract_and_persist_meeting_blocks(
    events: list, user, org, day: date_type, hostname: Optional[str]
) -> int:
    """
    Pull meeting start/end pairs out of raw_events and create standalone
    Block records. Meeting blocks bypass the regular compaction pipeline.
    """
    starts = {}
    ends = {}

    for event in events:
        app = event.app_name or ''
        bundle = event.bundle_id or ''

        if not bundle.startswith('meeting:'):
            continue

        meeting_app = bundle.split(':', 1)[1]

        if app == 'Meeting':
            starts.setdefault(meeting_app, []).append(event)
        elif app == 'Meeting-End':
            ends.setdefault(meeting_app, []).append(event)

    if not starts:
        return 0

    created = 0
    with transaction.atomic():
        for meeting_app, start_events in starts.items():
            end_events = ends.get(meeting_app, [])

            for start_ev in start_events:
                matching_end = next(
                    (e for e in end_events if e.start_ts > start_ev.start_ts),
                    None
                )

                if not matching_end:
                    logger.debug(
                        f"[COMPACT-MEETING] Dangling start for {meeting_app} "
                        f"at {start_ev.start_ts} — will pick up next run"
                    )
                    continue

                end_events.remove(matching_end)

                block = _create_meeting_block(
                    start_ev, matching_end, meeting_app, user, org, day, hostname
                )
                if block:
                    RawEvent.objects.filter(
                        id__in=[start_ev.id, matching_end.id]
                    ).update(block=block)
                    created += 1

    return created


def _create_meeting_block(
    start_event, end_event, meeting_app: str,
    user, org, day: date_type, hostname: Optional[str]
) -> Optional[Block]:
    """Create a single meeting Block record from a start/end event pair."""
    duration_seconds = (end_event.start_ts - start_event.start_ts).total_seconds()
    minutes = max(1, int(duration_seconds / 60))

    if minutes < 1:
        logger.warning(
            f"[COMPACT-MEETING] Skipping {meeting_app} block: "
            f"duration {duration_seconds:.0f}s is too short"
        )
        return None

    if duration_seconds > 8 * 3600:
        logger.warning(
            f"[COMPACT-MEETING] {meeting_app} block capped: "
            f"raw duration {duration_seconds/3600:.1f}h > 8h"
        )
        minutes = 8 * 60

    client = None
    client_id = getattr(start_event, 'current_client_id', None)
    if client_id:
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            client = None

    if not client:
        device_id = _safe_device_id(getattr(start_event, 'device_id', None))
        if device_id:
            client = get_current_client_for_user(user, device_id=device_id)

    billing_rate = _resolve_billing_rate(
        org, user, client.id if client else None, task_type_id=None
    )
    billing_amount = round((minutes / 60) * float(billing_rate), 2)

    hours = round(minutes / 60.0, 2)
    title = start_event.window_title or f"{meeting_app.title()} meeting"

    try:
        new_block = Block.objects.create(
            org=org,
            user=user,
            device_id=_safe_device_id(getattr(start_event, 'device_id', None)),
            hostname=start_event.hostname or hostname or "unknown",
            start=start_event.start_ts,
            end=end_event.start_ts,
            day=day,
            minutes=minutes,
            is_meeting=True,
            title=f"{meeting_app.title()} Meeting",
            window_title=title,
            url="",
            file_path="",
            app_name=f"{meeting_app.title()} Meeting",
            bundle_id=f"meeting:{meeting_app}",
            hints={
                'is_meeting': True,
                'meeting_app': meeting_app,
                'meeting_detection_sources':
                    (getattr(start_event, 'ctx', {}) or {})
                    .get('meeting_detector', {})
                    .get('detection_sources'),
                'meeting_detection_confidence':
                    (getattr(start_event, 'ctx', {}) or {})
                    .get('meeting_detector', {})
                    .get('confidence'),
            },
            client=client,
            approved=False,
            is_billable=True,
            billing_rate=billing_rate,
            billing_amount=billing_amount,
        )

        try:
            from tracker.services.classification_service import ClassificationService
            service = ClassificationService(org=org, user=user)
            decision = service.classify(new_block, skip_ai=False)
            service.apply(new_block, decision)
        except Exception as e:
            logger.error(
                f"[COMPACT-MEETING] Classification failed for block {new_block.id}: {e}",
                exc_info=True,
            )

        logger.info(
            f"[COMPACT-MEETING] Created {meeting_app} block {new_block.id}: "
            f"{minutes} min, client={client.name if client else 'UNATTRIBUTED'}"
        )
        return new_block

    except Exception as e:
        logger.exception(f"[COMPACT-MEETING] Failed to create block: {e}")
        return None


# =============================================================================
# Meeting safety nets (unchanged from v1.3.37)
# =============================================================================

def _filter_idle_inside_meetings(user, day: date_type) -> int:
    """Delete idle blocks that fall entirely within a meeting window."""
    meetings = list(Block.objects.filter(
        user=user,
        day=day,
        bundle_id__startswith='meeting:',
    ).only('id', 'start', 'end'))

    if not meetings:
        return 0

    deleted = 0
    for meeting in meetings:
        if not (meeting.start and meeting.end):
            continue

        idle_blocks = Block.objects.filter(
            user=user,
            day=day,
            bundle_id='__idle__',
            start__gte=meeting.start,
            end__lte=meeting.end,
        )

        count = idle_blocks.count()
        if count:
            RawEvent.objects.filter(block__in=idle_blocks).update(block=None)
            idle_blocks.delete()
            deleted += count
            logger.info(
                f"[COMPACT-MEETING] Deleted {count} idle block(s) "
                f"inside {meeting.bundle_id} window {meeting.id}"
            )

    return deleted


def _filter_foreground_inside_meetings(user, day: date_type) -> int:
    """Mark foreground blocks non-billable when entirely inside attributed meetings."""
    meetings = list(Block.objects.filter(
        user=user,
        day=day,
        bundle_id__startswith='meeting:',
        client__isnull=False,
    ).only('id', 'start', 'end', 'client_id', 'bundle_id'))

    if not meetings:
        return 0

    suppressed = 0
    for meeting in meetings:
        if not (meeting.start and meeting.end):
            continue

        candidates = Block.objects.filter(
            user=user,
            day=day,
            start__gte=meeting.start,
            end__lte=meeting.end,
            is_billable=True,
        ).exclude(
            bundle_id__startswith='meeting:',
        ).exclude(
            bundle_id='__idle__',
        ).exclude(
            categorized_by='manual',
        ).exclude(
            categorized_by='correction',
        )

        count = candidates.count()
        if count:
            for blk in candidates:
                blk.is_billable = False
                blk.billing_amount = Decimal('0.00')
                blk.save(update_fields=['is_billable', 'billing_amount'])

            suppressed += count
            logger.info(
                f"[COMPACT-MEETING] Suppressed {count} foreground block(s) "
                f"inside {meeting.bundle_id} client={meeting.client_id} "
                f"window {meeting.id}"
            )

    return suppressed


# =============================================================================
# Auto-categorization (delegates to ClassificationService)
# =============================================================================

def auto_categorize_block(block: Block) -> bool:
    """Auto-categorize a block via ClassificationService deterministic stages."""
    if block.is_categorized:
        return False

    state = getattr(block, 'classification_state', None)
    if state and state != 'captured':
        return False

    org = getattr(block, 'org', None)
    user = getattr(block, 'user', None)

    if not org:
        logger.warning(f"[AUTO-CAT] Block {block.id} has no org — skipping")
        return False

    try:
        from tracker.services.classification_service import ClassificationService
        service = ClassificationService(org=org, user=user)
        decision = service.classify(block, skip_ai=False)
        service.apply(block, decision)

        block.refresh_from_db()
        final_state = block.classification_state

        if final_state in ('committed', 'proposed', 'suppressed'):
            logger.info(
                f"[AUTO-CAT] Block {block.id} ({block.app_name}) → "
                f"state={final_state}"
            )
            return True
        else:
            return False

    except Exception as e:
        logger.error(
            f"[AUTO-CAT] Classification failed for block {block.id}: {e}",
            exc_info=True,
        )
        return False


def auto_compact_all_active_users(minutes_back: int = 30) -> Dict[str, int]:
    """Auto-compact recent events for ALL active users (Celery beat task)."""
    stats = {
        'users_processed': 0,
        'blocks_created': 0,
        'errors': 0,
    }

    cutoff = timezone.now() - timedelta(minutes=minutes_back)

    users_with_events = RawEvent.objects.filter(
        start_ts__gte=cutoff,
        block__isnull=True
    ).values('user').annotate(count=Count('id')).filter(count__gt=0)

    logger.info(f"[AUTO-COMPACT] Found {len(users_with_events)} users with unlinked events")

    for user_data in users_with_events:
        user_id = user_data['user']
        event_count = user_data['count']

        try:
            user = User.objects.get(id=user_id)
            logger.info(f"[AUTO-COMPACT] Processing {user.username}: {event_count} events")

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
    """Main entry point — compacts today's events for one user."""
    today = timezone.localdate()
    if isinstance(user, str):
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            return 0
    return compact_day(user, today, hostname=hostname, org=org)


# =============================================================================
# compact_day — main compaction logic with v1.3.39 content-split
# =============================================================================

def compact_day(user, day: date_type, hostname: Optional[str] = None, org=None) -> int:
    """
    Compact raw events into blocks for one user/day.

    v1.3.39 — group by (app, client, content_bucket) so personal browsing
    doesn't merge with legitimate work.
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

    qs = RawEvent.objects.filter(
        user=user,
        start_ts__date=day,
        block__isnull=True,
    ).order_by("start_ts")

    if hostname:
        qs = qs.filter(hostname=hostname)

    events = list(qs)
    if not events:
        return 0

    logger.info(f"[COMPACT] Processing {len(events)} unlinked events for {user.username}")

    # Stage 0: meeting blocks (parallel to foreground activity)
    meeting_block_count = _extract_and_persist_meeting_blocks(
        events, user, org, day, hostname
    )
    if meeting_block_count:
        logger.info(f"[COMPACT] Created {meeting_block_count} meeting blocks")

    # Remove meeting events from foreground processing
    events = [
        e for e in events
        if not (
            (e.app_name in ("Meeting", "Meeting-End"))
            and (e.bundle_id or "").startswith("meeting:")
        )
    ]
    if not events:
        idle_cleaned = 0
        foreground_suppressed = 0
        if meeting_block_count:
            idle_cleaned = _filter_idle_inside_meetings(user, day)
            foreground_suppressed = _filter_foreground_inside_meetings(user, day)
            logger.info(
                f"[COMPACT] Meeting-only batch: created {meeting_block_count}, "
                f"idle-cleaned {idle_cleaned}, fg-suppressed {foreground_suppressed}"
            )
        return meeting_block_count

    # Build event records with REAL durations
    events_with_duration = []
    for event in events:
        duration_minutes = (event.end_ts - event.start_ts).total_seconds() / 60.0

        events_with_duration.append({
            "event": event,
            "start": event.start_ts,
            "end": event.end_ts,
            "duration_minutes": duration_minutes,
            "app_name": event.app_name or "",
            "bundle_id": event.bundle_id or "",
            "window_title": event.window_title or "",
            "url": event.url or "",
            "file_path": event.file_path or "",
            "hostname": event.hostname or hostname or "unknown",
            "device_id": _safe_device_id(getattr(event, "device_id", None)),
            "current_client_id": getattr(event, "current_client_id", None),
        })

    # Split into sessions using REAL inter-event gaps (next.start - prev.end)
    sessions = []
    current_session = [events_with_duration[0]]

    for i in range(1, len(events_with_duration)):
        prev = events_with_duration[i - 1]
        curr = events_with_duration[i]
        gap_seconds = (curr["start"] - prev["end"]).total_seconds()

        if gap_seconds > SESSION_GAP.total_seconds():
            sessions.append(current_session)
            current_session = [curr]
        else:
            current_session.append(curr)

    if current_session:
        sessions.append(current_session)

    # =========================================================================
    # v1.3.39: Group within session by (app, client, CONTENT_BUCKET)
    # =========================================================================
    # The content_bucket dimension prevents Fox News from being merged with
    # Onvio into the same Block. See tracker/utils/content_classifier.py.
    blocks_to_create = []
    for session in sessions:
        by_app_client: Dict[str, List] = {}
        for ev in session:
            app = _app_key(ev)
            client_id = ev.get("current_client_id") or 0
            content_bucket = classify_event_content(ev["event"])

            # v1.3.46: Universal content-identifier grouping. When the
            # user opens a different file/URL/document, that's different
            # work — even if the agent's current_client_id is stale.
            # Without this, e.g. opening St Mary's Church QB file while
            # current_client_id still points at St Mary's Cemetery would
            # merge both into one wrong block. The file_path/URL/title
            # captures the user's actual context independent of the
            # agent's client opinion.
            content_id = _content_identifier(
                ev.get("window_title") or "",
                ev.get("file_path") or "",
                ev.get("url") or "",
            )
            content_part = f"|{content_id}" if content_id else ""

            key = f"{app}|{client_id}|{content_bucket}{content_part}"
            by_app_client.setdefault(key, []).append(ev)

        for key, app_events in by_app_client.items():
            if not app_events:
                continue

            block_start = min(e["start"] for e in app_events)
            block_end = max(e["end"] for e in app_events)
            new_event_minutes = sum(e["duration_minutes"] for e in app_events)

            if new_event_minutes < MIN_BLOCK_MINUTES:
                continue

            titles = [e["window_title"] for e in app_events if e["window_title"]]
            titles = [t for t in titles if t.lower() not in ("", "open", "untitled", "new tab")]
            window_title = max(titles, key=len) if titles else app_events[0]["window_title"]

            urls = [e["url"] for e in app_events if e["url"]]
            paths = [e["file_path"] for e in app_events if e["file_path"]]
            client_id = app_events[0].get("current_client_id")

            # v1.3.39: drop client attribution on pure-personal blocks.
            # If every event in this group is high-confidence personal content,
            # the agent's client selection is stale — the user was reading news,
            # not working on any client. Mixed/ambiguous blocks keep the client.
            source_events = [e["event"] for e in app_events]
            if is_high_confidence_personal(source_events):
                if client_id:
                    logger.info(
                        f"[COMPACT] Dropped client_id={client_id} from pure-personal block: "
                        f"app={app_events[0]['app_name']!r} "
                        f"events={len(app_events)} "
                        f"first_title={(app_events[0]['window_title'] or '')[:60]!r}"
                    )
                client_id = None

            blocks_to_create.append({
                "start": block_start,
                "end": block_end,
                "app_name": app_events[0]["app_name"],
                "bundle_id": app_events[0]["bundle_id"],
                "window_title": window_title,
                "url": urls[0] if urls else "",
                "file_path": paths[0] if paths else "",
                "hostname": app_events[0]["hostname"],
                "device_id": app_events[0]["device_id"],
                "current_client_id": client_id,
                "source_events": source_events,
            })

    # Merge into existing blocks where possible
    existing_blocks = list(Block.objects.filter(user=user, day=day).order_by("start"))

    existing_by_app_client = {}
    for b in existing_blocks:
        app = _app_key(b)
        client_id = b.client_id or 0
        key = f"{app}|{client_id}"
        existing_by_app_client.setdefault(key, []).append(b)

    created_count = 0
    merged_count = 0
    blocks_to_categorize = []

    with transaction.atomic():
        for block_data in blocks_to_create:
            app = _app_key(block_data)
            new_start = block_data["start"]
            new_end = block_data["end"]
            new_client_id = block_data.get("current_client_id") or 0
            key = f"{app}|{new_client_id}"

            merge_target = None
            for existing in existing_by_app_client.get(key, []):
                gap_to_existing = (
                    (new_start - existing.end).total_seconds()
                    if existing.end else float("inf")
                )
                gap_from_existing = (
                    (existing.start - new_end).total_seconds()
                    if existing.start else float("inf")
                )

                # Merge only when gap is small AND non-negative
                # (block 10594 fix preserved from v1.3.37)
                if 0 <= gap_to_existing < SESSION_GAP.total_seconds() or \
                   0 <= gap_from_existing < SESSION_GAP.total_seconds():
                    merge_target = existing
                    break

                if existing.start and existing.end:
                    if new_start >= existing.start and new_start <= existing.end:
                        merge_target = existing
                        break

            if merge_target:
                try:
                    locked = Block.objects.select_for_update().get(id=merge_target.id)

                    event_ids = [e.id for e in block_data["source_events"]]
                    RawEvent.objects.filter(id__in=event_ids).update(block=locked)

                    updated_start = min(locked.start, new_start)
                    updated_end = max(locked.end, new_end)
                    updated_minutes = _calculate_minutes_from_events(
                        RawEvent.objects.filter(block=locked)
                    )

                    update_fields = {
                        "start": updated_start,
                        "end": updated_end,
                        "minutes": updated_minutes,
                    }

                    if locked.billing_rate and updated_minutes:
                        update_fields["billing_amount"] = round(
                            (updated_minutes / 60) * float(locked.billing_rate), 2
                        )

                    if locked.is_categorized and locked.category_hours:
                        category = list(locked.category_hours.keys())[0]
                        update_fields["category_hours"] = {
                            category: round(updated_minutes / 60.0, 2)
                        }

                    Block.objects.filter(id=locked.id).update(**update_fields)
                    merged_count += 1
                    continue

                except Block.DoesNotExist:
                    pass

            new_block = _create_block(block_data, user, org, day)
            if new_block:
                created_count += 1
                if not new_block.is_categorized:
                    blocks_to_categorize.append(new_block)

                existing_by_app_client.setdefault(key, []).append(new_block)

    # Auto-categorize new blocks
    auto_cat_count = 0
    for block in blocks_to_categorize:
        if auto_categorize_block(block):
            auto_cat_count += 1

    # Safety nets
    idle_cleaned = 0
    foreground_suppressed = 0
    if meeting_block_count:
        idle_cleaned = _filter_idle_inside_meetings(user, day)
        foreground_suppressed = _filter_foreground_inside_meetings(user, day)

    logger.info(
        f"[COMPACT] Created {created_count}, merged {merged_count}, "
        f"auto-cat {auto_cat_count}, meetings {meeting_block_count}, "
        f"idle-cleaned {idle_cleaned}, fg-suppressed {foreground_suppressed}"
    )
    return created_count + merged_count + meeting_block_count


def _resolve_billing_rate(org, user, client_id, task_type_id=None):
    """Billing rate resolution — unchanged from v1.3.37."""
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
    """Create a new block. Work pattern detection, idle classification, billing rate resolution unchanged."""
    app_name = (block_data.get("app_name") or "").lower()
    bundle_id = (block_data.get("bundle_id") or "").lower()
    window_title = (block_data.get("window_title") or "").lower()
    url = (block_data.get("url") or "").lower()
    file_path = (block_data.get("file_path") or "").lower()

    NEVER_IDLE_DOMAINS = {
        'claude.ai', 'chat.openai.com', 'chatgpt.com',
        'github.com', 'gitlab.com', 'bitbucket.org',
        'stackoverflow.com', 'docs.python.org',
        'localhost', '127.0.0.1',
        'figma.com', 'canva.com',
        'notion.so', 'docs.google.com',
        'slack.com', 'teams.microsoft.com',
        'zoom.us', 'meet.google.com',
        'qbo.intuit.com', 'quickbooks.intuit.com',
        'cchaxcess.com', 'irs.gov',
    }

    NEVER_IDLE_APPS = {
        'code', 'vscode', 'visual studio', 'sublime', 'sublime_text',
        'pycharm', 'intellij', 'webstorm', 'xcode', 'android studio',
        'terminal', 'iterm', 'iterm2', 'warp', 'hyper',
        'figma', 'sketch', 'photoshop',
        'zoom', 'teams', 'slack',
    }

    is_work_pattern = False
    for domain in NEVER_IDLE_DOMAINS:
        if domain in url:
            is_work_pattern = True
            break

    if not is_work_pattern:
        for app in NEVER_IDLE_APPS:
            if app in app_name:
                is_work_pattern = True
                break

    if is_work_pattern:
        is_idle = False
    else:
        is_idle = is_idle_activity(
            app_name=block_data.get("app_name"),
            bundle_id=block_data.get("bundle_id"),
            window_title=block_data.get("window_title")
        )

    device_id = block_data.get("device_id", 0)
    source_events = block_data.get('source_events', [])

    minutes = _calculate_minutes_for_events_list(source_events)

    client = None
    client_id = block_data.get("current_client_id")
    if client_id:
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            pass
    if not client and device_id:
        client = get_current_client_for_user(user, device_id=device_id)

    client_id_for_rate = block_data.get("current_client_id")
    task_type_id_for_rate = block_data.get("task_type_id")
    billing_rate = _resolve_billing_rate(org, user, client_id_for_rate, task_type_id_for_rate)
    billing_amount = round((minutes / 60) * float(billing_rate), 2)

    if is_idle:
        client = None
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
            is_meeting=False,
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
            is_meeting=False,
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

    event_ids = [e.id for e in block_data['source_events']]
    RawEvent.objects.filter(id__in=event_ids).update(block=new_block)

    return new_block


def compact_recent_events(user, hostname: Optional[str] = None, minutes_back: int = 15) -> int:
    """Quick compaction of recent events. Called from raw_events POST endpoint."""
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
    """Recalculate minutes for a specific block using real event intervals."""
    try:
        block = Block.objects.get(id=block_id)
        new_minutes = _calculate_minutes_from_events(RawEvent.objects.filter(block=block))
        if new_minutes != block.minutes:
            Block.objects.filter(id=block_id).update(minutes=new_minutes)
        return new_minutes
    except Block.DoesNotExist:
        return 0


# =============================================================================
# Cleanup (unchanged from v1.3.37)
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