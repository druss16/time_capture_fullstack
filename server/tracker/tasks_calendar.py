"""
Calendar sync Celery tasks.

Architecture:
- sync_all_calendars: master task, runs every 15 min, dispatches per-user subtasks
- sync_user_calendar: per-user task, fetches events, saves to CalendarEvent
- Skip users with too many failures (auto-pause until they reconnect)

Privacy: events save with title (matched against client names later) but
we never display titles to other users. See CalendarEvent model docs.
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.db import transaction

from tracker.models import (
    UserIntegration,
    CalendarEvent,
)
from tracker.integrations import msgraph

logger = logging.getLogger(__name__)


# How far back / forward to fetch each sync
SYNC_LOOKBACK_DAYS = 1   # catches events from this morning if sync started later
SYNC_LOOKAHEAD_DAYS = 7  # week ahead for upcoming meetings

# Pause sync for users who keep failing
MAX_FAILURE_COUNT = 5


# ─── Master dispatch task ─────────────────────────────────────────────────────

@shared_task(name='tracker.sync_all_calendars')
def sync_all_calendars():
    """
    Master task: dispatches sync subtasks for every actively connected user.
    Scheduled by Celery beat every 15 min.
    """
    eligible = UserIntegration.objects.filter(
        provider='microsoft_calendar',
        is_connected=True,
        sync_failure_count__lt=MAX_FAILURE_COUNT,
    ).values_list('id', flat=True)
    
    eligible_ids = list(eligible)
    logger.info(f"[CAL-SYNC] Dispatching sync for {len(eligible_ids)} integrations")
    
    for integration_id in eligible_ids:
        sync_user_calendar.delay(integration_id)
    
    return {'dispatched': len(eligible_ids)}


# ─── Per-user sync task ───────────────────────────────────────────────────────

@shared_task(
    name='tracker.sync_user_calendar',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def sync_user_calendar(self, integration_id):
    """
    Fetch and save calendar events for one user.
    
    Idempotent: uses (user, provider, external_id) unique constraint.
    Re-syncs overwrite via update_or_create.
    """
    try:
        integration = UserIntegration.objects.select_related('user', 'org').get(
            id=integration_id,
            provider='microsoft_calendar',
            is_connected=True,
        )
    except UserIntegration.DoesNotExist:
        logger.warning(f"[CAL-SYNC] Integration {integration_id} not found or inactive")
        return {'status': 'skipped', 'reason': 'not_found'}
    
    if integration.sync_failure_count >= MAX_FAILURE_COUNT:
        logger.warning(f"[CAL-SYNC] Skipping {integration.user.username} — too many failures")
        return {'status': 'skipped', 'reason': 'too_many_failures'}
    
    user = integration.user
    org = integration.org
    
    start_dt = timezone.now() - timedelta(days=SYNC_LOOKBACK_DAYS)
    end_dt = timezone.now() + timedelta(days=SYNC_LOOKAHEAD_DAYS)
    
    try:
        raw_events = msgraph.fetch_calendar_view(
            integration=integration,
            start_dt=start_dt,
            end_dt=end_dt,
        )
    except msgraph.MSGraphAuthError as e:
        # Auth failures already update integration in fetch_calendar_view
        logger.warning(f"[CAL-SYNC] Auth error for {user.username}: {e}")
        return {'status': 'auth_error', 'error': str(e)}
    except msgraph.MSGraphAPIError as e:
        logger.error(f"[CAL-SYNC] API error for {user.username}: {e}")
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.last_sync_error = f"API error: {str(e)[:200]}"
        integration.save(update_fields=['sync_failure_count', 'last_sync_error'])
        # Retry with backoff
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {'status': 'failed', 'error': str(e)}
    except Exception as e:
        logger.exception(f"[CAL-SYNC] Unexpected error for {user.username}")
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.last_sync_error = f"Unexpected: {str(e)[:200]}"
        integration.save(update_fields=['sync_failure_count', 'last_sync_error'])
        return {'status': 'error', 'error': str(e)}
    
    # Save events to DB (idempotent via unique_together constraint)
    saved_count = 0
    skipped_count = 0
    
    with transaction.atomic():
        for evt in raw_events:
            external_id = evt.get('id')
            if not external_id:
                continue
            
            # Skip cancelled events — we delete them to keep DB clean
            if evt.get('isCancelled'):
                CalendarEvent.objects.filter(
                    user=user,
                    provider='microsoft',
                    external_id=external_id,
                ).delete()
                skipped_count += 1
                continue
            
            try:
                start_iso = evt.get('start', {}).get('dateTime')
                end_iso = evt.get('end', {}).get('dateTime')
                if not start_iso or not end_iso:
                    skipped_count += 1
                    continue
                
                # Parse Microsoft's ISO format (always UTC because of Prefer header)
                from datetime import datetime
                event_start = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
                event_end = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
                if event_start.tzinfo is None:
                    from datetime import timezone as dt_timezone
                    event_start = event_start.replace(tzinfo=dt_timezone.utc)
                    event_end = event_end.replace(tzinfo=dt_timezone.utc)
                                
                # Extract attendees minimally — email + domain + response
                attendees_raw = evt.get('attendees', []) or []
                attendees = []
                for a in attendees_raw[:30]:  # cap to avoid bloat
                    addr = a.get('emailAddress', {}) or {}
                    email = addr.get('address', '') or ''
                    domain = email.split('@')[-1].lower() if '@' in email else ''
                    response = (a.get('status', {}) or {}).get('response', 'none')
                    attendees.append({
                        'email': email,
                        'domain': domain,
                        'response': response,
                    })
                
                # Extract meeting URL
                meeting_url = (
                    evt.get('onlineMeetingUrl')
                    or (evt.get('onlineMeeting') or {}).get('joinUrl', '')
                    or ''
                )
                
                # Save / update
                cal_event, _created = CalendarEvent.objects.update_or_create(
                    user=user,
                    provider='microsoft',
                    external_id=external_id,
                    defaults={
                        'org': org,
                        'title': (evt.get('subject') or '')[:1000],
                        'description': (evt.get('bodyPreview') or '')[:2000],
                        'location': ((evt.get('location') or {}).get('displayName') or '')[:255],
                        'meeting_url': meeting_url,
                        'start': event_start,
                        'end': event_end,
                        'attendees': attendees,
                    },
                )

                # Match to client (Strategy 1: direct rules, Strategy 2: fuzzy title)
                try:
                    from tracker.calendar_matching import find_best_match
                    match_event = {
                        'title': evt.get('subject', ''),
                        'attendees': attendees,
                        'categories': evt.get('categories', []) or [],
                    }
                    matched_client, confidence, method = find_best_match(match_event, org)
                    if matched_client and confidence >= 0.70:
                        cal_event.extracted_client = matched_client
                        cal_event.extraction_confidence = confidence
                        cal_event.save(update_fields=['extracted_client', 'extraction_confidence'])
                        logger.info(
                            f"[CAL-MATCH] '{cal_event.title[:40]}' → {matched_client.name} "
                            f"({confidence:.2f}, {method})"
                        )
                except Exception as e:
                    logger.warning(f"[CAL-MATCH] Match failed for {external_id}: {e}")

                saved_count += 1
            except Exception as e:
                logger.warning(f"[CAL-SYNC] Failed to save event {external_id}: {e}")
                skipped_count += 1
                continue
    
    # Update integration sync stats
    integration.last_synced_at = timezone.now()
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    integration.save(update_fields=['last_synced_at', 'last_sync_error', 'sync_failure_count'])
    
    logger.info(
        f"[CAL-SYNC] ✅ {user.username}: {saved_count} saved, {skipped_count} skipped"
    )
    return {
        'status': 'ok',
        'user': user.username,
        'saved': saved_count,
        'skipped': skipped_count,
    }