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

import os
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


# ─────────────────────────────────────────────────────────────────────────────
# Company FILE PATH capture — the fix for ambiguous company NAMES.
#
# The title bar carries QuickBooks' Company Name field, which the client typed
# when the file was created. For a firm doing 135 parish/cemetery books that
# name is routinely non-unique: fourteen distinct .qbw files in one directory
# all announce themselves as some flavour of "St. Mary's Church", and the only
# disambiguator (Clinton / Rome / Minoa / Baldwinsville / NY Mills / …) lives
# in the FILENAME, which never reaches any window title.
#
# qbw.exe holds an open handle to the company file it has loaded, so the path
# is readable from the process handle table:
#
#     Q:\QB\QB2024 Files\St. Mary's Church_Clinton_QB2024.QBW
#
# That string is unique per client and routes through the same folder/filename
# client matcher that already works for Office documents.
#
# COST: psutil.open_files() enumerates the process handle table — materially
# more expensive than reading a window title. Rate-limited to one enumeration
# per ENUM_INTERVAL_SECONDS, with an immediate re-read whenever the company
# NAME changes (i.e. the user switched files), so a switch is never served
# stale from cache.
#
# PRIVACY: paths only, from QuickBooks processes only, and only files ending
# in .qbw. No file contents are read or opened.
# ─────────────────────────────────────────────────────────────────────────────

QB_COMPANY_EXT = '.qbw'


def _norm_for_pairing(text: str) -> str:
    """Lowercase alphanumerics only — 'St. Mary's Church_Clinton' → 'stmaryschurchclinton'."""
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


# Bookkeeping noise firms bolt onto company filenames. Stripped before matching
# so 'St. Mary's Church_Clinton_QB2024.QBW' and 'st mary's church_Baldwinsville
# .qbw' both reduce to the client identity and nothing else. Patterns are taken
# from a real 135-file production directory.
_STEM_PREFIX_RE = re.compile(r'^(restored|fixed|copy of|copy)[_\-\s]+', re.IGNORECASE)
_STEM_YEAR_RE = re.compile(r'[_\-.\s]*qb?w?\s*20\d\d$', re.IGNORECASE)
_STEM_DATE_RE = re.compile(r'[_\-.\s]*\d{6,8}[a-z]?$', re.IGNORECASE)


def clean_company_file_stem(path: str) -> str:
    """
    Company filename → client identity.

      'Q:\\QB\\QB2024 Files\\St. Mary's Church_Clinton_QB2024.QBW'
          → "St. Mary's Church_Clinton"
      'fixed_harrington homes of jamesville01142026b.qbw'
          → 'harrington homes of jamesville'
      'Midnight Express Towing & Recovery_qbw2024.qbw'
          → 'Midnight Express Towing & Recovery'

    Version years and working-copy dates are stripped because they are
    bookkeeping metadata, not client identity — 'Cadd Systems_03042025' and
    'Cadd Systems_022626' are the same client.
    """
    # Separator-agnostic: these are Windows paths, but the same helper is
    # exercised by tests (and mirrored server-side) on POSIX hosts.
    stem = (path or '').replace('/', '\\').rsplit('\\', 1)[-1]
    if '.' in stem:
        stem = stem.rsplit('.', 1)[0]
    stem = _STEM_PREFIX_RE.sub('', stem).strip()

    # Suffixes stack ('_QB2024' after a date, a date after '_QB2024') — peel
    # until stable rather than assuming an order.
    for _ in range(4):
        before = stem
        stem = _STEM_YEAR_RE.sub('', stem).strip()
        stem = _STEM_DATE_RE.sub('', stem).strip()
        if stem == before:
            break
    return stem.strip(' _-.')


# Why two mechanisms: handle enumeration is authoritative — it reports the file
# the process has OPEN right now — but psutil.open_files() on Windows resolves
# handles to paths through NtQueryObject, which routinely returns nothing for a
# MAPPED NETWORK DRIVE. This firm keeps every company file on Q:, and the first
# release (v1.7.14) reported zero paths from 217 events across 8 machines while
# the code was demonstrably running. So handles are tried first and QuickBooks'
# own recently-opened list is the fallback: a plain file/registry read, immune
# to handle resolution, that names the same paths.
#
# The MRU is "recently opened", not "currently open" — which is why the caller
# still pairs the candidates against the company name in the title before
# trusting one. That pairing is what makes a stale MRU entry harmless.

