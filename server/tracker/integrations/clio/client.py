"""
Clio Manage API v4 HTTP client.

One ClioClient wraps one Integration row (one org × clio). Firms authorize
our single registered Clio app; each firm's tokens live on their own
Integration row, so rate limits (which Clio applies per access token) are
naturally per-firm and do not contend across tenants.

REGIONS
-------
Clio runs four independent data regions and tokens are NOT portable between
them: a token minted at app.clio.com 401s against eu.app.clio.com. The
region is captured during OAuth (Integration.api_region) and every URL —
authorize, token, and API — is derived from it. Never hardcode a host.

RATE LIMITS
-----------
50 req/min per token during peak hours, higher off-peak, and the ceiling can
change without notice. We therefore do not hardcode a budget: we read
X-RateLimit-Remaining off every response and pause proactively as it nears
zero, and we honour Retry-After on the 429s we didn't dodge.

THE `fields` TRAP
-----------------
Clio returns ONLY `id` and `etag` when `fields` is omitted — silently, with a
200. Every read here takes `fields` as a required argument so that a missing
field list is an error at the call site instead of mysteriously empty data.
Nesting is one level deep: `matter{id,display_number}` is fine,
`matter{client{name}}` is a 400.
"""

import logging
import time
from datetime import timedelta
from typing import Iterator, Optional
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

from tracker.models import Integration

logger = logging.getLogger(__name__)

# ── Regions ─────────────────────────────────────────────────────────────
# Keys are stored on Integration.api_region. 'us' is the default for firms
# that never picked one (Clio's own default region).
REGION_HOSTS = {
    'us': 'app.clio.com',
    'ca': 'ca.app.clio.com',
    'eu': 'eu.app.clio.com',
    'au': 'au.app.clio.com',
}
DEFAULT_REGION = 'us'

API_PATH = '/api/v4'

# ── Tunables ────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60
TOKEN_REFRESH_BUFFER = timedelta(hours=1)   # access tokens last 30 days
PAGE_SIZE = 200                             # Clio's per-page maximum

# Pause when the remaining-request budget drops to this. Clio's window is
# 60s, so the wait is bounded by X-RateLimit-Reset.
RATE_LIMIT_FLOOR = 3


class ClioError(Exception):
    """Base exception for Clio client errors."""


class ClioAuthError(ClioError):
    """OAuth failure — revoked grant, dead refresh token, wrong region."""


class ClioRateLimitError(ClioError):
    """Still rate-limited after MAX_RETRIES."""


class ClioValidationError(ClioError):
    """422 from Clio — the payload was rejected (e.g. missing UTBMS codes)."""

    def __init__(self, message, response_body=None):
        super().__init__(message)
        self.response_body = response_body or {}


def region_host(region: str) -> str:
    """Host for a region key, falling back to US for unknown/blank values."""
    return REGION_HOSTS.get((region or '').lower(), REGION_HOSTS[DEFAULT_REGION])


def authorize_url(region: str, client_id: str, redirect_uri: str, state: str) -> str:
    """Build the consent URL the firm's browser is sent to."""
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'state': state,
        # Send the user back to us on decline rather than stranding them in Clio
        'redirect_on_decline': 'true',
    }
    return f'https://{region_host(region)}/oauth/authorize?{urlencode(params)}'


def token_url(region: str) -> str:
    return f'https://{region_host(region)}/oauth/token'


def deauthorize_url(region: str) -> str:
    return f'https://{region_host(region)}/oauth/deauthorize'


