"""Capture without Accessibility (and unchanged capture with it).

    python3 mac_agent/test_title_fallback.py

Drives main.capture_window — the function the tracking loop calls every
poll — with macOS stubbed out (via test_event_contract's stubs), once with
Accessibility untrusted and once trusted.
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import title_fallback as tf  # noqa: E402
import permissions as P  # noqa: E402
import doc_capture as dc  # noqa: E402


def _main():
    import test_event_contract as tec  # stubs AppKit/Quartz, redirects HOME
    return tec.main


class _Probes:
    def __init__(self, ax):
        self.ax = ax

    def ax_trusted(self):
        return self.ax

    def ax_prompt(self):
        return self.ax

    def installed(self, b):
        return False

    def running_path(self, b):
        return None

    def ae_status(self, b):
        return P.NOT_RUNNING

    def open_url(self, *a, **k):
        pass

    def tcc_reset_accessibility(self):
        return True


class Patched:
    """Swap main's OS-touching helpers for one test, restore after."""

    NAMES = ("osa", "get_window_title_via_ax", "get_window_document_via_ax",
             "_running_app_path", "_adobe_carry", "_adobe_backoff", "_spotlight",
             "PERMISSIONS", "AX_AVAILABLE")

    def __init__(self, main, ax, osa=None, ax_title=None):
        self.main = main
        self.saved = {n: getattr(main, n) for n in self.NAMES}
        self.scripts = []
        mon = P.PermissionMonitor(_Probes(ax), tempfile.mktemp(), log=lambda m: None)
        mon.refresh()
        main.PERMISSIONS = mon
        main.AX_AVAILABLE = True

        def fake_osa(script, bundle_id=None):
            self.scripts.append(script)
            return osa(script) if osa else ""
        main.osa = fake_osa
        main.get_window_title_via_ax = lambda pid: ax_title
        main.get_window_document_via_ax = lambda pid: None
        main._running_app_path = lambda pid: None
        main._adobe_carry = dc.DocCarryForward()
        main._adobe_backoff = dc.ScriptBackoff()
        main._spotlight = None
        main._CONTEXT.clear()
        main._CONTEXT_SEEN.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(self.main, n, v)
        self.main._CONTEXT.clear()
        self.main._CONTEXT_SEEN.clear()


SEP = tf.URL_TITLE_SEP


# ---------------------------------------------------------------- pure helpers

def test_extension_page_fresh_stale_and_wrong_app():
    e = {"source": "browser_extension", "url": "https://portal.acme.com/x",
         "title": "Acme — Invoices", "window_focused": True}
    now = 1000.0
    assert tf.extension_page(e, now - 5, "com.google.Chrome", now) == \
        {"title": "Acme — Invoices", "url": "https://portal.acme.com/x"}
    assert tf.extension_page(e, now - tf.EXTENSION_FRESH_S - 1, "com.google.Chrome", now) is None
    assert tf.extension_page(e, now - 5, "com.apple.Safari", now) is None, "no extension in Safari"
    assert tf.extension_page(e, now - 5, "com.tinyspeck.slackmacgap", now) is None
    assert tf.extension_page(None, now, "com.google.Chrome", now) is None


def test_split_and_basename():
    assert tf.split_url_title("https://a.b/c" + SEP + "Page") == ("https://a.b/c", "Page")
    assert tf.split_url_title("https://a.b/c") == ("https://a.b/c", None)
    assert tf.split_url_title("") == (None, None)
    assert tf.title_from_path("/Users/me/Clients/Acme/") == "Acme"
    assert tf.title_from_path(None) == ""


# ---------------------------------------------------------------- no Accessibility

def test_browser_title_from_applescript_without_ax():
    main = _main()
    with Patched(main, ax=False,
                 osa=lambda s: "https://portal.acme.com/x" + SEP + "Acme — Invoices") as p:
        title, url, fpath, mode = main.capture_window("com.google.Chrome", 42, None)
    assert mode == "no_accessibility"
    assert title == "Acme — Invoices" and url == "https://portal.acme.com/x"
    assert len(p.scripts) == 1, "URL and title in ONE osascript"
    assert "title of active tab" in p.scripts[0]


def test_browser_title_from_fresh_extension_without_ax():
    main = _main()
    with Patched(main, ax=False, osa=lambda s: "https://portal.acme.com/x") as p:
        main._CONTEXT["browser_extension"] = {
            "source": "browser_extension", "url": "https://portal.acme.com/x",
            "title": "Acme — Invoices", "window_focused": True}
        main._CONTEXT_SEEN["browser_extension"] = time.time()
        title, url, _, _ = main.capture_window("com.microsoft.edgemac", 42, None)
        assert title == "Acme — Invoices" and url == "https://portal.acme.com/x"
        assert "title of active tab" not in p.scripts[0], \
            "extension already gave the title: ask AppleScript for the URL only"


def test_browser_url_from_extension_when_automation_is_denied():
    main = _main()
    with Patched(main, ax=False, osa=lambda s: ""):
        main._CONTEXT["browser_extension"] = {"url": "https://portal.acme.com/x",
                                              "title": "Acme"}
        main._CONTEXT_SEEN["browser_extension"] = time.time()
        title, url, _, _ = main.capture_window("com.google.Chrome", 42, None)
    assert (title, url) == ("Acme", "https://portal.acme.com/x")