# QuickBooks' per-user settings file. Its exact home moved across versions, so
# probe all known locations rather than betting on one.
_QBW_INI_DIRS = (
    r'%APPDATA%\Intuit\QuickBooks',
    r'%LOCALAPPDATA%\Intuit\QuickBooks',
    r'%PROGRAMDATA%\Intuit\QuickBooks',
    r'%USERPROFILE%\AppData\Roaming\Intuit\QuickBooks',
)
_QBW_INI_NAMES = ('QBWUSER.INI', 'qbwuser.ini')

# Any absolute path ending in .qbw, drive-letter or UNC.
_QBW_PATH_RE = re.compile(r'((?:[A-Za-z]:\\|\\\\)[^\r\n"|*?<>]{0,200}?\.qbw)', re.IGNORECASE)


def _paths_from_handles(diag: dict) -> list[str]:
    """Open .qbw paths read from qbw.exe's handle table. Authoritative when it
    works; commonly empty for files on a mapped network drive."""
    try:
        import psutil
    except Exception as e:
        diag['err'] = f'psutil:{type(e).__name__}'
        return []

    found = set()
    procs = 0
    try:
        for proc in psutil.process_iter(['name']):
            try:
                if (proc.info.get('name') or '').lower() not in QB_EXE_NAMES:
                    continue
                procs += 1
                for f in proc.open_files():
                    path = f.path
                    if path and path.lower().endswith(QB_COMPANY_EXT):
                        found.add(path)
            except Exception as e:
                # AccessDenied is the expected failure here — record it once so
                # the server can tell "refused" from "no QuickBooks running".
                diag.setdefault('err', type(e).__name__)
                continue
    except Exception as e:
        diag['err'] = type(e).__name__
        logger.warning("QB handle enumeration failed: %s", e)
    diag['procs'] = procs
    diag['handles'] = len(found)
    return sorted(found)


def _paths_from_mru(diag: dict) -> list[str]:
    r"""Company file paths from QuickBooks' own recently-opened list.

    Two sources, both plain reads that never touch a handle table:
      - QBWUSER.INI  (per-user settings file; location varies by version)
      - HKCU\Software\Intuit\QuickBooks  (registry, scanned for .qbw values)
    """
    found = []

    for raw_dir in _QBW_INI_DIRS:
        base = os.path.expandvars(raw_dir)
        if '%' in base or not os.path.isdir(base):
            continue
        # QB nests per-version dirs ("QuickBooks 2024"), so look one level down too.
        candidates = [base] + [os.path.join(base, d) for d in os.listdir(base)[:20]
                               if os.path.isdir(os.path.join(base, d))]
        for d in candidates:
            for name in _QBW_INI_NAMES:
                fp = os.path.join(d, name)
                if not os.path.isfile(fp):
                    continue
                try:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                        text = fh.read(600_000)
                except Exception as e:
                    diag.setdefault('err', f'ini:{type(e).__name__}')
                    continue
                for m in _QBW_PATH_RE.finditer(text):
                    p = m.group(1).strip()
                    if p not in found:
                        found.append(p)
    diag['ini'] = len(found)

    if sys.platform == 'win32':
        try:
            import winreg
            n_before = len(found)
            stack = [r'Software\Intuit\QuickBooks']
            visited = 0
            while stack and visited < 60:
                keypath = stack.pop()
                visited += 1
                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, keypath)
                except Exception:
                    continue
                try:
                    i = 0
                    while True:
                        try:
                            _n, val, _t = winreg.EnumValue(key, i)
                        except OSError:
                            break
                        i += 1
                        if isinstance(val, str) and '.qbw' in val.lower():
                            for m in _QBW_PATH_RE.finditer(val):
                                p = m.group(1).strip()
                                if p not in found:
                                    found.append(p)
                    j = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(key, j)
                        except OSError:
                            break
                        j += 1
                        stack.append(keypath + '\\' + sub)
                finally:
                    try:
                        winreg.CloseKey(key)
                    except Exception:
                        pass
            diag['reg'] = len(found) - n_before
        except Exception as e:
            diag.setdefault('err', f'reg:{type(e).__name__}')

    return found


