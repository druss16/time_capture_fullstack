"""
Tests for update retry/backoff, and a structural check of the updater script.

WHY THESE EXIST
---------------
The 1.9.3 -> 1.9.4 update failed on a real machine and left no usable trace:

    13:34:55  Update bat launched - exiting old agent
    13:35:04  (agent restarts - STILL 1.9.3)
    13:35:08  Nag says installed but still on 1.9.3 - retrying
    13:35:12  Zip update failed: [Errno 13] Permission denied: ...-1.9.4.zip

Expand-Archive was still extracting, and still holding the zip, when the
scheduled task restarted the old agent, which re-downloaded onto the file its
own updater had open. Then the retry sat out a FLAT HOUR while logging "will
retry next cycle" — which is not what the code did.

These cases pin the three things that had to change: a per-attempt zip name, a
backoff that grows from a minute instead of starting at an hour, and an updater
that waits and verifies rather than sleeping and hoping.

    python3 windows_agent/update_checker_test.py
"""
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


import update_checker as uc

_tmp = tempfile.mkdtemp()
uc._nag_file = lambda: os.path.join(_tmp, ".update_nagged")


def write_nag(**kw):
    with open(uc._nag_file(), "w") as f:
        json.dump(kw, f)


print("Update retry/backoff:")

# ── The flat-hour bug ─────────────────────────────────────────────────────
write_nag(version="1.9.4", ts=time.time() - 90, download_ok=False, attempts=1)
check("first failure retries after ~60s, NOT an hour",
      uc._already_nagged("1.9.4") is False)

write_nag(version="1.9.4", ts=time.time() - 30, download_ok=False, attempts=1)
check("but not instantly — 30s in, still backing off",
      uc._already_nagged("1.9.4") is True)

write_nag(version="1.9.4", ts=time.time() - 90, download_ok=False, attempts=2)
check("second failure waits longer (120s)",
      uc._already_nagged("1.9.4") is True)

write_nag(version="1.9.4", ts=time.time() - 300, download_ok=False, attempts=2)
check("second failure does retry once 120s has passed",
      uc._already_nagged("1.9.4") is False)

write_nag(version="1.9.4", ts=time.time() - 3700, download_ok=False, attempts=99)
check("backoff is capped — a machine is never stuck forever",
      uc._already_nagged("1.9.4") is False)

# ── A different version must not inherit the old one's penalty ───────────
write_nag(version="1.9.4", ts=time.time(), download_ok=False, attempts=5)
check("a NEW version is never blocked by the previous one's failures",
      uc._already_nagged("1.9.5") is False)

# ── attempts counter ──────────────────────────────────────────────────────
os.path.exists(uc._nag_file()) and os.remove(uc._nag_file())
uc._mark_nagged("1.9.4", download_ok=False)
uc._mark_nagged("1.9.4", download_ok=False)
uc._mark_nagged("1.9.4", download_ok=False)
with open(uc._nag_file()) as f:
    d = json.load(f)
check("consecutive failures accumulate", d["attempts"] == 3)

uc._mark_nagged("1.9.5", download_ok=False)
with open(uc._nag_file()) as f:
    d = json.load(f)
check("a new version resets the counter", d["attempts"] == 1)

# ── The self-heal that DID work in the field must keep working ───────────
write_nag(version="1.9.4", ts=time.time(), download_ok=True, attempts=0)
check("claims installed but running an older build -> retry anyway",
      uc._already_nagged("1.9.4") is False)

print("\nUpdater script:")

ps1 = uc._UPDATER_PS1

check("waits for the processes to actually exit",
      "Get-Process" in ps1 and "AddSeconds(60)" in ps1)
check("retries extraction instead of giving up on one lock",
      re.search(r"for \(\$i = 1; \$i -le \d+", ps1) is not None)
check("kills anything the scheduled task started mid-extraction",
      ps1.count("Stop-Agent") >= 3)
check("verifies what actually landed on disk",
      "version.py" in ps1 and "APP_VERSION" in ps1)
check("keeps the zip when extraction failed, for diagnosis",
      "EXTRACTION FAILED" in ps1 and "zip kept" in ps1)
check("only deletes the zip on success",
      re.search(r"if \(\$ok\) \{\s*\n\s*Remove-Item -LiteralPath \$Zip", ps1) is not None)
check("writes its own log — the agent is gone by then",
      "$LogFile" in ps1 and "Out-File" in ps1)
check("cleans up old zips (37 MB each)",
      "AddDays(-1)" in ps1)
check("every param the caller passes is declared",
      all(f"${p}" in ps1 for p in ("Zip", "InstallDir", "Watchdog", "Version", "LogFile")))
check("balanced braces",
      ps1.count("{") == ps1.count("}"))

# ── The Errno 13 itself: two attempts must not share a path ──────────────
print("\nZip path collision:")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "update_checker.py")).read()
check("zip name is unique per attempt (pid+timestamp)",
      'f"TimeTrackerAgent-{latest_version}-{stamp}.zip"' in src)
check("the old fixed name that caused [Errno 13] is gone",
      'f"TimeTrackerAgent-{latest_version}.zip"' not in src)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
