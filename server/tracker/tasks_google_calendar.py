"""
Google Calendar sync Celery tasks — the Google counterpart of tasks_calendar.py.

  - sync_all_google_calendars: master, every 15 min
  - sync_user_google_calendar: per-user. events.list(singleEvents=true) on the
    primary calendar. A FULL sync covers [now - LOOKBACK, now + LOOKAHEAD] and
    stores the nextSyncToken; incremental runs send only that token. A 410
    (token invalidated) wipes this user's Google events and re-runs the full
    sync, as Google's sync guide prescribes.

Why a daily full sync as well: incremental results report CHANGED events only.
An event created weeks ahead, outside the full-sync window, never enters the
store unless it changes again — so the window is re-walked once
FULL_SYNC_EVERY has elapsed, which rolls it forward.

Events are written in exactly the shape the Microsoft sync writes (see
tasks_calendar.upsert_calendar_event), with the same client pre-matching, so
Stage 6 and the time-off derivation treat both providers the same.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from tracker.integrations import google
from tracker.models import CalendarEvent, UserIntegration
from tracker.tasks_calendar import MAX_FAILURE_COUNT, upsert_calendar_event

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 1       # same as the Microsoft sync
LOOKAHEAD_DAYS = 30     # wider than Microsoft's 7: incremental keeps it fresh
FULL_SYNC_EVERY = timedelta(hours=24)

# Google responseStatus → the Graph vocabulary the rest of the code stores.
RESPONSE_MAP = {
    'accepted': 'accepted',
    'declined': 'declined',
    'tentative': 'tentativelyAccepted',
    'needsAction': 'none',
}


@shared_task(name='tracker.sync_all_google_calendars')
def sync_all_google_calendars():
    ids = list(UserIntegration.objects.filter(
        provider='google_calendar',
        is_connected=True,
        sync_failure_count__lt=MAX_FAILURE_COUNT,
    ).values_list('id', flat=True))
    for integration_id in ids:
        sync_user_google_calendar.delay(integration_id)
    logger.info(f"[GCAL-SYNC] Dispatched {len(ids)} Google Calendar syncs")
    return {'dispatched': len(ids)}


@shared_task(
    name='tracker.sync_user_google_calendar',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def sync_user_google_calendar(self, integration_id):
    try:
        integration = UserIntegration.objects.select_related('user', 'org').get(
            id=integration_id, provider='google_calendar', is_connected=True,
        )
    except UserIntegration.DoesNotExist:
        return {'status': 'skipped', 'reason': 'not_found'}
    if integration.sync_failure_count >= MAX_FAILURE_COUNT:
        return {'status': 'skipped', 'reason': 'too_many_failures'}

    user = integration.user
    try:
        result = run_google_calendar_sync(integration)
    except google.GoogleAuthError as e:
        logger.warning(f"[GCAL-SYNC] Auth error for {user.username}: {e}")
        return {'status': 'auth_error', 'error': str(e)}
    except google.GoogleTransientError as e:
        # Dropped connection: retry, but never count it toward the cutoff that
        # stops syncing for good (same rule as Gmail).
        logger.warning(f"[GCAL-SYNC] Transient network error for {user.username}: {e}")
        integration.last_sync_error = f"Temporary network error (will retry): {str(e)[:160]}"
        integration.save(update_fields=['last_sync_error'])
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {'status': 'transient', 'error': str(e)}
    except google.GoogleAPIError as e:
        logger.error(f"[GCAL-SYNC] API error for {user.username}: {e}")
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.last_sync_error = f"API error: {str(e)[:200]}"
        integration.save(update_fields=['sync_failure_count', 'last_sync_error'])
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {'status': 'failed', 'error': str(e)}
    except Exception as e:
        logger.exception(f"[GCAL-SYNC] Unexpected error for {user.username}")
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.last_sync_error = f"Unexpected: {str(e)[:200]}"
        integration.save(update_fields=['sync_failure_count', 'last_sync_error'])
        return {'status': 'error', 'error': str(e)}

    try:
        from tracker.calendar_timeoff import derive_time_off_for_user
        derive_time_off_for_user(integration.org, user)
    except Exception as e:
        logger.warning(f"[GCAL-SYNC] time-off derivation failed for {user.username}: {e}")

    logger.info(f"[GCAL-SYNC] {user.username}: {result}")
    return {'status': 'ok', 'user': user.username, **result}


def run_google_calendar_sync(integration):
    now = timezone.now()
    due_full = (
        not integration.sync_cursor
        or not integration.sync_cursor_set_at
        or now - integration.sync_cursor_set_at >= FULL_SYNC_EVERY
    )
    mode = 'full' if due_full else 'incremental'
    window_start = now - timedelta(days=LOOKBACK_DAYS)

    if due_full:
        events, token = google.calendar_list_events(
            integration, time_min=window_start, time_max=now + timedelta(days=LOOKAHEAD_DAYS),
        )
    else:
        try:
            events, token = google.calendar_list_events(integration, sync_token=integration.sync_cursor)
        except google.GoogleCursorExpired:
            logger.warning(f"[GCAL-SYNC] syncToken expired for {integration.user.username} — full resync")
            # Google: a 410 means wipe the local store and sync from scratch.
            CalendarEvent.objects.filter(user=integration.user, provider='google').delete()
            events, token = google.calendar_list_events(
                integration, time_min=window_start, time_max=now + timedelta(days=LOOKAHEAD_DAYS),
            )
            mode = 'full_resync'
            due_full = True

    saved, removed, skipped = _apply_events(integration, events)

    if due_full:
        # Anything we hold inside the window that the full listing did not
        # return has been deleted (or we lost access to it).
        seen = {e.get('id') for e in events if e.get('id')}
        stale = CalendarEvent.objects.filter(
            user=integration.user, provider='google',
            end__gt=window_start, start__lt=now + timedelta(days=LOOKAHEAD_DAYS),
        ).exclude(external_id__in=seen)
        removed += stale.count()
        stale.delete()

    integration.last_synced_at = now
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    fields = ['last_synced_at', 'last_sync_error', 'sync_failure_count']
    if token:
        integration.sync_cursor = token
        fields.append('sync_cursor')
        if due_full:
            integration.sync_cursor_set_at = now
            fields.append('sync_cursor_set_at')
    integration.save(update_fields=fields)
    return {'mode': mode, 'saved': saved, 'removed': removed, 'skipped': skipped}


def _parse_when(when):
    """Google {dateTime} or {date} → (aware UTC datetime, is_all_day)."""
    when = when or {}
    if when.get('dateTime'):
        dt = datetime.fromisoformat(when['dateTime'].replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt.astimezone(dt_timezone.utc), False
    if when.get('date'):
        # All-day: midnight UTC of that date, as the Graph sync stores it
        # (calendar_timeoff reads .date() off start/end; end is exclusive).
        d = datetime.fromisoformat(when['date'])
        return d.replace(tzinfo=dt_timezone.utc), True
    return None, False


def _show_as(evt):
    etype = evt.get('eventType') or ''
    if etype == 'outOfOffice':
        return 'oof'
    if etype == 'workingLocation':
        return 'workingElsewhere'
    return 'free' if evt.get('transparency') == 'transparent' else 'busy'


def _meeting_url(evt):
    if evt.get('hangoutLink'):
        return evt['hangoutLink']
    for ep in ((evt.get('conferenceData') or {}).get('entryPoints') or []):
        if ep.get('entryPointType') == 'video' and ep.get('uri'):
            return ep['uri']
    return ''


def map_event(evt):
    """Google event → CalendarEvent defaults (same shape as the Graph sync)."""
    start, all_day = _parse_when(evt.get('start'))
    end, _ = _parse_when(evt.get('end'))
    if not start or not end:
        return None
    attendees = []
    for a in (evt.get('attendees') or [])[:30]:
        email = (a.get('email') or '').strip()
        attendees.append({
            'email': email,
            'domain': email.split('@')[-1].lower() if '@' in email else '',
            'response': RESPONSE_MAP.get(a.get('responseStatus') or '', 'none'),
        })
    return {
        'title': (evt.get('summary') or '')[:1000],
        'description': (evt.get('description') or '')[:2000],
        'location': (evt.get('location') or '')[:255],
        'meeting_url': _meeting_url(evt),
        'start': start,
        'end': end,
        'is_all_day': all_day,
        'show_as': _show_as(evt)[:16],
        'attendees': attendees,
    }


def _apply_events(integration, events):
    user, org = integration.user, integration.org
    saved = removed = skipped = 0
    with transaction.atomic():
        for evt in events:
            external_id = evt.get('id')
            if not external_id:
                continue
            if evt.get('status') == 'cancelled':
                removed += CalendarEvent.objects.filter(
                    user=user, provider='google', external_id=external_id,
                ).delete()[0]
                continue
            # Declined by the user themselves: not time they spent.
            me = next((a for a in (evt.get('attendees') or []) if a.get('self')), None)
            if me and me.get('responseStatus') == 'declined':
                removed += CalendarEvent.objects.filter(
                    user=user, provider='google', external_id=external_id,
                ).delete()[0]
                continue
            try:
                defaults = map_event(evt)
                if defaults is None:
                    skipped += 1
                    continue
                defaults['org'] = org
                upsert_calendar_event(
                    user=user, org=org, provider='google',
                    external_id=external_id[:255], defaults=defaults,
                )
                saved += 1
            except Exception as e:
                logger.warning(f"[GCAL-SYNC] Failed to save event {external_id}: {e}")
                skipped += 1
    return saved, removed, skipped