def _paths_from_cmdline(diag: dict) -> list[str]:
    """Company file path from qbw.exe's COMMAND LINE.

    Opening a company by double-clicking the .qbw, or from the Windows recent
    list, launches QuickBooks with the path as an argument. Reading a command
    line needs only PROCESS_QUERY_LIMITED_INFORMATION, which a normal user
    holds even against an ELEVATED process — unlike duplicating its handles,
    which is what returns AccessDenied in the field.

    Blind to a company opened from inside a running QuickBooks (File > Open,
    or Open Second Company), so it complements the other mechanisms rather
    than replacing them.
    """
    found = []
    try:
        import psutil
    except Exception as e:
        # Record even this: a counter that is simply ABSENT reads as "not
        # reached", which is the same ambiguity the whole probe exists to kill.
        diag['cmd'] = 0
        diag['cmd_err'] = f'psutil:{type(e).__name__}'
        return found
    try:
        for proc in psutil.process_iter(['name']):
            try:
                if (proc.info.get('name') or '').lower() not in QB_EXE_NAMES:
                    continue
                for arg in (proc.cmdline() or []):
                    for m in _QBW_PATH_RE.finditer(arg or ''):
                        p = m.group(1).strip()
                        if p not in found:
                            found.append(p)
            except Exception as e:
                diag.setdefault('cmd_err', type(e).__name__)
                continue
    except Exception as e:
        diag.setdefault('cmd_err', type(e).__name__)
    diag['cmd'] = len(found)
    return found


def _record_environment(diag: dict):
    """Facts that decide WHICH mechanism can ever work here.

    AccessDenied against a same-user process, plus an empty HKCU read, both
    point at the same thing: the agent and QuickBooks are not the same
    security context. Guessing which cost a release cycle — so measure it.
    """
    try:
        import getpass
        diag['me'] = (getpass.getuser() or '')[:24]
    except Exception:
        pass
    try:
        import psutil
        for proc in psutil.process_iter(['name']):
            try:
                if (proc.info.get('name') or '').lower() not in QB_EXE_NAMES:
                    continue
                try:
                    # 'DOMAIN\user' -> 'user'; this is the comparison that
                    # tells elevation apart from a different account.
                    diag['qbuser'] = (proc.username() or '').split('\\')[-1][:24]
                except Exception as e:
                    diag['qbuser'] = f'?{type(e).__name__}'
                break
            except Exception:
                continue
    except Exception:
        pass
    # Is the agent ITSELF elevated? The task asks for HighestAvailable, and the
    # field data shows QuickBooks running elevated as the SAME user — which
    # means these users can elevate. So if this reports 0, the task is not
    # taking effect, and that is a smaller fix than any new mechanism.
    if sys.platform == 'win32':
        try:
            import ctypes
            diag['admin'] = int(bool(ctypes.windll.shell32.IsUserAnAdmin()))
        except Exception:
            diag['admin'] = -1

    # Do the MRU locations we probe actually EXIST? 'ini=0' alone cannot tell
    # "file absent" from "file present but no paths in it" — and last round
    # reported inidirs=2 while finding nothing, which is exactly that ambiguity.
    # Count the FILES, not just the directories.
    seen, ini_files = [], 0
    for raw_dir in _QBW_INI_DIRS:
        base = os.path.expandvars(raw_dir)
        if '%' in base or not os.path.isdir(base):
            continue
        seen.append(base)
        try:
            candidates = [base] + [os.path.join(base, d) for d in os.listdir(base)[:20]
                                   if os.path.isdir(os.path.join(base, d))]
            for d in candidates:
                for name in _QBW_INI_NAMES:
                    if os.path.isfile(os.path.join(d, name)):
                        ini_files += 1
        except Exception:
            continue
    diag['inidirs'] = len(seen)
    diag['inifiles'] = ini_files
    if sys.platform == 'win32':
        try:
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                           r'Software\Intuit\QuickBooks'))
            diag['regkey'] = 1
        except Exception:
            diag['regkey'] = 0



