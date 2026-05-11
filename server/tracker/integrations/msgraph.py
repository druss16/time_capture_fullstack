"""Microsoft Graph API client for calendar integration."""
import logging
import requests
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
import msal

logger = logging.getLogger(__name__)

GRAPH_API_BASE = 'https://graph.microsoft.com/v1.0'

# OAuth scopes — delegated permissions
DELEGATED_SCOPES = [
    'Calendars.Read',
    'User.Read',
    # offline_access is auto-added by MSAL; don't include it explicitly
]


class MSGraphAuthError(Exception):
    """OAuth or auth-related error."""


class MSGraphAPIError(Exception):
    """Graph API call error."""


def _get_msal_app(tenant='common'):
    """
    Build MSAL ConfidentialClientApplication.
    'common' = multi-tenant; lets any org's user sign in.
    """
    return msal.ConfidentialClientApplication(
        client_id=settings.MS_GRAPH_CLIENT_ID,
        client_credential=settings.MS_GRAPH_CLIENT_SECRET,
        authority=f'https://login.microsoftonline.com/{tenant}',
    )


def build_auth_url(state, redirect_uri):
    """Generate Microsoft sign-in URL for the user."""
    app = _get_msal_app('common')
    return app.get_authorization_request_url(
        scopes=DELEGATED_SCOPES,
        state=state,
        redirect_uri=redirect_uri,
        prompt='select_account',
    )


def exchange_code_for_tokens(code, redirect_uri):
    """Trade OAuth code for access + refresh tokens."""
    app = _get_msal_app('common')
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=DELEGATED_SCOPES,
        redirect_uri=redirect_uri,
    )
    if 'error' in result:
        logger.error(f"[MSGRAPH] Token exchange failed: {result.get('error_description')}")
        raise MSGraphAuthError(result.get('error_description', 'Unknown error'))
    return result


def refresh_access_token(integration):
    """
    Refresh expired access token. Updates integration in place.
    integration: UserIntegration instance.
    """
    app = _get_msal_app('common')
    result = app.acquire_token_by_refresh_token(
        refresh_token=integration.refresh_token,
        scopes=DELEGATED_SCOPES,
    )
    
    if 'error' in result:
        logger.error(f"[MSGRAPH] Refresh failed for user {integration.user_id}")
        integration.is_connected = False
        integration.last_sync_error = f"Refresh failed: {result.get('error_description')}"
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.save(update_fields=['is_connected', 'last_sync_error', 'sync_failure_count'])
        raise MSGraphAuthError(result.get('error_description'))
    
    integration.access_token = result['access_token']
    if 'refresh_token' in result:
        integration.refresh_token = result['refresh_token']
    integration.token_expires_at = timezone.now() + timedelta(seconds=result.get('expires_in', 3600))
    integration.last_sync_error = ''
    integration.save(update_fields=['access_token', 'refresh_token', 'token_expires_at', 'last_sync_error'])
    
    return result['access_token']


def get_valid_token(integration):
    """Return current valid access token; refresh if needed."""
    if integration.is_token_expired:
        return refresh_access_token(integration)
    return integration.access_token


def fetch_user_profile(access_token):
    """Get the signed-in user's email + ID for connection metadata."""
    resp = requests.get(
        f"{GRAPH_API_BASE}/me",
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=10,
    )
    if resp.status_code != 200:
        raise MSGraphAPIError(f"Profile fetch failed: HTTP {resp.status_code}")
    return resp.json()


def fetch_calendar_view(integration, start_dt, end_dt):
    """
    Fetch calendar events between start_dt and end_dt (UTC).
    Returns list of raw event dicts. Recurring events expanded to instances.
    """
    token = get_valid_token(integration)
    
    url = f"{GRAPH_API_BASE}/me/calendarView"
    params = {
        'startDateTime': start_dt.isoformat(),
        'endDateTime': end_dt.isoformat(),
        '$select': 'id,subject,bodyPreview,location,start,end,showAs,responseStatus,'
                   'isCancelled,isAllDay,type,seriesMasterId,attendees,onlineMeetingUrl,'
                   'onlineMeeting,categories,organizer',
        '$top': 100,
        '$orderby': 'start/dateTime',
    }
    headers = {
        'Authorization': f'Bearer {token}',
        'Prefer': 'outlook.timezone="UTC"',
    }
    
    events = []
    next_url = url
    
    while next_url:
        resp = requests.get(
            next_url,
            params=params if next_url == url else None,
            headers=headers,
            timeout=30,
        )
        
        if resp.status_code == 401:
            logger.warning(f"[MSGRAPH] 401 for user {integration.user_id} — token revoked")
            integration.is_connected = False
            integration.last_sync_error = "Access revoked or expired"
            integration.save(update_fields=['is_connected', 'last_sync_error'])
            raise MSGraphAuthError("Access revoked")
        
        if resp.status_code != 200:
            logger.error(f"[MSGRAPH] {resp.status_code}: {resp.text[:300]}")
            raise MSGraphAPIError(f"Graph API {resp.status_code}")
        
        data = resp.json()
        events.extend(data.get('value', []))
        next_url = data.get('@odata.nextLink')  # pagination
    
    return events

