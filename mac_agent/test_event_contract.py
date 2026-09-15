"""Does the Mac agent emit an event the server will accept?

tracker/views.raw_events has required BOTH start_ts and end_ts since
v1.3.38 and returns 400 for anything else — "TL Wall is beta — no compat
path", in its own words. The Mac agent was still sending the single-ts_utc
shape it has sent since April, so every event it posted was rejected.

This test builds a payload with the real write_event() and replays the
server's validation against it. It stubs the macOS frameworks so it runs
in a plain interpreter, on any machine, with no GUI and no network.

    python3 mac_agent/test_event_contract.py
    python3 -m pytest mac_agent/test_event_contract.py -q
"""
import os
import sqlite3
import sys
import time
import types
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


def _install_stubs():
    """Stand in for the frameworks main.py imports at module scope."""
    _stub("Quartz",
          CGWindowListCopyWindowInfo=lambda *a: [],
          kCGWindowListOptionOnScreenOnly=0,
          kCGWindowListOptionOnScreenAboveWindow=0,
          kCGNullWindowID=0,
          CGEventSourceSecondsSinceLastEventType=lambda *a: 0.0,
          kCGEventSourceStateCombinedSessionState=0,
          kCGEventMouseMoved=0, kCGEventKeyDown=0, kCGEventScrollWheel=0)
    _stub("timetracker_gui", run_gui_app=lambda **k: None,
          show_pairing_window=lambda *a, **k: None, GUI_AVAILABLE=False)
    _stub("quick_switcher", QuickSwitcher=object,
          start_hotkey_listener=lambda *a, **k: None,
          stop_hotkey_listener=lambda *a, **k: None)
    _stub("certifi", where=lambda: "/etc/ssl/cert.pem")
    _stub("objc")
    _stub("Foundation", NSObject=object, NSLog=lambda *a: None)
    _stub("UserNotifications")
    _stub("AppKit", NSWorkspace=object, NSApplication=object,
          NSRunningApplication=object, NSWorkspaceApplicationKey=0)


_install_stubs()
import main  # noqa: E402


SIG = ("Microsoft Excel", "com.microsoft.Excel",
       "Varacchi 2024 1040.xlsx - Excel", None,
       "/Users/dan/Clients/Varacchi/2024 1040.xlsx")


def _fresh_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE raw_events (id INTEGER PRIMARY KEY, ts_utc TEXT, "
        "app_name TEXT, bundle_id TEXT, window_title TEXT, url TEXT, "
        "file_path TEXT, user TEXT, hostname TEXT)"
    )
    return conn, cur


def _emit(start_ts, end_ts, sig=SIG):
    """Run the real write_event and return the payload it tried to POST."""
    captured = []
    original = main.post_event_async
    main.post_event_async = lambda payload, user, host: captured.append(payload)
    try:
        conn, cur = _fresh_db()
        main.write_event(conn, cur, "dan", "macbook", sig,
                         start_ts=start_ts, end_ts=end_ts)
        rows = cur.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        conn.close()
    finally:
        main.post_event_async = original
    return captured, rows


def _server_would_accept(item):
    """tracker/views.py raw_events, transcribed. Returns (ok, reason)."""
    start_raw = item.get("start_ts")
    end_raw = item.get("end_ts")
    if not start_raw or not end_raw:
        return False, "Missing start_ts or end_ts (v1.3.38 requires both)"
    try:
        start_dt = datetime.fromisoformat(start_raw)
        end_dt = datetime.fromisoformat(end_raw)
    except (TypeError, ValueError):
        return False, "Invalid start_ts/end_ts format"
    if end_dt <= start_dt:
        return False, "end_ts must be > start_ts"
    return True, ""


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------

def test_payload_passes_server_validation():
    now = time.time()
    captured, _ = _emit(now - 60, now)
    assert len(captured) == 1, "write_event did not emit"
    ok, reason = _server_would_accept(captured[0])
    assert ok, f"server would reject this event: {reason}"


def test_old_single_timestamp_shape_is_gone():
    """The shape the server rejects must not be what we send."""
    now = time.time()
    captured, _ = _emit(now - 60, now)
    payload = captured[0]
    assert "ts_utc" not in payload, (
        "payload still carries ts_utc — that is the rejected shape"
    )
    ok, _ = _server_would_accept({"ts_utc": payload["start_ts"]})
    assert not ok, "the validation transcription is wrong; it accepts ts_utc"


def test_interval_is_the_one_we_asked_for():
    now = time.time()
    captured, _ = _emit(now - 300, now)
    p = captured[0]
    span = (datetime.fromisoformat(p["end_ts"])
            - datetime.fromisoformat(p["start_ts"])).total_seconds()
    assert abs(span - 300) < 1.0, f"interval was {span}s, expected 300s"


def test_classifier_fields_are_present():
    """Fields the server-side classifier reads off RawEvent."""
    now = time.time()
    captured, _ = _emit(now - 60, now)
    p = captured[0]
    for field in ("agent_version", "inference", "content_identity",
                  "app_name", "bundle_id", "window_title", "file_path",
                  "hostname", "device_id", "ctx"):
        assert field in p, f"payload is missing {field}"
    assert p["agent_version"], "agent_version must not be empty"


def test_content_identity_reads_the_file():
    """Same contract as tracker/utils/content_identity.py: a string."""
    now = time.time()
    captured, _ = _emit(now - 60, now)
    ident = captured[0]["content_identity"]
    assert isinstance(ident, str), f"content_identity is {type(ident)}"
    assert ident == "file=2024 1040", (
        f"expected the POSIX basename identity, got {ident!r}"
    )


def test_content_identity_survives_a_titleless_window():
    now = time.time()
    sig = ("Finder", "com.apple.finder", "", None, None)
    captured, _ = _emit(now - 60, now, sig=sig)
    assert captured[0]["content_identity"] == "", (
        "a window with nothing to identify should yield the empty identity"
    )


def test_backwards_interval_is_refused_not_sent():
    """An inverted interval is dropped here, not bounced by the server."""
    now = time.time()
    captured, rows = _emit(now, now - 60)
    assert captured == [], "an end-before-start event was sent to the server"
    assert rows == 0, "an end-before-start event was written to SQLite"


def test_local_write_happens_even_when_post_fails():
    """Offline capture must not depend on the POST succeeding."""
    def boom(*a, **k):
        raise RuntimeError("network down")

    original = main.post_event_async
    main.post_event_async = boom
    try:
        conn, cur = _fresh_db()
        now = time.time()
        try:
            main.write_event(conn, cur, "dan", "macbook", SIG,
                             start_ts=now - 60, end_ts=now)
        except RuntimeError:
            pass  # the POST is what failed; the row is what we check
        rows = cur.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        conn.close()
    finally:
        main.post_event_async = original
    assert rows == 1, "the local SQLite row was lost when the POST failed"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    total = len([n for n in globals() if n.startswith("test_")])
    print(f"\n{total - failures}/{total} passed")
    sys.exit(1 if failures else 0)
