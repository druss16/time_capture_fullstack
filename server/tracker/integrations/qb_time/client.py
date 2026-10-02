"""
QuickBooks Time (formerly TSheets) API client for one Integration row.

    api = QBTimeClient(integration)
    for jobcode in api.paginated('jobcodes', active='both'):
        ...

QuickBooks Time is a separate product from QuickBooks Online, with its own
OAuth app and its own API host — a QBO token does not open it.

Reference: https://tsheetsteam.github.io/api_docs/
  · access tokens last 10 days; refresh with grant_type=refresh_token
  · collections come back keyed by id under results.<endpoint>, with a
    top-level `more` flag for pagination (limit ≤ 200)
  · 200 requests per 5 minutes per token; 429 beyond that

⚠️ Verified against the published API reference but NOT yet exercised against
a live account. Reads tolerate missing keys rather than raising.
"""
import logging
import time
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

API_BASE = 'https://rest.tsheets.com/api/v1'
PAGE_LIMIT = 200
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 4
TOKEN_REFRESH_BUFFER = timedelta(hours=12)
# A 429 means the 5-minute window is spent. Waiting it out is cheaper than
# failing a sync that is otherwise fine.
RATE_LIMIT_WAIT_SECONDS = 60


class QBTimeError(Exception):
    pass


class QBTimeAuthError(QBTimeError):
    """The grant is gone — the firm has to reconnect."""


class QBTimeNotAvailable(QBTimeError):
    """The endpoint exists but this account cannot use it (plan / feature off)."""


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return f'{API_BASE}/authorize?' + urlencode({
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'state': state,
    })


def grant_url() -> str:
    return f'{API_BASE}/grant'


def is_configured() -> bool:
    return bool(settings.QBTIME_CLIENT_ID and settings.QBTIME_CLIENT_SECRET
                and settings.QBTIME_REDIRECT_URI)


def records(payload: dict, endpoint: str) -> list:
    """The rows of one response page, whichever shape the endpoint uses.

    Most collections are an object keyed by id; tolerate a list too.
    """
    block = ((payload or {}).get('results') or {}).get(endpoint) or {}
    if isinstance(block, dict):
        return list(block.values())
    if isinstance(block, list):
        return block
    return []


class QBTimeClient:
    def __init__(self, integration, *, session=None, sleep=time.sleep):
        if integration.provider != 'qb_time':
            raise QBTimeError(f'Integration {integration.id} is not qb_time.')
        if not integration.is_connected:
            raise QBTimeError(f'Integration {integration.id} is not connected.')
        if not (settings.QBTIME_CLIENT_ID and settings.QBTIME_CLIENT_SECRET):
            raise QBTimeError('QBTIME_CLIENT_ID and QBTIME_CLIENT_SECRET must be set.')
        self.integration = integration
        self.http = session or requests
        self._sleep = sleep

    # ── OAuth ────────────────────────────────────────────────────────────
    def _ensure_fresh_token(self, force=False):
        expires_at = self.integration.token_expires_at
        if not force and expires_at and (expires_at - TOKEN_REFRESH_BUFFER) > timezone.now():
            return
        if not self.integration.refresh_token:
            raise QBTimeAuthError('No refresh token on file. Reconnect QuickBooks Time.')

        try:
            resp = self.http.post(grant_url(), data={
                'grant_type': 'refresh_token',
                'refresh_token': self.integration.refresh_token,
                'client_id': settings.QBTIME_CLIENT_ID,
                'client_secret': settings.QBTIME_CLIENT_SECRET,
            }, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            # A network blip, not a revoked grant — stay connected and retry later.
            raise QBTimeError(f'Token refresh request failed: {e}')

        if resp.status_code != 200:
            self.integration.is_connected = False
            self.integration.last_sync_status = 'failed'
            self.integration.last_sync_error = (
                f'Token refresh failed: HTTP {resp.status_code}. Reconnect QuickBooks Time.'
            )
            self.integration.save(update_fields=[
                'is_connected', 'last_sync_status', 'last_sync_error', 'updated_at',
            ])
            raise QBTimeAuthError(f'Token refresh failed (HTTP {resp.status_code}).')

        apply_tokens(self.integration, resp.json())
        self.integration.save(update_fields=[
            'access_token', 'refresh_token', 'token_expires_at', 'updated_at',
        ])

    # ── Requests ─────────────────────────────────────────────────────────
    def get(self, endpoint: str, **params) -> dict:
        self._ensure_fresh_token()
        url = f'{API_BASE}/{endpoint}'
        refreshed = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.http.get(url, params=params, timeout=DEFAULT_TIMEOUT, headers={
                    'Authorization': f'Bearer {self.integration.access_token}',
                    'Accept': 'application/json',
                })
            except requests.RequestException as e:
                logger.warning('QB Time GET %s network error (%d/%d): %s',
                               endpoint, attempt, MAX_RETRIES, e)
                self._sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401 and not refreshed:
                refreshed = True
                self._ensure_fresh_token(force=True)
                continue
            if resp.status_code == 401:
                raise QBTimeAuthError(f'QB Time {endpoint} returned 401 after refresh.')
            if resp.status_code == 429:
                logger.info('QB Time rate limit on %s; waiting %ss', endpoint, RATE_LIMIT_WAIT_SECONDS)
                self._sleep(RATE_LIMIT_WAIT_SECONDS)
                continue
            if resp.status_code in (403, 404, 417):
                # Plan or feature not enabled for this account (e.g. Projects
                # is an Elite feature). Callers treat this as "no data here".
                raise QBTimeNotAvailable(f'QB Time {endpoint}: HTTP {resp.status_code}')
            if resp.status_code >= 500:
                self._sleep(2 ** attempt)
                continue
            raise QBTimeError(f'QB Time {endpoint}: HTTP {resp.status_code} {resp.text[:200]}')

        raise QBTimeError(f'QB Time {endpoint}: gave up after {MAX_RETRIES} attempts.')

    def paginated(self, endpoint: str, **params):
        """Every record of a collection, page by page."""
        page = 1
        while True:
            payload = self.get(endpoint, page=page, limit=PAGE_LIMIT, **params)
            rows = records(payload, endpoint)
            yield from rows
            if not payload.get('more') or not rows:
                return
            page += 1


def apply_tokens(integration, tokens: dict):
    """Write a /grant response onto the integration (not saved)."""
    integration.access_token = tokens['access_token']
    if tokens.get('refresh_token'):
        integration.refresh_token = tokens['refresh_token']
    integration.token_expires_at = timezone.now() + timedelta(
        seconds=int(tokens.get('expires_in') or 10 * 24 * 3600)
    )
