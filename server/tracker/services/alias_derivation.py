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

# Structured-field tiers (email/website domains)
CONF_EMAIL_DOMAIN = 0.95   # full domain with TLD, e.g. "fullypromoted.com"
CONF_EMAIL_HOST = 0.90     # host without TLD, e.g. "fullypromoted"

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
    "lands", "land", "works", "place", "home", "group", "service",
    "services", "solutions", "systems",
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

    # Corporate suffix stripping (apply to base and to punct variants).
    # Guard: if stripping leaves a SINGLE token, that token must not be a
    # common English word. "LandS LLC" -> "LandS" is a lone token that
    # fuzzy-collides with "lands"/"website" and caused real false positives.
    # Multi-token results ("Acme Roofing") are always fine.
    for src in {base, no_period, both}:
        stripped = _strip_corp_suffix(src)
        if stripped.lower() != src.lower():
            stripped_tokens = [t for t in stripped.split() if t]
            if len(stripped_tokens) == 1 and \
                    stripped_tokens[0].lower() in UNSAFE_SINGLE_TOKENS:
                continue
            add(stripped, CONF_SUFFIX)
            add(_strip_periods(stripped), CONF_SUFFIX)

    # Honorific stripping
    low_tokens = _tokens(base)
    if low_tokens and low_tokens[0].lower() in HONORIFICS:
        remainder_tokens = low_tokens[1:]
        # Drop any leading connector left behind, e.g. "Mr. & Mrs. X" -> "& Mrs. X".
        # Strip leading "&"/"and" and any further honorific ("Mrs.").
        while remainder_tokens and (
            remainder_tokens[0].lower() in {"&", "and"}
            or remainder_tokens[0].lower() in HONORIFICS
        ):
            remainder_tokens = remainder_tokens[1:]
        remainder = " ".join(remainder_tokens)
        if remainder and remainder_tokens[0].lower() not in {"&", "and"}:
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
                # Skip when the second token isn't a clean name word (e.g.
                # underscore-delimited "Patricks_St", or another title token),
                # which produces broken truncations like "St Patricks_St".
                if len(toks) >= 2:
                    second = toks[1]
                    second_ok = (
                        "_" not in second
                        and second.lower().rstrip(".") not in TITLE_FORMS
                        and second.lower() not in {"&", "and"}
                    )
                    if second_ok:
                        for form in forms:
                            add(_strip_periods(f"{_titlecase(form)} {second}"),
                                CONF_TITLE)

    # Ampersand variants.
    # IMPORTANT: replace "&" with " and " (spaced), not "and", so "L&S" becomes
    # "L and S" not the glued junk token "LandS". "LandS" is a 5-char token that
    # fuzzy-matches common English ("website", "lands", news text) and caused
    # real false positives (IRS page, news headline -> "LandS LLC"). The no-
    # connector variant likewise gets a space so "L&S" -> "L S", never "LS"
    # glued into a word.
    if "&" in base:
        and_variant = _collapse_ws(base.replace("&", " and "))
        drop_variant = _collapse_ws(base.replace("&", " "))
        for v in (and_variant, drop_variant):
            if v.lower() == base.lower():
                continue
            # Reject if the variant collapsed to a single glued token (e.g. a
            # two-initial name like "B&S" with nothing else). A lone short
            # token is exactly the false-positive class we're removing.
            v_tokens = [t for t in v.split() if t]
            if len(v_tokens) <= 1:
                continue
            add(v, CONF_PUNCT)

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


# Free / shared email providers — a client's email being @gmail.com must NOT
# make "gmail.com" an alias. Lowercase.
FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "me.com", "live.com", "msn.com", "comcast.net",
    "verizon.net", "att.net", "sbcglobal.net", "ymail.com", "protonmail.com",
    "proton.me", "mail.com", "gmx.com", "twc.com", "roadrunner.com",
    "rochester.rr.com", "syr.rr.com", "earthlink.net", "frontier.com",
}


