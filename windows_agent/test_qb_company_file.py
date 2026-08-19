"""
Tests for the agent's QuickBooks company-FILE capture.

Covers the piece that has no server-side equivalent: deciding WHICH open
company file the user is working in when QB Accountant's "Open Second Company"
has two loaded at once — the (Primary) / (Secondary) pair seen in production.

Pure functions only; no Windows APIs are called, so this runs anywhere:

    python windows_agent/test_qb_company_file.py

Exits non-zero if any assertion fails.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qb_company_tracker import (  # noqa: E402
    _resolve_active,
    _extract_company_from_main_title as company_of,
    clean_company_file_stem as clean,
)

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


QB = r"Q:\QB\QB2024 Files"
CHURCH = rf"{QB}\St. Mary's Church_Clinton_QB2024.QBW"
CEMETERY = rf"{QB}\St. Mary's Cemetery Clinton_QB2024.QBW"
CADD = rf"{QB}\Cadd Systems_03042025.qbw"

print("\n=== title parsing (unchanged behaviour) ===")
check("main window title yields the company name",
      company_of("St. Mary's Church - QuickBooks Accountant Desktop Plus 2024 - [Home]")
      == "St. Mary's Church")
check("Primary marker is part of the company segment, not stripped here",
      company_of("St. Mary's Church (Primary) - QuickBooks Accountant Desktop Plus 2024")
      == "St. Mary's Church (Primary)")
check("a modal title yields no company",
      company_of("Make General Journal Entries") is None)
check("bare product chrome yields no company",
      company_of("QuickBooks Accountant Desktop Plus 2024") is None)

print("\n=== single company open (the common case) ===")
check("one file open → that file, even with no usable title",
      _resolve_active([CHURCH], None) == CHURCH)
check("one file open → that file, title ignored",
      _resolve_active([CADD], "St. Mary's Church") == CADD)
check("no files open → None",
      _resolve_active([], "St. Mary's Church") is None)

print("\n=== two companies open (Open Second Company) ===")
check("church title picks the church file, not the cemetery",
      _resolve_active([CHURCH, CEMETERY], "St. Mary's Church") == CHURCH)
check("cemetery title picks the cemetery file, not the church",
      _resolve_active([CHURCH, CEMETERY], "St. Mary's Cemetery") == CEMETERY)
check("(Primary) marker still pairs to the right file",
      _resolve_active([CHURCH, CEMETERY], "St. Mary's Church (Primary)") == CHURCH)
check("an unrelated second file does not confuse the pairing",
      _resolve_active([CHURCH, CADD], "Cadd Systems") == CADD)

print("\n=== two open, unresolvable → abstain rather than guess ===")
check("no company name (nameless modal, cache cold) → abstain",
      _resolve_active([CHURCH, CEMETERY], None) is None)
check("company name that fits BOTH open files → abstain",
      _resolve_active(
          [rf"{QB}\St. Mary's Church_Clinton_QB2024.QBW",
           rf"{QB}\St. Mary's Church Cemetery Clinton_QB2024.QBW"],
          "St. Mary's Church") is None)
check("company name matching neither open file → abstain",
      _resolve_active([CHURCH, CEMETERY], "Krueger Funeral Home") is None)

print("\n=== pairing survives filename bookkeeping noise ===")
check("dated working copy still pairs to its company name",
      _resolve_active([rf"{QB}\Cadd Systems_022626.qbw", CHURCH], "Cadd Systems")
      == rf"{QB}\Cadd Systems_022626.qbw")
check("clean() drops the version year for pairing",
      clean(CHURCH) == "St. Mary's Church_Clinton")


# ── v1.7.15: MRU fallback + probe diagnostics ────────────────────────────────
from qb_company_tracker import (  # noqa: E402
    _QBW_PATH_RE, _paths_from_mru, get_capture_diagnostics,
)

print("\n=== company-file path extraction (MRU / registry text) ===")


def found(text):
    return [m.group(1) for m in _QBW_PATH_RE.finditer(text)]


check("pulls a drive-letter path out of INI text",
      found(r"PriorCompany1=Q:\QB\QB2024 Files\St. Mary's Church_Clinton_QB2024.QBW")
      == [r"Q:\QB\QB2024 Files\St. Mary's Church_Clinton_QB2024.QBW"])
check("pulls a UNC path (share not mapped to a letter)",
      found(r'x=\\tlwserver\QB\QB2024 Files\Sacred Heart Cicero_QB2024.qbw')
      == [r'\\tlwserver\QB\QB2024 Files\Sacred Heart Cicero_QB2024.qbw'])
check("finds several entries in one MRU blob",
      len(found(r'A=Q:\QB\a.qbw' + '\n' + r'B=Q:\QB\b.qbw')) == 2)
check("ignores .qbw sidecars that are not company files",
      found(r'Q:\QB\x.qbw.TLG') == [r'Q:\QB\x.qbw'])   # truncates at .qbw, sidecar tail dropped
check("does not run past a line ending",
      found('A=Q:\\QB\\a.qbw\nnoise') == [r'Q:\QB\a.qbw'])
check("no false positive on text without a path",
      found('PriorCompany1=') == [])

print("\n=== probe never raises, always reports ===")
_diag = {}
try:
    _paths_from_mru(_diag)          # no QuickBooks on this host — must not raise
    _mru_ok = True
except Exception:
    _mru_ok = False
check("MRU read is safe on a machine with no QuickBooks", _mru_ok)
check("MRU probe records its counters", 'ini' in _diag)
check("get_capture_diagnostics returns a dict", isinstance(get_capture_diagnostics(), dict))


print("\n=== v1.7.16: command-line mechanism + environment probe ===")
from qb_company_tracker import _paths_from_cmdline, _record_environment  # noqa: E402

check("extracts a company file from a QuickBooks command line",
      found(r'"C:\Program Files\Intuit\QBW.EXE" "Q:\QB\QB2024 Files\Sacred Heart Cicero_QB2024.qbw"')
      == [r"Q:\QB\QB2024 Files\Sacred Heart Cicero_QB2024.qbw"])
check("a bare launch with no company argument yields nothing",
      found(r'"C:\Program Files\Intuit\QBW.EXE"') == [])

_d = {}
try:
    _paths_from_cmdline(_d)
    _cmd_ok = True
except Exception:
    _cmd_ok = False
check("cmdline probe is safe with no QuickBooks running", _cmd_ok)
check("cmdline probe records its counter", 'cmd' in _d)

_e = {}
try:
    _record_environment(_e)
    _env_ok = True
except Exception:
    _env_ok = False
check("environment probe never raises", _env_ok)
check("environment probe reports the agent user", 'me' in _e)


print("\n=== v1.7.17: share scan (reads the drive, not the process) ===")
import tempfile, time as _time, os as _os  # noqa: E402
import qb_company_tracker as _qbt  # noqa: E402

# A miniature QuickBooks directory: three parishes, only one of them in use.
_tmp = tempfile.mkdtemp()
_now = _time.time()


def _mk(name, age_seconds):
    fp = _os.path.join(_tmp, name)
    with open(fp, 'w') as fh:
        fh.write('x')
    _os.utime(fp, (_now - age_seconds, _now - age_seconds))
    return fp


# Clinton: transaction log touched seconds ago -> someone is working in it.
_mk("St. Mary's Church_Clinton_QB2024.QBW", 90_000)
_mk("St. Mary's Church_Clinton_QB2024.QBW.TLG", 5)
# Hamilton and Minoa: nothing touched for a day -> idle.
_mk("St. Mary's Church_Hamilton_QB2024.QBW", 90_000)
_mk("St. Mary's Church_Hamilton_QB2024.QBW.TLG", 90_000)
_mk("St. Mary's Church_Minoa_QB2024.QBW", 90_000)

_qbt._share_cache.update({'dirs': [_tmp], 'discovered_at': _time.monotonic(),
                          'paths': [], 'scanned_at': 0.0})
_d = {}
_hot = _qbt._paths_from_share(_d)

check("sees every company file in the directory", _d.get('sharefiles') == 3)
check("reports only the file being worked in as active", len(_hot) == 1)
check("and it is the Clinton file, identified by its transaction log",
      _hot and _hot[0].endswith("St. Mary's Church_Clinton_QB2024.QBW"))
check("idle parishes are not reported active",
      not any('Hamilton' in p or 'Minoa' in p for p in _hot))

print("\n=== the whole point: title says 'St. Mary's Church', share says WHICH ===")
check("ambiguous title + one active file -> resolves to Clinton",
      _qbt._resolve_active(_hot, "St. Mary's Church").endswith(
          "St. Mary's Church_Clinton_QB2024.QBW"))

# Two same-family files active at once (two staff, two parishes, one share).
_qbt._share_cache['scanned_at'] = 0.0
_mk("St. Mary's Church_Hamilton_QB2024.QBW.TLG", 5)
_d2 = {}
_hot2 = _qbt._paths_from_share(_d2)
check("two same-family files active -> both reported", len(_hot2) == 2)
check("...and the ambiguous title ABSTAINS rather than guessing a parish",
      _qbt._resolve_active(_hot2, "St. Mary's Church") is None)
check("...but a title naming the town still resolves",
      _qbt._resolve_active(_hot2, "St. Mary's Church Hamilton").endswith(
          "St. Mary's Church_Hamilton_QB2024.QBW"))

print("\n=== safety ===")
_qbt._share_cache.update({'dirs': [], 'discovered_at': _time.monotonic(),
                          'paths': [], 'scanned_at': 0.0})
_d3 = {}
check("no company directory found -> returns nothing, does not raise",
      _qbt._paths_from_share(_d3) == [])
check("and records that it found no directories", _d3.get('share') == 0)
import shutil as _shutil  # noqa: E402
_shutil.rmtree(_tmp, ignore_errors=True)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