def test_photoshop_title_from_document_without_ax():
    main = _main()
    path = "/Users/a/Dropbox/D&F/D&F FB Cover Photo.psd"
    with Patched(main, ax=False, osa=lambda s: path):
        title, url, fpath, mode = main.capture_window("com.adobe.Photoshop", 7, None)
    assert mode == "no_accessibility"
    assert title == "D&F FB Cover Photo.psd" and fpath == path


def test_finder_title_from_its_target_without_ax():
    main = _main()
    with Patched(main, ax=False, osa=lambda s: "/Users/a/Clients/Acme Corp/"):
        title, _, fpath, _ = main.capture_window("com.apple.finder", 9, None)
    assert fpath == "/Users/a/Clients/Acme Corp"
    assert title == "Acme Corp"


def test_excel_title_from_workbook_without_ax():
    main = _main()
    with Patched(main, ax=False, osa=lambda s: "/Users/a/Clients/Acme/Q3 Budget.xlsx"):
        title, _, _, _ = main.capture_window("com.microsoft.Excel", 9, None)
    assert title == "Q3 Budget.xlsx"


def test_unscriptable_app_gets_empty_title_not_a_crash():
    main = _main()
    with Patched(main, ax=False) as p:
        title, url, fpath, mode = main.capture_window("com.tinyspeck.slackmacgap", 11, None)
    assert (title, url, fpath, mode) == ("", None, None, "no_accessibility")
    assert p.scripts == [], "no AppleScript for an app with no dictionary"


# ---------------------------------------------------------------- with Accessibility

def test_with_ax_behaviour_is_unchanged():
    main = _main()
    ax_title = "Feed | LinkedIn - Google Chrome - Dan"
    with Patched(main, ax=True, osa=lambda s: "https://www.linkedin.com/feed/",
                 ax_title=ax_title) as p:
        title, url, _, mode = main.capture_window("com.google.Chrome", 42, None)
        assert mode == "full"
        assert title == ax_title, "AX title, not the tab title"
        assert url == "https://www.linkedin.com/feed/"
        assert "title of active tab" not in p.scripts[0], "no extra AppleScript work"
        assert "-1743" in p.scripts[0], "denials are re-raised so they are visible"

        # A non-scriptable app with AX: AX title, zero AppleScript.
        p.scripts.clear()
        main.get_window_title_via_ax = lambda pid: "#general - Acme - Slack"
        title, _, _, _ = main.capture_window("com.tinyspeck.slackmacgap", 11, None)
        assert title == "#general - Acme - Slack" and p.scripts == []


def test_adobe_cleanup_still_applies_with_ax():
    main = _main()
    path = "/Users/a/Dropbox/D&F/D&F FB Cover Photo.psd"
    with Patched(main, ax=True, osa=lambda s: path,
                 ax_title="D&F FB Cover Photo.psd @ 95.4% (Layer 3, RGB/8) *"):
        title, _, fpath, _ = main.capture_window("com.adobe.Photoshop", 7, None)
        assert (title, fpath) == ("D&F FB Cover Photo.psd", path)
        # A dialog in front: carried forward, as before.
        main.get_window_title_via_ax = lambda pid: "JPEG Options"
        title, _, fpath, _ = main.capture_window("com.adobe.Photoshop", 7, None)
        assert (title, fpath) == ("D&F FB Cover Photo.psd", path)


# ---------------------------------------------------------------- -1743

def test_denied_osascript_is_recorded_for_the_checklist():
    main = _main()
    saved_run, saved_perm = main.subprocess.run, main.PERMISSIONS
    mon = P.PermissionMonitor(_Probes(True), tempfile.mktemp(), log=lambda m: None)
    main.PERMISSIONS = mon
    try:
        main.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(
            a, 1, "", "execution error: Not authorized to send Apple events to "
                      "Google Chrome. (-1743)")
        assert main.osa("tell app", bundle_id="com.google.Chrome") == ""
        assert mon.automation.get("com.google.Chrome") == P.DENIED
        main.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, "x\n", "")
        assert main.osa("tell app", bundle_id="com.google.Chrome") == "x"
        assert mon.automation.get("com.google.Chrome") == P.GRANTED
    finally:
        main.subprocess.run, main.PERMISSIONS = saved_run, saved_perm


def test_frontmost_detection_has_an_ax_free_path():
    """NSWorkspace needs no permission; System Events needs Automation of
    System Events only. Neither reads AX, so the right app and pid come
    through with Accessibility off."""
    main = _main()
    import inspect
    src = inspect.getsource(main.get_frontmost_app)
    assert "get_frontmost_via_nsworkspace" in src
    for fn in (main.get_frontmost_via_nsworkspace, main.get_frontmost_via_system_events):
        s = inspect.getsource(fn)
        assert "AXUIElement" not in s and "AXIsProcessTrusted" not in s


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_") and callable(globals()[n])]
    for name in names:
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:
            failures += 1
            import traceback
            traceback.print_exc()
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(names) - failures}/{len(names)} passed")
    sys.exit(1 if failures else 0)