def _email_candidates(email: str) -> list[tuple[str, float]]:
    """Generate (alias, confidence) candidates from a client email's domain.

    "billing@fullypromoted.com" -> [("fullypromoted.com", 0.95),
                                    ("fullypromoted", 0.90)]

    Skips free/shared providers (gmail, etc.) and guards the host-without-TLD
    against common-word collisions (an email at "services.com" must not yield
    the junk token "services").
    """
    out: list[tuple[str, float]] = []
    if not email or "@" not in email:
        return out
    domain = email.split("@")[-1].strip().lower().strip(".")
    if not domain or "." not in domain:
        return out
    if domain in FREE_EMAIL_DOMAINS:
        return out

    # Full domain with TLD — safe as-is; the dotted form won't fuzzy-match prose.
    if len(domain) >= MIN_ALIAS_LEN:
        out.append((domain, CONF_EMAIL_DOMAIN))

    # Host without TLD: "fullypromoted.com" -> "fullypromoted". Take the label
    # immediately left of the public suffix. Naive: second-to-last label.
    labels = domain.split(".")
    if len(labels) >= 2:
        host = labels[-2]
        if (len(host) >= MIN_ALIAS_LEN
                and host not in UNSAFE_SINGLE_TOKENS
                and host.isalpha()):  # drop hosts with digits/hyphens for now
            out.append((host, CONF_EMAIL_HOST))

    return out


def _titlecase(form: str) -> str:
    # "saint" -> "Saint", "st." -> "St.", "st" -> "St"
    if form.endswith("."):
        return form[:-1].capitalize() + "."
    return form.capitalize()


# Tokens that don't distinguish one client from another. Used by the
# multi-parish ambiguity guard below. Saint/title words and entity words
# ("church", "cemetery") are shared across many religious clients, so an
# alias must retain at least one token OUTSIDE this set that is unique to
# the client (typically a town or distinctive saint name).
_NON_DISTINGUISHING = {
    "st", "saint", "mt", "mount", "ft", "fort", "dr", "doctor",
    "the", "of", "and", "for", "a", "an",
    "church", "cemetery", "parish", "catholic", "chapel", "fund",
    "foundation", "school", "ministry", "ministries", "mission",
}


def _distinctive_token_sig(alias: str) -> frozenset:
    """The set of distinguishing (non-generic) tokens in an alias, normalized.

    Used to detect when a stripped alias has lost the token that separated
    it from a sibling client (e.g. 'St Patrick Church' from both the Jordan
    and Taberg parishes).
    """
    s = _strip_periods(_strip_possessives(alias)).lower()
    s = s.replace("_", " ")
    toks = [t for t in re.split(r"[\s\-]+", s) if t]
    return frozenset(
        t for t in toks
        if len(t) >= 3 and t not in _NON_DISTINGUISHING
    )


# --- Collision rejection + public entry point ------------------------------

