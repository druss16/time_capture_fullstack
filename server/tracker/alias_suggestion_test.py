"""
Unit tests for the inline alias-suggestion helpers.

Two functions gate what gets offered / persisted:
  - alias_is_safe_to_add     — the sibling-collision / multi-parish guard.
    PURE (only depends on alias_derivation), so it always runs here.
  - suggest_alias_for_block  — mines a distinctive title subject and skips
    titles that are generic or already match the client. Needs the classifier's
    normalize gates, so it runs only where the full app deps are installed
    (CI / the app container); otherwise those cases are SKIPPED, not failed.

Uses duck-typed fakes — never queries the database. Run standalone:

    python tracker/alias_suggestion_test.py

Exits non-zero if any assertion fails.
"""
import os
import sys
from types import SimpleNamespace

# Put the server root (dir with manage.py) on the path so `tracker...` imports
# resolve when run standalone. No django.setup(): the collision guard is pure,
# and the extraction cases lazily import the classifier themselves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.services.alias_suggestion import (  # noqa: E402
    suggest_alias_for_block, alias_is_safe_to_add,
)


def _client(cid, name, aliases=None):
    return SimpleNamespace(id=cid, name=name, aliases=aliases or [])


def _block(title):
    return SimpleNamespace(window_title=title)


_passed = _failed = _skipped = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


# --- alias_is_safe_to_add (pure — always runs) -----------------------------
print("alias_is_safe_to_add:")
target = _client(1, "John Smith PC")
siblings = [target, _client(2, "Jane Smith PC"), _client(3, "Miller & Co")]

check("distinctive alias, no collision -> safe",
      alias_is_safe_to_add("Smith Combined", target, siblings) is True)
check("shared single token matches sibling -> unsafe",
      alias_is_safe_to_add("Smith", target, siblings) is False)
check("equals a sibling's name -> unsafe",
      alias_is_safe_to_add("Miller & Co", target, siblings) is False)
check("too short -> unsafe",
      alias_is_safe_to_add("abc", target, siblings) is False)
check("unique alias -> safe",
      alias_is_safe_to_add("Wexford Holdings", target, siblings) is True)

# --- suggest_alias_for_block (needs the classifier; skip if unavailable) ----
print("suggest_alias_for_block:")
smith = _client(1, "John Smith PC")
extraction_cases = [
    ("distinctive unmatched title -> suggests subject",
     lambda: suggest_alias_for_block(
         _block("Smith Combined 2023.xlsx - Excel"), smith) == "Smith Combined"),
    ("generic title -> None",
     lambda: suggest_alias_for_block(_block("Home - Excel"), smith) is None),
    ("title already matches client -> None",
     lambda: suggest_alias_for_block(_block("John Smith PC.xlsx"), smith) is None),
    ("title already an alias -> None",
     lambda: suggest_alias_for_block(
         _block("Smith Combined.xlsx"),
         _client(1, "John Smith PC", ["Smith Combined"])) is None),
]
try:
    # Probe the lazy classifier import once; if the app deps aren't installed
    # (e.g. running against bare homebrew python), skip rather than fail.
    suggest_alias_for_block(_block("probe"), smith)
    probe_ok = True
except Exception as e:  # ModuleNotFoundError etc.
    probe_ok = False
    _skipped = len(extraction_cases)
    print(f"  SKIP  classifier unavailable ({type(e).__name__}) — "
          f"{_skipped} case(s) skipped; run in CI / the app container")

if probe_ok:
    for label, fn in extraction_cases:
        check(label, fn())

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