class ClioClient:
    """
    HTTP client for one Integration row.

        integration = Integration.objects.get(organization=org, provider='clio')
        client = ClioClient(integration)
        for matter in client.paginated_get('/matters', fields='id,display_number,description'):
            ...
    """

    def __init__(self, integration: Integration):
        if integration.provider != 'clio':
            raise ClioError(
                f'Integration {integration.id} is not clio (got {integration.provider}).'
            )
        if not integration.is_connected:
            raise ClioError(f'Integration {integration.id} is not connected.')

        self.integration = integration
        self.client_id = getattr(settings, 'CLIO_CLIENT_ID', '')
        self.client_secret = getattr(settings, 'CLIO_CLIENT_SECRET', '')

        if not (self.client_id and self.client_secret):
            raise ClioError(
                'CLIO_CLIENT_ID and CLIO_CLIENT_SECRET must be set in settings.'
            )

        self.host = region_host(integration.api_region)
        self.base_url = f'https://{self.host}{API_PATH}'

    # ────────────────────────────────────────────────────────────────────
    # OAuth
    # ────────────────────────────────────────────────────────────────────

    def _ensure_fresh_token(self):
        """
        Refresh the access token if it is expired or close to it.

        Clio access tokens last 30 days and refresh tokens never expire, so
        this is a rare path — but a firm that revokes us in Clio's UI kills
        both, and that surfaces here as a non-200 on refresh.
        """
        expires_at = self.integration.token_expires_at
        if expires_at and (expires_at - TOKEN_REFRESH_BUFFER) > timezone.now():
            return

        if not self.integration.refresh_token:
            raise ClioAuthError(
                f'Integration {self.integration.id} has no refresh_token. '
                f'Firm must re-authorize.'
            )

        logger.info(
            'Refreshing Clio access token for integration %s (region %s)',
            self.integration.id, self.integration.api_region,
        )

        try:
            resp = requests.post(
                token_url(self.integration.api_region),
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': self.integration.refresh_token,
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            # Network blip — leave the integration connected so the next run retries
            raise ClioError(f'Clio token refresh request failed: {e}')

        if resp.status_code != 200:
            self.integration.is_connected = False
            self.integration.last_sync_status = 'failed'
            self.integration.last_sync_error = (
                f'Token refresh failed: HTTP {resp.status_code} {resp.text[:200]}'
            )
            self.integration.save(update_fields=[
                'is_connected', 'last_sync_status', 'last_sync_error', 'updated_at',
            ])
            raise ClioAuthError(
                f'Clio token refresh failed (HTTP {resp.status_code}). '
                f'Firm must re-authorize.'
            )

        data = resp.json()
        self.integration.access_token = data['access_token']
        if data.get('refresh_token'):
            self.integration.refresh_token = data['refresh_token']
        expires_in = int(data.get('expires_in', 30 * 24 * 3600))
        self.integration.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        self.integration.save(update_fields=[
            'access_token', 'refresh_token', 'token_expires_at', 'updated_at',
        ])

    # ────────────────────────────────────────────────────────────────────
    # Request plumbing
    # ────────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            'Authorization': f'Bearer {self.integration.access_token}',
            'Accept': 'application/json',
        }

    @staticmethod
    def _respect_rate_limit(resp):
        """
        Pause *before* we get throttled.

        Clio publishes the remaining budget on every response. When it runs
        low we sleep until the window resets rather than spending the last
        few requests and eating a 429 — which matters on sync/push jobs that
        issue hundreds of calls back to back.
        """
        remaining = resp.headers.get('X-RateLimit-Remaining')
        reset = resp.headers.get('X-RateLimit-Reset')
        if remaining is None:
            return
        try:
            remaining = int(remaining)
        except (TypeError, ValueError):
            return
        if remaining > RATE_LIMIT_FLOOR:
            return

        wait = 1.0
        if reset:
            try:
                wait = max(0.0, float(reset) - time.time()) + 1.0
            except (TypeError, ValueError):
                pass
        wait = min(wait, MAX_BACKOFF_SECONDS)
        logger.info('Clio budget low (%s left), pausing %.1fs for window reset', remaining, wait)
        time.sleep(wait)

    def _request(self, method: str, path: str, *, params=None, json_body=None,
                 absolute_url: Optional[str] = None) -> dict:
        """
        One authenticated request with token refresh, 429 backoff, and 5xx retry.

        `absolute_url` is used when following Clio's pagination `next` link,
        which arrives as a fully-qualified URL.
        """
        self._ensure_fresh_token()

        url = absolute_url or f'{self.base_url}{path}'
        backoff = INITIAL_BACKOFF_SECONDS
        refreshed_once = False

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers={**self._headers(), 'Content-Type': 'application/json'},
                    params=params or None,
                    json=json_body,
                    timeout=DEFAULT_TIMEOUT,
                )
            except requests.RequestException as e:
                logger.warning('Clio %s %s network error (attempt %d/%d): %s',
                               method, path, attempt, MAX_RETRIES, e)
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            if resp.status_code in (200, 201, 204):
                self._respect_rate_limit(resp)
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()

            if resp.status_code == 401:
                if refreshed_once:
                    raise ClioAuthError(
                        f'Clio {method} {path} returned 401 after refresh. '
                        f'Check that region "{self.integration.api_region}" matches '
                        f'the firm\'s Clio account.'
                    )
                logger.warning('Clio 401 on %s — forcing token refresh', path)
                self.integration.token_expires_at = timezone.now()
                self._ensure_fresh_token()
                refreshed_once = True
                continue

            if resp.status_code == 429:
                retry_after = resp.headers.get('Retry-After')
                try:
                    wait = int(retry_after) if retry_after else backoff
                except (TypeError, ValueError):
                    wait = backoff
                wait = min(wait, MAX_BACKOFF_SECONDS)
                logger.warning('Clio rate-limited on %s, sleeping %ss (attempt %d/%d)',
                               path, wait, attempt, MAX_RETRIES)
                time.sleep(wait)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            if resp.status_code == 422:
                # Payload rejected — surface the body so callers can explain
                # *why* (missing UTBMS codes is the common one).
                body = {}
                try:
                    body = resp.json()
                except ValueError:
                    pass
                raise ClioValidationError(
                    f'Clio rejected {method} {path}: {resp.text[:300]}', body
                )

            if resp.status_code >= 500:
                logger.warning('Clio server error %d on %s (attempt %d/%d)',
                               resp.status_code, path, attempt, MAX_RETRIES)
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            raise ClioError(
                f'Clio {method} {path} failed: HTTP {resp.status_code} {resp.text[:300]}'
            )

        raise ClioRateLimitError(f'Clio {method} {path} exceeded {MAX_RETRIES} retries.')

    # ────────────────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────────────────

    def get(self, path: str, *, fields: str, params: Optional[dict] = None) -> dict:
        """Single GET. `fields` is required — see the module docstring."""
        params = dict(params or {})
        params['fields'] = fields
        return self._request('GET', path, params=params)

    def paginated_get(self, path: str, *, fields: str,
                      params: Optional[dict] = None) -> Iterator[dict]:
        """
        Yield every record from a paginated collection.

        Clio v4 returns {"data": [...], "meta": {"paging": {"next": "<url>"}}}.
        The `next` link is absolute and already carries fields/limit/cursor,
        so it is followed verbatim.
        """
        params = dict(params or {})
        params['fields'] = fields
        params.setdefault('limit', PAGE_SIZE)

        next_url = None
        while True:
            if next_url:
                payload = self._request('GET', path, absolute_url=next_url)
            else:
                payload = self._request('GET', path, params=params)

            for record in payload.get('data') or []:
                yield record

            next_url = ((payload.get('meta') or {}).get('paging') or {}).get('next')
            if not next_url:
                break

    def post(self, path: str, body: dict, *, fields: Optional[str] = None) -> dict:
        """
        Create a record. Clio wraps write payloads in a `data` envelope.

        Passing `fields` echoes the created record back with those fields
        populated, saving a follow-up GET (we use it to capture new activity
        ids on push).
        """
        params = {'fields': fields} if fields else None
        return self._request('POST', path, params=params, json_body={'data': body})

    def patch(self, path: str, body: dict, *, fields: Optional[str] = None) -> dict:
        params = {'fields': fields} if fields else None
        return self._request('PATCH', path, params=params, json_body={'data': body})

    def deauthorize(self):
        """
        Tell Clio to invalidate our token. Best-effort: a firm that already
        revoked us in Clio's UI makes this a no-op, which is fine.
        """
        try:
            requests.post(
                deauthorize_url(self.integration.api_region),
                data={'token': self.integration.access_token},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.warning('Clio deauthorize call failed (ignored): %s', e)
