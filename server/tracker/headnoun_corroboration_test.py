"""
Regression tests for HEAD-NOUN corroboration in the distinctive-token matcher.

A client whose name carries only ONE distinctive word ("St. John's Church" is
{john, church, st}, where "church" and "st" are floored as generic) can be 100%
covered by a title that merely contains that one word. `_corroborated` exists to
stop that: a lone distinctive word only counts if the client's GENERIC HEAD NOUN
is present too.

The bug this locks down: that check accepted ANY generic token, and "st" is
generic. Since nearly every title in this book of business contains "st", the
guard rubber-stamped every "St. X" client that shared a first name with the
title. A file named "St. John's Cemetery bills" scored "St. John's CHURCH" at
97% coverage and offered it as the fix — a church billed for a cemetery's work.

CRITICAL invariant: only a real head noun (church, cemetery, school, parish…)
may corroborate. Connectors and legal noise ("st", "the", "of", "inc") may not.
The documented good cases must keep working: "Franciscan Church of the
Assumption" still corroborates "Assumption Church", because "church" IS the
head noun and it is present.

Pure module — no Django needed. Run inside the app container or bare:
    python tracker/headnoun_corroboration_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.utils.client_name_match import (  # noqa: E402
    build_token_index, _corroborated, _tokenize, strip_app_chrome,
    detect_booked_absent,
)

# A roster shaped like the real one: same-saint church/cemetery pairs, a
# location-qualified cemetery, and the "The New School" trap.
ROSTER = {
    402: "St. John's Church",
    385: "St John Cemetery-Rome",
    404: "St. John the Baptist Church",
    125: "St. Mary's Cemetery Bville",
    169: "Assumption Church",
    500: "The New School",
    600: "Inventory Plus, Inc",
}
INDEX = build_token_index(ROSTER)


def toks(title):
    return set(_tokenize(strip_app_chrome(title)))


def check(desc, got, want):
    status = "ok  " if got == want else "FAIL"
    print(f"  [{status}] {desc}  (got {got}, want {want})")
    return got == want


def main():
    ok = True

    # ── the bug ────────────────────────────────────────────────────────────
    cemetery_bill = "8-30-2026 St. John's Cemetery bills etc_.pdf - Work - Microsoft Edge"
    ok &= check(
        "a CEMETERY title must not corroborate the same-saint CHURCH",
        _corroborated(toks(cemetery_bill), 402, INDEX), False,
    )
    ok &= check(
        "…and must not be offered as a replacement either",
        detect_booked_absent(cemetery_bill, 125, INDEX, ROSTER) is None, True,
    )

    # ── the documented good cases must survive ─────────────────────────────
    ok &= check(
        "a lone distinctive word WITH its head noun still corroborates",
        _corroborated(toks("Franciscan Church of the Assumption"), 169, INDEX), True,
    )
    ok &= check(
        "two distinctive words need no head noun at all",
        _corroborated(toks("St. John the Baptist bulletin"), 404, INDEX), True,
    )
    ok &= check(
        "'New Vendor' still does not corroborate 'The New School'",
        _corroborated(toks("New Vendor"), 500, INDEX), False,
    )
    ok &= check(
        "a 1040 for MORSE, JOHN M still does not corroborate St. John's Church",
        _corroborated(toks("2025 UltraTax CS / 1040 [MORSE, JOHN M]"), 402, INDEX), False,
    )

    # ── "st" specifically may never stand in for the head noun ─────────────
    ok &= check(
        "'st' alone cannot corroborate — it is a connector, not a head noun",
        _corroborated(toks("St Someone Else invoice"), 402, INDEX), False,
    )
    ok &= check(
        "…but the actual head noun still does",
        _corroborated(toks("St. John's Church bulletin"), 402, INDEX), True,
    )

    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
