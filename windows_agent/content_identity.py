"""
content_identity.py — per-app activity identity from window title (+ url when present).

GOAL
====
Give compaction a STABLE, per-activity identity for browser/SPA events so that
(a) different clients' work in the same app land in different blocks, and
(b) personal browsing separates from billable work.

This is PURE STRING PARSING. No UIA, no network, no capture risk. It runs in the
agent (added to the event payload as `content_identity`) AND can be mirrored in
compaction. Designed and unit-tested against the real 1,652-title corpus pulled
from org 21 on 2026-06-29.

DESIGN PRINCIPLES
=================
- Return a short stable string, or '' when there's no confident identity.
- WORK identity is specific (qbo:customer=..., paychex:company=70189236,
  file=st francis xavier...). PERSONAL is not identified here — it falls through
  to '' and the downstream content classifier tags it personal. Keeping the two
  jobs separate is what makes this safe.
- Never guess. An ambiguous title returns '' (downstream keeps the block separate
  and flagged, never silently bills or drops).
- Order matters: most specific extractors first.

WHAT IT INTENTIONALLY DOES NOT DO
=================================
- It does not classify billable vs non-billable. That's content_classifier.py.
- It does not split two parishes that both appear only as generic PDF opens with
  no distinguishing basename — that's unsolvable from titles and is a
  client-attribution problem, not the mixing bug.
"""

from __future__ import annotations
import re
from urllib.parse import urlparse
from typing import Optional

# Zero-width chars Edge injects into "Microsoft\u200b Edge"
_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)

# Browser chrome suffixes to strip before parsing.
_BROWSER_SUFFIXES = (
    " - Work - Microsoft Edge",
    " - Personal - Microsoft Edge",
    " - Microsoft Edge",
    " - Google Chrome",
    " — Mozilla Firefox",
    " - Mozilla Firefox",
    " - Brave",
)

# " and N more page(s)" multi-tab counter — the audit's #1 noise source.
_MORE_PAGES_RE = re.compile(r"\s+and\s+\d+\s+more\s+pages?\s*$", re.IGNORECASE)

# Trailing "(N)" unread counters, e.g. "Inbox (572)"
_UNREAD_RE = re.compile(r"\s*\(\d+\)\s*$")


def _clean_title(title: str) -> str:
    """Strip zero-width chars, browser suffix, and the multi-tab page counter."""
    if not title:
        return ""
    t = title.translate(_ZW).strip()
    # Strip page-counter first (it sits before the browser suffix sometimes,
    # after it other times depending on Edge build), then suffix, then re-strip
    # counter in case order was reversed.
    t = _MORE_PAGES_RE.sub("", t)
    for suf in _BROWSER_SUFFIXES:
        if t.endswith(suf):
            t = t[: -len(suf)].strip()
            break
    t = _MORE_PAGES_RE.sub("", t).strip()
    return t


