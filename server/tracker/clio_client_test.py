"""
Tests for the Clio Manage HTTP client.

Covers the three behaviours that fail *silently* at scale rather than loudly:

1. REGION ROUTING — a token minted in one Clio region 401s in every other.
   A wrong host does not raise at construction time; it surfaces later as an
   auth error that looks like a revoked grant. Pin it here.

2. RATE-LIMIT PAUSING — Clio allows ~50 req/min per firm. The client is
   supposed to pause as the published budget nears zero rather than spend the
   last requests and eat 429s. If this regresses, syncs still "work" — they
   just crawl behind retry backoff.

3. PAGINATION — Clio returns records under `data` with the next page as an
   absolute URL at `meta.paging.next`. If the next-link is ever ignored, every
   sync silently truncates at 200 records with no error at all. That is the
   worst failure mode in this file.

No network, no database: `_request` and `time.sleep` are stubbed.

Needs Django importable (the module pulls in tracker.models); if unavailable
(bare python), the cases are SKIPPED, not failed.

    python manage.py shell -c "import tracker.clio_client_test"
or standalone where Django is configured:
    python tracker/clio_client_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


try:
    from tracker.integrations.clio import client as clio
    _ok = True
except Exception as e:  # ModuleNotFoundError / ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("Clio client:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


class _FakeResponse:
    """Minimal stand-in carrying only the rate-limit headers."""

    def __init__(self, headers):
        self.headers = headers


if _ok:
    # ── 1. Region routing ────────────────────────────────────────────────
    print("Clio client — region routing:")
    check("us -> app.clio.com", clio.region_host('us') == 'app.clio.com')
    check("eu -> eu.app.clio.com", clio.region_host('eu') == 'eu.app.clio.com')
    check("ca -> ca.app.clio.com", clio.region_host('ca') == 'ca.app.clio.com')
    check("au -> au.app.clio.com", clio.region_host('au') == 'au.app.clio.com')
    check("uppercase region normalizes", clio.region_host('EU') == 'eu.app.clio.com')
    check("blank falls back to US", clio.region_host('') == 'app.clio.com')
    check("None falls back to US", clio.region_host(None) == 'app.clio.com')
    check("unknown falls back to US", clio.region_host('mars') == 'app.clio.com')

    print("Clio client — OAuth URLs follow the region:")
    eu_auth = clio.authorize_url('eu', 'cid', 'https://api.example.com/cb', 'eu:abc')
    check("authorize URL uses regional host", eu_auth.startswith('https://eu.app.clio.com/oauth/authorize?'))
    check("authorize URL carries client_id", 'client_id=cid' in eu_auth)
    check("authorize URL carries state", 'state=eu%3Aabc' in eu_auth)
    check("authorize URL requests a code", 'response_type=code' in eu_auth)
    check("token URL uses regional host",
          clio.token_url('au') == 'https://au.app.clio.com/oauth/token')
    check("deauthorize URL uses regional host",
          clio.deauthorize_url('ca') == 'https://ca.app.clio.com/oauth/deauthorize')

    # ── 2. Rate-limit pausing ────────────────────────────────────────────
    print("Clio client — pauses before exhausting the budget:")

    slept = []
    _real_sleep = clio.time.sleep
    clio.time.sleep = lambda s: slept.append(s)
    try:
        slept.clear()
        clio.ClioClient._respect_rate_limit(_FakeResponse({'X-RateLimit-Remaining': '40'}))
        check("healthy budget -> no pause", slept == [])

        slept.clear()
        clio.ClioClient._respect_rate_limit(_FakeResponse({'X-RateLimit-Remaining': '0'}))
        check("exhausted budget -> pauses", len(slept) == 1 and slept[0] > 0)

        slept.clear()
        clio.ClioClient._respect_rate_limit(_FakeResponse({}))
        check("no headers -> no pause (non-Clio/proxy response)", slept == [])

        slept.clear()
        clio.ClioClient._respect_rate_limit(
            _FakeResponse({'X-RateLimit-Remaining': 'garbage'}))
        check("unparseable header -> no pause, no crash", slept == [])

        slept.clear()
        clio.ClioClient._respect_rate_limit(_FakeResponse({
            'X-RateLimit-Remaining': '1',
            'X-RateLimit-Reset': str(clio.time.time() + 9999),
        }))
        check("pause is capped, never unbounded",
              len(slept) == 1 and slept[0] <= clio.MAX_BACKOFF_SECONDS)
    finally:
        clio.time.sleep = _real_sleep

    # ── 3. Pagination ────────────────────────────────────────────────────
    print("Clio client — pagination follows meta.paging.next:")

    def _client_with_pages(pages):
        """A ClioClient that replays canned payloads instead of calling out."""
        c = object.__new__(clio.ClioClient)
        calls = []

        def fake_request(method, path, params=None, json_body=None, absolute_url=None):
            calls.append({'url': absolute_url, 'params': params})
            return pages[len(calls) - 1]

        c._request = fake_request
        c._calls = calls
        return c

    two_pages = [
        {'data': [{'id': 1}, {'id': 2}],
         'meta': {'paging': {'next': 'https://eu.app.clio.com/api/v4/matters?page_token=2'}}},
        {'data': [{'id': 3}], 'meta': {'paging': {}}},
    ]
    c = _client_with_pages(two_pages)
    got = list(c.paginated_get('/matters', fields='id'))
    check("yields records across pages", [r['id'] for r in got] == [1, 2, 3])
    check("first call uses params, not an absolute URL", c._calls[0]['url'] is None)
    check("first call sends the fields list", c._calls[0]['params']['fields'] == 'id')
    check("first call requests a full page", c._calls[0]['params']['limit'] == clio.PAGE_SIZE)
    check("second call follows the next link verbatim",
          c._calls[1]['url'] == 'https://eu.app.clio.com/api/v4/matters?page_token=2')
    check("stops when next is absent", len(c._calls) == 2)

    c = _client_with_pages([{'data': [], 'meta': {}}])
    check("empty collection yields nothing",
          list(c.paginated_get('/matters', fields='id')) == [])

    c = _client_with_pages([{}])
    check("missing data key does not crash",
          list(c.paginated_get('/matters', fields='id')) == [])

    # ── 4. The `fields` trap ─────────────────────────────────────────────
    # Clio returns only id+etag when `fields` is omitted — a 200 with silently
    # empty records. `fields` is keyword-only and required so that omitting it
    # is a TypeError at the call site rather than mystery data at runtime.
    print("Clio client — `fields` cannot be forgotten:")
    c = _client_with_pages([{'data': [], 'meta': {}}])
    try:
        c.paginated_get('/matters')
        _raised = False
    except TypeError:
        _raised = True
    check("paginated_get without fields raises TypeError", _raised)

    try:
        clio.ClioClient.get(c, '/matters/1')
        _raised = False
    except TypeError:
        _raised = True
    check("get without fields raises TypeError", _raised)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
