"""
Alias derivation for TimeTracker client names.

Pure logic, no DB access. Given a list of client names, produces candidate
aliases with confidence scores, applies cross-client collision rejection,
and returns survivors.

Usage from sync/onboarding/backfill code:

    from tracker.services.alias_derivation import derive_for_org

    results = derive_for_org([(client_id, name), ...])
    # results: list of DerivedAlias(client_id, alias, confidence)

The management command (derive_aliases.py) appends each survivor's alias
string to the flat Client.aliases JSON list (the structure Stage 3 of the
classifier actually reads), skipping any that already exist. Confidence is
NOT persisted per-alias: Stage 3 assigns strength by match type at classify
time (URL domain 0.92, file path 0.90, title alias 0.82), so the confidence
score here is advisory only — used for --min-confidence filtering and for
ordering the dry-run preview.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

# --- Confidence tiers (mirror the brief) -----------------------------------
CONF_ORIGINAL = 1.0
CONF_PUNCT = 0.9
CONF_SUFFIX = 0.85
CONF_TITLE = 0.8
CONF_ACRONYM = 0.7
CONF_TOKEN = 0.6  # distinctive single-token (deferred / second pass)

MIN_ALIAS_LEN = 4   # Stage 3 _alias_is_safe rejects anything < 4 chars
MIN_ACRONYM_LEN = 3

# Tokens that don't count toward acronyms / distinctiveness.
STOP_TOKENS = {"and", "the", "of", "for", "a", "an", "&"}

# Corporate suffixes to strip. Longest-first matters for matching.
CORP_SUFFIXES = [
    "corporation", "incorporated", "company", "limited",
    "dds pc", "pllc", "llp", "llc", "l.p.", "lp", "p.c.", "pc",
    "p.a.", "pa", "inc.", "inc", "corp.", "corp", "co.", "ltd.", "ltd",
    "co", "dds",
]

# Title abbreviations: each maps to its set of interchangeable forms.
TITLE_FORMS = {
    "st": ["st.", "st", "saint"],
    "mt": ["mt.", "mt", "mount"],
    "dr": ["dr.", "dr", "doctor"],
}

# Honorifics to strip entirely (pass-through producing the remainder).
HONORIFICS = ["mr.", "mr", "mrs.", "mrs", "ms.", "ms"]

# Dictionary/geographic words that are unsafe as standalone single-token
# aliases. Not exhaustive — collision check is the real safety net.
UNSAFE_SINGLE_TOKENS = {
    "apple", "boston", "river", "summit", "park", "main", "first",
    "national", "american", "general", "united", "premier", "valley",
    "lake", "north", "south", "east", "west", "central", "metro",
}


@dataclass(frozen=True)
class DerivedAlias:
    client_id: object
    alias: str
    confidence: float


# --- Normalization helpers -------------------------------------------------

def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _strip_periods(s: str) -> str:
    return _collapse_ws(s.replace(".", ""))


def _strip_possessives(s: str) -> str:
    # "John's" -> "John", "James'" -> "James"
    return _collapse_ws(re.sub(r"(\w)['’]s\b", r"\1", s
                               ).replace("'", "").replace("’", ""))


def _strip_corp_suffix(s: str) -> str:
    low = s.lower().rstrip(" .,")
    for suf in CORP_SUFFIXES:
        # match suffix at end, optionally preceded by comma/space
        pat = r"[,\s]+" + re.escape(suf) + r"$"
        m = re.search(pat, low)
        if m:
            return _collapse_ws(s[: m.start()])
    return _collapse_ws(s)


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[\s\-]+", s) if t]


def _significant_tokens(s: str) -> list[str]:
    return [t for t in _tokens(_strip_periods(_strip_possessives(s)))
            if t.lower() not in STOP_TOKENS]


# --- Per-client candidate generation ---------------------------------------

def _candidates(name: str) -> list[tuple[str, float]]:
    """Generate (alias, confidence) candidates for one client name."""
    out: list[tuple[str, float]] = []

    def add(alias: str, conf: float) -> None:
        alias = _collapse_ws(alias)
        if len(alias) >= MIN_ALIAS_LEN:
            out.append((alias, conf))

    base = _collapse_ws(name)
    add(base, CONF_ORIGINAL)

    # Punctuation / possessive family
    no_period = _strip_periods(base)
    no_poss = _strip_possessives(base)
    both = _strip_periods(_strip_possessives(base))
    for v in (no_period, no_poss, both):
        if v.lower() != base.lower():
            add(v, CONF_PUNCT)

    # Corporate suffix stripping (apply to base and to punct variants)
    for src in {base, no_period, both}:
        stripped = _strip_corp_suffix(src)
        if stripped.lower() != src.lower():
            add(stripped, CONF_SUFFIX)
            add(_strip_periods(stripped), CONF_SUFFIX)

    # Honorific stripping
    low_tokens = _tokens(base)
    if low_tokens and low_tokens[0].lower() in HONORIFICS:
        remainder = " ".join(low_tokens[1:])
        add(remainder, CONF_PUNCT)
        add(_strip_possessives(_strip_periods(remainder)), CONF_PUNCT)

    # Title expansions (St <-> Saint, Mt <-> Mount, Dr <-> Doctor)
    toks = _tokens(base)
    if toks:
        head = toks[0].lower().rstrip(".")
        for key, forms in TITLE_FORMS.items():
            if head == key or toks[0].lower() in forms:
                for form in forms:
                    rebuilt = " ".join([_titlecase(form)] + toks[1:])
                    add(rebuilt, CONF_TITLE)
                    add(_strip_possessives(_strip_periods(rebuilt)), CONF_TITLE)
                # truncated common form: "Saint Theresa" / "St Theresa"
                if len(toks) >= 2:
                    for form in forms:
                        add(_strip_periods(f"{_titlecase(form)} {toks[1]}"),
                            CONF_TITLE)

    # Ampersand variants
    if "&" in base:
        add(base.replace("&", "and"), CONF_PUNCT)
        add(_collapse_ws(base.replace("&", "")), CONF_PUNCT)

    # Acronym from significant tokens (post suffix strip)
    sig = _significant_tokens(_strip_corp_suffix(base))
    if len(sig) >= 3:
        acro = "".join(t[0] for t in sig).upper()
        if len(acro) >= MIN_ACRONYM_LEN:
            add(acro, CONF_ACRONYM)

    # Distinctive single token (deferred per brief — generated but low conf,
    # heavily filtered by collision check + unsafe list)
    if len(sig) >= 2:
        for t in sig:
            cleaned = _strip_possessives(t)
            if (len(cleaned) >= MIN_ALIAS_LEN
                    and cleaned.lower() not in UNSAFE_SINGLE_TOKENS):
                add(cleaned, CONF_TOKEN)

    return out


def _titlecase(form: str) -> str:
    # "saint" -> "Saint", "st." -> "St.", "st" -> "St"
    if form.endswith("."):
        return form[:-1].capitalize() + "."
    return form.capitalize()


# --- Collision rejection + public entry point ------------------------------

def derive_for_org(
    clients: list[tuple[object, str]],
) -> list[DerivedAlias]:
    """
    clients: list of (client_id, client_name).
    Returns deduped DerivedAlias list with cross-client collisions dropped.

    Collision rule: any candidate alias (case-insensitive) that is produced
    by more than one distinct client is dropped for all of them. Candidates
    that equal another client's *original* name are also dropped.
    """
    # client_id -> {alias_lower: (alias, best_conf)}
    per_client: dict[object, dict[str, tuple[str, float]]] = defaultdict(dict)
    # alias_lower -> set of client_ids that produced it
    producers: dict[str, set] = defaultdict(set)
    # all original names (lower) -> client_id
    originals: dict[str, object] = {}

    for cid, name in clients:
        originals[_collapse_ws(name).lower()] = cid

    for cid, name in clients:
        for alias, conf in _candidates(name):
            key = alias.lower()
            cur = per_client[cid].get(key)
            if cur is None or conf > cur[1]:
                per_client[cid][key] = (alias, conf)
            producers[key].add(cid)

    results: list[DerivedAlias] = []
    for cid, aliases in per_client.items():
        for key, (alias, conf) in aliases.items():
            # collision with another client's candidate
            if len(producers[key]) > 1:
                # keep only if this is the client's own original name
                if not (conf == CONF_ORIGINAL):
                    continue
                # original-name collision is a genuine dup name; keep both
            # collision with a *different* client's original name
            owner = originals.get(key)
            if owner is not None and owner != cid:
                continue
            results.append(DerivedAlias(cid, alias, round(conf, 3)))

    results.sort(key=lambda d: (str(d.client_id), -d.confidence, d.alias))
    return results