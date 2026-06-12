"""
qb_company_tracker.py — persistent QuickBooks company-file capture (Windows agent).

THE PROBLEM
-----------
QuickBooks Desktop puts the open company file in the MAIN window's title:

    "Pinnacle Sealing & Plowing Inc.  - QuickBooks Accountant Desktop Plus 2024 - [Home]"

…but users spend most of their time in child windows and modals whose titles
carry NO company:

    "Preview Paycheck"
    "Select Date Range For Liabilities"
    "Positive deduction?"
    "QuickBooks Accountant Desktop Plus 2024"        (bare chrome)

When the agent samples the foreground window during a modal, the company is
invisible — so 30-minute payroll sessions attribute to nothing.

THE FIX
-------
Treat "which company is open" as SESSION STATE, not a per-sample read:

  - When the foreground process is qbw.exe, enumerate ALL top-level windows
    belonging to that PID (not just the foreground one), find the main window
    whose title matches "{Company} - QuickBooks ...", extract the company.
  - Cache it keyed by PID with a timestamp.
  - get_company(pid) returns the cached company for that QB process — so
    every qbw.exe event gets stamped with the company even when the sampled
    window is a nameless modal.
  - Cache invalidates automatically: when the main window shows a DIFFERENT
    company (user switched files) the cache updates; when the PID dies the
    entry is purged.

INTEGRATION (agent/main.py) — three wires:
------------------------------------------
  1. Import at top:
         from qb_company_tracker import QBCompanyTracker
     Instantiate once near other singletons:
         qb_tracker = QBCompanyTracker()

  2. In the capture/sample path, where the foreground window's pid/exe/title
     are already known (the same place qb_company inference happens today):

         if qb_tracker.is_qb_process(exe_name):
             qb_company = qb_tracker.get_company(pid)   # enumerate+cache inside
             if qb_company:
                 # attach to the event's inference payload exactly like the
                 # existing qb_company evidence — same key, same shape, so the
                 # server-side Stage 8 inference path consumes it unchanged.
                 inference_evidence.append({'source': 'qb_company',
                                            'value': qb_company})

  3. (Optional but recommended) On the agent's periodic housekeeping tick:
         qb_tracker.purge_dead()
     Cheap; prevents stale PIDs lingering across QB restarts.

WINDOWS-ONLY. Uses ctypes against user32 — no extra dependencies, PyInstaller
friendly. On non-Windows import it degrades to a no-op tracker so the same
code path can exist in the Mac agent without branching.

SAFETY PROPERTIES
-----------------
  - Read-only: enumerates window titles, touches nothing.
  - Rate-limited: enumeration runs at most once per ENUM_INTERVAL_SECONDS per
    PID; between runs get_company() serves the cache. Window enumeration is
    cheap (~1ms) but there's no reason to hammer it every 250ms sample.
  - Fail-open: any ctypes error returns the last cached value (or None) and
    logs once. A tracker failure can never break event capture.
"""

from __future__ import annotations

import re
import sys
import time
import logging

logger = logging.getLogger('agent.qb_tracker')

# Re-enumerate a PID's windows at most this often. Between runs, serve cache.
ENUM_INTERVAL_SECONDS = 15.0

# Drop cache entries not refreshed in this long (QB likely closed / PID reused).
CACHE_TTL_SECONDS = 30 * 60

# Process names that count as QuickBooks Desktop.
QB_EXE_NAMES = {'qbw.exe', 'qbw', 'qbw32.exe', 'qbw32'}

# Main-window title shape: "{Company} - QuickBooks ..." (en-dash tolerated).
_QB_MAIN_RE = re.compile(r'^(?P<company>.+?)\s+[-\u2013]\s+quickbooks\b', re.IGNORECASE)

# Bare-chrome titles that match the regex shape but carry no company.
_BARE_PREFIXES = ('intuit', 'quickbooks')


def _extract_company_from_main_title(title: str) -> str | None:
    """'{Company} - QuickBooks ... - [Screen]' → 'Company', else None."""
    if not title:
        return None
    # Strip trailing screen bracket first: "... - [Vendor Center: X]"
    bracket = title.rfind(' - [')
    if bracket > 0:
        title = title[:bracket]
    m = _QB_MAIN_RE.match(title.strip())
    if not m:
        return None
    company = m.group('company').strip().strip('-\u2013').strip()
    low = company.lower()
    if not company or len(company) < 4:
        return None
    if any(low.startswith(p) for p in _BARE_PREFIXES):
        return None
    return company


