"""Window titles without Accessibility.

Accessibility is the only way to read an arbitrary app's window title, but it
is not the only way to know what someone is working on. Without it:

* Browsers: the TimeTracker extension posts the active tab's title and URL to
  the local context bus (main.py, 127.0.0.1:7321) — use it while fresh. Else
  AppleScript asks the browser for the tab's URL AND title in one call
  (Automation only, no Accessibility).
* Adobe, Office, iWork, Preview, TextEdit, Finder: the agent already asks
  these apps over AppleScript for the document's path; its file name is the
  title. (Adobe needs nothing new: an empty title is classified "empty", the
  path script runs, and DocCarryForward reports the file's basename — the
  same cleanup and dialog carry-forward as with Accessibility.)
* Everything else (Slack desktop, Figma, Canva...): empty title, app name
  still recorded. That is the honest gap Accessibility closes.

With Accessibility trusted NOTHING here runs: titles come from AX exactly as
before, and no AppleScript is added for apps AX already covers.

Pure functions; main.py wires them in. Tested in test_title_fallback.py.
"""
from __future__ import annotations

import os
import time
from typing import Dict, Optional

# A post this old no longer describes the front tab. The extension posts on
# every tab switch / navigation and re-posts about every 30s.
EXTENSION_FRESH_S = 45.0

# Browsers the extension runs in (Safari has none).
EXTENSION_BROWSERS = frozenset({
    "com.google.Chrome", "com.google.Chrome.beta", "com.google.Chrome.canary",
    "com.microsoft.edgemac", "com.microsoft.edgemac.Beta",
    "com.brave.Browser", "company.thebrowser.Browser", "com.vivaldi.Vivaldi",
})

# Apps whose AppleScript path (main._DOC_PATH_SCRIPTS / finder) names the
# document; its basename stands in for the title.
TITLE_FROM_PATH_BUNDLES = frozenset({
    "com.microsoft.Excel", "com.microsoft.Word", "com.microsoft.Powerpoint",
    "com.apple.iWork.Numbers", "com.apple.iWork.Pages", "com.apple.iWork.Keynote",
    "com.apple.Preview", "com.apple.TextEdit", "com.apple.finder",
})

# Separator between URL and title when one browser script returns both. A
# control character no URL or page title contains.
URL_TITLE_SEP = "\x1f"


def extension_page(entry: Optional[dict], received_at: Optional[float],
                   bundle_id: str, now: Optional[float] = None) -> Optional[Dict[str, Optional[str]]]:
    """The extension's view of the front tab, if it is about THIS browser
    and fresh. {"title", "url"} or None."""
    if bundle_id not in EXTENSION_BROWSERS or not entry or not received_at:
        return None
    now = time.time() if now is None else now
    if now - received_at > EXTENSION_FRESH_S:
        return None
    if entry.get("window_focused") is False:
        return None
    title = (entry.get("title") or "").strip()
    url = (entry.get("url") or "").strip() or None
    if not title and not url:
        return None
    return {"title": title, "url": url}


def split_url_title(out: str) -> (Optional[str], Optional[str]):
    """Parse a browser script that returned "url<SEP>title"."""
    if not out:
        return None, None
    if URL_TITLE_SEP in out:
        url, title = out.split(URL_TITLE_SEP, 1)
        return (url.strip() or None), (title.strip() or None)
    return (out.strip() or None), None


def title_from_path(path: Optional[str]) -> str:
    """'/Users/me/Clients/Acme/Q3 Budget.xlsx' -> 'Q3 Budget.xlsx'."""
    if not path:
        return ""
    p = path.rstrip("/")
    return os.path.basename(p) if p else ""


def resolve_no_ax_title(bundle_id: str, title: str, url: Optional[str],
                        file_path: Optional[str], ext: Optional[dict]) -> (str, Optional[str]):
    """Final (title, url) for a poll made WITHOUT Accessibility.

    `title` is what the poll already has (AppleScript tab title, Adobe's
    carried/cleaned title, or ""), `ext` the fresh extension page or None.
    """
    title = title or ""
    if ext:
        if not title and ext.get("title"):
            title = ext["title"]
        if not url and ext.get("url"):
            url = ext["url"]
    if not title and bundle_id in TITLE_FROM_PATH_BUNDLES:
        title = title_from_path(file_path)
    return title, url


class PollCostMeter:
    """Per-poll cost of getting the title/URL/path, by capture mode. Logged
    every `every_s` so the no-Accessibility path's AppleScript cost is
    visible in the agent log."""

    def __init__(self, log, every_s: float = 300.0, clock=time.time):
        self.log = log
        self.every_s = every_s
        self.clock = clock
        self._since = clock()
        self._n: Dict[str, int] = {}
        self._sum: Dict[str, float] = {}
        self._max: Dict[str, float] = {}

    def add(self, mode: str, seconds: float) -> None:
        self._n[mode] = self._n.get(mode, 0) + 1
        self._sum[mode] = self._sum.get(mode, 0.0) + seconds
        self._max[mode] = max(self._max.get(mode, 0.0), seconds)
        if self.clock() - self._since >= self.every_s:
            self.flush()

    def flush(self) -> None:
        for mode, n in sorted(self._n.items()):
            avg = self._sum[mode] / n * 1000
            self.log(f"[CAPTURE-COST] mode={mode} polls={n} "
                     f"avg={avg:.0f}ms max={self._max[mode] * 1000:.0f}ms")
        self._n, self._sum, self._max = {}, {}, {}
        self._since = self.clock()
