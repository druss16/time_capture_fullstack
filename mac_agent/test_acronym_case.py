"""Client acronyms only match when written in UPPERCASE.

"Vehicle Acquisition Network" -> "VAN" used to match the ordinary word "Van",
filing an Easterns dealer listing ("... Passenger Van ...") to the wrong client.

    python3 <agent>/test_acronym_case.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_client_switcher import _build_client_matchers, _regex_match  # noqa: E402
from widget_state_tracker import WidgetStateTracker  # noqa: E402

VAN = "Vehicle Acquisition Network"
LISTING = ("New 2026 Chrysler Pacifica Select Passenger Van in Camp Springs "
           "#C181444 | Easterns Chrysler Dodge Jeep Ram")


def _title_match(title, name):
    return WidgetStateTracker._title_matches_client(title, None, None, name, [])


def _switch(title, name, path=None):
    matchers = _build_client_matchers([{"id": 1, "name": name, "aliases": []}], 50)
    return _regex_match(title, path, matchers, 50)


def test_word_van_is_not_the_van_acronym():
    assert not _title_match(LISTING, VAN)
    assert _switch(LISTING, VAN) is None


def test_uppercase_acronym_still_matches():
    assert _title_match("VAN Q3 report.xlsx - Excel", VAN)
    hit = _switch("VAN Q3 report.xlsx - Excel", VAN)
    assert hit is not None and hit.match_method == "acronym"


def test_uppercase_acronym_in_file_path():
    hit = _switch("report.pdf", VAN, path="/Clients/VAN/2026/report.pdf")
    assert hit is not None and hit.match_method == "acronym"


def test_full_name_still_matches_any_case():
    assert _title_match("vehicle acquisition network - invoices", VAN)
    assert _switch("vehicle acquisition network - invoices", VAN) is not None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001 - test harness
            failures += 1
            print(f"FAIL  {fn.__name__}: {type(e).__name__}: {e!r}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    raise SystemExit(1 if failures else 0)
