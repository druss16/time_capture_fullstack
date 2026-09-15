"""A QB Center vendor must not be able to veto the client a document names.

Run either way:
    python manage.py shell -c "import tracker.title_specificity_test"
    python tracker/title_specificity_test.py

No Django needed — client_name_match is pure.

WHAT THIS GUARDS
----------------
`_named_only_in_center` has always refused to reroute a block TO a client whose
whole case is the "[Vendor Center: X]" tag — that names somebody the client does
business with, not the client. But it ran only on the winner and only after the
ambiguity gate, so such a client could still be the runner-up that suppressed
the real answer. Noise never had to win to do damage.

HONEST SCOPE. These rosters are CONSTRUCTED — padded to twenty-odd parishes so
the IDF weights behave like a real firm's, but they are not org 21. The live
block this came from ("Church of Sacred Heart and St. Mary", 2026-09-14) is
reproduced here as `2-word client vs bracket` and lands at 66% against a 65%
gate, which is consistent with what the UI showed — but only if org 21 really
has a client the bracket matches. `manage.py shadow_title_specificity` settles
that against the real roster. The flag ships OFF until it does.

THE INVARIANT THAT MATTERS MOST is the abstention section. This rule must only
ever remove a FAKE second opinion. Where two real clients are both named, the
title still fingerprints neither. If `two real clients still abstain` ever
fails, the change has started inventing answers, which is worse than the silence
it replaced.
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "cnm", os.path.join(os.path.dirname(__file__), "utils", "client_name_match.py"))
cnm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cnm)

FAILED = []


def check(label, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILED.append(label)


# Padding so token distinctiveness behaves like a real roster's rather than a
# handful of clients', where every weight is degenerate.
PAD = {1000 + i: n for i, n in enumerate([
    "Holy Cross Church", "St Joseph Church", "Our Lady of Lourdes", "St Ann Parish",
    "Blessed Sacrament", "St John the Evangelist", "Christ the King", "St Paul Church",
    "Immaculate Conception", "St Peter Church", "Transfiguration Parish", "St Rose Church",
    "Good Shepherd Parish", "St Cecilia Church", "Holy Family Parish", "St Lucy Church",
    "St Andrew Church", "Assumption Parish", "St Charles Church", "Nativity Parish",
])}
PARISHES = {
    1: "Sacred Heart & St. Mary's Church",
    9: "St. Francis Xavier Church",
    99: "Diocese of Syracuse",       # exists only to be named in a Vendor tag
}
ROSTER = {**PAD, **PARISHES}
IDX = cnm.build_token_index(ROSTER)

QB = " - QuickBooks Accountant Desktop Plus 2024"
CENTER = " - [Vendor Center: DIOCESE OF SYRACUSE.]"


def detect(title, roster=None, center=True):
    """Detect with the flag forced, since it ships OFF by default."""
    names = roster or ROSTER
    idx = IDX if roster is None else cnm.build_token_index(names)
    cnm.CENTER_ONLY_CANNOT_SUPPRESS = center
    try:
        d = cnm.detect_title_client(title, idx, names)
    finally:
        cnm.CENTER_ONLY_CANNOT_SUPPRESS = False
    return d["client_name"] if d else None


def main():
    print("A bracket-only vendor cannot veto the document's client:")
    # Ties the correct client at 100% of its mass, purely on bracket tokens.
    check("1-word client vs bracket resolves",
          detect("ST. FRANCIS XAVIER (Secondary)" + QB + CENTER)
          == "St. Francis Xavier Church")
    # The live block. 66% against a 65% gate — a whisker over.
    check("2-word client vs bracket resolves",
          detect("Church of Sacred Heart and St. Mary" + QB + CENTER)
          == "Sacred Heart & St. Mary's Church")
    check("…and both are silent with the flag off (this IS the bug)",
          detect("ST. FRANCIS XAVIER (Secondary)" + QB + CENTER, center=False) is None
          and detect("Church of Sacred Heart and St. Mary" + QB + CENTER,
                     center=False) is None)

    print("\nA bracket-only vendor still cannot WIN:")
    check("a title that names nobody but the vendor stays silent",
          detect("Payroll register" + QB + CENTER) is None)
    check("a diocese named in the DOCUMENT still resolves",
          detect("Diocese of Syracuse annual report" + QB) == "Diocese of Syracuse")

    print("\nThe abstentions that must survive:")
    check("two real clients in one title still abstain",
          detect("Sacred Heart & St. Mary and St. Francis Xavier Church" + QB)
          is None)
    check("a bare family name still abstains",
          detect("Sacred Heart" + QB,
                 {**PAD, 175: "Sacred Heart Basilica",
                  360: "Sacred Heart Church-Cicero"}) is None)
    check("no bracket, no behaviour change",
          detect("Church of Sacred Heart and St. Mary" + QB)
          == detect("Church of Sacred Heart and St. Mary" + QB, center=False))

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED:")
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("all passed")


main()
