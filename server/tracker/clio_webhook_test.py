"""
Tests for the Clio webhook path's pure logic.

DELIBERATELY DATABASE-FREE. These run via `manage.py shell`, and in this
deployment that shell is wired to the live production database — so a test
here that called .objects.create() would create real rows in a real firm's
data. Every case below either works on unsaved model instances or exercises a
branch that returns before touching the ORM.

What is covered is what is dangerous to get wrong:

1. `verify_signature` — the ONLY thing standing between a public, unauthed
   URL and writes into a firm's client list. The URL token is not a secret
   in any meaningful sense (it travels in logs and proxies); the HMAC is the
   whole security model. A comparison that is merely loose rather than wrong
   would pass casual inspection and let anything through.

2. `webhook_base_url` / `callback_url` — this string is handed to Clio ONCE
   and then lives on their side for up to a month. Getting it wrong does not
   fail loudly at deploy; it fails as deliveries that never arrive, which
   looks exactly like "the firm hasn't added any clients lately".

3. `handle_event`'s refusals — a malformed or hostile payload must be
   reported, never raised, and a `deleted` event must not remove anything.

    python manage.py shell -c "import tracker.clio_webhook_test"
"""
import hashlib
import hmac
import json
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
    from django.test import override_settings

    from tracker.integrations.clio.webhooks import (
        callback_url,
        handle_event,
        verify_signature,
        webhook_base_url,
        SUBSCRIPTION_DAYS,
        RENEW_WHEN_REMAINING,
        WATCHED_MODELS,
    )
    from tracker.models import ClioWebhook, Integration
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("Clio webhooks:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    SECRET = 'a-firms-shared-secret'
    BODY = b'{"event":"contact.updated","data":{"id":4242}}'

    def unsaved_hook(secret=SECRET, model='contact'):
        """A ClioWebhook that has never been saved — no DB, no queries."""
        return ClioWebhook(
            integration=Integration(id=1, organization_id=1, provider='clio'),
            model=model, url_token='tok-abc', shared_secret=secret,
            status='active', external_id='wh-1',
        )

    def sign(body, secret=SECRET):
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    print("Clio webhooks — verify_signature is the whole security model:")
    hook = unsaved_hook()
    check("accepts a correct lowercase-hex signature",
          verify_signature(hook, BODY, sign(BODY)))
    check("accepts uppercase hex (casing must not reject a real callback)",
          verify_signature(hook, BODY, sign(BODY).upper()))
    check("tolerates surrounding whitespace",
          verify_signature(hook, BODY, f'  {sign(BODY)}  '))
    check("rejects a wrong signature",
          not verify_signature(hook, BODY, 'de' * 32))
    check("rejects an empty signature",
          not verify_signature(hook, BODY, ''))
    check("rejects a None signature",
          not verify_signature(hook, BODY, None))
    check("rejects a truncated-but-prefix-correct signature",
          not verify_signature(hook, BODY, sign(BODY)[:32]))
    check("rejects when the body gained one trailing byte",
          not verify_signature(hook, BODY + b' ', sign(BODY)))
    check("rejects when the body lost one byte",
          not verify_signature(hook, BODY[:-1], sign(BODY)))
    check("rejects when we hold no secret at all",
          not verify_signature(unsaved_hook(secret=''), BODY, sign(BODY)))

    # ONE key now. Clio signs with the secret we supply at creation — proven
    # by the first real callback verifying first try with rejected_count at
    # zero — so the handshake secret is no longer stored or accepted.
    check("verifies against the secret we supplied",
          verify_signature(unsaved_hook(), BODY, sign(BODY)))
    check("a Clio-generated handshake secret is NOT accepted",
          not verify_signature(unsaved_hook(), BODY, sign(BODY, 'clio-generated-secret')))
    check("still rejects an unrelated secret",
          not verify_signature(unsaved_hook(), BODY, sign(BODY, 'neither-of-them')))

    # The cross-tenant case: per-subscription secrets are the reason one
    # firm's captured callback cannot be replayed against another's URL.
    check("another firm's secret does not verify",
          not verify_signature(hook, BODY, sign(BODY, 'a-different-firms-secret')))
    check("a signature is body-specific, not just secret-specific",
          not verify_signature(hook, b'{"data":{"id":1}}', sign(BODY)))

    print("\nClio webhooks — handle_event refuses bad input without raising:")
    r = handle_event(hook, b'not json at all')
    check("malformed body is reported, not raised",
          r['ok'] is False and 'bad_json' in r['reason'])

    r = handle_event(hook, b'\xff\xfe binary garbage')
    check("undecodable bytes are reported, not raised", r['ok'] is False)

    r = handle_event(hook, json.dumps({'event': 'contact.updated', 'data': {}}).encode())
    check("payload carrying no record id is refused",
          r['ok'] is False and r['reason'] == 'no_record_id')

    r = handle_event(hook, json.dumps({'event': 'contact.updated'}).encode())
    check("payload with no data envelope is refused", r['ok'] is False)

    # A delete must reach the 'noted' branch and return BEFORE any ORM call.
    # If this ever starts touching the database, this test raises here rather
    # than quietly deactivating a real client.
    r = handle_event(hook, json.dumps(
        {'event': 'contact.deleted', 'data': {'id': 4242}}).encode())
    check("a delete is recorded, never applied", r['ok'] and r['action'] == 'noted_delete')

    r = handle_event(unsaved_hook(model='matter'), json.dumps(
        {'event': 'matter.deleted', 'data': {'id': 77}}).encode())
    check("a matter delete is also only recorded", r['action'] == 'noted_delete')

    r = handle_event(unsaved_hook(model='bill'), json.dumps(
        {'event': 'bill.updated', 'data': {'id': 5}}).encode())
    check("a model we never subscribed to is refused", r['ok'] is False)

    print("\nClio webhooks — the callback URL Clio keeps for a month:")
    with override_settings(
        CLIO_WEBHOOK_BASE_URL='',
        CLIO_REDIRECT_URI='https://api.example.com/api/integrations/clio/callback/',
    ):
        check("origin is derived from CLIO_REDIRECT_URI",
              webhook_base_url() == 'https://api.example.com')
        # Built with reverse(), so this also proves the route is wired.
        check("callback url carries the subscription token",
              callback_url(hook)
              == 'https://api.example.com/api/integrations/clio/webhook/tok-abc/')

    with override_settings(CLIO_WEBHOOK_BASE_URL='https://hooks.example.com/'):
        check("an explicit override wins",
              webhook_base_url() == 'https://hooks.example.com')

    with override_settings(CLIO_WEBHOOK_BASE_URL='', CLIO_REDIRECT_URI=''):
        check("no configured URL yields empty, not a broken one",
              webhook_base_url() == '')
        check("callback_url is empty when there is no base",
              callback_url(hook) == '')

    with override_settings(CLIO_WEBHOOK_BASE_URL='', CLIO_REDIRECT_URI='not-a-url'):
        check("an unparseable redirect URI yields empty, not a mangled host",
              webhook_base_url() == '')

    print("\nClio webhooks — renewal leaves room to fail:")
    # Clio's ceiling is 31 days. Asking for more is rejected outright; asking
    # for exactly the ceiling leaves no slack for a failed renewal.
    check("subscription length stays under Clio's 31-day maximum",
          SUBSCRIPTION_DAYS < 31)
    check("renewal starts with days to spare, not hours",
          RENEW_WHEN_REMAINING.days >= 5)
    check("nightly renewal gets many attempts before expiry",
          SUBSCRIPTION_DAYS - RENEW_WHEN_REMAINING.days >= 14)

    print("\nClio webhooks — subscribed fields match what the upsert reads:")
    from tracker.integrations.clio.sync import CONTACT_FIELDS, MATTER_FIELDS
    # A shorter field list on the webhook than on the sync would write a
    # half-populated record over a complete one.
    check("contact hook requests the sync's own field list",
          WATCHED_MODELS['contact'] == CONTACT_FIELDS)
    check("matter hook requests the sync's own field list",
          WATCHED_MODELS['matter'] == MATTER_FIELDS)
    check("we watch exactly contacts and matters",
          set(WATCHED_MODELS) == {'contact', 'matter'})

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