# ─────────────────────────────────────────────────────────────────────────────
# Mechanism 4 — read the SHARE, not the process.
#
# The field verdict was unambiguous: agent_user == qbw_user on every machine,
# handle duplication refused, command line readable but empty. QuickBooks runs
# ELEVATED, so no amount of asking Windows about that process will work from a
# normal-integrity agent.
#
# So stop asking about the process. QuickBooks touches files on the share while
# a company is open — the transaction log beside the .qbw, and the lock files it
# creates on open and removes on close. Staff read Q:\QB\QB2024 Files all day,
# so the agent inherits that access: no elevation, no handle duplication,
# nothing for Windows to deny.
#
# What this can and cannot do: a "hot" file means SOMEONE on the share has it
# open, not necessarily this user — seven machines share that drive. That is
# fine, because it is not being used to pick a client outright. It is used to
# DISAMBIGUATE the company name already in the title: if the title says
# "St. Mary's Church" and only the Clinton file is active, that is the answer.
# Two same-family files hot at once -> abstain, as everywhere else here.
# ─────────────────────────────────────────────────────────────────────────────

# A company file counts as in-use if it or a sidecar changed this recently.
# Generous on purpose: QuickBooks writes the transaction log on activity, so an
# idle-but-open file can go quiet for a while.
# The winner must lead the runner-up by this much. Sibling files sit idle for
# hours, so a real edit stands out easily; anything closer is a coin flip.
SHARE_MIN_GAP_SECONDS = 90

# Directory discovery is the expensive part, and the answer never changes.
SHARE_DISCOVERY_INTERVAL = 30 * 60
SHARE_SCAN_INTERVAL = 60.0

# Depth-2 covers the real layout (Q:\QB\QB2024 Files) without walking a whole
# volume. Caps keep a misconfigured drive from turning this into a crawl.
_SHARE_MAX_DIRS = 300
_SHARE_MAX_ENTRIES = 4000
_SHARE_SKIP_DIRS = {
    'windows', 'program files', 'program files (x86)', 'programdata',
    '$recycle.bin', 'system volume information', 'appdata', 'temp', 'tmp',
    'node_modules', '.git', 'onedrive', 'perflogs', 'recovery',
}

_share_cache = {'dirs': [], 'discovered_at': 0.0, 'files': {}, 'scanned_at': 0.0}


def _candidate_roots() -> list[str]:
    """Drive letters that exist, network drives first — the company files live
    on a share, so looking there first usually ends discovery immediately."""
    import string
    roots = []
    for letter in string.ascii_uppercase:
        root = f'{letter}:\\'
        try:
            if not os.path.isdir(root):
                continue
        except Exception:
            continue
        remote = False
        if sys.platform == 'win32':
            try:
                import ctypes
                # DRIVE_REMOTE == 4
                remote = ctypes.windll.kernel32.GetDriveTypeW(root) == 4
            except Exception:
                pass
        roots.append((0 if remote else 1, root))
    roots.sort()
    return [r for _, r in roots]


def _discover_company_dirs(diag: dict) -> list[str]:
    """Directories that actually contain .qbw company files."""
    now = time.monotonic()
    if (_share_cache['dirs']
            and (now - _share_cache['discovered_at']) < SHARE_DISCOVERY_INTERVAL):
        return _share_cache['dirs']

    found, visited = [], 0
    try:
        for root in _candidate_roots():
            queue = [(root, 0)]
            while queue and visited < _SHARE_MAX_DIRS:
                path, depth = queue.pop(0)
                visited += 1
                try:
                    with os.scandir(path) as it:
                        subdirs, has_qbw = [], False
                        for n, entry in enumerate(it):
                            if n > _SHARE_MAX_ENTRIES:
                                break
                            try:
                                if entry.is_file() and entry.name.lower().endswith(QB_COMPANY_EXT):
                                    has_qbw = True
                                elif entry.is_dir() and depth < 2:
                                    if entry.name.lower() not in _SHARE_SKIP_DIRS:
                                        subdirs.append(entry.path)
                            except Exception:
                                continue
                        if has_qbw and path not in found:
                            found.append(path)
                        queue.extend((d, depth + 1) for d in subdirs)
                except Exception:
                    continue
            if found:
                break     # a share with company files on it — good enough
    except Exception as e:
        diag.setdefault('share_err', type(e).__name__)

    _share_cache['dirs'] = found
    _share_cache['discovered_at'] = now
    diag['sharedirs'] = len(found)
    return found



