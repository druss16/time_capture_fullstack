"""
The true state of a mail/calendar integration.

`UserIntegration.is_connected` is one bit, and it is wrong in both directions:

  * A row is created at OAuth *start* to hold the state token; only the
    callback stores tokens. Abandon the Microsoft consent screen and the row
    persists forever with no tokens — the Connections page has nothing to show
    but "Not connected", which is indistinguishable from never having tried.
    Five TL Wall mailboxes sat that way from 2026-06-16 and everyone assumed
    mail was on.

  * Sync dispatch filters `sync_failure_count__lt=5` (tasks_mail.py:60,
    tasks_calendar.py:46). At 5 consecutive failures the row is skipped
    permanently while `is_connected` stays True — so the page says "Connected"
    about an integration that has not run in weeks. Three TL Wall calendars
    were in that state for 17 days.

One assessor, shared by the API and `manage.py integration_health`, so the
page and the command can never disagree about what is true.
"""
from django.utils import timezone

# Mirrors MAX_FAILURE_COUNT in tasks_mail.py / tasks_calendar.py. If those
# change, this must change with them — the number IS the dispatch cutoff.
MAX_FAILURE_COUNT = 5
STALE_HOURS = 24

OK = 'ok'
NEVER_CONNECTED = 'never_connected'
PAUSED = 'paused'
EXPIRED = 'expired'
DISCONNECTED = 'disconnected'
STALE = 'stale'

# Short label + what the person should do. Written for the account holder,
# who cannot be expected to know what a refresh token is.
PRESENTATION = {
    OK: ('Connected', ''),
    NEVER_CONNECTED: (
        'Setup never finished',
        'You started connecting but the Microsoft sign-in was never completed. '
        'Connect again to finish.',
    ),
    PAUSED: (
        'Syncing stopped',
        'We stopped after repeated failures, so nothing has synced since. '
        'Reconnect to start it again.',
    ),
    EXPIRED: (
        'Sign-in expired',
        'Microsoft needs you to sign in again before syncing can continue.',
    ),
    DISCONNECTED: ('Not connected', ''),
    STALE: (
        'No recent sync',
        'This has not synced in over a day. If it stays this way, reconnect.',
    ),
}

# States where syncing is NOT happening and only the account holder can fix it.
NEEDS_ACTION = (NEVER_CONNECTED, PAUSED, EXPIRED)


def assess(integration):
    """Return (state, detail) for one UserIntegration row.

    Order matters: the checks run worst-first, because a row can be several of
    these at once and the most actionable one is what a person needs to see.
    """
    has_refresh = bool((integration.refresh_token or '').strip())
    fails = integration.sync_failure_count or 0

    if not has_refresh and not integration.last_synced_at:
        return (NEVER_CONNECTED, 'no tokens were ever stored')
    if fails >= MAX_FAILURE_COUNT:
        return (PAUSED, f'{fails} consecutive failures')
    if not integration.is_connected:
        return (DISCONNECTED, (integration.last_sync_error or '')[:200])
    if integration.token_expires_at and integration.token_expires_at <= timezone.now():
        return (EXPIRED, f'expired {integration.token_expires_at:%Y-%m-%d}')
    if integration.last_synced_at:
        hours = (timezone.now() - integration.last_synced_at).total_seconds() / 3600
        if hours > STALE_HOURS:
            return (STALE, f'last sync {hours:.0f}h ago')
    return (OK, '')


def health_payload(integration):
    """The `health` object the Connections page renders."""
    state, detail = assess(integration)
    label, guidance = PRESENTATION[state]
    return {
        'state': state,
        'label': label,
        'guidance': guidance,
        'detail': detail,
        'needs_action': state in NEEDS_ACTION,
        # is_connected on its own — kept so the page can show where the two
        # disagree rather than quietly papering over it.
        'syncing': state in (OK, STALE),
    }
