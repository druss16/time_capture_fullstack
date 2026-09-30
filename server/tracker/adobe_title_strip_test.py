"""
Adobe view state must never reach the client matcher, and must not fragment.

THE BUG, MEASURED ON A LIVE MAC (2026-09-30)
--------------------------------------------
Photoshop titles its document window with the zoom, the SELECTED LAYER, the
colour mode and an unsaved marker:

    "D&F FB Cover Photo.psd @ 95.4% (Layer 3, RGB/8) *"

Every zoom or layer click is a new title, so one file became dozens of events.
And a text layer's name is its text:

    "au text.psd @ 100% ( With over 15 years of experience in the beauty
     industry, Aurel, RGB/8) *"

which the matcher scored like any other title words. A layer that mentions
another client would have filed the block to that client.

As with the browser-chrome strips, the OVER-strip matters as much as the
under-strip: cases below that assert text SURVIVES are load-bearing.

Pure — no database, no Django settings:

    python server/tracker/adobe_title_strip_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = 0


def check(label, cond, extra=''):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label} {extra}")


import importlib.util  # noqa: E402

# Loaded straight off disk, like browser_chrome_strip_test.py: importing the
# `tracker.utils` package runs its __init__, which needs a configured Django.
_UTILS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_UTILS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


srv = _load("_srv_content_identity", "content_identity.py")
_clean_title = srv._clean_title
content_identity = srv.content_identity
normalize_ingested_title = srv.normalize_ingested_title
strip_adobe_view_state = srv.strip_adobe_view_state

print("Real Photoshop titles lose their view state:")
REAL = {
    "D&F FB Cover Photo.psd @ 95.4% (Layer 3, RGB/8) *": "D&F FB Cover Photo.psd",
    "D&F FB Cover Photo.psd @ 178% (Rectangle 1 copy, RGB/8) *": "D&F FB Cover Photo.psd",
    "D&F FB Cover Photo.psd @ 100% (RGB/8) * - Saving 10%": "D&F FB Cover Photo.psd",
    "Untitled-1 @ 66.7% (RGB/8)": "Untitled-1",
    "logo.PNG @ 100% (Layer 1, RGB/8#)": "logo.PNG",
    "aurelia-cutout.png @ 66.7% (Layer 1, Layer Mask/8)": "aurelia-cutout.png",
}
for raw, want in REAL.items():
    got = strip_adobe_view_state(raw)
    check(f"{raw[:48]!r}", got == want, f"got {got!r}")

LAYER_TEXT = ("au text.psd @ 100% ( With over 15 years of experience in the "
              "beauty industry, Aurel, RGB/8) *")
check("text-layer words are gone at ingestion",
      normalize_ingested_title(LAYER_TEXT, "com.adobe.Photoshop", "Adobe Photoshop 2026")
      == "au text.psd")
check("...and in content_identity's cleaner", "beauty" not in _clean_title(LAYER_TEXT))

print("Illustrator / InDesign shapes (documented, unverified live):")
check("Illustrator unsaved marker before @",
      strip_adobe_view_state("Logo.ai* @ 150 % (CMYK/Preview)") == "Logo.ai")
check("InDesign leading marker, no bracket",
      strip_adobe_view_state("*Brochure.indd @ 75%") == "Brochure.indd")

print("Ingestion gate:")
check("Mac bundle relaxes the gate",
      normalize_ingested_title("Q3 plan @ 100% (Layer 1, RGB/8)", "com.adobe.Photoshop")
      == "Q3 plan")
check("Windows exe relaxes the gate",
      normalize_ingested_title("Q3 plan @ 100% (Layer 1, RGB/8)", "Photoshop.exe")
      == "Q3 plan")
check("other apps keep a non-document title",
      normalize_ingested_title("Standup @ 100% (confirmed)", "com.google.Chrome")
      == "Standup @ 100% (confirmed)")
check("a subject line is untouched",
      normalize_ingested_title("Sale @ 50% off - Inbox", "com.apple.mail")
      == "Sale @ 50% off - Inbox")
check("empty stays empty", normalize_ingested_title("", "com.adobe.Photoshop") == "")
check("None stays empty", normalize_ingested_title(None) == "")
check("ordinary title untouched",
      normalize_ingested_title("St. Mary's Church - QuickBooks Desktop", "qbw.exe")
      == "St. Mary's Church - QuickBooks Desktop")

print("Identity is stable across zoom/layer changes:")
a = content_identity("Scan CCF06232026_0001.pdf @ 100% (Layer 1, RGB/8) *")
b = content_identity("Scan CCF06232026_0001.pdf @ 50% (Layer 2, RGB/8)")
check("same identity", a and a == b, f"{a!r} vs {b!r}")

print("Mirror: agent and server regexes are identical:")
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "mac_agent"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mac_content_identity", os.path.join(sys.path[0], "content_identity.py"))
    mac = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mac)
    check("_ADOBE_VIEW_STATE_RE", mac._ADOBE_VIEW_STATE_RE.pattern == srv._ADOBE_VIEW_STATE_RE.pattern)
    check("_ADOBE_DOC_EXT_RE", mac._ADOBE_DOC_EXT_RE.pattern == srv._ADOBE_DOC_EXT_RE.pattern)
except Exception as e:  # the agent tree may not be deployed beside the server
    print(f"  SKIP  mac_agent not importable here ({type(e).__name__})")

print("Matcher strips (need app imports):")
try:
    strip_app_chrome = _load("_srv_cnm", "client_name_match.py").strip_app_chrome
    out = strip_app_chrome(LAYER_TEXT)
    check("client_name_match.strip_app_chrome drops layer text",
          "beauty" not in out.lower() and "au text.psd" in out, repr(out))
    qb = "St. Patrick's Church  - QuickBooks Accountant Desktop *Plus* 2024"
    check("QuickBooks strip unchanged",
          "Plus" not in strip_app_chrome(qb) and "Patrick" in strip_app_chrome(qb))
except Exception as e:
    print(f"  SKIP  client_name_match unavailable ({type(e).__name__}: {e})")

print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    sys.exit(1)
