"""
Tests for ageing the Clio matter anchor before it reaches Block.hints.

WHY THESE EXIST
---------------
The anchor is tier 0 in matter attribution — it outranks the folder memory and
an explicit matter number in the filename, because "Clio had this matter open"
is knowledge rather than inference. That standing is only earned while the
statement is PRESENT TENSE.

The browser extension goes silent the moment the browser loses focus, but the
agent's context bus never expires anything: it holds the last payload and
`snapshot_ctx()` copies it onto every later event. So without ageing, a lawyer
who opened matter 00001 in the morning, closed Chrome, and spent the day in Word
on matter 00002's documents had every one of those blocks stamped 00001 — the
strongest signal in the system pointing at the wrong client's matter.

The hazard is the same one the client-side matcher keeps re-learning: a
confident wrong answer is worse than no answer. Every case below asks whether a
stale anchor is refused, and whether a live one still survives.

Needs Django importable; if unavailable, cases are SKIPPED.

    python manage.py shell -c "import tracker.clio_anchor_freshness_test"
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
        _fresh_clio_matter_id, _parse_ctx_timestamp, CLIO_ANCHOR_TTL_SECONDS,
    )
    from datetime import datetime, timedelta, timezone as dt_timezone
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("Clio anchor freshness:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


BASE = datetime(2026, 9, 18, 14, 0, 0, tzinfo=dt_timezone.utc) if _ok else None


class _E:
    """A source event carrying whatever the extension last posted."""

    def __init__(self, end_ts, matter_id=None, focused_at=None, omit_stamp=False,
                 extra=None, start_ts=None):
        self.end_ts = end_ts
        self.start_ts = start_ts if start_ts is not None else end_ts
        bx = dict(extra or {})
        if matter_id is not None:
            bx['clio_matter_id'] = matter_id
        if focused_at is not None and not omit_stamp:
            bx['tab_focused_at'] = (
                focused_at.isoformat().replace('+00:00', 'Z')
                if hasattr(focused_at, 'isoformat') else focused_at
            )
        self.ctx = {'browser_extension': bx} if bx else {}


if _ok:
    print("Clio anchor freshness:")

    # ── The anchor survives while Clio is genuinely on screen ──────────────
    check("anchor posted this instant is fresh",
          _fresh_clio_matter_id(_E(BASE, '12345', BASE)) == '12345')

    check("one missed 30s keepalive still counts as open",
          _fresh_clio_matter_id(
              _E(BASE, '12345', BASE - timedelta(seconds=45))) == '12345')

    check("right at the TTL boundary is still open",
          _fresh_clio_matter_id(
              _E(BASE, '12345',
                 BASE - timedelta(seconds=CLIO_ANCHOR_TTL_SECONDS))) == '12345')

    # ── The leak this change exists to close ──────────────────────────────
    check("one second past the TTL is refused",
          _fresh_clio_matter_id(
              _E(BASE, '12345',
                 BASE - timedelta(seconds=CLIO_ANCHOR_TTL_SECONDS + 1))) == '')

    check("THE BUG: morning Clio visit does not stamp afternoon Word work",
          _fresh_clio_matter_id(
              _E(BASE, '00001', BASE - timedelta(hours=5))) == '')

    # ── Refuse what cannot be verified ────────────────────────────────────
    check("anchor with no tab_focused_at is refused, not trusted",
          _fresh_clio_matter_id(_E(BASE, '12345', BASE, omit_stamp=True)) == '')

    check("unparseable tab_focused_at is refused",
          _fresh_clio_matter_id(_E(BASE, '12345', 'not-a-timestamp')) == '')

    check("empty tab_focused_at is refused",
          _fresh_clio_matter_id(_E(BASE, '12345', '')) == '')

    check("event with no usable timestamp is refused",
          _fresh_clio_matter_id(
              _E(None, '12345', BASE, start_ts=None)) == '')

    # ── Nothing to lift ───────────────────────────────────────────────────
    check("no anchor in ctx -> empty",
          _fresh_clio_matter_id(_E(BASE, None, BASE)) == '')

    check("no browser_extension ctx at all -> empty",
          _fresh_clio_matter_id(_E(BASE)) == '')

    check("blank anchor value -> empty",
          _fresh_clio_matter_id(_E(BASE, '   ', BASE)) == '')

    # ── Shape handling ────────────────────────────────────────────────────
    check("numeric matter id is coerced to string",
          _fresh_clio_matter_id(_E(BASE, 12345, BASE)) == '12345')

    check("context arriving mid-event is fresh, not stale",
          _fresh_clio_matter_id(
              _E(BASE, '12345', BASE + timedelta(seconds=5))) == '12345')

    check("falls back to start_ts when end_ts is absent",
          _fresh_clio_matter_id(
              _E(None, '12345', BASE, start_ts=BASE)) == '12345')

    check("a naive event timestamp is read as UTC, not crashed on",
          _fresh_clio_matter_id(
              _E(BASE.replace(tzinfo=None), '12345', BASE)) == '12345')

    # ── The QBO payload rides the same context; leave it alone ────────────
    check("QBO fields on the same ctx do not confuse the anchor",
          _fresh_clio_matter_id(
              _E(BASE, '12345', BASE,
                 extra={'qbo_company_id': '99', 'url': 'https://app.clio.com/'})) == '12345')

    # ── Timestamp parsing ─────────────────────────────────────────────────
    check("parses the extension's Z-suffixed ISO stamp",
          _parse_ctx_timestamp('2026-09-18T14:00:00.000Z') is not None)

    check("parses an offset-suffixed stamp",
          _parse_ctx_timestamp('2026-09-18T14:00:00+00:00') is not None)

    check("a naive stamp is assumed UTC rather than refused",
          _parse_ctx_timestamp('2026-09-18T14:00:00') is not None)

    check("None parses to None", _parse_ctx_timestamp(None) is None)

    check("garbage parses to None", _parse_ctx_timestamp('yesterday') is None)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
