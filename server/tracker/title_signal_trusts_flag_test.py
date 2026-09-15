"""_title_signal must report the claim the row was RAISED on.

Run either way:
    python manage.py shell -c "import tracker.title_signal_trusts_flag_test"
    python tracker/title_signal_trusts_flag_test.py

Django is not needed: client_name_match is pure, and it is registered under
its real dotted path below so misfile_evidence's function-level imports resolve
without pulling in tracker/utils/__init__ (which does need Django).

WHAT THIS GUARDS
----------------
A row reaches the evidence layer only because `detect_mismatch` (or
`detect_booked_absent`) is still firing on it. But `_title_signal` asked
`detect_title_client`, which answers a different question:

    detect_mismatch      ranks the OTHER clients, excluding the booked one.
    detect_title_client  ranks EVERY client including the booked one, and
                         abstains when two come out close.

A title naming the booked client AND a rival therefore gives a clean answer to
the first and a tie to the second. The row gets flagged; the evidence layer
then reports nothing supporting any rival; `rivals` is empty; no branch sets a
verdict; the Draft keeps its default of needs_human. Org 21: 76 of 145 rows.

THE INVARIANT THAT MATTERS MOST is the last section. This must not invent
accusations — every client it names is one detect_mismatch already names on the
tab today. A title that names nobody, or that names only the booked client,
must still produce no rival.
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# misfile_evidence imports django.db/django.utils at module scope for the APPLY
# path, which none of this touches. Same stub as misfile_evidence_test.
if 'django' not in sys.modules:
    for name, attrs in (
        ('django', {}),
        ('django.db', {'transaction': types.SimpleNamespace(atomic=None)}),
        ('django.utils', {}),
        ('django.utils.timezone', {'now': lambda: None}),
    ):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    sys.modules['django'].db = sys.modules['django.db']
    sys.modules['django'].utils = sys.modules['django.utils']
    sys.modules['django.utils'].timezone = sys.modules['django.utils.timezone']

# Register stub parents so `from tracker.utils.client_name_match import ...`
# resolves to the pure module instead of the Django-dependent package.
for pkg in ('tracker', 'tracker.utils'):
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = []
        sys.modules[pkg] = m
cnm = _load('tracker.utils.client_name_match',
            os.path.join(HERE, 'utils', 'client_name_match.py'))
ma = _load('_misfile_evidence',
           os.path.join(HERE, 'services', 'misfile_evidence.py'))

FAILED = []


def check(label, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILED.append(label)


# Padded so token distinctiveness behaves like a real roster's — IDF weights
# are log((n+1)/df) and go degenerate on a handful of clients.
NAMES = {i: n for i, n in enumerate([
    "Internal - Accounting", "Internal - Tax",
    "St. Mary's Church", "St. Mary's Cemetery", "Hamilton Brothers Excavating",
    "Cutting Edge Decks, Inc", "St Francis of Assisi",
    "Holy Cross Church", "St Joseph Church", "Our Lady of Lourdes",
    "St Ann Parish", "Blessed Sacrament", "St John the Evangelist",
    "Christ the King", "St Paul Church", "Immaculate Conception",
    "Transfiguration Parish", "St Rose Church", "Good Shepherd Parish",
    "St Cecilia Church", "Holy Family Parish", "St Lucy Church",
])}
MARY, CEMETERY, HAMILTON, DECKS, SFA = 2, 3, 4, 5, 6


class Ctx:
    names = NAMES
    index = cnm.build_token_index(NAMES)
    firm_name = "TL Wall Accounting"

    def name(self, cid):
        return NAMES.get(cid, '')


class Blk:
    def __init__(self, title, client_id):
        self.window_title = title
        self.client_id = client_id


def signal(title, booked, flag):
    before = ma.TITLE_SIGNAL_TRUSTS_THE_FLAG
    ma.TITLE_SIGNAL_TRUSTS_THE_FLAG = flag
    try:
        return ma._title_signal(Blk(title, booked), Ctx())
    finally:
        ma.TITLE_SIGNAL_TRUSTS_THE_FLAG = before


def main():
    ctx = Ctx()

    # The acronym path is the clean, demonstrable divergence: detect_mismatch
    # has one, detect_title_client has none. Every row raised this way produced
    # no title signal, hence no rival, hence the needs_human default.
    T_ACRONYM = "SFA P&L 2025"
    mism = cnm.detect_mismatch(T_ACRONYM, DECKS, ctx.index, NAMES,
                               firm_name=ctx.firm_name)
    titled = cnm.detect_title_client(T_ACRONYM, ctx.index, NAMES,
                                     firm_name=ctx.firm_name)
    print("The two detectors genuinely disagree on this title:")
    check("detect_mismatch names a rival", bool(mism))
    check("…via its acronym path", bool(mism) and mism.get('match_kind') == 'acronym')
    check("detect_title_client abstains", titled is None)

    print("\nSo the signal follows the detector that raised the row:")
    check("with the flag OFF there is no title signal at all",
          signal(T_ACRONYM, DECKS, False) is None)
    s = signal(T_ACRONYM, DECKS, True)
    check("with it ON the signal exists", s is not None)
    check("…and names the client the flag accused",
          bool(s) and bool(mism) and s.supports == mism['looks_like_client_id'])
    check("…still marked as the claim under review, not a witness",
          bool(s) and s.independent is False)
    check("…and an acronym gets the BASE weight, not the full-name bonus",
          bool(s) and s.weight == 0.55)

    print("\nA real distinctive name still scores above the floor:")
    s2 = signal("Hamilton Brothers Excavating 2026 invoices", DECKS, True)
    check("the rival is named", bool(s2) and s2.supports == HAMILTON)
    check("…and outweighs an acronym", bool(s2) and s2.weight > 0.55)

    print("\nAn INTERNAL target is refused, exactly as the reading detector does:")
    # The firm is "TL Wall Accounting and Tax Corp" and the roster carries
    # "Internal - Accounting". One shared word, and every title containing the
    # firm's own name — a QuickBooks banner, a WordPress tab — pointed there.
    T_FIRM = "T.L. Wall Accounting & Tax Corp.  - QuickBooks Accountant Desktop Plus 2024"
    raw = cnm.detect_mismatch(T_FIRM, DECKS, ctx.index, NAMES,
                              firm_name=ctx.firm_name)
    if raw and cnm.is_internal_client(raw['looks_like_client_name'], ctx.firm_name):
        check("detect_mismatch would have named an internal client", True)
        check("…and the signal refuses it", signal(T_FIRM, DECKS, True) is None)
    else:
        # The roster here may not reproduce it; the guard is asserted directly.
        check("an internal client is never a title-signal target",
              all(signal(f"{n} work", DECKS, True) is None
                  for n in NAMES.values()
                  if cnm.is_internal_client(n, ctx.firm_name)))

    print("\nIt must not invent anything the detector did not say:")
    check("a title naming nobody stays silent",
          signal("Payroll register 2026", DECKS, True) is None)
    check("a title naming ONLY the booked client names no rival",
          (signal("Hamilton Brothers Excavating W-2", HAMILTON, True) or
           type('x', (), {'supports': HAMILTON})()).supports == HAMILTON)
    check("with no booked client it falls back to the reading detector",
          signal("Cutting Edge Decks year end", None, True) is not None)
    check("the fallback is unchanged from today's behaviour",
          (signal("Cutting Edge Decks year end", None, True) or 0).supports
          == (signal("Cutting Edge Decks year end", None, False) or 1).supports)

    print()
    if FAILED:
        print(f'{len(FAILED)} FAILED:')
        for f in FAILED:
            print(f'  - {f}')
        raise SystemExit(1)
    print('all title-signal tests passed')


main()
