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