# ─────────────────────────────────────────────────────────────────────────────
# REPORT FACTS, DO NOT DECIDE.
#
# Four mechanisms have now been shipped and four have failed, each costing a
# release to learn one thing. The last one failed for an avoidable reason: the
# share scan narrows candidates by the company name in the title, and most
# QuickBooks samples are modals ("Make General Journal Entries") that carry no
# company — which is the entire reason this module exists. So it discarded
# every candidate before comparing anything, and reported cands=0.
#
# The deciding does not belong here. The server knows the client list, the
# block's whole title history, and what the neighbouring blocks were; the agent
# knows none of that. So the agent's job is reduced to reporting what it can
# see, and every future refinement becomes a server deploy instead of another
# agent release and another day of waiting.
#
# Cheap by construction: one cached directory listing, no per-file stat, no
# process access, nothing that can be denied.
# ─────────────────────────────────────────────────────────────────────────────

# How many recently-touched company files to report. Enough that the real one
# is present even when several people are working on the share at once.
RECENT_REPORT_LIMIT = 10


def get_capture_report(window_title: str | None = None) -> dict:
    """Everything the agent can see about which company file is in use.

    Returns raw observations only:
      company : the company name in the title, if any (may be None — modals)
      recent  : [{'f': filename, 'age': seconds since modified}, …] newest first
      diag    : mechanism counters, for diagnosing this from the server side

    Never raises. Every field may be absent; the server treats missing as
    unknown rather than as evidence.
    """
    report: dict = {}
    diag: dict = {}
    try:
        company = (_extract_company_from_main_title(window_title or '')
                   or get_company_global())
        if company:
            report['company'] = company[:120]
    except Exception as e:
        diag['co_err'] = type(e).__name__

    # The authoritative mechanisms first — if either works we say so plainly.
    try:
        exact = _paths_from_handles(diag) or _paths_from_cmdline(diag)
        if exact:
            report['exact'] = exact[:4]
    except Exception as e:
        diag.setdefault('err', type(e).__name__)

    try:
        report['recent'] = _recent_company_files(diag)
    except Exception as e:
        diag.setdefault('share_err', type(e).__name__)

    report['diag'] = diag
    _last_diag.clear()
    _last_diag.update(diag)
    return report


def _recent_company_files(diag: dict) -> list:
    """The most recently modified company files on the share, newest first.

    No company-name filtering and no threshold — both were mistakes. A filter
    needs a company name that usually is not there, and a threshold needs the
    file server's clock to agree with this machine's. Ages are reported as
    observed and the server decides what they mean.
    """
    dirs = _discover_company_dirs(diag)
    diag['sharedirs'] = len(dirs)
    if not dirs:
        return []

    now = time.monotonic()
    if not _share_cache['files'] or (now - _share_cache['scanned_at']) >= SHARE_SCAN_INTERVAL:
        seen = {}
        for d in dirs:
            try:
                with os.scandir(d) as it:
                    for entry in it:
                        try:
                            low = entry.name.lower()
                            # Both the company file and its sidecars matter:
                            # QuickBooks writes the transaction log far more
                            # often than the .qbw itself.
                            base = low
                            for tail in ('.tlg', '.nd', '.lgb', '.dsn', '.sds'):
                                if base.endswith(tail):
                                    base = base[:-len(tail)]
                                    break
                            if not base.endswith(QB_COMPANY_EXT):
                                continue
                            mt = entry.stat().st_mtime
                            if mt > seen.get(base, (0, ''))[0]:
                                seen[base] = (mt, base)
                        except Exception:
                            continue
            except Exception as e:
                diag.setdefault('share_err', type(e).__name__)
        _share_cache['files'] = seen
        _share_cache['scanned_at'] = now

    seen = _share_cache['files']
    diag['sharefiles'] = len(seen)
    if not seen:
        return []

    import time as _t
    wall = _t.time()
    ordered = sorted(seen.values(), reverse=True)[:RECENT_REPORT_LIMIT]
    out = []
    for mt, name in ordered:
        out.append({'f': name[:120], 'age': int(max(0, wall - mt))})
    diag['recent'] = len(out)
    return out


