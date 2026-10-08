"""
Asana API client for one Integration row. Read-only.

    api = AsanaClient(integration)
    for project in api.paginated('projects', workspace=gid, opt_fields='name,archived'):
        ...

Reference: https://developers.asana.com/docs
  · OAuth: authorize at app.asana.com/-/oauth_authorize, tokens from
    app.asana.com/-/oauth_token; access tokens last an hour, refresh tokens
    do not expire until the grant is revoked
  · every response is {"data": ...}; collections page with `limit` (≤100)
    and `offset`, the next offset in `next_page.offset`
  · 429 carries Retry-After (seconds); 150 requests/minute on a free
    workspace, 1500 on paid
"""
import logging
import time
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

API_BASE = 'https://app.asana.com/api/1.0'
AUTHORIZE_URL = 'https://app.asana.com/-/oauth_authorize'
TOKEN_URL = 'https://app.asana.com/-/oauth_token'
PAGE_LIMIT = 100
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 4
# Tokens last an hour; refresh with a few minutes to spare.
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)
MAX_RETRY_AFTER = 120


class AsanaError(Exception):
    pass


class AsanaAuthError(AsanaError):
    """The grant is gone — the firm has to reconnect."""


class AsanaNotAvailable(AsanaError):
    """This resource is not visible to the connected account (403 / 404)."""


def is_configured() -> bool:
    return bool(settings.ASANA_CLIENT_ID and settings.ASANA_CLIENT_SECRET
                and settings.ASANA_REDIRECT_URI)


def authorize_url(state: str) -> str:
    params = {
        'client_id': settings.ASANA_CLIENT_ID,
        'redirect_uri': settings.ASANA_REDIRECT_URI,
        'response_type': 'code',
        'state': state,
    }
    if settings.ASANA_SCOPES:
        params['scope'] = settings.ASANA_SCOPES
    return f'{AUTHORIZE_URL}?{urlencode(params)}'


def exchange_code(code: str, *, http=requests) -> dict:
    resp = http.post(TOKEN_URL, data={
        'grant_type': 'authorization_code',
        'client_id': settings.ASANA_CLIENT_ID,
        'client_secret': settings.ASANA_CLIENT_SECRET,
        'redirect_uri': settings.ASANA_REDIRECT_URI,
        'code': code,
    }, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        raise AsanaError(f'Token exchange HTTP {resp.status_code}: {resp.text[:300]}')
    return resp.json()


def apply_tokens(integration, tokens: dict):
    """Write a token response onto the integration (not saved)."""
    integration.access_token = tokens['access_token']
    if tokens.get('refresh_token'):
        integration.refresh_token = tokens['refresh_token']
    integration.token_expires_at = timezone.now() + timedelta(
        seconds=int(tokens.get('expires_in') or 3600))


class AsanaClient:
    def __init__(self, integration, *, session=None, sleep=time.sleep):
        if integration.provider != 'asana':
            raise AsanaError(f'Integration {integration.id} is not asana.')
        if not integration.is_connected:
            raise AsanaError(f'Integration {integration.id} is not connected.')
        if not (settings.ASANA_CLIENT_ID and settings.ASANA_CLIENT_SECRET):
            raise AsanaError('ASANA_CLIENT_ID and ASANA_CLIENT_SECRET must be set.')
        self.integration = integration
        self.http = session or requests
        self._sleep = sleep

    # ── OAuth ────────────────────────────────────────────────────────────
    def _ensure_fresh_token(self, force=False):
        expires_at = self.integration.token_expires_at
        if not force and expires_at and (expires_at - TOKEN_REFRESH_BUFFER) > timezone.now():
            return
        if not self.integration.refresh_token:
            raise AsanaAuthError('No refresh token on file. Reconnect Asana.')
        try:
            resp = self.http.post(TOKEN_URL, data={
                'grant_type': 'refresh_token',
                'client_id': settings.ASANA_CLIENT_ID,
                'client_secret': settings.ASANA_CLIENT_SECRET,
                'redirect_uri': settings.ASANA_REDIRECT_URI,
                'refresh_token': self.integration.refresh_token,
            }, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            # A network blip, not a revoked grant — stay connected, retry later.
            raise AsanaError(f'Token refresh request failed: {e}')
        if resp.status_code != 200:
            self.integration.is_connected = False
            self.integration.last_sync_status = 'failed'
            self.integration.last_sync_error = (
                f'Token refresh failed: HTTP {resp.status_code}. Reconnect Asana.')
            self.integration.save(update_fields=[
                'is_connected', 'last_sync_status', 'last_sync_error', 'updated_at'])
            raise AsanaAuthError(f'Token refresh failed (HTTP {resp.status_code}).')
        apply_tokens(self.integration, resp.json())
        self.integration.save(update_fields=[
            'access_token', 'refresh_token', 'token_expires_at', 'updated_at'])

    # ── Requests ─────────────────────────────────────────────────────────
    def get(self, path: str, **params) -> dict:
        self._ensure_fresh_token()
        url = f'{API_BASE}/{path.lstrip("/")}'
        refreshed = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.http.request('GET', url, params=params, timeout=DEFAULT_TIMEOUT, headers={
                    'Authorization': f'Bearer {self.integration.access_token}',
                    'Accept': 'application/json',
                })
            except requests.RequestException as e:
                logger.warning('Asana GET %s network error (%d/%d): %s', path, attempt, MAX_RETRIES, e)
                self._sleep(2 ** attempt)
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401 and not refreshed:
                refreshed = True
                self._ensure_fresh_token(force=True)
                continue
            if resp.status_code == 401:
                raise AsanaAuthError(f'Asana {path} returned 401 after refresh.')
            if resp.status_code == 429:
                try:
                    wait = int(resp.headers.get('Retry-After') or 30)
                except ValueError:
                    wait = 30
                logger.info('Asana rate limit on %s; waiting %ss', path, wait)
                self._sleep(min(max(wait, 1), MAX_RETRY_AFTER))
                continue
            if resp.status_code in (402, 403, 404):
                raise AsanaNotAvailable(f'Asana {path}: HTTP {resp.status_code}')
            if resp.status_code >= 500:
                self._sleep(2 ** attempt)
                continue
            raise AsanaError(f'Asana GET {path}: HTTP {resp.status_code} {resp.text[:200]}')
        raise AsanaError(f'Asana GET {path}: gave up after {MAX_RETRIES} attempts.')

    def paginated(self, path: str, **params):
        """Every record of a collection, page by page."""
        offset = None
        while True:
            page = dict(params, limit=PAGE_LIMIT)
            if offset:
                page['offset'] = offset
            payload = self.get(path, **page)
            rows = payload.get('data') or []
            yield from rows
            offset = ((payload.get('next_page') or {}).get('offset'))
            if not offset or not rows:
                return
