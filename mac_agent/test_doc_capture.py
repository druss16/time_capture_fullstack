"""Adobe document capture, dialog carry-forward and Spotlight path lookup.

Pure Python — no GUI, no AppleScript, no Spotlight. The real titles below were
read from the live agent log on a Mac running Photoshop 2026 and Acrobat Pro
(~/Library/ActivityAgent/agent.sqlite3, 2026-09-30).

    python3 mac_agent/test_doc_capture.py
    python3 -m pytest mac_agent/test_doc_capture.py -q
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import doc_capture as dc  # noqa: E402
from content_identity import (  # noqa: E402
    _clean_title,
    content_identity,
    strip_adobe_view_state,
)


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------

REAL_PHOTOSHOP_TITLES = {
    "D&F FB Cover Photo.psd @ 95.4% (Layer 3, RGB/8) *": "D&F FB Cover Photo.psd",
    "D&F FB Cover Photo.psd @ 178% (Rectangle 1 copy, RGB/8) *": "D&F FB Cover Photo.psd",
    "D&F FB Cover Photo.psd @ 100% (RGB/8)": "D&F FB Cover Photo.psd",
    "D&F FB Cover Photo.psd @ 100% (RGB/8) * - Saving 10%": "D&F FB Cover Photo.psd",
    "au text.psd @ 100% ( With over 15 years of experience in the beauty "
    "industry, Aurel, RGB/8) *": "au text.psd",
    "au text.psd @ 100% (OUR STORY, RGB/8) *": "au text.psd",
    "Untitled-1 @ 66.7% (RGB/8)": "Untitled-1",
    "logo.PNG @ 100% (Layer 1, RGB/8#)": "logo.PNG",
    "aurelia-cutout.png @ 66.7% (Layer 1, Layer Mask/8)": "aurelia-cutout.png",
    "aurelia-cutout.png @ 66.7% (Layer 1, RGB/8) - Saving 10%": "aurelia-cutout.png",
    "holiday gift.jpeg @ 836% (Layer 7, RGB/8#) *": "holiday gift.jpeg",
}


def test_real_photoshop_titles_lose_their_view_state():
    for raw, want in REAL_PHOTOSHOP_TITLES.items():
        assert strip_adobe_view_state(raw) == want, raw
        assert strip_adobe_view_state(raw, is_adobe=True) == want, raw


def test_zoom_and_layer_changes_collapse_to_one_signature():
    variants = [t for t in REAL_PHOTOSHOP_TITLES if t.startswith("D&F")]
    assert len({dc.normalize_adobe_title("photoshop", t) for t in variants}) == 1


def test_text_layer_words_never_reach_the_matcher():
    raw = ("au text.psd @ 100% ( With over 15 years of experience in the "
           "beauty industry, Aurel, RGB/8) *")
    for cleaned in (_clean_title(raw), dc.normalize_adobe_title("photoshop", raw)):
        assert "beauty" not in cleaned.lower()
        assert "experience" not in cleaned.lower()


def test_illustrator_and_indesign_shapes():
    # Not installed on the build Mac — shapes from Adobe's UI.
    assert strip_adobe_view_state("Logo.ai* @ 150 % (CMYK/Preview)") == "Logo.ai"
    assert strip_adobe_view_state("Logo.ai @ 66.67% (RGB/GPU Preview)") == "Logo.ai"
    assert strip_adobe_view_state("*Brochure.indd @ 75%") == "Brochure.indd"
    assert strip_adobe_view_state("Brochure.indd @ 75% [Converted]") == "Brochure.indd"
    assert strip_adobe_view_state("Brochure.indd @ 125,5 %") == "Brochure.indd"


def test_other_titles_are_left_alone():
    # "@ N%" not followed by a bracket or the end: a subject line.
    assert strip_adobe_view_state("Sale @ 50% off everything") == "Sale @ 50% off everything"
    # Right shape but no Adobe-looking document name and no Adobe app claimed.
    t = "Standup @ 100% (confirmed) - Google Calendar"
    assert strip_adobe_view_state(t) == t
    assert strip_adobe_view_state("Q3 goals @ 100% (team)") == "Q3 goals @ 100% (team)"
    # ...but from an Adobe app the name need not look like a file.
    assert strip_adobe_view_state("Q3 goals @ 100% (team)", is_adobe=True) == "Q3 goals"
    assert strip_adobe_view_state("") == ""
    assert strip_adobe_view_state("Inbox - dan@x.com") == "Inbox - dan@x.com"


def test_content_identity_of_a_photoshop_title_is_stable():
    a = content_identity("Scan CCF06232026_0001.pdf @ 100% (Layer 1, RGB/8) *")
    b = content_identity("Scan CCF06232026_0001.pdf @ 50% (Layer 2, RGB/8)")
    assert a and a == b


def test_after_effects_and_premiere_titles():
    t, p = dc.parse_project_title(
        "aftereffects",
        "Adobe After Effects 2026 - /Users/amy/Dropbox/ClientX/Promo.aep *")
    assert p == "/Users/amy/Dropbox/ClientX/Promo.aep"
    assert not t.endswith("*")
    t, p = dc.parse_project_title(
        "premiere", "Adobe Premiere Pro 2024 - /Users/amy/Dropbox/ClientY/Cut.prproj")
    assert p == "/Users/amy/Dropbox/ClientY/Cut.prproj"
    # Unsaved / relative / wrong extension: no path, never a guess.
    assert dc.parse_project_title("aftereffects",
                                  "Adobe After Effects 2026 - Untitled Project.aep *")[1] is None
    assert dc.parse_project_title("premiere",
                                  "Adobe Premiere Pro 2024 - /Users/a/x.aep")[1] is None
    assert dc.parse_project_title("aftereffects", "Render Queue") == ("Render Queue", None)
    assert dc.parse_project_title("aftereffects", "") == ("", None)


# ---------------------------------------------------------------------------
# Bundle ids
# ---------------------------------------------------------------------------

def test_bundle_id_prefix_matching():
    assert dc.adobe_kind("com.adobe.Photoshop") == "photoshop"
    assert dc.adobe_kind("com.adobe.AfterEffects") == "aftereffects"
    assert dc.adobe_kind("com.adobe.AfterEffects.application") == "aftereffects"
    assert dc.adobe_kind("com.adobe.AfterEffectsRenderEngine") == "ae_render"
    assert dc.adobe_kind("com.adobe.ame.application.23") == "media_encoder"
    assert dc.adobe_kind("com.adobe.ame.application.26") == "media_encoder"
    assert dc.adobe_kind("com.adobe.PremierePro.24") == "premiere"
    assert dc.adobe_kind("com.adobe.PremierePro") == "premiere"
    assert dc.adobe_kind("com.adobe.illustrator") == "illustrator"
    assert dc.adobe_kind("com.adobe.InDesign") == "indesign"
    assert dc.adobe_kind("com.adobe.Acrobat.Pro") == "acrobat"
    # Look-alikes are NOT matches.
    assert dc.adobe_kind("com.adobe.PhotoshopElements") is None
    assert dc.adobe_kind("com.adobe.acc.AdobeCreativeCloud") is None
    assert dc.adobe_kind("com.adobe.distiller") is None
    assert dc.adobe_kind("com.microsoft.Excel") is None
    assert dc.adobe_kind("") is None
    assert dc.adobe_kind(None) is None


def test_background_render_tools_are_not_documents():
    assert "media_encoder" in dc.BACKGROUND_KINDS
    assert "ae_render" in dc.BACKGROUND_KINDS
    assert not (dc.BACKGROUND_KINDS & dc.SCRIPTABLE_KINDS)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

def test_photoshop_dialogs_and_home_screen():
    for t in ("Save As", "JPEG Options", "Save a Copy", "New Document",
              "Export As", "Image Size", "Layer Style", "Smart Sharpen",
              "Color Picker (Foreground Color)", "Create Rectangle",
              "PNG Format Options", "Photoshop Format Options", "Progress",
              "Match Font"):
        assert dc.classify_adobe_title("photoshop", t) == "dialog", t
    assert dc.classify_adobe_title("photoshop", "Adobe Photoshop 2026") == "home"
    assert dc.classify_adobe_title("photoshop", "Adobe Photoshop") == "home"
    assert dc.classify_adobe_title("photoshop", "") == "empty"
    for t in REAL_PHOTOSHOP_TITLES:
        assert dc.classify_adobe_title("photoshop", t) == "doc", t


def test_acrobat_dialogs():
    assert dc.classify_adobe_title("acrobat", "Print") == "dialog"
    assert dc.classify_adobe_title("acrobat", "Page Setup") == "dialog"
    assert dc.classify_adobe_title("acrobat", "Adobe Acrobat") == "home"
    assert dc.classify_adobe_title("acrobat", "GrowU_EIN_Doc.pdf") == "doc"
    assert dc.classify_adobe_title(
        "acrobat", "Website Development Proposal - Aurelia") == "doc"


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_dialog_carries_the_last_document():
    clk = Clock()
    cf = dc.DocCarryForward(ttl=180, clock=clk)
    bid = "com.adobe.Photoshop"
    doc = ("D&F FB Cover Photo.psd", "/Users/a/Dropbox/D&F/D&F FB Cover Photo.psd")
    assert cf.apply(bid, "doc", *doc) == (doc[0], doc[1], False)
    clk.t += 20
    assert cf.apply(bid, "dialog", "JPEG Options", None) == (doc[0], doc[1], True)
    assert cf.apply(bid, "empty", "", None) == (doc[0], doc[1], True)


def test_carry_forward_expires_and_home_forgets():
    clk = Clock()
    cf = dc.DocCarryForward(ttl=180, clock=clk)
    bid = "com.adobe.Photoshop"
    cf.apply(bid, "doc", "a.psd", "/x/a.psd")
    clk.t += 181
    assert cf.apply(bid, "dialog", "Save As", None) == ("Save As", None, False)
    cf.apply(bid, "doc", "a.psd", "/x/a.psd")
    cf.apply(bid, "home", "Adobe Photoshop 2026", None)
    assert cf.apply(bid, "dialog", "Save As", None) == ("Save As", None, False)


def test_carry_forward_is_per_bundle():
    cf = dc.DocCarryForward(clock=Clock())
    cf.apply("com.adobe.Photoshop", "doc", "a.psd", "/x/a.psd")
    assert cf.apply("com.adobe.Acrobat.Pro", "dialog", "Print", None) == ("Print", None, False)


def test_a_path_from_the_app_beats_the_memory():
    cf = dc.DocCarryForward(clock=Clock())
    bid = "com.adobe.Photoshop"
    cf.apply(bid, "doc", "a.psd", "/x/ClientA/a.psd")
    # The script answered during the dialog with a DIFFERENT document.
    assert cf.apply(bid, "dialog", "Save As", "/x/ClientB/b.psd") == \
        ("b.psd", "/x/ClientB/b.psd", True)
    # Same document: keep the remembered (clean) title.
    cf.apply(bid, "doc", "Cover.psd", "/x/ClientA/Cover.psd")
    assert cf.apply(bid, "dialog", "Save As", "/x/ClientA/Cover.psd") == \
        ("Cover.psd", "/x/ClientA/Cover.psd", True)


# ---------------------------------------------------------------------------
# AppleScript targeting + backoff
# ---------------------------------------------------------------------------

def test_script_targets_the_running_copy():
    s = dc.adobe_path_script("photoshop", "com.adobe.Photoshop",
                             "/Applications/Adobe Photoshop 2026/Adobe Photoshop 2026.app")
    assert 'tell application "/Applications/Adobe Photoshop 2026/Adobe Photoshop 2026.app"' in s
    assert "with timeout of 2 seconds" in s
    assert 'on error\nreturn ""' in s
    assert "as alias" in s
    s = dc.adobe_path_script("acrobat", "com.adobe.Acrobat.Pro", None)
    assert 'tell application id "com.adobe.Acrobat.Pro"' in s
    assert dc.adobe_path_script("aftereffects", "com.adobe.AfterEffects", None) is None
    assert dc.adobe_path_script("media_encoder", "com.adobe.ame.application.26", None) is None


def test_script_app_path_is_escaped():
    ref = dc.applescript_app_ref("x", '/Apps/We"ird\\Name.app')
    assert ref == 'application "/Apps/We\\"ird\\\\Name.app"'


def test_slow_app_is_benched():
    clk = Clock()
    b = dc.ScriptBackoff(slow_after=1.5, bench_for=60, clock=clk)
    b.record(42, 0.3)
    assert not b.blocked(42)
    b.record(42, 2.1)
    assert b.blocked(42)
    assert not b.blocked(43)
    clk.t += 61
    assert not b.blocked(42)


# ---------------------------------------------------------------------------
# AXDocument
# ---------------------------------------------------------------------------

def test_axdocument_urls():
    assert dc.file_url_to_path(
        "file:///Users/a/Dropbox/Client%20X/Cover%20Photo.psd") == \
        "/Users/a/Dropbox/Client X/Cover Photo.psd"
    assert dc.file_url_to_path("file:///Users/a/Folder/") == "/Users/a/Folder"
    assert dc.file_url_to_path("/Users/a/b.pdf") == "/Users/a/b.pdf"
    assert dc.file_url_to_path("https://example.com/a.pdf") is None
    assert dc.file_url_to_path("") is None
    assert dc.file_url_to_path(None) is None

    class NSURLish:
        def __init__(self, p, f):
            self._p, self._f = p, f

        def path(self):
            return self._p

        def isFileURL(self):
            return self._f

    assert dc.file_url_to_path(NSURLish("/x/y.psd", True)) == "/x/y.psd"
    assert dc.file_url_to_path(NSURLish("/x", False)) is None


# ---------------------------------------------------------------------------
# Spotlight
# ---------------------------------------------------------------------------

def test_filename_extraction():
    assert dc.extract_filename("D&F FB Cover Photo.psd") == "D&F FB Cover Photo.psd"
    assert dc.extract_filename("Report 2024.pdf — Edited") == "Report 2024.pdf"
    assert dc.extract_filename("*Brochure.indd") == "Brochure.indd"
    assert dc.extract_filename("GrowU_EIN_Doc.pdf") == "GrowU_EIN_Doc.pdf"
    assert dc.extract_filename("Website Development Proposal - Aurelia") is None
    assert dc.extract_filename("Untitled-1") is None
    assert dc.extract_filename("main.py — repo") is None      # code: not resolved
    assert dc.extract_filename("Re: see attached invoice.pdf") is None  # not at start
    assert dc.extract_filename(".psd") is None
    assert dc.extract_filename("") is None


def test_mdquery_escaping():
    assert dc.mdquery_escape("Cover Photo.psd") == "Cover Photo.psd"
    assert dc.mdquery_escape('He said "hi".pdf') == 'He said \\"hi\\".pdf'
    assert dc.mdquery_escape("back\\slash.pdf") == "back\\\\slash.pdf"
    # Wildcards must be literal, or an exact lookup becomes a pattern search.
    assert dc.mdquery_escape("50*off?.psd") == "50\\*off\\?.psd"
    assert dc.mdquery_escape("D&F (v2) [final].psd") == "D&F (v2) [final].psd"


class FakeRunner:
    """Stands in for subprocess.run for mdfind / mdls / lsof."""

    def __init__(self, mdfind_out="", mdls=None, open_files=None, raise_timeout=False):
        self.mdfind_out = mdfind_out
        self.mdls = mdls or {}
        self.open_files = open_files or {}   # pid -> [paths]
        self.raise_timeout = raise_timeout
        self.calls = []

    def __call__(self, cmd, capture_output=True, text=True, timeout=None):
        self.calls.append(cmd)
        assert timeout is not None and timeout <= 1.0, "every call needs a hard timeout"
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if cmd[0] == "mdfind":
            return subprocess.CompletedProcess(cmd, 0, self.mdfind_out, "")
        if cmd[0] == "mdls":
            paths = cmd[4:]
            return subprocess.CompletedProcess(
                cmd, 0, "\0".join(self.mdls.get(p, "(null)") for p in paths), "")
        if cmd[0] == "lsof":
            pid = int(cmd[cmd.index("-p") + 1])
            out = "p%d\nfcwd\nn/\n" % pid + "".join(
                f"f{i}\nn{p}\n" for i, p in enumerate(self.open_files.get(pid, [])))
            return subprocess.CompletedProcess(cmd, 0, out, "")
        raise AssertionError(cmd)


def _md(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")


ROOTS = lambda: ["/Users/a/Library/CloudStorage/Dropbox", "/Users/a/Documents"]  # noqa: E731
NOW = 1_800_000_000.0
A = "/Users/a/Library/CloudStorage/Dropbox/ClientA/Banner.psd"
B = "/Users/a/Library/CloudStorage/Dropbox/ClientB/Banner.psd"


def test_query_is_scoped_escaped_and_case_sensitive():
    p = "/Users/a/Library/CloudStorage/Dropbox/ClientX/Cover*.psd"
    run = FakeRunner(p + "\n", open_files={7: [p]})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Cover*.psd", pid=7) == p
    cmd = run.calls[0]
    assert cmd.count("-onlyin") == 2
    # Escaped wildcard, and NO `c` modifier: the match is case-sensitive.
    assert cmd[-1] == 'kMDItemFSName == "Cover\\*.psd"'


def test_a_different_case_is_a_different_file():
    # The live case: title "pepsi logo.psd", only "Pepsi Logo.psd" indexed.
    other = "/Users/a/Desktop/Pepsi/Pepsi Logo.psd"
    run = FakeRunner(other + "\n", open_files={7: [other]},
                     mdls={other: _md(NOW - 30)})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("pepsi logo.psd", pid=7) is None
    assert sr.last_outcome["pepsi logo.psd"] == "miss"


def test_a_single_match_alone_is_not_enough():
    # One indexed file of that name, but nothing says it is the one in use:
    # the index can miss the real file.
    run = FakeRunner(A + "\n", mdls={A: _md(NOW - 3 * 86400)})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd", pid=7) is None
    assert sr.last_outcome["Banner.psd"] == "unconfirmed"


def test_single_match_confirmed_by_recent_use():
    run = FakeRunner(A + "\n", mdls={A: _md(NOW - 120)})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd", pid=None) == A


def test_single_match_confirmed_by_the_app_holding_it_open():
    run = FakeRunner(A + "\n", open_files={7: [A]})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd", pid=7) == A


def test_open_file_via_private_prefix_counts():
    # lsof reports /private/tmp/... for a file Spotlight lists as /tmp/...
    p = "/tmp/x/ClientX/Banner.psd"
    run = FakeRunner(p + "\n", open_files={7: ["/private" + p]})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd", pid=7) == p


def test_open_by_ANOTHER_process_does_not_count():
    run = FakeRunner(A + "\n", open_files={99: [A]})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd", pid=7) is None


def test_multiple_matches_take_the_only_confirmed_one():
    run = FakeRunner(f"{A}\n{B}\n", open_files={7: [B]})
    assert dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW)) \
        .resolve_now("Banner.psd", pid=7) == B
    run = FakeRunner(f"{A}\n{B}\n", mdls={A: _md(NOW - 86400), B: _md(NOW - 60)})
    assert dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW)) \
        .resolve_now("Banner.psd") == B


def test_multiple_matches_abstain_when_in_doubt():
    # Both confirmed.
    run = FakeRunner(f"{A}\n{B}\n", mdls={A: _md(NOW - 30), B: _md(NOW - 60)})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd") is None
    assert sr.last_outcome["Banner.psd"] == "ambiguous"
    # Neither confirmed (what this Mac's Spotlight reported for its files).
    run = FakeRunner(f"{A}\n{B}\n")
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd", pid=7) is None
    assert sr.last_outcome["Banner.psd"] == "unconfirmed"


def test_unconfirmed_is_rechecked_soon_but_misses_are_cached():
    clk = Clock(NOW)
    run = FakeRunner(A + "\n")
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=clk, unconfirmed_ttl=30)
    assert sr.lookup("Banner.psd", pid=7, wait=1.0) is None
    n = len(run.calls)
    assert sr.lookup("Banner.psd", pid=7, wait=1.0) is None
    assert len(run.calls) == n, "cached within the TTL"
    clk.t += 31
    run.open_files = {7: [A]}   # the user has now opened it
    assert sr.lookup("Banner.psd", pid=7, wait=1.0) == A

    run = FakeRunner("")
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW), miss_ttl=300)
    sr.lookup("Nope.psd", wait=1.0)
    sr.lookup("Nope.psd", wait=1.0)
    assert len(run.calls) == 1


def test_near_names_and_hidden_copies_do_not_count():
    a = "/Users/a/Documents/ClientA/Banner.psd"
    run = FakeRunner(
        f"{a}\n/Users/a/Documents/ClientB/Banner.psd.bak\n"
        "/Users/a/Library/CloudStorage/Dropbox/.dropbox.cache/Banner.psd\n",
        mdls={a: _md(NOW - 10)})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now("Banner.psd") == a


def test_unicode_normalization_does_not_block_a_match():
    import unicodedata
    nfd = unicodedata.normalize("NFD", "Café Menu.pdf")
    p = "/Users/a/Documents/Cafe Co/" + nfd
    run = FakeRunner(p + "\n", mdls={p: _md(NOW - 10)})
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
    assert sr.resolve_now(unicodedata.normalize("NFC", "Café Menu.pdf")) == p


def test_timeout_abstains_and_retries_soon():
    clk = Clock()
    run = FakeRunner(raise_timeout=True)
    sr = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=clk, error_ttl=30)
    assert sr.resolve_now("Cover.psd") is None
    assert sr.last_outcome["Cover.psd"] == "timeout"
    clk.t += 31
    assert sr.cached("Cover.psd") == (False, None)


def test_lookup_never_waits_long():
    def slow(cmd, **kw):
        time.sleep(0.6)
        if cmd[0] == "mdfind":
            return subprocess.CompletedProcess(cmd, 0, "/Users/a/Documents/x/Slow.psd\n", "")
        if cmd[0] == "lsof":
            return subprocess.CompletedProcess(cmd, 0, "n/Users/a/Documents/x/Slow.psd\n", "")
        return subprocess.CompletedProcess(cmd, 0, "(null)", "")
    sr = dc.SpotlightResolver(roots=ROOTS, runner=slow)
    t0 = time.time()
    assert sr.lookup("Slow.psd", pid=7, wait=0.1) is None
    assert time.time() - t0 < 0.4
    time.sleep(2.2)
    assert sr.lookup("Slow.psd", pid=7, wait=0) == "/Users/a/Documents/x/Slow.psd"


def test_no_roots_no_query():
    run = FakeRunner("/x/a.psd\n")
    sr = dc.SpotlightResolver(roots=lambda: [], runner=run, clock=Clock())
    assert sr.resolve_now("a.psd") is None
    assert run.calls == []


def test_path_source_registry():
    dc.remember_path_source("/x/a.psd", "spotlight")
    assert dc.path_source("/x/a.psd") == "spotlight"
    dc.remember_path_source("/x/a.psd", "applescript")
    assert dc.path_source("/x/a.psd") == "applescript"
    assert dc.path_source(None) is None
    assert dc.path_source("/never/seen") is None


# ---------------------------------------------------------------------------
# Through main.try_get_url_or_path, with macOS stubbed out
# ---------------------------------------------------------------------------

def _main():
    import test_event_contract as tec  # stubs AppKit/Quartz and redirects HOME
    return tec.main


def test_photoshop_through_the_capture_path():
    main = _main()
    calls = []
    saved = (main.osa, main.get_window_document_via_ax, main._running_app_path,
             main._adobe_carry, main._adobe_backoff)
    try:
        main.osa = lambda s: calls.append(s) or "/Users/a/Dropbox/D&F/D&F FB Cover Photo.psd"
        main.get_window_document_via_ax = lambda pid: None
        main._running_app_path = lambda pid: "/Applications/Adobe Photoshop 2026/Adobe Photoshop 2026.app"
        main._adobe_carry = dc.DocCarryForward()
        main._adobe_backoff = dc.ScriptBackoff()

        r = main.try_get_url_or_path(
            "com.adobe.Photoshop", pid=7,
            title="D&F FB Cover Photo.psd @ 95.4% (Layer 3, RGB/8) *")
        assert r["title"] == "D&F FB Cover Photo.psd"
        assert r["file_path"] == "/Users/a/Dropbox/D&F/D&F FB Cover Photo.psd"
        assert dc.path_source(r["file_path"]) == "applescript"
        assert len(calls) == 1

        # A dialog: no AppleEvent at all, the document is carried.
        r = main.try_get_url_or_path("com.adobe.Photoshop", pid=7, title="JPEG Options")
        assert r["title"] == "D&F FB Cover Photo.psd"
        assert r["file_path"] == "/Users/a/Dropbox/D&F/D&F FB Cover Photo.psd"
        assert len(calls) == 1, "must not script an app that is showing a dialog"

        # Media Encoder in front: nothing asked, nothing invented.
        r = main.try_get_url_or_path("com.adobe.ame.application.26", pid=8, title="Queue")
        assert r == {"url": None, "file_path": None, "title": "Queue"}
        assert len(calls) == 1
    finally:
        (main.osa, main.get_window_document_via_ax, main._running_app_path,
         main._adobe_carry, main._adobe_backoff) = saved


def test_unknown_app_falls_back_to_axdocument_then_spotlight():
    main = _main()
    saved = (main.get_window_document_via_ax, main._spotlight)
    try:
        main.get_window_document_via_ax = lambda pid: "/Users/a/Docs/Plan.key"
        r = main.try_get_url_or_path("com.example.editor", pid=9, title="Plan.key")
        assert r["file_path"] == "/Users/a/Docs/Plan.key"
        assert dc.path_source("/Users/a/Docs/Plan.key") == "axdocument"

        main.get_window_document_via_ax = lambda pid: None
        est = "/Users/a/Documents/ClientZ/Estimate.pdf"
        run = FakeRunner(est + "\n", open_files={9: [est]})
        main._spotlight = dc.SpotlightResolver(roots=ROOTS, runner=run, clock=Clock(NOW))
        r = main.try_get_url_or_path("com.example.viewer", pid=9, title="Estimate.pdf")
        assert r["file_path"] == "/Users/a/Documents/ClientZ/Estimate.pdf"
        assert dc.path_source(r["file_path"]) == "spotlight"

        # Browsers never take either fallback.
        run.calls.clear()
        r = main.try_get_url_or_path("org.mozilla.firefox", pid=9, title="Estimate.pdf")
        assert r["file_path"] is None and run.calls == []
    finally:
        main.get_window_document_via_ax, main._spotlight = saved


def test_payload_says_where_the_path_came_from():
    main = _main()
    import test_event_contract as tec
    path = "/Users/a/Documents/ClientZ/Estimate.pdf"
    dc.remember_path_source(path, "spotlight")
    now = time.time()
    captured, _ = tec._emit(now - 60, now, sig=(
        "Preview", "com.apple.Preview", "Estimate.pdf", None, path))
    assert captured[0]["ctx"].get("file_path_source") == "spotlight"
    ok, reason = tec._server_would_accept(captured[0])
    assert ok, reason


# ---------------------------------------------------------------------------
# Bundle id fallback (NSRunningApplication intermittently answers nil)
# ---------------------------------------------------------------------------

def _fake_bundle(root, name, bid, nested_in=None):
    import plistlib
    base = os.path.join(nested_in or root, name)
    os.makedirs(os.path.join(base, "Contents", "MacOS"), exist_ok=True)
    if bid is not None:
        with open(os.path.join(base, "Contents", "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleIdentifier": bid}, f)
    exe = os.path.join(base, "Contents", "MacOS", name.split(".")[0])
    open(exe, "w").close()
    return base, exe


def test_bundle_id_read_from_the_executables_info_plist():
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        app, exe = _fake_bundle(root, "Adobe Photoshop 2026.app", "com.adobe.Photoshop")
        assert dc.app_bundle_for_executable(exe) == ("com.adobe.Photoshop", app)


def test_chrome_code_sign_clone_bundle_is_recognised():
    # Chrome relaunches from ".../Google Chrome.app.bundle/Contents/MacOS/..."
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        app, exe = _fake_bundle(root, "Google Chrome.app.bundle", "com.google.Chrome")
        assert dc.app_bundle_for_executable(exe) == ("com.google.Chrome", app)


def test_nested_helper_reports_its_own_bundle():
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        outer, _ = _fake_bundle(root, "Host.app", "com.example.host")
        helper, exe = _fake_bundle(root, "Helper.app", "com.example.helper",
                                   nested_in=os.path.join(outer, "Contents", "Frameworks"))
        assert dc.app_bundle_for_executable(exe) == ("com.example.helper", helper)


def test_non_bundle_executables_and_missing_ids_give_nothing():
    import tempfile
    assert dc.app_bundle_for_executable(None) == ("", "")
    assert dc.app_bundle_for_executable("/usr/bin/python3") == ("", "")
    with tempfile.TemporaryDirectory() as root:
        _, exe = _fake_bundle(root, "NoId.app", None)
        assert dc.app_bundle_for_executable(exe) == ("", "")


def test_bundle_cache_is_revalidated_when_a_pid_is_recycled():
    import tempfile
    dc._BUNDLE_CACHE.clear()
    with tempfile.TemporaryDirectory() as root:
        _, exe_a = _fake_bundle(root, "A.app", "com.example.a")
        _, exe_b = _fake_bundle(root, "B.app", "com.example.b")
        current = {"exe": exe_a}
        lookup = lambda pid: current["exe"]
        assert dc.bundle_info_for_pid(4242, lookup)[0] == "com.example.a"
        current["exe"] = exe_b          # same pid, different process
        assert dc.bundle_info_for_pid(4242, lookup)[0] == "com.example.b"
        current["exe"] = None           # process gone
        assert dc.bundle_info_for_pid(4242, lookup) == ("", "")
    dc._BUNDLE_CACHE.clear()


def test_bundle_info_for_this_python_process_does_not_raise():
    # Live syscall: whatever python this is, the call must answer, not throw.
    bid, app = dc.bundle_info_for_pid(os.getpid())
    assert isinstance(bid, str) and isinstance(app, str)


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
