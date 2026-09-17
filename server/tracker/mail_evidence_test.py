"""
Tests for _build_mail_evidence (tracker.views_block_evidence).

Stage 7 composes a full sentence of reasoning when mail decides a block's
client — "3 signals received from acmecorp.com -> Acme" — and then drops it.
The evidence panel listed mail as deferred, so an Outlook block could be
attributed by email and the "Show details" expansion would show only agent
selection and title aliases. This builder is what puts the reasoning back.

Two things it must get right beyond the happy path:

  * The unmapped case is the ACTIONABLE one. Mail with a counterparty that no
    rule maps can never attribute to anybody, and nothing else in the product
    says so. That has to read as a finding, not as silence.

  * Mail is restricted to the block's own user. Everything shown is already
    stored (a domain, never an address; a subject only when it already matched
    a client at >= 0.85), but org members and MavOps admins can read this
    endpoint for ANY block, and showing them who a colleague emailed at 2pm is
    not what the Connections card promised whoever connected that mailbox.

Run inside the app container:
    python manage.py shell -c "import tracker.mail_evidence_test"

Exits non-zero if any assertion fails.
"""
import os
import sys
from types import SimpleNamespace

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
    from django.utils import timezone
    from tracker import models as tracker_models
    from tracker.views_block_evidence import _build_mail_evidence
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("mail evidence:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


class _FakeManager:
    """Stands in for MailSignal.objects — the builder only ever chains
    filter -> select_related -> order_by and then iterates."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, **kw):
        return self

    def select_related(self, *a):
        return self

    def order_by(self, *a):
        return self

    def __iter__(self):
        return iter(self._rows)


def sig(domain, client=None, subject='', client_id=None):
    return SimpleNamespace(
        other_party_domain=domain,
        extracted_client_id=client_id if client_id is not None else (client.id if client else None),
        extracted_client=client,
        subject_extract=subject,
        occurred_at=timezone.now() if _ok else None,
        direction='in',
    )


def run(rows, *, same_user=True, mail_disabled=False):
    """Call the builder with `rows` visible, as the block's own user by default."""
    original = tracker_models.MailSignal
    fake = SimpleNamespace(objects=_FakeManager(rows))
    tracker_models.MailSignal = fake
    try:
        block = SimpleNamespace(
            user_id=7,
            start=timezone.now(),
            org=SimpleNamespace(disable_mail_integration=mail_disabled),
        )
        who = SimpleNamespace(id=7 if same_user else 8)
        return _build_mail_evidence(block, who)
    finally:
        tracker_models.MailSignal = original


if _ok:
    print("mail evidence:")

    acme = SimpleNamespace(id=41, name='Acme Corp')
    beck = SimpleNamespace(id=42, name='Beck CPA')

    # --- the happy path: mail decided this, and says so --------------------
    out = run([sig('acmecorp.com', acme), sig('acmecorp.com', acme)])
    check("two emails with one client -> named in the summary",
          out is not None and 'Acme Corp' in out['summary'] and '2 emails' in out['summary'])
    check("the counterparty domain is shown, not an address",
          out['matched'][0]['domains'] == ['acmecorp.com'])

    out = run([sig('acmecorp.com', acme, subject='Q3 close for Acme Corp')])
    check("a stored subject is quoted when there is one",
          "about 'Q3 close for Acme Corp'" in out['summary'])
    check("singular reads as one email, not '1 emails'",
          '1 email ' in out['summary'] and '1 emails' not in out['summary'])

    # --- most signals wins, same as Stage 7 --------------------------------
    out = run([sig('acmecorp.com', acme), sig('beck.com', beck), sig('acmecorp.com', acme)])
    check("the client with the most signals leads",
          out['matched'][0]['client_name'] == 'Acme Corp')
    check("the runner-up is still listed, not hidden",
          len(out['matched']) == 2 and out['matched'][1]['client_name'] == 'Beck CPA')

    # --- the actionable case ------------------------------------------------
    out = run([sig('acmecorp.com'), sig('acmecorp.com'), sig('typeform.com')])
    check("no mapped domain -> says so plainly",
          'none from a domain mapped to a client' in out['summary'])
    check("unmapped domains are ranked by volume",
          [u['domain'] for u in out['unmapped_domains']] == ['acmecorp.com', 'typeform.com'])
    check("nothing is claimed as matched",
          out['matched'] == [])

    # --- mixed: a match plus an unmapped domain worth acting on -------------
    out = run([sig('acmecorp.com', acme), sig('stranger.com')])
    check("a match does not bury the unmapped domain",
          out['matched'][0]['client_name'] == 'Acme Corp'
          and out['unmapped_domains'] == [{'domain': 'stranger.com', 'count': 1}])

    # --- silence ------------------------------------------------------------
    check("no mail in the window -> nothing to render",
          run([]) is None)

    # --- the privacy gate ---------------------------------------------------
    check("a colleague or admin asking gets nothing",
          run([sig('acmecorp.com', acme)], same_user=False) is None)
    check("org kill switch honored",
          run([sig('acmecorp.com', acme)], mail_disabled=True) is None)

print()
print(f"mail evidence: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