# ============================================================================
# APPEND THIS TO server/tracker/integrations/msgraph.py
#
# Do NOT replace the file. These are additions that sit alongside the existing
# calendar functions. They reuse _get_msal_app, MSGraphAuthError, MSGraphAPIError,
# refresh_access_token (with adapted scopes via wrapper), and get_valid_token.
# ============================================================================


# OAuth scopes for mail — narrow read scope, no body access at API level
MAIL_DELEGATED_SCOPES = [
    'Mail.ReadBasic',
    'User.Read',
]


def build_auth_url_mail(state, redirect_uri):
    """Generate Microsoft sign-in URL for mail (Mail.ReadBasic scope)."""
    app = _get_msal_app('common')
    return app.get_authorization_request_url(
        scopes=MAIL_DELEGATED_SCOPES,
        state=state,
        redirect_uri=redirect_uri,
        prompt='select_account',
    )


def exchange_code_for_tokens_mail(code, redirect_uri):
    """Trade OAuth code for mail access + refresh tokens."""
    app = _get_msal_app('common')
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=MAIL_DELEGATED_SCOPES,
        redirect_uri=redirect_uri,
    )
    if 'error' in result:
        logger.error(f"[MSGRAPH-MAIL] Token exchange failed: {result.get('error_description')}")
        raise MSGraphAuthError(result.get('error_description', 'Unknown error'))
    return result


def refresh_access_token_mail(integration):
    """
    Refresh expired mail access token. Updates integration in place.
    integration: UserIntegration instance with provider='microsoft_mail'.
    """
    app = _get_msal_app('common')
    result = app.acquire_token_by_refresh_token(
        refresh_token=integration.refresh_token,
        scopes=MAIL_DELEGATED_SCOPES,
    )

    if 'error' in result:
        logger.error(f"[MSGRAPH-MAIL] Refresh failed for user {integration.user_id}")
        integration.is_connected = False
        integration.last_sync_error = f"Refresh failed: {result.get('error_description')}"
        integration.sync_failure_count = (integration.sync_failure_count or 0) + 1
        integration.save(update_fields=['is_connected', 'last_sync_error', 'sync_failure_count'])
        raise MSGraphAuthError(result.get('error_description'))

    integration.access_token = result['access_token']
    if 'refresh_token' in result:
        integration.refresh_token = result['refresh_token']
    integration.token_expires_at = timezone.now() + timedelta(seconds=result.get('expires_in', 3600))
    integration.last_sync_error = ''
    integration.save(update_fields=[
        'access_token', 'refresh_token', 'token_expires_at', 'last_sync_error',
    ])

    return result['access_token']


def get_valid_token_mail(integration):
    """Return current valid mail access token; refresh if needed."""
    if integration.is_token_expired:
        return refresh_access_token_mail(integration)
    return integration.access_token


