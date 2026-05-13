"""
CCH Axcess Practice HTTP client.

⚠️ ENDPOINT URLs ARE PLACEHOLDERS until you have Wolters Kluwer developer
portal access. Update TOKEN_URL and BASE_URL after applying to the
CCH Axcess Integration Vendor Program and getting subscription keys.

OAUTH FLOW (Authorization Code grant per WK docs):
1. MavOps registers one OAuth app with WK (one client_id / client_secret).
2. Each firm authorizes via /auth/authorize redirect; we capture the auth
   code and exchange for tokens.
3. Tokens are stored encrypted on tracker.Integration.access_token /
   refresh_token (existing fields).
4. This client refreshes tokens automatically when access_token expires.

DESIGN PRINCIPLES
-----------------
- Stateless functions; pass the Integration row in.
- No silent fallback — if the integration is disconnected, raise.
- All HTTP calls log to logging.getLogger(__name__).
- Pagination handled inside paginated_get().
- 429 rate-limit retry with exponential backoff.
"""

import logging
import time
from datetime import timedelta
from typing import Iterator, Optional

import requests
from django.conf import settings
from django.utils import timezone

from tracker.models import Integration

logger = logging.getLogger(__name__)

# ⚠️ PLACEHOLDERS — confirm against your WK developer portal once you have access.
TOKEN_URL = 'https://api.cchaxcess.com/oauth/token'
BASE_URL = 'https://api.cchaxcess.com/v1'

# Tunables
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)
PAGE_SIZE = 100


class AxcessError(Exception):
    """Base exception for CCH Axcess client errors."""


class AxcessAuthError(AxcessError):
    """OAuth-related failure (expired refresh token, revoked grant, etc.)."""


class AxcessRateLimitError(AxcessError):
    """Got 429s past MAX_RETRIES."""


class AxcessClient:
    """
    HTTP client for one Integration row (one org × cch_axcess).

    Usage:
        integration = Integration.objects.get(organization=org, provider='cch_axcess')
        client = AxcessClient(integration)
        for record in client.paginated_get('/clients'):
            ...
    """

    def __init__(self, integration: Integration):
        if integration.provider != 'cch_axcess':
            raise AxcessError(
                f'Integration {integration.id} is not cch_axcess (got {integration.provider}).'
            )
        if not integration.is_connected:
            raise AxcessError(f'Integration {integration.id} is not connected.')

        self.integration = integration
        self.client_id = getattr(settings, 'CCH_AXCESS_CLIENT_ID', '')
        self.client_secret = getattr(settings, 'CCH_AXCESS_CLIENT_SECRET', '')
        self.subscription_key = getattr(settings, 'CCH_AXCESS_SUBSCRIPTION_KEY', '')

        if not (self.client_id and self.client_secret):
            raise AxcessError(
                'CCH_AXCESS_CLIENT_ID and CCH_AXCESS_CLIENT_SECRET must be set in settings.'
            )

    # ────────────────────────────────────────────────────────────────────
    # OAuth — refresh access token using Integration.refresh_token
    # ────────────────────────────────────────────────────────────────────

    def _ensure_fresh_token(self):
        """Refresh access_token if expired or about to expire."""
        expires_at = self.integration.token_expires_at
        if expires_at and (expires_at - TOKEN_REFRESH_BUFFER) > timezone.now():
            return  # Still fresh

        if not self.integration.refresh_token:
            raise AxcessAuthError(
                f'Integration {self.integration.id} has no refresh_token. '
                f'User must re-authorize.'
            )

        logger.info('Refreshing CCH Axcess access token for integration %s', self.integration.id)

        resp = requests.post(
            TOKEN_URL,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self.integration.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
            },
            timeout=DEFAULT_TIMEOUT,
        )

        if resp.status_code != 200:
            self.integration.is_connected = False
            self.integration.last_sync_status = 'failed'
            self.integration.last_sync_error = (
                f'Token refresh failed: HTTP {resp.status_code} {resp.text[:200]}'
            )
            self.integration.save()
            raise AxcessAuthError(
                f'Token refresh failed (HTTP {resp.status_code}). User must re-authorize.'
            )

        data = resp.json()
        self.integration.access_token = data['access_token']
        if 'refresh_token' in data:
            self.integration.refresh_token = data['refresh_token']
        expires_in = int(data.get('expires_in', 3600))
        self.integration.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        self.integration.save(update_fields=[
            'access_token', 'refresh_token', 'token_expires_at', 'updated_at',
        ])

    # ────────────────────────────────────────────────────────────────────
    # Request helpers
    # ────────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {
            'Authorization': f'Bearer {self.integration.access_token}',
            'Accept': 'application/json',
        }
        if self.subscription_key:
            # Wolters Kluwer typically uses Ocp-Apim-Subscription-Key header
            h['Ocp-Apim-Subscription-Key'] = self.subscription_key
        return h

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        """Single GET request with auth + retry handling."""
        self._ensure_fresh_token()

        url = f'{BASE_URL}{path}'
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(MAX_RETRIES):
            resp = requests.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=DEFAULT_TIMEOUT,
            )

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 401:
                # Token might have expired between check and call — refresh once
                logger.warning('Got 401 from %s, refreshing token and retrying', path)
                self.integration.token_expires_at = timezone.now()  # Force refresh
                self._ensure_fresh_token()
                continue

            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', backoff))
                logger.warning('Rate-limited on %s, sleeping %ss (attempt %d/%d)',
                               path, retry_after, attempt + 1, MAX_RETRIES)
                time.sleep(retry_after)
                backoff = min(backoff * 2, 60)
                continue

            if resp.status_code >= 500:
                logger.warning('Server error %d on %s (attempt %d/%d)',
                               resp.status_code, path, attempt + 1, MAX_RETRIES)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            # 4xx other than 401/429 — surface immediately
            raise AxcessError(f'GET {path} failed: HTTP {resp.status_code} {resp.text[:200]}')

        raise AxcessRateLimitError(f'GET {path} exceeded {MAX_RETRIES} retries.')

    def paginated_get(self, path: str, params: Optional[dict] = None) -> Iterator[dict]:
        """
        Yields individual records from a paginated endpoint.

        Assumes WK Practice API returns:
            { "data": [...], "next": "<url or null>", "page": N, "total": M }

        If your actual response shape differs, adjust the loop below once
        you confirm against the WK developer portal.
        """
        params = dict(params or {})
        params.setdefault('pageSize', PAGE_SIZE)
        page = 1
        seen = 0

        while True:
            params['page'] = page
            response = self.get(path, params=params)
            data = response.get('data') or response.get('items') or []
            for record in data:
                yield record
                seen += 1

            # Two possible pagination indicators: an absolute 'next' link, or page metadata
            next_link = response.get('next') or response.get('nextLink')
            total = response.get('total') or response.get('totalCount')

            if next_link:
                page += 1
                continue
            if total is not None and seen < total:
                page += 1
                continue
            break

    def post(self, path: str, json_body: dict) -> dict:
        """Single POST request. Used for write path (WIP push)."""
        self._ensure_fresh_token()

        url = f'{BASE_URL}{path}'
        resp = requests.post(
            url,
            headers={**self._headers(), 'Content-Type': 'application/json'},
            json=json_body,
            timeout=DEFAULT_TIMEOUT,
        )

        if resp.status_code in (200, 201):
            return resp.json() if resp.content else {}
        if resp.status_code == 401:
            raise AxcessAuthError('POST failed with 401 even after token refresh.')
        raise AxcessError(f'POST {path} failed: HTTP {resp.status_code} {resp.text[:500]}')