def _paths_from_share(diag: dict, company: str | None = None) -> list[str]:
    """Which company file matching `company` is being worked in right now.

    WHY RELATIVE, NOT ABSOLUTE. The first version asked "was this file touched
    in the last 15 minutes?" and every one of 1,099 files answered no, on
    machines where people were demonstrably working in QuickBooks. Two ordinary
    causes, neither of which we can rule out remotely: SMB serves directory
    metadata from a client-side cache, so enumerated timestamps can be stale;
    and the file server's clock need not agree with the workstation's, so an
    absolute age is measured against the wrong zero.

    Both distort every file on the share by roughly the same amount — so the
    ORDERING survives even when the absolute ages are wrong. Among the handful
    of files whose name matches the company already in the title, the one the
    user is actually in is the most recently touched. That comparison needs no
    trustworthy clock and no fresh cache.

    Narrowing by company name first also makes a direct stat() affordable: a
    dozen candidates instead of 1,099, so we can bypass the cached directory
    entry and ask the server for each one.
    """
    dirs = _discover_company_dirs(diag)
    diag['sharedirs'] = len(dirs)
    if not dirs:
        diag['share'] = 0
        return []

    now = time.monotonic()
    if not _share_cache['files'] or (now - _share_cache['scanned_at']) >= SHARE_SCAN_INTERVAL:
        listing = {}
        try:
            for d in dirs:
                try:
                    with os.scandir(d) as it:
                        for entry in it:
                            try:
                                if entry.is_file() and entry.name.lower().endswith(QB_COMPANY_EXT):
                                    listing[entry.path] = entry.name
                            except Exception:
                                continue
                except Exception as e:
                    diag.setdefault('share_err', type(e).__name__)
        except Exception as e:
            diag.setdefault('share_err', type(e).__name__)
        _share_cache['files'] = listing
        _share_cache['scanned_at'] = now
    listing = _share_cache['files']
    diag['sharefiles'] = len(listing)
    if not listing:
        diag['share'] = 0
        return []

    # Narrow to the company already named in the title. Without a company we
    # cannot compare like with like, so there is nothing useful to do here.
    cnorm = _norm_for_pairing(re.sub(r'\s*\([^)]*\)\s*$', '', company or ''))
    if len(cnorm) < 4:
        diag['share'] = 0
        diag['cands'] = 0
        return []
    candidates = [p for p in listing
                  if cnorm in _norm_for_pairing(clean_company_file_stem(p))]
    diag['cands'] = len(candidates)
    if not candidates:
        diag['share'] = 0
        return []

    # Direct stat, not the cached directory entry — and include the sidecars,
    # since QuickBooks writes the transaction log far more often than the
    # company file itself.
    scored = []
    for path in candidates[:40]:
        newest = 0.0
        for probe in (path, path + '.TLG', path + '.tlg',
                      path + '.ND', path + '.nd'):
            try:
                mt = os.stat(probe).st_mtime
                if mt > newest:
                    newest = mt
            except Exception:
                continue
        if newest:
            scored.append((newest, path))
    if not scored:
        diag['share'] = 0
        return []

    scored.sort(reverse=True)
    import time as _t
    # How stale is the freshest candidate, in minutes? If this is large while
    # someone is demonstrably working, the transaction log is not reaching the
    # server and no timing signal exists to read.
    diag['freshmin'] = int(max(0, (_t.time() - scored[0][0]) / 60))
    if len(scored) > 1:
        diag['gapmin'] = int(max(0, (scored[0][0] - scored[1][0]) / 60))

    # A clear winner needs daylight between it and the runner-up; otherwise two
    # parishes are equally plausible and guessing is the failure mode this
    # whole feature exists to remove.
    if len(scored) > 1 and (scored[0][0] - scored[1][0]) < SHARE_MIN_GAP_SECONDS:
        diag['share'] = 0
        return []

    diag['share'] = 1
    return [scored[0][1]]