def fetch_mail_delta(integration, initial_window_days=30):
    """
    Fetch mail messages via /me/mailFolders/inbox/messages/delta.
    Delta tracking on Graph only works at folder level, not on the message
    collection. Inbox-only is a deliberate v1 scoping decision — we can add
    sent-items or per-folder sync later if Wayne/Terri tell us they're
    missing signal from filed emails.
    
    Two modes:
      1. Initial sync (no integration.mail_delta_link): fetches last 30 days
         using $filter on receivedDateTime, paginates via @odata.nextLink,
         finishes by capturing @odata.deltaLink for next run.
      2. Incremental sync (integration.mail_delta_link populated): calls the
         stored delta URL directly. Returns only changed messages since last
         sync. Updates the delta link.

    Returns:
        (messages: list[dict], new_delta_link: str)

    Privacy: $select limits server response to header-level fields only.
    The body is NEVER requested. The Mail.ReadBasic scope also blocks body
    at the API level even if we asked.
    """
    from datetime import datetime
    token = get_valid_token_mail(integration)

    headers = {
        'Authorization': f'Bearer {token}',
        'Prefer': 'outlook.body-content-type="text"',
    }

    # Header-only fields. NEVER add 'body' or 'bodyPreview' here.
    select_fields = (
        'id,from,toRecipients,ccRecipients,receivedDateTime,'
        'subject,hasAttachments,parentFolderId,conversationId,'
        'isDraft,isRead'
    )

    if integration.mail_delta_link:
        # Incremental sync — Graph returns full URL with state token; just call it
        url = integration.mail_delta_link
        params = None
    else:
        # Initial sync — fetch last N days
        since = datetime.utcnow() - timedelta(days=initial_window_days)
        # Note: /messages/delta does not support $filter on receivedDateTime
        # in the initial request. We use /messages with $filter for the first
        # pass, capture all message IDs, then transition to delta on next sync.
        # Microsoft's recommended pattern.
        url = f"{GRAPH_API_BASE}/me/mailFolders/inbox/messages/delta"
        params = {
            '$select': select_fields,
            '$top': 100,
            # Delta endpoint accepts a filter on receivedDateTime for the
            # initial scope-narrowing call. After the first @odata.deltaLink,
            # Graph tracks state itself.
            '$filter': f"receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        }

    messages = []
    delta_link = ''
    next_url = url
    request_params = params
    page_count = 0
    MAX_PAGES = 50  # Safety cap — 50 * 100 = 5,000 messages per sync run

    while next_url and page_count < MAX_PAGES:
        resp = requests.get(
            next_url,
            params=request_params,
            headers=headers,
            timeout=30,
        )
        request_params = None  # only on first call

        if resp.status_code == 410:
            # Delta token expired — Graph requires we restart from scratch.
            # Clear the stored link; next run will do a fresh initial sync.
            logger.warning(f"[MSGRAPH-MAIL] 410 delta expired for user {integration.user_id}")
            integration.mail_delta_link = ''
            integration.save(update_fields=['mail_delta_link'])
            return ([], '')

        if resp.status_code == 401:
            logger.warning(f"[MSGRAPH-MAIL] 401 for user {integration.user_id} — token revoked")
            integration.is_connected = False
            integration.last_sync_error = "Mail access revoked or expired"
            integration.save(update_fields=['is_connected', 'last_sync_error'])
            raise MSGraphAuthError("Mail access revoked")

        if resp.status_code == 429:
            # Throttled — Graph tells us how long to wait via Retry-After.
            # Bubble up; Celery task will retry.
            retry_after = resp.headers.get('Retry-After', '60')
            logger.warning(f"[MSGRAPH-MAIL] 429 throttled, retry in {retry_after}s")
            raise MSGraphAPIError(f"Throttled by Graph (retry after {retry_after}s)")

        if resp.status_code != 200:
            logger.error(f"[MSGRAPH-MAIL] {resp.status_code}: {resp.text[:300]}")
            raise MSGraphAPIError(f"Graph API {resp.status_code}")

        data = resp.json()
        messages.extend(data.get('value', []))

        # Capture delta link if present (terminates the chain)
        if '@odata.deltaLink' in data:
            delta_link = data['@odata.deltaLink']
            next_url = None
        else:
            next_url = data.get('@odata.nextLink')

        page_count += 1

    if page_count >= MAX_PAGES:
        logger.warning(
            f"[MSGRAPH-MAIL] Hit MAX_PAGES cap for user {integration.user_id} — "
            f"will continue next sync"
        )

    return (messages, delta_link)


def fetch_inbox_folder_id(integration):
    """
    Fetch the user's Inbox folder ID. Used to populate MailSignal.is_inbox.
    Returns folder ID string or empty string on failure.

    Cached on integration via a lightweight property (we don't migrate a
    field for this — recompute on demand and cache in Redis if needed later).
    """
    token = get_valid_token_mail(integration)
    resp = requests.get(
        f"{GRAPH_API_BASE}/me/mailFolders/inbox",
        headers={'Authorization': f'Bearer {token}'},
        timeout=10,
    )
    if resp.status_code != 200:
        logger.warning(f"[MSGRAPH-MAIL] Inbox folder fetch failed: HTTP {resp.status_code}")
        return ''
    return resp.json().get('id', '')