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
    """How many of the five spellings land on the right client.

    FULL_NAME_BEATS_PARTIAL is pinned off: it ships ON, and leaving it at the
    module default would let a different rule supply the answers this test is
    attributing to these two. A test that measures one flag has to hold every
    other flag still.
    """
    cnm.FULL_NAME_BEATS_PARTIAL = False
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

    print("\nThe rows org 21's 30-day shadow run actually broke on:")
    # Not invented. Every title below is copied from the run that reported
    # 314 NEW FLAGS and 54 LOST, which is what the two guards exist to fix.
    REAL = {**PAD,
            101: "Communication Workers", 102: "All Saints Church",
            103: "St. Peters Church", 104: "St Peter's Cemetery",
            105: "St. Marks Church", 106: "St. Francis Xavier Church",
            107: "St. Francis Xavier Cemetery"}
    CASES = [
        # The 314-row false positive: a generic English plural in a title
        # reaching a client's distinctive word through one folded "s".
        ("Client Communications", None),
        # The 54 LOST: "saints" folded into the stopword "saint".
        ("All Saints Church  - QuickBooks", 102),
        ("All Saints Client Information - Processing, Managing Info - Excel", 102),
        ("FW: All Saints JUN26 - Message (HTML)", 102),
        ("St Marks_Balance Sheet_JUNE 2026.pdf - Adobe Acrobat Reader (64-bit)", 105),
        ("July reports for St Marks - Message (HTML)", 105),
        # Block 66704, the row this whole line of work started from.
        ("St. Peter's Church 2026 audit", 103),
        ("St Peters Church 2026 audit", 103),
        # Entity class earning its place: a CEMETERY title must not read as
        # the Church, and must reach the Cemetery when one exists.
        ("ST. FRANCIS XAVIER CEMETERY (Secondary)  - QuickBooks", 107),
        ("St Peter's Cemetery plots", 104),
    ]

    def run(plurals, entity):
        cnm.FULL_NAME_BEATS_PARTIAL = False
        cnm.NORMALIZE_PLURALS, cnm.ENTITY_CLASS_SEPARATES = plurals, entity
        idx = cnm.build_token_index(REAL)
        n = sum(1 for t, want in CASES
                if (cnm.detect_title_client(t, idx, REAL) or {}).get("client_id") == want)
        cnm.NORMALIZE_PLURALS = cnm.ENTITY_CLASS_SEPARATES = False
        return n

    off, on = run(False, False), run(True, True)
    print(f"    flags off {off}/{len(CASES)} · all on {on}/{len(CASES)}")
    check("every one of them is right with the guards in place",
          on == len(CASES))
    check("…and that is better than today", on > off)

    print("\nEach guard is load-bearing:")
    cnm.NORMALIZE_PLURALS = True
    check("'saints' is NOT folded — it would land in _STOPish",
          cnm._stem("saints") == "saints")
    check("'peters' still is — 'peter' is distinctive",
          cnm._stem("peters") == "peter")
    idx = cnm.build_token_index(REAL)
    raw = lambda t: set(cnm._tokenize(cnm.strip_app_chrome(t), stem=False))
    check("the Communications match is recognised as stem-dependent",
          cnm._stem_dependent(raw("Client Communications"), 101, idx))
    check("…so is the St. Peters rescue — the two are indistinguishable there",
          cnm._stem_dependent(raw("St. Peter's Church 2026 audit"), 103, idx))
    check("only COVERAGE separates them, which is what the bar uses",
          cnm.score_title_against_client(
              set(cnm._tokenize("Client Communications")), 101, idx)[0]
          < cnm.STEM_COVERAGE
          <= cnm.score_title_against_client(
              set(cnm._tokenize("St. Peter's Church 2026 audit")), 103, idx)[0])
    cnm.NORMALIZE_PLURALS = False

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED:")
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("all plural / entity-class tests passed")


main()
