"""
Tests for ageing the QuickBooks Online company hint before it reaches Block.hints.

WHY THESE EXIST
---------------
The extension reports the active QBO company (realmId + name). The agent's
context bus never expires anything, so that payload was copied onto EVERY later
event — Slack, Figma, Google Docs — and compaction lifted it onto the block,
where Stage 8 turns a mapped realm into a 0.95 client signal. One look at QBO
in the morning could file an afternoon of unrelated work to that company.

A realm describes the screen only while the screen IS QuickBooks Online, so a
hint is kept only when the event's own URL is a QBO page AND the extension saw
it within the same window the Clio anchor uses.

Needs Django importable; if unavailable, cases are SKIPPED.

    python manage.py shell -c "import tracker.qbo_hint_freshness_test"
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
    from tracker.services.compaction import (
        _fresh_qbo_company, _is_qbo_url, QBO_HINT_TTL_SECONDS,
    )
    from datetime import datetime, timedelta, timezone as dt_timezone
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("QBO hint freshness:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


BASE = datetime(2026, 9, 29, 14, 0, 0, tzinfo=dt_timezone.utc) if _ok else None
QBO = 'https://qbo.intuit.com/app/homepage'


class _E:
    """A source event: its own URL, plus whatever the extension last posted."""

    def __init__(self, url, end_ts, realm='9130', name='Acme Co', focused_at=None,
                 omit_stamp=False, start_ts=None):
        self.url = url
        self.end_ts = end_ts
        self.start_ts = start_ts if start_ts is not None else end_ts
        bx = {}
        if realm is not None:
            bx['qbo_company_id'] = realm
        if name is not None:
            bx['qbo_company_name'] = name
        stamp = focused_at if focused_at is not None else end_ts
        if stamp is not None and not omit_stamp:
            bx['tab_focused_at'] = stamp.isoformat().replace('+00:00', 'Z')
        self.ctx = {'browser_extension': bx}


if _ok:
    print("QBO hint freshness:")

    # ── The bug: a QBO realm riding onto non-QBO work ────────────────────
    check("a fresh realm on a Slack event is dropped",
          _fresh_qbo_company(_E('https://app.slack.com/client/T1/C2', BASE)) == ("", ""))

    check("a fresh realm on a Figma event is dropped",
          _fresh_qbo_company(_E('https://www.figma.com/design/abc/Acme-Rebrand', BASE)) == ("", ""))

    check("a realm on an event with no URL (desktop app) is dropped",
          _fresh_qbo_company(_E(None, BASE)) == ("", ""))

    check("a look-alike host is not QBO",
          _fresh_qbo_company(_E('https://qbo.intuit.com.evil.example/app', BASE)) == ("", ""))

    # ── Staleness, even on a QBO page ────────────────────────────────────
    check("a realm last seen long ago is dropped even on a QBO URL",
          _fresh_qbo_company(_E(QBO, BASE, focused_at=BASE - timedelta(hours=3))) == ("", ""))

    check("just past the TTL is stale",
          _fresh_qbo_company(_E(QBO, BASE, focused_at=BASE - timedelta(
              seconds=QBO_HINT_TTL_SECONDS + 1))) == ("", ""))

    check("a hint with no tab_focused_at is refused, not trusted",
          _fresh_qbo_company(_E(QBO, BASE, omit_stamp=True)) == ("", ""))

    # ── What must still work ─────────────────────────────────────────────
    check("a fresh realm on a QBO page is kept, with its name",
          _fresh_qbo_company(_E(QBO, BASE)) == ('9130', 'Acme Co'))

    check("exactly at the TTL is still fresh",
          _fresh_qbo_company(_E(QBO, BASE, focused_at=BASE - timedelta(
              seconds=QBO_HINT_TTL_SECONDS)))[0] == '9130')

    check("a QBO subdomain counts",
          _fresh_qbo_company(_E('https://c17.qbo.intuit.com/app/invoice', BASE))[0] == '9130')

    check("a scheme-less QBO URL counts",
          _is_qbo_url('qbo.intuit.com/app/homepage'))

    check("a missing name still yields the realm",
          _fresh_qbo_company(_E(QBO, BASE, name=None)) == ('9130', ''))

    check("no realm at all yields nothing",
          _fresh_qbo_company(_E(QBO, BASE, realm=None)) == ("", ""))

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