def derive_for_org(
    clients: list,
) -> list[DerivedAlias]:
    """
    clients: list of either (client_id, name) or (client_id, name, email).
    The 3-tuple form adds email-domain aliases. Both forms are accepted so
    existing callers don't break.

    Returns deduped DerivedAlias list with cross-client collisions dropped.

    Collision rule: any candidate alias (case-insensitive) that is produced
    by more than one distinct client is dropped for all of them. Candidates
    that equal another client's *original* name are also dropped.
    """
    # Normalize input to (cid, name, email) triples.
    norm = []
    for row in clients:
        if len(row) == 3:
            cid, name, email = row
        else:
            cid, name = row
            email = ""
        norm.append((cid, name, email or ""))

    # client_id -> {alias_lower: (alias, best_conf)}
    per_client: dict[object, dict[str, tuple[str, float]]] = defaultdict(dict)
    # alias_lower -> set of client_ids that produced it
    producers: dict[str, set] = defaultdict(set)
    # all original names (lower) -> client_id
    originals: dict[str, object] = {}
    # aliases that came from structured fields (email) — exempt from the
    # name-based multi-parish distinctive-token guard.
    field_aliases: set[str] = set()  # alias_lower keys

    for cid, name, email in norm:
        originals[_collapse_ws(name).lower()] = cid

    # Full distinctive-token signature per client, from the original name.
    # Used to reject derived aliases that have become non-distinguishing
    # against a sibling (the multi-parish problem).
    client_sig: dict[object, frozenset] = {}
    for cid, name, email in norm:
        client_sig.setdefault(cid, _distinctive_token_sig(name))

    for cid, name, email in norm:
        candidates = _candidates(name)
        email_cands = _email_candidates(email)
        for alias, conf in email_cands:
            field_aliases.add(alias.lower())
        for alias, conf in candidates + email_cands:
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

            # Multi-parish ambiguity guard: if this is a DERIVED alias (not the
            # original name) whose distinctive tokens no longer distinguish it
            # from a sibling client, drop it. E.g. "St Patrick Church" derived
            # from "St. Patrick's Church-Jordan" has signature {patrick} (after
            # 'church' is treated as non-distinguishing), which is also a subset
            # of "St. Patrick's Taberg" -> would match both. Keep the original
            # full names; only suppress the over-stripped variants.
            #
            # Email-domain aliases are exempt: a domain like "fullypromoted.com"
            # is not a name fragment and shouldn't be judged by name-token
            # overlap. It is still subject to the cross-client collision check
            # above (if two clients share a domain, neither gets it).
            if conf < CONF_ORIGINAL and key not in field_aliases:
                sig = _distinctive_token_sig(alias)
                if sig:
                    ambiguous = False
                    for other_cid, other_sig in client_sig.items():
                        if other_cid == cid:
                            continue
                        # If this alias's distinctive tokens are all present in
                        # another client's name, the alias can't tell them apart.
                        if sig <= other_sig:
                            ambiguous = True
                            break
                    if ambiguous:
                        continue

            results.append(DerivedAlias(cid, alias, round(conf, 3)))

    results.sort(key=lambda d: (str(d.client_id), -d.confidence, d.alias))
    return results


# --- Ambiguity self-heal ---------------------------------------------------

def find_ambiguous_derived(clients) -> dict:
    """
    Find already-STORED aliases that have become ambiguous against a sibling.

    clients: list of (client_id, name, stored_aliases) tuples, where
    stored_aliases is the flat list of alias strings currently on the client.

    Returns {client_id: [alias, ...]} listing stored aliases whose distinctive
    tokens no longer distinguish them from another client (the multi-parish
    problem, e.g. bare "St Mary's" once a second St Mary's exists), or that
    equal another client's original name.

    This is the mirror image of derive_for_org's guards, applied to aliases
    that were written BEFORE the colliding sibling existed — which append-only
    derivation can prevent adding but cannot retroactively remove.

    Provenance-AGNOSTIC: it reports ambiguity only. Callers MUST restrict
    actual removal to aliases known to be auto-derived, so manually-entered
    (and unmarked legacy) aliases are never touched.
    """
    norm = []
    for cid, name, stored in clients:
        norm.append((cid, name, list(stored or [])))

    originals: dict[str, object] = {}
    client_sig: dict[object, frozenset] = {}
    for cid, name, _ in norm:
        originals[_collapse_ws(name).lower()] = cid
        client_sig.setdefault(cid, _distinctive_token_sig(name))

    flagged: dict[object, list] = {}
    for cid, name, stored in norm:
        own_name_lower = _collapse_ws(name).lower()
        for alias in stored:
            if not isinstance(alias, str):
                continue
            key = _collapse_ws(alias).lower()
            if not key or key == own_name_lower:
                continue

            ambiguous = False

            # Equals a DIFFERENT client's original name → it would match them.
            owner = originals.get(key)
            if owner is not None and owner != cid:
                ambiguous = True

            # Multi-parish: distinctive tokens are a subset of a sibling's
            # name signature, so the alias can't tell the two apart.
            if not ambiguous:
                sig = _distinctive_token_sig(alias)
                if sig:
                    for other_cid, other_sig in client_sig.items():
                        if other_cid == cid:
                            continue
                        if sig <= other_sig:
                            ambiguous = True
                            break

            if ambiguous:
                flagged.setdefault(cid, []).append(alias)

    return flagged