def _norm(s: str) -> str:
    """Normalize an identity value: lowercase, collapse whitespace, trim."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# ---------------------------------------------------------------------------
# Per-app extractors. Each takes the CLEANED title (and optional url) and
# returns an identity string or None. Ordered most-specific first.
# ---------------------------------------------------------------------------

# QBO customer page puts the client in the title: "Customer - UPSTATE CEREBRAL PALSY, INC."
_QBO_CUSTOMER_RE = re.compile(r"^Customer\s*-\s*(.+)$", re.IGNORECASE)

# Paychex carries a stable company id in parens: "TL Wall ... (70189236), Dashboard"
_PAYCHEX_COMPANY_RE = re.compile(r"\((\d{6,})\)")

# Scanner output: SKMBT_4232...pdf  /  CCF06232026_0001.pdf  /  DOC062726-...pdf
_SCAN_FILE_RE = re.compile(r"\b(SKMBT_\d+|CCF\d+|DOC\d+[-\d]*)\b", re.IGNORECASE)

# Generic ".pdf" doc title (church/bank statements) — basename is the identity.
_PDF_RE = re.compile(r"^(.*?\.pdf)\b", re.IGNORECASE)


def _qbo_identity(title: str, url: str) -> Optional[str]:
    in_qbo = ("qbo.intuit.com" in (url or "")) or ("quickbooks" in title.lower())
    # Customer detail — strongest signal, carries the client name.
    m = _QBO_CUSTOMER_RE.match(title)
    if m and (in_qbo or url == ""):
        name = _norm(m.group(1))
        if len(name) >= 3:
            return f"qbo:customer={name}"
    if not in_qbo:
        return None
    # No customer in title — fall back to the QBO section so QBO work groups
    # together (Invoice/Check/Deposit/Report builder all => qbo work), but
    # distinctly from other apps. Section comes from the url path when present.
    if url:
        path = urlparse(url if "://" in url else "https://" + url).path
        seg = [p for p in path.split("/") if p]
        # /app/<section>...
        if len(seg) >= 2 and seg[0] == "app":
            return f"qbo:section={_norm(seg[1])}"
    # URL absent: use the leading words of the title as a coarse section.
    head = _norm(re.split(r"\s+-\s+", title)[0])
    if head and head not in ("quickbooks", "home", "new tab"):
        return f"qbo:section={head}"
    return "qbo:section=home"


def _paychex_identity(title: str, url: str) -> Optional[str]:
    is_paychex = ("paychex.com" in (url or "")) or ("paychex" in title.lower()) \
        or _PAYCHEX_COMPANY_RE.search(title) is not None and "," in title
    if not is_paychex:
        return None
    m = _PAYCHEX_COMPANY_RE.search(title)
    if m:
        return f"paychex:company={m.group(1)}"
    return "paychex:section=home"


def _pinnacle_identity(title: str, url: str) -> Optional[str]:
    is_pin = ("prismhr.com" in (url or "")) or title.lower().startswith("pinnacle employee services")
    if not is_pin:
        return None
    # Title form: "Pinnacle Employee Services - <Report Name>"
    parts = re.split(r"\s*-\s*", title, maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        return f"pinnacle:report={_norm(parts[1])}"
    return "pinnacle:home"


def _scan_or_pdf_identity(title: str, url: str) -> Optional[str]:
    # Scanner batch files — strip the trailing page/version noise to a stable id.
    m = _SCAN_FILE_RE.search(title)
    if m:
        return f"file={_norm(m.group(1))}"
    # Any *.pdf basename (church/bank statements). Use the filename up to .pdf.
    m = _PDF_RE.match(title)
    if m:
        base = m.group(1)
        # drop a leading "*" the app uses for unsaved/marked files
        base = base.lstrip("*").strip()
        # drop trailing " (1)"/" (003)" copy markers for stability
        base = re.sub(r"\s*\(\d+\)\s*\.pdf$", ".pdf", base, flags=re.IGNORECASE)
        return f"file={_norm(base)}"
    return None


# Known work web-apps where the host (or host+1 path segment) is a fine identity.
_WORK_HOST_PREFIXES = (
    "onvio", "thomsonreuters.com", "cocounsel", "taxwise.com", "cchaxcess",
    "support.cch.com", "irs.gov", "dol.gov", "ssa.gov", "nhtsa", "tlwallaccounting.com",
    "mystreetscape.com", "onlinebanking.mtb.com", "secure.chase.com", "key.com",
    "navyfederal", "pathfinder", "myapps.paychex.com", "flex.paychex.com",
)


def _work_host_identity(title: str, url: str) -> Optional[str]:
    if not url:
        # Onvio shows as bare "Onvio" title with no url very often.
        if title.lower().startswith("onvio"):
            return "web:onvio"
        return None
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for pref in _WORK_HOST_PREFIXES:
        if pref in host:
            path = urlparse(url if "://" in url else "https://" + url).path
            seg = [p for p in path.split("/") if p]
            if seg:
                return f"web:{host}/{_norm(seg[0])}"
            return f"web:{host}"
    return None


_EXTRACTORS = (
    _qbo_identity,
    _paychex_identity,
    _pinnacle_identity,
    _scan_or_pdf_identity,
    _work_host_identity,
)


def content_identity(window_title: str, url: str = "", file_path: str = "") -> str:
    """Return a stable per-activity identity, or '' if none is confident.

    Priority:
      1. Real file_path basename (Office docs etc.) — most reliable.
      2. Per-app title/url extractors (QBO customer, Paychex company, scans/PDFs,
         known work hosts).
      3. '' — no confident identity (downstream keeps separate + classifies).
    """
    # 1. Office file path (already reliable today).
    if file_path:
        base = re.split(r"[\\/]", file_path)[-1]
        base = re.sub(r"\.(xlsx?|docx?|pptx?|pdf)$", "", base, flags=re.IGNORECASE)
        if len(base) >= 3:
            return f"file={_norm(base)}"

    title = _clean_title(window_title)
    if not title:
        return ""

    for fn in _EXTRACTORS:
        try:
            ident = fn(title, url or "")
        except Exception:
            ident = None
        if ident:
            return ident

    return ""
