"""
Fuzz / robustness tests for _build_client_matchers.

The desktop agent builds its client-name regex matchers at startup from
server-provided client names + aliases. A single malformed string used to crash
the whole agent before it could start (re.error: unbalanced/unterminated group),
because the matcher was compiled from partially-escaped user data.

These tests guarantee the builder NEVER raises, no matter how hostile the input.
Run standalone (no network, no customer data):

    python -m pytest windows_agent/test_client_matchers_fuzz.py -q
    # or without pytest:
    python windows_agent/test_client_matchers_fuzz.py
"""
import itertools
import re

from ai_client_switcher import _build_client_matchers


# Every character class that has ever broken (or could break) a naive regex build.
HOSTILE_TOKENS = [
    "(", ")", "[", "]", "{", "}", "*", "+", "?", "|", "^", "$", "\\", ".", "&",
    "(unclosed", "unopened)", "[unclosed", "a[b", "a(b", "a{2,", "a)b(c",
    "401(k)", "Smith (Trust", "Estate of Doe (", "Foo * Bar", "a\\", "\\1",
    "(?:group)", "(?P<x>y)", "a**b", "a++", "(((", ")))", "[[[", "]]]",
    "  ", "\t", "\n", "", "  (  ", "trailing (", "- Profit & Loss",
    "ST. MARY OF THE ASSUMPTION CHURCH (Secon - Profit & Loss",  # the real culprit
    "café (société)", "naïve — dash", "emoji 🙂 (x", "x" * 500 + "(",
]


_next_id = itertools.count(1)


def _client(name, aliases=None):
    return {"id": next(_next_id), "name": name, "aliases": aliases or []}


def test_hostile_names_never_raise():
    """A hostile string in the NAME field must not crash the builder."""
    for tok in HOSTILE_TOKENS:
        for sens in (0, 50, 100):
            # Must return a list (possibly empty) and never raise.
            _build_client_matchers([_client(tok)], sensitivity=sens)


def test_hostile_aliases_never_raise():
    """A hostile string in the ALIASES field must not crash the builder."""
    for tok in HOSTILE_TOKENS:
        _build_client_matchers([_client("Valid Client", aliases=[tok])], sensitivity=50)


def test_hostile_pairs_never_raise():
    """Combinations of hostile fragments (name + alias) must not crash."""
    for a, b in itertools.product(HOSTILE_TOKENS[:12], repeat=2):
        _build_client_matchers([_client(a, aliases=[b])], sensitivity=50)


def test_whole_hostile_client_list_never_raises():
    """One bad record in a big list must not take the whole build down."""
    clients = [_client("Acme LLC"), _client("Johnson Family (Trust)")]
    clients += [_client(t, aliases=[t]) for t in HOSTILE_TOKENS]
    matchers = _build_client_matchers(clients, sensitivity=50)
    assert isinstance(matchers, list)


def test_every_compiled_pattern_is_valid():
    """Whatever patterns come out must actually be usable (searchable)."""
    clients = [_client(t, aliases=[t]) for t in HOSTILE_TOKENS] + [
        _client("Johnson Family (Trust)"),
        _client("Dauphin & Fantacone"),
    ]
    for matcher in _build_client_matchers(clients, sensitivity=100):
        for pat, _needle, _kind in matcher["patterns"]:
            # A compiled pattern must not blow up on .search().
            assert isinstance(pat, re.Pattern)
            pat.search("some arbitrary filename (test).pdf")


def test_normal_matching_still_works():
    """Guardrails must not have broken real matching."""
    matchers = _build_client_matchers(
        [_client("Johnson Family (Trust)")], sensitivity=100
    )
    # Flatten all compiled patterns for this single client.
    pats = [entry[0] for m in matchers for entry in m["patterns"]]
    assert pats, "expected at least one compiled pattern"

    def hits(text):
        return any(p.search(text.lower()) for p in pats)

    assert hits("JOHNSON_FAMILY_TRUST_invoice.pdf")   # punctuation dropped
    assert hits("johnson family (trust) 2026.qbw")    # exact
    assert hits("johnson-family-trust.pdf")           # dashed
    assert not hits("smith_llc_report.pdf")           # unrelated


if __name__ == "__main__":
    # Allow running without pytest installed.
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001 - test harness
            failures += 1
            print(f"FAIL  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    raise SystemExit(1 if failures else 0)
