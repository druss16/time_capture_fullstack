"""Google OAuth 2.0 + Gmail / Calendar REST client (per-user integrations).

Mirrors integrations/msgraph.py, with plain `requests` — no google-api-client
or google-auth dependency. Both flows share ONE OAuth client
(GOOGLE_OAUTH_CLIENT_ID/SECRET) and differ by scope and redirect URI:

  gmail            openid email gmail.metadata          (headers only)
  google_calendar  openid email calendar.events.readonly

PRIVACY — Gmail
  * `gmail.metadata` cannot return a message body or attachment at all; the
    API refuses format=full/raw under it.
  * messages.get still returns `snippet` by default even for format=metadata,
    so every message read passes a `fields` mask that leaves snippet (and the
    payload parts, where attachment filenames live) out of the RESPONSE. What
    never crosses the wire can never be stored by mistake.

Gmail API quirks this module encodes:
  * Under gmail.metadata, messages.list REJECTS the `q` parameter. There is no
    server-side date filter, so the initial window is walked newest-first by
    label (INBOX / SENT) and stops at the first page that crosses the cutoff.
  * history.list works under gmail.metadata; a startHistoryId that is too old
    returns 404, which means "do a full sync again".
Calendar: events.list with a syncToken returns 410 when the token is
invalidated, which likewise means "full sync again".
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
GMAIL_BASE = 'https://gmail.googleapis.com/gmail/v1/users/me'
CALENDAR_BASE = 'https://www.googleapis.com/calendar/v3'

GMAIL_SCOPES = [
    'openid',
    'email',
    'https://www.googleapis.com/auth/gmail.metadata',
]
CALENDAR_SCOPES = [
    'openid',
    'email',
    'https://www.googleapis.com/auth/calendar.events.readonly',
]

# Headers we ask Gmail for. Nothing else is requested.
GMAIL_METADATA_HEADERS = ('From', 'To', 'Cc', 'Subject', 'Date')
# Response mask: NO snippet, NO payload.parts (attachment filenames live there).
GMAIL_MESSAGE_FIELDS = 'id,threadId,labelIds,internalDate,payload/mimeType,payload/headers'

# Refresh this long before the recorded expiry, so a token never lapses mid-sync.
EXPIRY_SKEW = timedelta(seconds=60)
DISCONNECT_THRESHOLD = 3
METADATA_WORKERS = 8


class GoogleAuthError(Exception):
    """OAuth or auth-related error."""


class GoogleAPIError(Exception):
    """Google API call error."""


class GoogleCursorExpired(GoogleAPIError):
    """Gmail historyId (404) or Calendar syncToken (410) no longer valid."""


PROVIDER_CONFIG = {
    'gmail': {
        'scopes': GMAIL_SCOPES,
        'redirect_setting': 'GOOGLE_GMAIL_REDIRECT_URI',
        'label': 'Gmail',
    },
    'google_calendar': {
        'scopes': CALENDAR_SCOPES,
        'redirect_setting': 'GOOGLE_CALENDAR_REDIRECT_URI',
        'label': 'Google Calendar',
    },
}


def redirect_uri_for(provider):
    """The redirect URI a flow signs in with — and must exchange with."""
    return getattr(settings, PROVIDER_CONFIG[provider]['redirect_setting'])


# ─── OAuth ────────────────────────────────────────────────────────────────────

def build_auth_url(provider, state, login_hint=''):
    """Google consent URL for one provider's flow.

    access_type=offline + prompt=consent: Google only issues a refresh token on
    a consent screen, and a user who connected once before would otherwise get
    an access token alone and stop syncing an hour later.

    Each flow REQUESTS only its own scopes, so the consent screen for Gmail
    never mentions Calendar and vice versa. include_granted_scopes=true is
    Google's incremental-authorization mode (product decision: one OAuth
    client for both products): a person who connects both ends up with one
    grant covering both, rather than two grants that fight. Consequence worth
    knowing: the tokens stored on the Gmail row may ALSO carry calendar scope
    (and vice versa). Nothing reads outside its own API with them, and it is
    why disconnect does not call Google's revoke endpoint — revoking one
    product's token would revoke the whole grant, killing the other product.

    Whether the flow's OWN scope was actually granted is checked on callback
    (granted_scopes_missing): Google's granular consent lets a user untick it.
    """
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': redirect_uri_for(provider),
        'response_type': 'code',
        'scope': ' '.join(PROVIDER_CONFIG[provider]['scopes']),
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
        'state': state,
    }
    if login_hint:
        params['login_hint'] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(provider, code):
    """Trade the authorization code for access + refresh tokens."""
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                'code': code,
                'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
                'redirect_uri': redirect_uri_for(provider),
                'grant_type': 'authorization_code',
            },
            timeout=15,
        )
    except requests.RequestException as e:
        raise GoogleAuthError(f'Token exchange request failed: {e}')
    data = _json(resp)
    if resp.status_code != 200 or 'access_token' not in data:
        desc = data.get('error_description') or data.get('error') or f'HTTP {resp.status_code}'
        logger.error(f"[GOOGLE] Token exchange failed ({provider}): {desc}")
        raise GoogleAuthError(desc)
    return data


def fetch_userinfo(access_token):
    """OpenID userinfo — `sub` and `email` for the connection metadata."""
    resp = requests.get(
        USERINFO_URL,
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=10,
    )
    if resp.status_code != 200:
        raise GoogleAPIError(f'userinfo failed: HTTP {resp.status_code}')
    return resp.json()


def granted_scopes_missing(provider, token_result):
    """Scopes the user UNTICKED on the consent screen.

    Google's granular consent lets a user approve sign-in but decline the
    Gmail/Calendar checkbox. The exchange still succeeds; every API call then
    403s. Catch it at connect time instead of after five failed syncs.
    """
    # Strict: no `scope` in the response counts as nothing granted. Google
    # always returns it; if that ever changes we want a loud refusal, not a
    # half-connected row that 403s on every sync.
    granted = set((token_result.get('scope') or '').split())
    wanted = [s for s in PROVIDER_CONFIG[provider]['scopes'] if s.startswith('https://')]
    return [s for s in wanted if s not in granted]


def refresh_access_token(integration):
    """Refresh an expired access token. Updates the integration in place.

    Failure handling mirrors msgraph.refresh_access_token_mail:
      * no refresh token → the consent screen was never finished; say so.
      * invalid_grant → terminal (revoked, password change, 7-day expiry of
        an OAuth app left in "Testing"): disconnect now, ask for a reconnect.
      * anything else → transient; disconnect only after 3 in a row.
    """
    if not (integration.refresh_token or '').strip():
        integration.is_connected = False
        integration.last_sync_error = (
            'Never connected — the Google consent screen was never completed. '
            'Reconnect from Settings → Connections.'
        )
        integration.save(update_fields=['is_connected', 'last_sync_error'])
        raise GoogleAuthError('No refresh token — this integration was never fully connected.')

    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
                'refresh_token': integration.refresh_token,
                'grant_type': 'refresh_token',
            },
            timeout=15,
        )
        data = _json(resp)
        ok = resp.status_code == 200 and 'access_token' in data
    except requests.RequestException as e:
        data, ok = {'error': 'network', 'error_description': str(e)}, False

    if not ok:
        fail_count = (integration.sync_failure_count or 0) + 1
        is_terminal = data.get('error') == 'invalid_grant'
        will_disconnect = is_terminal or fail_count >= DISCONNECT_THRESHOLD
        desc = data.get('error_description') or data.get('error') or 'unknown'
        logger.error(
            f"[GOOGLE] Refresh failed for user {integration.user_id} "
            f"({integration.provider}, attempt {fail_count}, terminal={is_terminal}): {desc[:200]}"
        )
        integration.sync_failure_count = fail_count
        if is_terminal:
            label = PROVIDER_CONFIG.get(integration.provider, {}).get('label', 'Google')
            integration.last_sync_error = (
                f'{label} access needs to be granted again — reconnect from '
                f'Settings → Connections.'
            )
        else:
            integration.last_sync_error = f'Refresh failed: {desc}'[:500]
        if will_disconnect:
            integration.is_connected = False
        integration.save(update_fields=['is_connected', 'last_sync_error', 'sync_failure_count'])
        raise GoogleAuthError(desc)

    integration.access_token = data['access_token']
    # Google normally keeps the original refresh token; store a new one if sent.
    if data.get('refresh_token'):
        integration.refresh_token = data['refresh_token']
    integration.token_expires_at = timezone.now() + timedelta(seconds=int(data.get('expires_in', 3600)))
    integration.is_connected = True
    integration.last_sync_error = ''
    integration.sync_failure_count = 0
    integration.save(update_fields=[
        'access_token', 'refresh_token', 'token_expires_at',
        'is_connected', 'last_sync_error', 'sync_failure_count',
    ])
    return data['access_token']


def get_valid_token(integration):
    """Current access token, refreshed first if it is (about to be) expired."""
    exp = integration.token_expires_at
    if not integration.access_token or (exp and timezone.now() >= exp - EXPIRY_SKEW):
        return refresh_access_token(integration)
    return integration.access_token


# ─── HTTP plumbing ────────────────────────────────────────────────────────────

def _json(resp):
    try:
        return resp.json()
    except ValueError:
        return {}


def _check(resp, integration, what):
    """Map a non-200 into the right exception. Returns parsed JSON on 200."""
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 401:
        raise _Unauthorized()
    if resp.status_code in (403, 429):
        body = _json(resp)
        reason = ''
        try:
            reason = body['error']['errors'][0].get('reason', '')
        except (KeyError, IndexError, TypeError):
            pass
        if reason in ('insufficientPermissions', 'forbidden', 'accessNotConfigured') \
                or 'insufficient' in str(body).lower():
            # The user unticked the scope, or the API is not enabled on the
            # Cloud project. Waiting will not fix either.
            integration.is_connected = False
            integration.last_sync_error = (
                f'Google refused {what}: {reason or "forbidden"}. Reconnect and '
                f'leave every permission ticked.'
            )
            integration.save(update_fields=['is_connected', 'last_sync_error'])
            raise GoogleAuthError(f'{what}: {reason or resp.status_code}')
        raise GoogleAPIError(f'{what}: throttled ({resp.status_code} {reason})')
    logger.error(f"[GOOGLE] {what} HTTP {resp.status_code}: {resp.text[:300]}")
    raise GoogleAPIError(f'{what}: HTTP {resp.status_code}')


class _Unauthorized(Exception):
    pass


def _get(integration, url, params=None, what='request'):
    """GET with the integration's token; one forced refresh on a 401.

    A 401 on a token we believed valid is usually revocation, occasionally a
    clock-skew race at expiry. Refresh once: refresh_access_token turns a real
    revocation into invalid_grant → disconnect with a readable message.
    """
    token = get_valid_token(integration)
    for attempt in (1, 2):
        resp = requests.get(url, params=params, headers={'Authorization': f'Bearer {token}'}, timeout=30)
        try:
            return resp, _check(resp, integration, what)
        except _Unauthorized:
            if attempt == 2:
                integration.is_connected = False
                integration.last_sync_error = 'Google access revoked or expired'
                integration.save(update_fields=['is_connected', 'last_sync_error'])
                raise GoogleAuthError('Access revoked')
            integration.token_expires_at = timezone.now() - timedelta(seconds=1)
            token = refresh_access_token(integration)


# ─── Gmail ────────────────────────────────────────────────────────────────────

def gmail_get_profile(integration):
    """{'emailAddress', 'historyId', ...} for the mailbox."""
    _, data = _get(integration, f'{GMAIL_BASE}/profile', what='gmail profile')
    return data


def _metadata_params():
    return [('format', 'metadata'), ('fields', GMAIL_MESSAGE_FIELDS)] + [
        ('metadataHeaders', h) for h in GMAIL_METADATA_HEADERS
    ]


def gmail_get_messages(integration, message_ids):
    """Header metadata for many messages, fetched in parallel.

    Returns a list of message dicts (masked — see GMAIL_MESSAGE_FIELDS).
    Messages deleted between listing and fetching (404) are skipped.
    The token is resolved once up front so worker threads never refresh.
    """
    ids = [m for m in message_ids if m]
    if not ids:
        return []
    token = get_valid_token(integration)
    params = _metadata_params()

    def fetch(mid):
        r = requests.get(
            f'{GMAIL_BASE}/messages/{mid}',
            params=params,
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )
        return mid, r

    results = []
    with ThreadPoolExecutor(max_workers=min(METADATA_WORKERS, len(ids))) as pool:
        responses = list(pool.map(fetch, ids))
    for mid, r in responses:
        if r.status_code == 404:
            continue
        try:
            results.append(_check(r, integration, 'gmail message'))
        except _Unauthorized:
            integration.is_connected = False
            integration.last_sync_error = 'Google access revoked or expired'
            integration.save(update_fields=['is_connected', 'last_sync_error'])
            raise GoogleAuthError('Access revoked')
    return results


def gmail_list_page(integration, label_id, page_token=None, max_results=100):
    """One page of message ids under a label, newest first.

    Returns (ids, next_page_token or None). messages.list cannot filter by
    date under gmail.metadata (no `q`), so the caller pages until a page
    reaches past its cutoff. One page per call keeps every sync run small
    enough to finish inside the Celery time limit and persist its progress.
    """
    params = {'labelIds': label_id, 'maxResults': max_results}
    if page_token:
        params['pageToken'] = page_token
    _, data = _get(integration, f'{GMAIL_BASE}/messages', params=params, what='gmail list')
    ids = [m['id'] for m in (data.get('messages') or []) if m.get('id')]
    return ids, data.get('nextPageToken') or None


def gmail_list_history(integration, start_history_id, max_pages=50):
    """Changes since start_history_id.

    Returns (added: list[{'id','labelIds'}], deleted_ids: list[str], new_history_id).
    Raises GoogleCursorExpired on 404 (history too old — full resync needed).
    """
    added, deleted = {}, set()
    new_history_id = str(start_history_id)
    page_token = None
    for _ in range(max_pages):
        params = [
            ('startHistoryId', str(start_history_id)),
            ('historyTypes', 'messageAdded'),
            ('historyTypes', 'messageDeleted'),
            ('maxResults', '500'),
        ]
        if page_token:
            params.append(('pageToken', page_token))
        token = get_valid_token(integration)
        resp = requests.get(
            f'{GMAIL_BASE}/history', params=params,
            headers={'Authorization': f'Bearer {token}'}, timeout=30,
        )
        if resp.status_code == 404:
            raise GoogleCursorExpired('gmail historyId expired')
        try:
            data = _check(resp, integration, 'gmail history')
        except _Unauthorized:
            integration.is_connected = False
            integration.last_sync_error = 'Google access revoked or expired'
            integration.save(update_fields=['is_connected', 'last_sync_error'])
            raise GoogleAuthError('Access revoked')
        for h in data.get('history', []) or []:
            for rec in h.get('messagesAdded', []) or []:
                m = rec.get('message') or {}
                if m.get('id'):
                    added[m['id']] = {'id': m['id'], 'labelIds': m.get('labelIds') or []}
            for rec in h.get('messagesDeleted', []) or []:
                m = rec.get('message') or {}
                if m.get('id'):
                    deleted.add(m['id'])
        if data.get('historyId'):
            new_history_id = str(data['historyId'])
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    for mid in deleted:
        added.pop(mid, None)
    return list(added.values()), sorted(deleted), new_history_id


# ─── Calendar ─────────────────────────────────────────────────────────────────

def calendar_list_events(integration, sync_token='', time_min=None, time_max=None):
    """events.list on the primary calendar, all pages.

    Full sync: pass time_min/time_max. Incremental: pass sync_token only (Google
    rejects time bounds alongside a syncToken with a 400).
    Returns (events, next_sync_token). Raises GoogleCursorExpired on 410.
    """
    base = {'singleEvents': 'true', 'maxResults': '250', 'showDeleted': 'true'}
    if sync_token:
        base['syncToken'] = sync_token
    else:
        if time_min:
            base['timeMin'] = time_min.isoformat()
        if time_max:
            base['timeMax'] = time_max.isoformat()
    events, next_sync = [], ''
    page_token = None
    for _ in range(100):
        params = dict(base)
        if page_token:
            params['pageToken'] = page_token
        token = get_valid_token(integration)
        resp = requests.get(
            f'{CALENDAR_BASE}/calendars/primary/events', params=params,
            headers={'Authorization': f'Bearer {token}'}, timeout=30,
        )
        if resp.status_code == 410:
            raise GoogleCursorExpired('calendar syncToken expired')
        try:
            data = _check(resp, integration, 'calendar events')
        except _Unauthorized:
            integration.is_connected = False
            integration.last_sync_error = 'Google access revoked or expired'
            integration.save(update_fields=['is_connected', 'last_sync_error'])
            raise GoogleAuthError('Access revoked')
        events.extend(data.get('items', []) or [])
        page_token = data.get('nextPageToken')
        if not page_token:
            next_sync = data.get('nextSyncToken', '') or ''
            break
    return events, next_sync
