"""
doc_capture.py — which DOCUMENT is in front, for apps the Office/iWork
AppleScript table in main.py does not cover.

Three sources, tried in order by main.try_get_url_or_path():

  1. Adobe apps (Photoshop, Illustrator, InDesign, Acrobat): an AppleScript
     that asks the running app for its front document's file. After Effects
     and Premiere Pro: the project path from the window title.
  2. AXDocument: the file:// URL many Cocoa apps publish on their window.
  3. Spotlight: the window title names a file ("Cover Photo.psd"); look it up
     by exact name under the user's cloud/work folders. Abstains on any doubt.

Plus the Adobe title hygiene that goes with it: the zoom/layer/mode tail is cut
(content_identity.strip_adobe_view_state), and when the front window is a
dialog ("Save As", "JPEG Options") the app's last real document is reported
instead of the dialog's name.

WHY THE PATH MATTERS
A marketing agency keeps work as Dropbox/<Client>/<Project>/file.psd. The
folder names the client far more reliably than any file name does; the title
alone ("Banner.psd") names nobody.

Everything here is pure Python with injectable clocks/runners so it can be
unit-tested without a GUI (test_doc_capture.py). Nothing in this module talks
to AppKit or ApplicationServices; main.py passes in what it read.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

try:
    from content_identity import strip_adobe_view_state
except Exception:  # pragma: no cover - content_identity ships beside us
    def strip_adobe_view_state(title: str, is_adobe: bool = False) -> str:
        return title or ""


# ---------------------------------------------------------------------------
# Which Adobe app is this?
#
# Several Adobe bundle ids are VERSIONED, and several versions install side by
# side (this Mac has After Effects 2023-2026 and Media Encoder 2023-2026):
#
#   com.adobe.Photoshop                 2024/2025/2026 all share it
#   com.adobe.AfterEffects              2023/2024
#   com.adobe.AfterEffects.application  2025/2026
#   com.adobe.ame.application.23 .. .26 Media Encoder
#   com.adobe.PremierePro.24 (etc.)     Premiere Pro — versioned (unverified here)
#
# so kinds are matched by exact id OR "<prefix>." — never a bare startswith,
# which would make com.adobe.AfterEffectsRenderEngine look like After Effects.
# ---------------------------------------------------------------------------
_ADOBE_KINDS: Tuple[Tuple[str, str], ...] = (
    # (bundle id or prefix, kind). Longest/most specific first.
    ("com.adobe.AfterEffectsRenderEngine", "ae_render"),
    ("com.adobe.AfterEffects", "aftereffects"),
    ("com.adobe.PremierePro", "premiere"),
    ("com.adobe.ame.application", "media_encoder"),
    ("com.adobe.Photoshop", "photoshop"),
    ("com.adobe.illustrator", "illustrator"),   # unverified: not installed here
    ("com.adobe.InDesign", "indesign"),         # unverified: not installed here
    ("com.adobe.Acrobat.Pro", "acrobat"),
)


def adobe_kind(bundle_id: Optional[str]) -> Optional[str]:
    """'photoshop', 'aftereffects', ... or None for a non-Adobe bundle."""
    if not bundle_id:
        return None
    bid = bundle_id.strip()
    low = bid.lower()
    for key, kind in _ADOBE_KINDS:
        k = key.lower()
        if low == k or low.startswith(k + "."):
            return kind
    return None


# Background tools. They are never a document the user is working in; if one
# is frontmost the user is looking at a render queue, and that is all the
# window says. No path, no carry-forward.
BACKGROUND_KINDS = frozenset({"media_encoder", "ae_render"})

# Apps whose front document we can ASK for over AppleScript.
SCRIPTABLE_KINDS = frozenset({"photoshop", "illustrator", "indesign", "acrobat"})

# Apps whose window title carries the project path.
PROJECT_TITLE_KINDS = frozenset({"aftereffects", "premiere"})


# ---------------------------------------------------------------------------
# AppleScript
#
# Targeting: `tell application id "com.adobe.Photoshop"` is ambiguous when three
# Photoshop versions are installed — Launch Services picks one, and if it is not
# the RUNNING one AppleScript launches it. So main.py passes the running app's
# bundle path (NSRunningApplication.bundleURL for the frontmost pid) and we
# address that exact copy; the id form is only the fallback.
#
# Every script: `with timeout of 2 seconds` (an Adobe app showing a modal dialog
# can sit on an AppleEvent — Acrobat did exactly that during testing), wrapped in
# try/on error -> "". An unsaved document has no file and errors -> "".
#
# `... as alias` before POSIX path matters: Photoshop's `file path` is a file
# reference, and `POSIX path of (file path of current document)` raises inside
# the tell block. Verified on Photoshop 2026, 2026-09-30.
# ---------------------------------------------------------------------------
_PATH_EXPR = {
    # Verified live: Photoshop 2026 (saved -> path, unsaved -> error -> "").
    "photoshop": (
        'if (count of documents) is 0 then return ""\n'
        'return POSIX path of ((file path of current document) as alias)'
    ),
    # UNVERIFIED (not installed here) — Illustrator's documented dictionary:
    # document.file path (file). Unsaved documents have no file -> error -> "".
    "illustrator": (
        'if (count of documents) is 0 then return ""\n'
        'return POSIX path of ((file path of current document) as alias)'
    ),
    # UNVERIFIED (not installed here) — InDesign's documented dictionary:
    # document.full name (file); raises for a never-saved document.
    "indesign": (
        'if (count of documents) is 0 then return ""\n'
        'return POSIX path of ((full name of active document) as alias)'
    ),
    # Acrobat Pro: application.active doc -> document.file alias. Verified live
    # (2026-09-30): two same-named "Proposal Draft.pdf" files in two client
    # folders each resolved to their own path as they became active; no
    # document open -> error -> "".
    "acrobat": (
        'return POSIX path of ((file alias of active doc) as alias)'
    ),
}


def _as_string_literal(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def applescript_app_ref(bundle_id: str, app_path: Optional[str] = None) -> str:
    """`application "<path>"` for the running copy, else `application id`."""
    if app_path and app_path.endswith(".app"):
        return "application " + _as_string_literal(app_path)
    return "application id " + _as_string_literal(bundle_id)


def adobe_path_script(kind: str, bundle_id: str,
                      app_path: Optional[str] = None) -> Optional[str]:
    body = _PATH_EXPR.get(kind)
    if not body:
        return None
    return (
        f"tell {applescript_app_ref(bundle_id, app_path)} to try\n"
        "with timeout of 2 seconds\n"
        f"{body}\n"
        "end timeout\n"
        'on error\nreturn ""\nend try'
    )


class ScriptBackoff:
    """Stop asking an app that is not answering.

    An Adobe app in a modal state can hold an AppleEvent until the timeout.
    Paying that on every poll would stall the capture loop, so a slow answer
    benches that process for a while; the carry-forward covers the gap.
    """

    def __init__(self, slow_after: float = 1.5, bench_for: float = 60.0,
                 clock: Callable[[], float] = time.time):
        self.slow_after = slow_after
        self.bench_for = bench_for
        self.clock = clock
        self._until: Dict[int, float] = {}

    def blocked(self, pid: Optional[int]) -> bool:
        if pid is None:
            return False
        until = self._until.get(pid)
        if until is None:
            return False
        if self.clock() >= until:
            self._until.pop(pid, None)
            return False
        return True

    def record(self, pid: Optional[int], elapsed: float) -> None:
        if pid is not None and elapsed >= self.slow_after:
            self._until[pid] = self.clock() + self.bench_for


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------

# Acrobat titles are the PDF's own Title metadata or its file name, so there is
# no shape to tell a document from a dialog — dialogs are listed.
_ACROBAT_DIALOGS = frozenset(t.lower() for t in (
    "Print", "Page Setup", "Save As", "Save a Copy", "Save As PDF", "Open",
    "Export", "Export To", "Export PDF", "Preferences", "Document Properties",
    "Security", "Password", "Password Security - Settings", "Combine Files",
    "Organize Pages", "Insert Pages", "Extract Pages", "Delete Pages",
    "Rotate Pages", "Crop Pages", "Find", "Advanced Search", "Search",
    "Sign", "Fill & Sign", "Add Signature", "Stamp", "Redact", "Protect",
    "Compress PDF", "Optimize PDF", "Reduce File Size", "Scan", "Progress",
    "Alert", "Adobe Acrobat - Alert",
))

# The app's own name as a title means NO document (Photoshop's home screen,
# Acrobat's start page). Checked case-insensitively after the version number.
_APP_HOME_RE = re.compile(
    r"^Adobe\s+(?:Photoshop|Illustrator|InDesign|Acrobat(?:\s+(?:Pro|DC|Reader))*)"
    r"(?:\s+(?:\d{4}|CC|\(Beta\)))*\s*$",
    re.IGNORECASE,
)

# Photoshop/Illustrator/InDesign document windows always carry " @ <zoom>%".
_VIEW_STATE_RE = re.compile(r"\s@\s*\d{1,4}(?:[.,]\d{1,3})?\s?%")

# "Adobe After Effects 2026 - /Users/me/Dropbox/Client/Promo.aep *"
# "Adobe Premiere Pro 2024 - /Users/me/Dropbox/Client/Cut.prproj *"
# Premiere has no AppleScript dictionary; neither app is verified here (After
# Effects never finished starting during testing, and its DoScript command
# returned "1" for every expression rather than the value). Parsed
# defensively: only an absolute path with the right extension is accepted.
_PROJECT_TITLE_RE = re.compile(
    r"^Adobe\s+(?:After\s+Effects|Premiere\s+Pro)(?:\s+(?:\d{4}|\(Beta\)|Beta))*"
    r"\s+[-–—]\s+(?P<rest>.+?)\s*\*?\s*$",
    re.IGNORECASE,
)
_PROJECT_EXT = {"aftereffects": (".aep", ".aepx"), "premiere": (".prproj",)}


def normalize_adobe_title(kind: Optional[str], title: str) -> str:
    """The title with view state and the unsaved marker removed."""
    t = (title or "").strip()
    if not kind or not t:
        return t
    t = strip_adobe_view_state(t, is_adobe=True)
    # Unsaved/"Saving" markers left outside a view-state tail.
    t = re.sub(r"\s+-\s+Saving\s+\d{1,3}%\s*$", "", t)
    t = re.sub(r"\s*\*\s*$", "", t)
    return t.strip()


def classify_adobe_title(kind: Optional[str], raw_title: str) -> str:
    """'doc', 'dialog', 'home' or 'empty' for the RAW (uncleaned) title."""
    t = (raw_title or "").strip()
    if not t:
        return "empty"
    if _APP_HOME_RE.match(t):
        return "home"
    if kind in ("photoshop", "illustrator", "indesign"):
        # A document window always shows its zoom. Anything else in front —
        # "Save As", "Layer Style", "Smart Sharpen", "Color Picker (Foreground
        # Color)", "Create Rectangle" (all seen live) — is a dialog or panel.
        return "doc" if _VIEW_STATE_RE.search(t) else "dialog"
    if kind == "acrobat":
        return "dialog" if t.lower() in _ACROBAT_DIALOGS else "doc"
    return "doc"


def parse_project_title(kind: str, title: str) -> Tuple[str, Optional[str]]:
    """After Effects / Premiere: (title without unsaved marker, project path)."""
    t = (title or "").strip()
    m = _PROJECT_TITLE_RE.match(t)
    if not m:
        return re.sub(r"\s*\*\s*$", "", t), None
    rest = m.group("rest").strip()
    clean_title = t[: m.start("rest")] + rest
    exts = _PROJECT_EXT.get(kind, ())
    if rest.startswith("/") and rest.lower().endswith(exts):
        return clean_title, rest
    return clean_title, None


class DocCarryForward:
    """Report the app's last real document while a dialog is in front.

    Photoshop replaces the document title with the dialog's for the length of
    "Save As", "JPEG Options", "Image Size"... Those seconds belong to the
    document being saved, not to a window called "JPEG Options" that names no
    client. Remembered per bundle, for a short TTL — a dialog left open over
    lunch should not keep billing a file.

    If the path script DID answer while the dialog was up, that path is the
    source of truth regardless of what was remembered.
    """

    def __init__(self, ttl: float = 180.0, clock: Callable[[], float] = time.time):
        self.ttl = ttl
        self.clock = clock
        self._last: Dict[str, Tuple[str, Optional[str], float]] = {}

    def forget(self, bundle_id: str) -> None:
        self._last.pop(bundle_id, None)

    def apply(self, bundle_id: str, state: str, title: str,
              path: Optional[str]) -> Tuple[str, Optional[str], bool]:
        """(title, path, carried) to report for this poll."""
        now = self.clock()
        if state == "doc":
            self._last[bundle_id] = (title, path, now)
            return title, path, False
        if state == "home":
            self.forget(bundle_id)
            return title, path, False
        # dialog / empty
        mem = self._last.get(bundle_id)
        if mem and now - mem[2] > self.ttl:
            self.forget(bundle_id)
            mem = None
        if path:
            if mem and mem[1] == path:
                return mem[0], path, True
            return os.path.basename(path.rstrip("/")) or title, path, True
        if mem:
            return mem[0], mem[1], True
        return title, path, False


# ---------------------------------------------------------------------------
# AXDocument
# ---------------------------------------------------------------------------

def file_url_to_path(value) -> Optional[str]:
    """AXDocument's value (a file:// URL string or NSURL) -> POSIX path.

    Only local files. A browser publishes its PAGE url here; that is not a
    document path and is refused.
    """
    if value is None:
        return None
    try:
        if hasattr(value, "path") and callable(getattr(value, "path")) \
                and hasattr(value, "isFileURL"):
            return str(value.path()) if value.isFileURL() else None
    except Exception:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.startswith("/"):
        return s
    if s.lower().startswith("file://"):
        p = unquote(urlparse(s).path or "")
        if p.startswith("/") and len(p) > 1:
            return p.rstrip("/") or "/"
    return None


# ---------------------------------------------------------------------------
# Spotlight: file name in the title -> full path
# ---------------------------------------------------------------------------

# Document types worth resolving. Code/text types are left out on purpose:
# an editor's "main.py" names no client and exists in every repo.
_DOC_EXTS = (
    "psd", "psb", "ai", "ait", "eps", "indd", "idml", "aep", "aepx", "prproj",
    "pdf", "docx", "doc", "docm", "xlsx", "xls", "xlsm", "xlsb", "csv", "pptx",
    "ppt", "pages", "numbers", "key", "rtf", "png", "jpg", "jpeg", "tif",
    "tiff", "gif", "svg", "heic", "webp", "mp4", "mov", "m4v", "wav", "mp3",
    "aif", "aiff", "sketch", "fig", "xd", "qbw", "qbb", "afphoto", "afdesign",
)
_FILENAME_RE = re.compile(
    r"^\s*\*?\s*(?P<name>[^/\\:*?\"<>|\n]{1,200}?\.(?:" + "|".join(_DOC_EXTS)
    + r"))(?=$|\s|[\]\)*,;])",
    re.IGNORECASE,
)


def extract_filename(title: str) -> Optional[str]:
    """'D&F FB Cover Photo.psd' -> itself; 'Report.pdf — Edited' -> 'Report.pdf'.

    Only a file name at the START of the title counts: that is where every
    document app puts it, and anywhere else it is more likely a subject line.
    """
    if not title:
        return None
    m = _FILENAME_RE.match(title)
    if not m:
        return None
    name = m.group("name").strip()
    # A bare extension (".psd") or something too short to be a real name.
    if len(name) < 5 or name.startswith("."):
        return None
    return name


def mdquery_escape(name: str) -> str:
    """Escape a literal for an MDQuery string: `kMDItemFSName == "<here>"c`.

    Backslash and double quote end or break the string. `*` and `?` are
    WILDCARDS inside it — verified with mdfind: "pepsi*.psd" matched three
    different files, "pepsi\\*.psd" matched none — so an unescaped `*` in a file
    name would turn an exact lookup into a pattern search.
    """
    out = []
    for ch in name:
        if ch in '\\"*?':
            out.append("\\" + ch)
        elif ch in "\n\r\t":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def default_search_roots(home: Optional[str] = None) -> List[str]:
    """Where client work lives on a Mac: cloud-sync folders first."""
    home = home or os.path.expanduser("~")
    roots: List[str] = []
    cloud = os.path.join(home, "Library", "CloudStorage")
    try:
        for entry in sorted(os.listdir(cloud)):
            p = os.path.join(cloud, entry)
            if os.path.isdir(p):
                roots.append(p)
    except OSError:
        pass
    try:
        for entry in sorted(os.listdir(home)):
            if entry.startswith("Dropbox"):
                p = os.path.join(home, entry)
                if os.path.isdir(p) and not os.path.islink(p):
                    roots.append(p)
    except OSError:
        pass
    for sub in ("Documents", "Desktop"):
        p = os.path.join(home, sub)
        if os.path.isdir(p):
            roots.append(p)
    return roots


def _parse_md_date(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s or s == "(null)":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def _hidden(path: str) -> bool:
    return any(part.startswith(".") for part in path.split("/") if part)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


class SpotlightResolver:
    """File name -> one path, or None. Never blocks the caller for long.

    A lookup runs in a worker thread with hard subprocess timeouts; the caller
    waits at most `wait` seconds and otherwise gets None now and the cached
    answer on a later poll.

    THE RULE — a candidate is used only when it is PROVEN in use now:
      1. its name matches the title EXACTLY, case included ("pepsi logo.psd"
         does not resolve to "Pepsi Logo.psd": APFS is case-insensitive, but
         a different case is a different file as far as a person is
         concerned, and Spotlight's index had only the other one here);
      2. and it is confirmed by one of
           a. the frontmost app's process has that exact path OPEN (lsof -p):
              verified for Acrobat, which holds its PDFs open (0.04s);
           b. kMDItemLastUsedDate within `recent_window` (10 min);
      3. and exactly ONE candidate is confirmed.
    Anything else abstains — a wrong client folder is worse than none.

    WHY NOT "a single match is enough": the index can miss the real file (here
    ~/Documents/pepsi logo.psd was not indexed while a Desktop copy was), so a
    lone hit is not proof. WHY NOT kMDItemLastUsedDate alone: measured
    2026-09-30, Acrobat opening a PDF — by its own `open` AND through Launch
    Services (`open -a`) — never moved it; the only timestamps on the test
    files were their creation/save times. Photoshop could not be measured (it
    hung on relaunch). Leaning on it alone would mean the fallback never fires.
    """

    def __init__(self,
                 roots: Optional[Callable[[], List[str]]] = None,
                 runner: Optional[Callable[..., "subprocess.CompletedProcess"]] = None,
                 clock: Callable[[], float] = time.time,
                 hit_ttl: float = 300.0,
                 miss_ttl: float = 300.0,
                 unconfirmed_ttl: float = 30.0,
                 error_ttl: float = 30.0,
                 timeout: float = 1.0,
                 recent_window: float = 600.0,
                 max_candidates: int = 25):
        self.roots = roots or default_search_roots
        self.runner = runner or subprocess.run
        self.clock = clock
        self.hit_ttl = hit_ttl
        self.miss_ttl = miss_ttl
        self.unconfirmed_ttl = unconfirmed_ttl
        self.error_ttl = error_ttl
        self.timeout = timeout
        self.recent_window = recent_window
        self.max_candidates = max_candidates
        self._cache: Dict[Tuple[str, Optional[int]], Tuple[Optional[str], float]] = {}
        self._inflight: Dict[Tuple[str, Optional[int]], threading.Thread] = {}
        self._lock = threading.Lock()
        self.last_outcome: Dict[str, str] = {}

    # -- cache ---------------------------------------------------------------
    @staticmethod
    def _key(name: str, pid: Optional[int]) -> Tuple[str, Optional[int]]:
        return (_nfc(name), pid)

    def cached(self, name: str, pid: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        key = self._key(name, pid)
        with self._lock:
            hit = self._cache.get(key)
            if not hit:
                return False, None
            path, expires = hit
            if self.clock() >= expires:
                self._cache.pop(key, None)
                return False, None
            return True, path

    def _store(self, name, pid, path, ttl, outcome):
        with self._lock:
            self._cache[self._key(name, pid)] = (path, self.clock() + ttl)
            self.last_outcome[_nfc(name)] = outcome

    # -- lookup --------------------------------------------------------------
    def lookup(self, name: str, pid: Optional[int] = None,
               wait: float = 0.25) -> Optional[str]:
        if not name:
            return None
        found, path = self.cached(name, pid)
        if found:
            return path
        key = self._key(name, pid)
        with self._lock:
            t = self._inflight.get(key)
            if t is None or not t.is_alive():
                t = threading.Thread(target=self._run, args=(name, pid), daemon=True)
                self._inflight[key] = t
                t.start()
        if wait > 0:
            t.join(wait)
        found, path = self.cached(name, pid)
        return path if found else None

    def resolve_now(self, name: str, pid: Optional[int] = None) -> Optional[str]:
        """Synchronous resolve (tests / one-off); still honours the timeouts."""
        self._run(name, pid)
        return self.cached(name, pid)[1]

    def _run(self, name: str, pid: Optional[int]) -> None:
        try:
            path, ttl, outcome = self._resolve(name, pid)
        except Exception:
            path, ttl, outcome = None, self.error_ttl, "error"
        self._store(name, pid, path, ttl, outcome)
        with self._lock:
            self._inflight.pop(self._key(name, pid), None)

    def _candidates(self, name: str):
        """(paths, outcome-if-failed). Exact, case-sensitive name matches."""
        roots = [r for r in (self.roots() or []) if r]
        if not roots:
            return None, "no-roots"
        cmd = ["mdfind"]
        for r in roots:
            cmd += ["-onlyin", r]
        # No `c` modifier: the comparison is case-sensitive.
        cmd.append(f'kMDItemFSName == "{mdquery_escape(name)}"')
        try:
            out = self.runner(cmd, capture_output=True, text=True,
                              timeout=self.timeout)
        except subprocess.TimeoutExpired:
            # Spotlight is cold (a first query took 4.5s here). Retry soon.
            return None, "timeout"
        if getattr(out, "returncode", 0) not in (0, None):
            return None, "error"
        want = _nfc(name)
        paths = set()
        for line in (out.stdout or "").splitlines():
            p = line.strip()
            if not p or _hidden(p):
                continue
            # The basename must BE the name — exactly, case included.
            if _nfc(os.path.basename(p)) != want:
                continue
            paths.add(p)
        return sorted(paths), None

    def _resolve(self, name: str, pid: Optional[int]) -> Tuple[Optional[str], float, str]:
        paths, failed = self._candidates(name)
        if paths is None:
            ttl = self.miss_ttl if failed == "no-roots" else self.error_ttl
            return None, ttl, failed
        if not paths:
            return None, self.miss_ttl, "miss"
        if len(paths) > self.max_candidates:
            return None, self.unconfirmed_ttl, "ambiguous"
        confirmed = set(self._open_by(pid, paths)) | set(self._recently_used(paths))
        if len(confirmed) == 1:
            return confirmed.pop(), self.hit_ttl, "hit"
        if len(confirmed) > 1:
            return None, self.unconfirmed_ttl, "ambiguous"
        return None, self.unconfirmed_ttl, "unconfirmed"

    def _open_by(self, pid: Optional[int], paths: List[str]) -> List[str]:
        """Candidates the app process has open right now (lsof)."""
        if not pid:
            return []
        try:
            out = self.runner(["lsof", "-n", "-P", "-p", str(int(pid)), "-Fn"],
                              capture_output=True, text=True, timeout=self.timeout)
        except (subprocess.TimeoutExpired, ValueError, TypeError):
            return []
        open_paths = set()
        for line in (out.stdout or "").splitlines():
            if line.startswith("n/"):
                p = _nfc(line[1:])
                open_paths.add(p)
                # lsof reports /tmp as /private/tmp and the like.
                if p.startswith("/private/"):
                    open_paths.add(p[len("/private"):])
        return [p for p in paths if _nfc(p) in open_paths
                or _nfc(os.path.realpath(p)) in open_paths]

    def _recently_used(self, paths: List[str]) -> List[str]:
        try:
            out = self.runner(["mdls", "-name", "kMDItemLastUsedDate", "-raw"]
                              + paths, capture_output=True, text=True,
                              timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return []
        values = (out.stdout or "").split("\0")
        if len(values) < len(paths):
            return []
        now = self.clock()
        recent = []
        for p, v in zip(paths, values):
            ts = _parse_md_date(v)
            if ts is not None and 0 <= now - ts <= self.recent_window:
                recent.append(p)
        return recent


# ---------------------------------------------------------------------------
# Where did a path come from? Reported to the server in ctx.file_path_source
# so an inferred (Spotlight) path can be weighed below a stated one.
# ---------------------------------------------------------------------------
_PATH_SOURCE: Dict[str, str] = {}
_PATH_SOURCE_MAX = 512


def remember_path_source(path: Optional[str], source: str) -> None:
    if not path:
        return
    if len(_PATH_SOURCE) >= _PATH_SOURCE_MAX:
        _PATH_SOURCE.clear()
    _PATH_SOURCE[path] = source


def path_source(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return _PATH_SOURCE.get(path)


# ---------------------------------------------------------------------------
# Bundle id for a pid, when NSRunningApplication says nothing.
#
# The frontmost app is found by pid, and its bundle id read from
# NSRunningApplication. That lookup intermittently returns nil for a live,
# frontmost process (measured on one Mac over 7 days: 8% of Chrome events,
# 14% of Claude, 6 of 17 Photoshop). An empty bundle id silently switches off
# everything keyed on it: browser URL capture, the Office/iWork path scripts,
# Adobe document capture and its title cleanup. And because the bundle id is
# part of the window signature, the blank and real ids alternate as two
# "different" windows for the same document.
#
# The fallback asks the kernel for the process's executable path
# (proc_pidpath) and reads CFBundleIdentifier from the enclosing .app's
# Info.plist. Results are cached per pid and re-validated against the
# executable path, so a recycled pid can never inherit another app's id.
# ---------------------------------------------------------------------------
_BUNDLE_CACHE: Dict[int, Tuple[str, str, str]] = {}  # pid -> (exe, bundle_id, app_path)
_BUNDLE_CACHE_MAX = 256
_libproc = None


def proc_executable_path(pid: int) -> Optional[str]:
    """The executable path of a running process, or None."""
    global _libproc
    if not pid or pid <= 0:
        return None
    try:
        import ctypes
        if _libproc is None:
            _libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = ctypes.create_string_buffer(4096)  # PROC_PIDPATHINFO_MAXSIZE
        n = _libproc.proc_pidpath(int(pid), buf, ctypes.sizeof(buf))
        if n <= 0:
            return None
        return buf.value.decode("utf-8", "replace") or None
    except Exception:
        return None


def app_bundle_for_executable(exe: Optional[str]) -> Tuple[str, str]:
    """(bundle_id, bundle_path) of the bundle whose executable is `exe`.

    That is the innermost bundle, so a helper app nested inside another one
    reports its own id, the same answer NSRunningApplication gives. ("", "")
    when `exe` is not a bundle executable or its Info.plist has no id.
    """
    if not exe:
        return "", ""
    import plistlib
    # The executable lives at <bundle>/Contents/MacOS/<name>. Don't require the
    # bundle dir to end in ".app": Chrome relaunches from a code-sign clone,
    # ".../code_sign_clone.xXcofX/Google Chrome.app.bundle/Contents/MacOS/...".
    macos = os.path.dirname(exe)
    contents = os.path.dirname(macos)
    if os.path.basename(macos) != "MacOS" or os.path.basename(contents) != "Contents":
        return "", ""
    bundle = os.path.dirname(contents)
    try:
        with open(os.path.join(contents, "Info.plist"), "rb") as f:
            bid = str(plistlib.load(f).get("CFBundleIdentifier") or "")
    except Exception:
        bid = ""
    return (bid, bundle) if bid else ("", "")


def bundle_info_for_pid(pid: Optional[int],
                        exe_lookup: Callable[[int], Optional[str]] = proc_executable_path
                        ) -> Tuple[str, str]:
    """(bundle_id, app_path) for a pid via its executable; cached per pid."""
    if not pid:
        return "", ""
    exe = exe_lookup(pid)
    if not exe:
        return "", ""
    hit = _BUNDLE_CACHE.get(pid)
    if hit and hit[0] == exe:
        return hit[1], hit[2]
    bid, app = app_bundle_for_executable(exe)
    if bid:
        if len(_BUNDLE_CACHE) >= _BUNDLE_CACHE_MAX:
            _BUNDLE_CACHE.clear()
        _BUNDLE_CACHE[pid] = (exe, bid, app)
    return bid, app