def _enumerate_open_company_files(company: str | None = None) -> list[str]:
    """Company file paths, by whichever mechanism can see them.

    Also records HOW it went in _last_diag, which the agent ships in ctx even
    when the result is empty. v1.7.14 shipped with no diagnostic at all, so a
    total failure was indistinguishable from "nobody used QuickBooks" — the
    whole feature is fail-open, and a silent fail-open is unfalsifiable.
    """
    diag = {'procs': 0, 'handles': 0, 'ini': 0, 'reg': 0, 'cmd': 0, 'share': 0}

    paths = _paths_from_handles(diag)
    if paths:
        diag['src'] = 'handles'
        _last_diag.clear(); _last_diag.update(diag)
        return sorted(paths)

    paths = _paths_from_mru(diag)
    if paths:
        diag['src'] = 'mru'
        _last_diag.clear(); _last_diag.update(diag)
        return paths

    # Command line survives elevation, so it is the mechanism most likely to
    # work exactly where the other two just failed.
    paths = _paths_from_cmdline(diag)
    if paths:
        diag['src'] = 'cmdline'
        _last_diag.clear(); _last_diag.update(diag)
        return paths

    # Nothing about the PROCESS is readable from a normal-integrity agent when
    # QuickBooks runs elevated. The share is.
    paths = _paths_from_share(diag, company)
    diag['src'] = 'share' if paths else 'none'
    if not paths:
        # Nothing worked — spend the extra calls to report WHY, so the next
        # release is aimed rather than guessed.
        try:
            _record_environment(diag)
        except Exception:
            pass
    _last_diag.clear(); _last_diag.update(diag)
    return paths


# Last probe result, shipped in ctx so the server can see WHY a machine reports
# no company file rather than having to guess.
_last_diag: dict = {}


def get_capture_diagnostics() -> dict:
    return dict(_last_diag)


# Cached because handle-table enumeration is expensive. Invalidated on company
# change, so a file switch is picked up immediately rather than up to 15s late.
_files_cache = {'paths': [], 'enumerated_at': 0.0, 'company': None}


def get_open_company_files(company_hint: str | None = None) -> list[str]:
    """
    Every open QuickBooks company file path. Rate-limited; re-reads immediately
    when `company_hint` differs from the company seen at the last enumeration
    (the user switched company files). Fail-open: returns the last known list.
    """
    now = time.monotonic()
    stale = (now - _files_cache['enumerated_at']) >= ENUM_INTERVAL_SECONDS
    switched = company_hint is not None and company_hint != _files_cache['company']

    if not stale and not switched:
        return list(_files_cache['paths'])

    try:
        paths = _enumerate_open_company_files(company_hint)
        _files_cache['paths'] = paths
        _files_cache['enumerated_at'] = now
        _files_cache['company'] = company_hint
        return list(paths)
    except Exception as e:
        logger.warning("QB company-file cache refresh failed (fail-open): %s", e)
        return list(_files_cache['paths'])


def get_company_file_context(window_title: str | None = None) -> dict:
    """
    One handle-table read, both answers:

        {'open_files': [path, …], 'active': path | None}

    'active' is the file the user is actually working in, resolved as:
      1. Exactly one company file open  → that one. (The common case.)
      2. Several open (QB Accountant's "Open Second Company" — the Primary /
         Secondary pair) → pair them against the company NAME in the title:
         the name is a substring of its own filename, so a unique normalized
         match identifies the file.
      3. No unique winner → None. A coin flip between a parish and its cemetery
         is exactly the misattribution this capture exists to end, so abstain
         and let the server fall back to the existing title path.

    Callers should prefer this over calling get_open_company_files() and a
    separate resolver: enumerating the handle table is the expensive part, and
    doing it twice per event doubles that cost for nothing.
    """
    company = _extract_company_from_main_title(window_title or '') or get_company_global()
    paths = get_open_company_files(company_hint=company)
    return {'open_files': paths, 'active': _resolve_active(paths, company)}


def _resolve_active(paths: list[str], company: str | None) -> str | None:
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]

    # With two companies loaded, QB appends "(Primary)" / "(Secondary)" to the
    # company name — and that marker is exactly what breaks a naive substring
    # pair, since it is in the TITLE and never in the filename. Strip a trailing
    # parenthetical and try both forms. (Two-companies-open is the only case
    # that reaches here, so this path must handle the marker or it never pairs.)
    forms = []
    for form in (company or '', re.sub(r'\s*\([^)]*\)\s*$', '', company or '')):
        norm = _norm_for_pairing(form)
        if norm and norm not in forms:
            forms.append(norm)
    if not forms:
        return None

    matches = [
        p for p in paths
        if any(f in _norm_for_pairing(clean_company_file_stem(p)) for f in forms)
    ]
    return matches[0] if len(matches) == 1 else None


def get_active_company_file(window_title: str | None = None) -> str | None:
    """The open company file the user is working in, or None. See
    get_company_file_context() when you also want the full open set."""
    return get_company_file_context(window_title)['active']