if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def _windows_for_pid(pid: int) -> list[str]:
        """Titles of all visible top-level windows owned by `pid`."""
        titles: list[str] = []

        def _cb(hwnd, _lparam):
            try:
                if not _user32.IsWindowVisible(hwnd):
                    return True
                owner_pid = wintypes.DWORD()
                _user32.GetWindowThreadProcessId(
                    hwnd, ctypes.byref(owner_pid)
                )
                if owner_pid.value != pid:
                    return True
                length = _user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value:
                    titles.append(buf.value)
            except Exception:
                pass  # never let one window break enumeration
            return True

        try:
            _user32.EnumWindows(_EnumWindowsProc(_cb), 0)
        except Exception as e:
            logger.warning("EnumWindows failed for pid %s: %s", pid, e)
        return titles

else:
    def _windows_for_pid(pid: int) -> list[str]:  # non-Windows no-op
        return []


class QBCompanyTracker:
    """Per-PID cache of the open QuickBooks company file name."""

    def __init__(self):
        # pid -> {'company': str|None, 'enumerated_at': float, 'refreshed_at': float}
        self._cache: dict[int, dict] = {}
        self._warned = False

    @staticmethod
    def is_qb_process(exe_name: str) -> bool:
        return (exe_name or '').strip().lower() in QB_EXE_NAMES

    def get_company(self, pid: int) -> str | None:
        """
        Company for this QB process. Serves cache; re-enumerates the PID's
        windows at most every ENUM_INTERVAL_SECONDS. Fail-open: errors return
        the last known value.
        """
        now = time.monotonic()
        entry = self._cache.get(pid)

        if entry and (now - entry['enumerated_at']) < ENUM_INTERVAL_SECONDS:
            return entry['company']

        try:
            company = None
            for title in _windows_for_pid(pid):
                company = _extract_company_from_main_title(title)
                if company:
                    break

            if company:
                # Fresh read found the company (possibly a new one — user may
                # have switched files; always overwrite).
                self._cache[pid] = {
                    'company': company,
                    'enumerated_at': now,
                    'refreshed_at': now,
                }
                return company

            # No company visible this pass (e.g. a full-screen modal is the
            # only enumerable window, or QB is mid-transition). Keep serving
            # the previous value if we have one — that's the whole point.
            if entry:
                entry['enumerated_at'] = now  # rate-limit further enumerations
                return entry['company']

            # Never seen a company for this PID.
            self._cache[pid] = {
                'company': None, 'enumerated_at': now, 'refreshed_at': now,
            }
            return None

        except Exception as e:
            if not self._warned:
                logger.warning("QB tracker error (fail-open): %s", e)
                self._warned = True
            return entry['company'] if entry else None

    def purge_dead(self):
        """Drop entries not refreshed within CACHE_TTL_SECONDS."""
        now = time.monotonic()
        stale = [pid for pid, e in self._cache.items()
                 if (now - e['refreshed_at']) > CACHE_TTL_SECONDS]
        for pid in stale:
            self._cache.pop(pid, None)


# ─────────────────────────────────────────────────────────────────────────────
# Global (PID-free) mode — for callers that don't have the process id handy,
# e.g. the inference collectors, which receive a window context (app/title/
# path) but not a PID. Enumerates ALL visible top-level windows and returns
# the first QB main-window company found. Cached with the same rate limit.
#
# Assumption: one QuickBooks instance / one open company at a time — true for
# essentially all desktop QB usage. If a firm runs two company files at once
# (QB Enterprise multi-instance), prefer the per-PID API above.
# ─────────────────────────────────────────────────────────────────────────────

if sys.platform == 'win32':

    def _all_visible_window_titles() -> list[str]:
        titles: list[str] = []

        def _cb(hwnd, _lparam):
            try:
                if not _user32.IsWindowVisible(hwnd):
                    return True
                length = _user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value and 'quickbooks' in buf.value.lower():
                    titles.append(buf.value)
            except Exception:
                pass
            return True

        try:
            _user32.EnumWindows(_EnumWindowsProc(_cb), 0)
        except Exception as e:
            logger.warning("EnumWindows (global) failed: %s", e)
        return titles

else:
    def _all_visible_window_titles() -> list[str]:
        return []


_global_cache = {'company': None, 'enumerated_at': 0.0}
_global_warned = False


def get_company_global() -> str | None:
    """
    Company of the open QuickBooks file, found by scanning all visible
    windows for a QB main-window title. Rate-limited; serves cache between
    enumerations; fail-open (errors return last known value).
    """
    global _global_warned
    now = time.monotonic()

    if (now - _global_cache['enumerated_at']) < ENUM_INTERVAL_SECONDS:
        return _global_cache['company']

    try:
        company = None
        for title in _all_visible_window_titles():
            company = _extract_company_from_main_title(title)
            if company:
                break

        if company:
            _global_cache['company'] = company
        # No company visible this pass → keep serving the previous value
        # (that's the whole point: persistence through nameless modals).
        _global_cache['enumerated_at'] = now
        return _global_cache['company']

    except Exception as e:
        if not _global_warned:
            logger.warning("QB tracker global error (fail-open): %s", e)
            _global_warned = True
        return _global_cache['company']