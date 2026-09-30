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
PERMISSION_DENIED = 'permission_denied'

# Written to last_sync_error by the Google callback when the user signed in
# but unticked the data permission on Google's granular consent screen.
PERMISSION_DENIED_MARKER = 'permission_not_granted'

# Short label + what the person should do. Written for the account holder,
# who cannot be expected to know what a refresh token is.
PRESENTATION = {
    OK: ('Connected', ''),
    NEVER_CONNECTED: (
        'Setup never finished',
        'You started connecting but the {brand} sign-in was never completed. '
        'Connect again to finish.',
    ),
    PAUSED: (
        'Syncing stopped',
        'We stopped after repeated failures, so nothing has synced since. '
        'Reconnect to start it again.',
    ),
    EXPIRED: (
        'Sign-in expired',
        '{brand} needs you to sign in again before syncing can continue.',
    ),
    DISCONNECTED: ('Not connected', ''),
    PERMISSION_DENIED: (
        'Permission not granted',
        'You signed in to {brand} but the permission TimeTracker needs was left '
        'unticked, so nothing was connected. Connect again and leave it ticked.',
    ),
    STALE: (
        'No recent sync',
        'This has not synced in over a day. If it stays this way, reconnect.',
    ),
}

# States where syncing is NOT happening and only the account holder can fix it.
NEEDS_ACTION = (NEVER_CONNECTED, PAUSED, EXPIRED, PERMISSION_DENIED)


def provider_brand(provider):
    """Whose sign-in screen the account holder went through."""
    return 'Google' if provider in ('gmail', 'google_calendar') else 'Microsoft'


def assess(integration):
    """Return (state, detail) for one UserIntegration row.

    Order matters: the checks run worst-first, because a row can be several of
    these at once and the most actionable one is what a person needs to see.
    """
    has_refresh = bool((integration.refresh_token or '').strip())
    fails = integration.sync_failure_count or 0

    if not has_refresh and not integration.last_synced_at:
        if (integration.last_sync_error or '').startswith(PERMISSION_DENIED_MARKER):
            return (PERMISSION_DENIED, integration.last_sync_error[:200])
        return (NEVER_CONNECTED, 'no tokens were ever stored')
    if fails >= MAX_FAILURE_COUNT:
        return (PAUSED, f'{fails} consecutive failures')
    if not integration.is_connected:
        return (DISCONNECTED, (integration.last_sync_error or '')[:200])
    # Google access tokens live one hour and are refreshed at the start of
    # each sync, so between syncs a lapsed ACCESS token is normal, not a
    # sign-in problem; a dead refresh token surfaces as DISCONNECTED instead
    # (invalid_grant). The Microsoft rows keep their existing behaviour.
    is_google = integration.provider in ('gmail', 'google_calendar')
    if (not is_google and integration.token_expires_at
            and integration.token_expires_at <= timezone.now()):
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
    guidance = guidance.format(brand=provider_brand(integration.provider))
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
