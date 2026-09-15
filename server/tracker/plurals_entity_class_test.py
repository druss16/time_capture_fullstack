"""Plural normalisation and entity-class exclusion — which only work together.

Run either way:
    python manage.py shell -c "import tracker.plurals_entity_class_test"
    python tracker/plurals_entity_class_test.py

No Django needed — client_name_match is pure.

WHAT THIS GUARDS
----------------
`_tokenize` did no normalisation, so a roster reading "St. Peters Church"
(`peters`) could not match its own documents saying "St. Peter's" (`peter`).
Org 21 block 66704: the parish scored 0.09 coverage against its own file, and
with CENTER_ONLY_CANNOT_SUPPRESS on, "St Peter's Cemetery" won by default. With
that flag off — which is main today — the detector simply abstains. So the cost
of this gap is UNMATCHED time, not misfiled time; it becomes misfiled only if
the other flag ships first.

THE TRAP, and why these two flags ship as a pair: that stray "s" was the ONLY
token separating the Church from the Cemetery. Collapsing plurals alone makes
them collide, the ambiguity gate abstains, and matching gets WORSE — measured
below, not assumed. The head noun has to become a real differentiator at the
same moment the accidental one disappears.

Renaming the client is not the fix either, for the same reason: spelling it
"St. Peter's Church" puts it at 94% of the Cemetery and it matches nothing.
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


# Padded so IDF weights behave like a real roster's.
PAD = {1000 + i: n for i, n in enumerate([
    "Holy Cross Church", "St Joseph Church", "Our Lady of Lourdes",
    "St Ann Parish", "Blessed Sacrament", "St John the Evangelist",
    "Christ the King", "St Paul Church", "Immaculate Conception",
    "Transfiguration Parish", "St Rose Church", "Good Shepherd Parish",
    "St Cecilia Church", "Holy Family Parish", "St Lucy Church",
    "St Andrew Church", "Assumption Parish", "Nativity Parish",
])}
CHURCH, CEMETERY = 1, 2
NAMES = {**PAD, CHURCH: "St. Peters Church", CEMETERY: "St Peter's Cemetery"}

# The five spellings org 21's own files actually use.
DOCS = [
    ("St. Peter's Church 2026 audit", CHURCH),
    ("St Peters Church 2026 audit", CHURCH),
    ("ST PETERS CHURCH payroll", CHURCH),
    ("St Peter Church bills", CHURCH),
    ("St Peter's Cemetery plots", CEMETERY),
]


def score(plurals, entity):
    """How many of the five spellings land on the right client."""
    cnm.NORMALIZE_PLURALS, cnm.ENTITY_CLASS_SEPARATES = plurals, entity
    # The index MUST be rebuilt: NORMALIZE_PLURALS changes how client names
    # tokenize, and build_token_index runs once per roster.
    idx = cnm.build_token_index(NAMES)
    n = 0
    for doc, want in DOCS:
        d = cnm.detect_title_client(doc, idx, NAMES)
        if d and d["client_id"] == want:
            n += 1
    cnm.NORMALIZE_PLURALS = cnm.ENTITY_CLASS_SEPARATES = False
    return n


def main():
    print("The two flags are not independent:")
    today = score(False, False)
    plurals_only = score(True, False)
    both = score(True, True)
    print(f"    today {today}/5 · plurals only {plurals_only}/5 · both {both}/5")
    check("today the parish misses its own apostrophe spellings", today < 5)
    check("PLURALS ALONE MAKE IT WORSE — they must not ship alone",
          plurals_only < today)
    check("together they get every spelling right", both == len(DOCS))

    print("\nThe stem is timid on purpose:")
    cnm.NORMALIZE_PLURALS = True
    keep = ["cross", "mass", "jesus", "bus", "is"]
    check("never strips 'ss' or 'us', nor leaves a stub",
          all(cnm._stem(t) == t for t in keep))
    check("does fold a real plural", cnm._stem("peters") == "peter")
    check("…and both sides fold identically",
          cnm._tokenize("St. Peters") == cnm._tokenize("St. Peter's"))
    cnm.NORMALIZE_PLURALS = False

    print("\nEntity class only speaks when BOTH sides name one:")
    cnm.ENTITY_CLASS_SEPARATES = True
    idx = cnm.build_token_index(NAMES)
    toks = lambda t: set(cnm._tokenize(t))
    check("a cemetery is excluded from a title that says church",
          cnm._class_contradicts(toks("St Peter Church bills"), CEMETERY, idx))
    check("…and the church is not",
          not cnm._class_contradicts(toks("St Peter Church bills"), CHURCH, idx))
    check("a title naming NO class contradicts nobody",
          not cnm._class_contradicts(toks("St Peter 2026 audit"), CEMETERY, idx))
    check("a client with no class in its name is never excluded",
          not cnm._class_contradicts(toks("Holy Cross Church"), 1002, idx))
    cnm.ENTITY_CLASS_SEPARATES = False

    print("\nWith both flags off, nothing moves:")
    idx_off = cnm.build_token_index(NAMES)
    check("tokenisation is untouched",
          cnm._tokenize("St. Peters Church") == ["st", "peters", "church"])
    # What today actually does with an apostrophe spelling is ABSTAIN, not
    # misfile: the parish scores cov 0.09 against its own file and the Cemetery
    # reaches only 0.51 against a 0.55 gate, so nobody clears it. The Cemetery
    # answer seen on org 21's block 66704 needs the real roster AND
    # CENTER_ONLY_CANNOT_SUPPRESS — which is exactly why that flag is still off.
    # Unmatched time is the loss here, not wrong time.
    check("today it abstains rather than answering",
          cnm.detect_title_client("St. Peter's Church 2026 audit",
                                  idx_off, NAMES) is None)

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED:")
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("all plural / entity-class tests passed")


main()
