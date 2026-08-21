"""
Distinctive-token client-name mismatch matcher.

Problem: a block's window title names a *different* client than the client the
time is booked to (e.g. title "St. Anne Mother of Mary Catholic Church" booked
to "St. Peters Church"). Naive substring matching is useless here because
generic tokens ("st", "church", "inc") match many clients and create noise.

Approach — distinctive-token fingerprinting:
  1. Tokenize every client name. Build a document-frequency (df) map: how many
     clients contain each token.
  2. A token's DISTINCTIVENESS is inversely related to df. Tokens in 1 client
     are strong fingerprints; tokens in many clients ("church", "st") are weak.
  3. To score how strongly a title points at a client, sum the distinctiveness
     of that client's distinctive tokens that appear in the title, normalized by
     the client's total distinctive mass (so a client needs its OWN rare tokens
     present, not just any shared word).
  4. Flag a MISMATCH only when:
       - some OTHER client scores >= STRONG_HIT (title clearly fingerprints it),
       - AND that other client beats the booked client by >= MARGIN,
       - AND the other client contributed at least one HIGH-distinctiveness
         token (guards against a pile of medium tokens ganging up).
     Otherwise: no flag. Prefer misses over false alarms.

This mirrors the Basilica title-alias matcher discipline: distinctive-token
COVERAGE as the hit gate, not raw substring presence.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict


# Tokens that are never fingerprints on their own — legal/entity noise and the
# ubiquitous religious-org words in this book of business. They still get a df
# weight naturally, but we also hard-floor them so a roster quirk can't make
# "church" look distinctive.
_STOPish = {
    "the", "of", "and", "a", "an", "&", "inc", "inc.", "llc", "l.l.c", "co",
    "co.", "corp", "corp.", "ltd", "company", "group", "assoc", "associates",
    "st", "st.", "saint", "church", "parish", "catholic", "roman", "school",
    "center", "centre", "services", "service", "internal", "admin", "account",
    "accounts", "temp", "temps", "tax", "client", "clients",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# Names that represent the firm's own internal/admin buckets rather than a real
# external client. A mismatch touching one of these is real (worth seeing) but
# belongs in a SEPARATE bucket from client<->client billing errors, so the
# money-losing cases aren't drowned by internal bookkeeping noise.
#
# Detection is prefix/substring based on the normalized name. Kept deliberately
# small and explicit; extend per-org if new internal buckets appear.
_INTERNAL_MARKERS = (
    "internal",           # "Internal - Tax", "Internal - Accounting", "Internal"
    "admin",              # admin buckets
    "non-billable",
    "nonbillable",
    "overhead",
    "pto",
    "training",
)


def is_internal_client(name: str, firm_name: str | None = None) -> bool:
    """
    True if `name` is an internal/admin bucket (or the firm itself) rather than a
    real external client. `firm_name`, when supplied, catches the firm's own name
    appearing as a pseudo-client (e.g. the CS Connect 'TL Wall Accounting and Tax
    Corp' window that classifies to an internal record).
    """
    n = (name or "").strip().lower()
    if not n:
        return False
    for marker in _INTERNAL_MARKERS:
        if marker in n:
            return True
    if firm_name:
        fn = firm_name.strip().lower()
        # Compare on distinctive firm tokens (drop generic corp words) so
        # "TL Wall Accounting and Tax Corp" matches "TL Wall".
        fn_tokens = {t for t in _TOKEN_RE.findall(fn) if len(t) > 2 and t not in _STOPish}
        n_tokens = set(_TOKEN_RE.findall(n))
        if fn_tokens and fn_tokens <= n_tokens:
            return True
    return False


def _tokenize(name: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((name or "").lower()) if len(t) > 1]


# Words that don't contribute a letter to a client's initialism (SFA, SMA…).
# Connectors PLUS the generic org-type suffixes people drop when abbreviating
# ("St. Francis of Assisi Church" -> SFA, not SFAC). NOTE: "st"/"saint" are kept
# IN (they supply the leading S of SFA/SMA), so they're deliberately absent here.
_INITIALISM_STOP = {
    "of", "the", "and", "a", "an", "&", "at",
    "church", "parish", "catholic", "roman", "school", "cathedral", "basilica",
    "center", "centre", "services", "service", "company", "co", "corp", "inc",
    "llc", "ltd", "group", "comm", "community", "chapel", "ministries", "ministry",
}


def _initialism(name: str) -> str:
    """First letter of each significant word — 'St. Francis of Assisi' -> 'sfa',
    "St. Mary's of the Assumption" -> 'sma'. Lowercased; connectors dropped."""
    letters = []
    for part in re.split(r"[\s\-/&,.]+", (name or "").strip()):
        core = re.sub(r"[^a-z0-9]", "", part.lower())
        if not core or core in _INITIALISM_STOP:
            continue
        letters.append(core[0])
    return "".join(letters)


# Weight above which a token counts as saying something. The stopword cap in
# build_token_index is 0.15, and real distinctive tokens land around 3-5, so
# anything in between is noise either way.
CORROBORATION_FLOOR = 0.5


def build_token_index(client_names: dict[int, str]) -> dict:
    """
    client_names: {client_id: name}
    Returns an index with per-token document frequency and, per client, its set
    of tokens with precomputed distinctiveness weights.
    """
    df: dict[str, int] = defaultdict(int)
    client_tokens: dict[int, set[str]] = {}

    for cid, name in client_names.items():
        toks = set(_tokenize(name))
        client_tokens[cid] = toks
        for t in toks:
            df[t] += 1

    n = max(len(client_names), 1)

    def distinctiveness(tok: str) -> float:
        # Inverse-document-frequency style weight in [0, ~log n].
        # Generic/stop tokens are floored hard so they can't fingerprint.
        d = df.get(tok, 0) or 1
        w = math.log((n + 1) / d)
        if tok in _STOPish:
            w = min(w, 0.15)          # cap: present but near-worthless alone
        return w

    # Per-client distinctive mass + the weighted tokens themselves.
    client_weights: dict[int, dict[str, float]] = {}
    client_mass: dict[int, float] = {}
    for cid, toks in client_tokens.items():
        weights = {t: distinctiveness(t) for t in toks}
        client_weights[cid] = weights
        client_mass[cid] = sum(weights.values()) or 1.0

    # Per-client initialism (SFA, SMA…) + reverse map. Only 3+ letter initialisms
    # are indexed — 2-letter ones (SH, SM) collide too easily to be trustworthy.
    client_initialism: dict[int, str] = {}
    initialisms: dict[str, set] = defaultdict(set)
    for cid, name in client_names.items():
        ini = _initialism(name)
        client_initialism[cid] = ini
        if len(ini) >= 3:
            initialisms[ini].add(cid)

    # Inverted token -> client ids. A client sharing no token with the title
    # always scores zero, so this lets a scorer skip the roster instead of
    # walking every client for every block.
    token_clients: dict[str, set[int]] = defaultdict(set)
    for cid, toks in client_tokens.items():
        for t in toks:
            token_clients[t].add(cid)

    # Distinctive vs generic split per client, precomputed: _corroborated needs
    # it for every (block, rival) pair, and rebuilding these sets inside that
    # loop cost more than the scan it was filtering.
    client_distinctive: dict[int, set[str]] = {}
    client_generic: dict[int, set[str]] = {}
    for cid, weights in client_weights.items():
        client_distinctive[cid] = {t for t, w in weights.items() if w > CORROBORATION_FLOOR}
        client_generic[cid] = {t for t, w in weights.items() if w <= CORROBORATION_FLOOR}

    return {
        "df": dict(df),
        "n": n,
        "token_clients": dict(token_clients),
        "client_distinctive": client_distinctive,
        "client_generic": client_generic,
        "client_tokens": client_tokens,
        "client_weights": client_weights,
        "client_mass": client_mass,
        "distinctiveness": distinctiveness,
        "client_initialism": client_initialism,
        "initialisms": {k: v for k, v in initialisms.items()},
    }


def score_title_against_client(title_tokens: set[str], cid: int, index: dict) -> tuple[float, float, float]:
    """
    Returns (coverage, max_token_weight, abs_hit):
      coverage         = fraction of THIS client's distinctive mass present in
                         the title, in [0,1].
      max_token_weight = the single strongest distinctive token this client
                         contributed (gates against many-weak-tokens).
      abs_hit          = ABSOLUTE distinctive mass matched (not normalized).
                         "St. Anne Mother of Mary" carries far more absolute
                         mass than "St. Mary", which is how we tell a full
                         fingerprint from a thin generic one.
    """
    weights = index["client_weights"].get(cid, {})
    mass = index["client_mass"].get(cid, 1.0)
    hit = 0.0
    max_w = 0.0
    for t, w in weights.items():
        if t in title_tokens:
            hit += w
            if w > max_w:
                max_w = w
    return (hit / mass if mass else 0.0), max_w, hit


# ── Application chrome ──────────────────────────────────────────────────────
# A window title is "<document> - <application banner>". The banner is the app
# advertising itself, not evidence about the client, but it tokenizes just like
# the rest of the title — and QuickBooks' banner happens to contain a word that
# is a real client name here:
#
#   "St. Patrick's Church  - QuickBooks Accountant Desktop *Plus* 2024"
#                                                           ^^^^
#   -> scored "Inventory Plus, Inc" at abs=5.805, ABOVE the correct
#      "St. Patrick's Church" at 4.719, and the two together tripped the
#      ambiguity gate, so the block was silently booked to a third client.
#
# Stripping the banner before scoring recovered 55 mismatches over 120 days on
# org 21 and lost none.
#
# Deliberately NOT stripped: the "[Vendor Center: X]" / "[Customer Center: X]"
# segment. That is the QB vendor fingerprint Stage 4.6 uses to tell same-named
# parishes apart, and dropping it here cost 25 detections on the same window.
_APP_CHROME_RE = re.compile(r"\s*[-–]\s*QuickBooks\b[^-\[]*", re.I)


def strip_app_chrome(title: str) -> str:
    """Remove application-banner noise so only document text is scored."""
    return _APP_CHROME_RE.sub(" ", title or "")


# ── Tunables (strict defaults) ──────────────────────────────────────────────
STRONG_COVERAGE = 0.55   # winner must cover >=55% of its OWN distinctive mass
MIN_ABS_HIT = 1.6        # …and carry real absolute distinctive mass (a full
                         # name like "St Anne Mother of Mary" clears this; a
                         # thin "St. Mary" does not)
MIN_TOP_TOKEN = 0.80     # …with at least one genuinely distinctive token
COVERAGE_MARGIN = 0.30   # winner must out-cover the booked client by this
AMBIGUITY_RATIO = 0.65   # runner-up other-client's ABSOLUTE hit must be < this
                         # fraction of the winner's, else >1 client fingerprinted


def detect_mismatch(
    title: str,
    booked_cid: int,
    index: dict,
    client_names: dict[int, str],
    firm_name: str | None = None,
) -> dict | None:
    """
    Returns a mismatch record if the title fingerprints a DIFFERENT client more
    strongly than the booked one; otherwise None. Ranking is by ABSOLUTE
    distinctive mass matched, which distinguishes a full name in the title from
    a thin generic token that merely happens to be some client's main word.

    The record carries a `bucket`:
      "client"   — both sides are real external clients (billing-impacting;
                   e.g. UltraTax forward-fill). THIS is the money bucket.
      "internal" — either side is an internal/admin bucket or the firm itself
                   (real, worth seeing, but not a client billing error).
    """
    title_tokens = set(_tokenize(strip_app_chrome(title)))
    if not title_tokens:
        return None

    booked_cov, _, _ = score_title_against_client(title_tokens, booked_cid, index)

    def _acronym_match():
        """Fallback for when no distinctive WORD matched: a unique 3+ letter
        client initialism appearing as an UPPERCASE whole word in the raw title
        (e.g. 'SFA P&L 2025' booked elsewhere -> St. Francis of Assisi). The
        uppercase + uniqueness + length gates keep this conservative."""
        if booked_cov >= STRONG_COVERAGE:
            return None
        inis = index.get("initialisms") or {}
        booked_ini = (index.get("client_initialism") or {}).get(booked_cid, "")
        for tok in title_tokens:
            if len(tok) < 3 or tok == booked_ini:
                continue
            cids = inis.get(tok)
            if not cids or len(cids) != 1:
                continue                       # unknown or ambiguous initialism
            cand = next(iter(cids))
            if cand == booked_cid:
                continue                       # title initials the booked client
            if not re.search(r"\b" + re.escape(tok.upper()) + r"\b", title):
                continue                       # require the UPPERCASE acronym
            booked_name = client_names[booked_cid]
            looks_name = client_names[cand]
            bucket = (
                "internal"
                if is_internal_client(booked_name, firm_name)
                or is_internal_client(looks_name, firm_name)
                else "client"
            )
            return {
                "looks_like_client_id": cand,
                "looks_like_client_name": looks_name,
                "looks_like_coverage": 1.0,
                "looks_like_abs_hit": 0.0,
                "booked_coverage": round(booked_cov, 3),
                "runner_up_abs_hit": 0.0,
                "top_token_weight": 0.0,
                "bucket": bucket,
                "match_kind": "acronym",
                "matched_token": tok.upper(),
            }
        return None

    # Rank OTHER clients by absolute hit mass; keep top two.
    best_cid = None
    best_cov = best_topw = best_abs = 0.0
    second_abs = 0.0
    for cid in client_names:
        if cid == booked_cid:
            continue
        cov, topw, abs_hit = score_title_against_client(title_tokens, cid, index)
        if abs_hit > best_abs:
            second_abs = best_abs
            best_abs, best_cid, best_cov, best_topw = abs_hit, cid, cov, topw
        elif abs_hit > second_abs:
            second_abs = abs_hit

    if best_cid is None or best_abs <= 0:
        return _acronym_match()

    # Ambiguity gate (mass-based): if another client's absolute fingerprint is
    # nearly as strong, the title doesn't point at ONE client → suppress.
    if second_abs >= AMBIGUITY_RATIO * best_abs:
        return _acronym_match()

    # Strict strength gates.
    if (
        best_cov >= STRONG_COVERAGE
        and best_abs >= MIN_ABS_HIT
        and best_topw >= MIN_TOP_TOKEN
        and (best_cov - booked_cov) >= COVERAGE_MARGIN
    ):
        booked_name = client_names[booked_cid]
        looks_name = client_names[best_cid]
        bucket = (
            "internal"
            if is_internal_client(booked_name, firm_name)
            or is_internal_client(looks_name, firm_name)
            else "client"
        )
        return {
            "looks_like_client_id": best_cid,
            "looks_like_client_name": looks_name,
            "looks_like_coverage": round(best_cov, 3),
            "looks_like_abs_hit": round(best_abs, 3),
            "booked_coverage": round(booked_cov, 3),
            "runner_up_abs_hit": round(second_abs, 3),
            "top_token_weight": round(best_topw, 3),
            "bucket": bucket,
        }

    return _acronym_match()

# Gates for the "booked client is absent from its own title" verdict. Looser
# than detect_mismatch on purpose: this claim is only that the booking is WRONG,
# never which client is right, so it does not need to survive the ambiguity gate.
ABSENT_BOOKED_COVERAGE = 0.40   # booked covers <40% of its own distinctive mass
ABSENT_RIVAL_COVERAGE = 0.90    # …while somebody else's whole name is present


def _corroborated(title_tokens: set[str], cid: int, index: dict) -> bool:
    """Is this client's NAME in the title, or just one of its words?

    Weighted coverage cannot tell the difference. "The New School" is 94%
    covered by the single word "New" — because "the" and "school" are floored
    as generic — so the QuickBooks dialog titled "New Vendor" scores it at 94%.
    Identically, a 1040 for "MORSE, JOHN M" scores "St. John's Church" at 93%
    off the taxpayer's first name.

    A real name in a title corroborates itself, one of two ways:
      - two or more distinctive words of it appear ("St. John the Baptist"), or
      - its one distinctive word appears WITH its generic head noun
        ("Assumption" + "Church" for "Assumption Church").

    "New Vendor" carries neither "the" nor "school", and the 1040 carries
    neither "st" nor "church", so both fall away — while "Franciscan Church of
    the Assumption" still corroborates "Assumption Church".
    """
    pre = index.get("client_distinctive")
    if pre is not None:
        distinctive = pre.get(cid) or set()
        generic = index["client_generic"].get(cid) or set()
    else:                                # index predates the precomputed split
        weights = index["client_weights"].get(cid) or {}
        distinctive = {t for t, w in weights.items() if w > CORROBORATION_FLOOR}
        generic = {t for t, w in weights.items() if w <= CORROBORATION_FLOOR}

    if not distinctive or not distinctive <= title_tokens:
        return False                     # a distinctive word of the name is missing
    if len(distinctive) >= 2:
        return True
    return bool(generic & title_tokens)  # lone word needs its head noun alongside


def detect_booked_absent(
    title: str,
    booked_cid: int,
    index: dict,
    client_names: dict[int, str],
    firm_name: str | None = None,
    max_candidates: int = 3,
) -> dict | None:
    """
    "This block is on the wrong client, and I can't say which one is right."

    detect_mismatch only fires when exactly ONE other client is fingerprinted,
    so a title naming a client with same-family siblings — "Franciscan Church of
    the Assumption" against both "Assumption Church" and "St. Mary's of the
    Assumption" — trips the ambiguity gate and reports nothing, even when the
    booked client scored 0.023 and is plainly not in the title at all.

    Those are two different claims. Naming the replacement requires resolving
    the ambiguity; saying the booking is wrong does not. This returns the
    second claim, with the rival candidates listed rather than picked, so a
    human resolves the tie. Nothing here feeds reconcile — detect_title_client
    still abstains on these, which is what keeps them read-only.

    Returns {booked_coverage, candidates: [...]} or None.
    """
    title_tokens = set(_tokenize(strip_app_chrome(title)))
    if not title_tokens:
        return None

    booked_cov, _, booked_abs = score_title_against_client(
        title_tokens, booked_cid, index
    )
    if booked_cov >= ABSENT_BOOKED_COVERAGE:
        return None                      # the title does name the booked client

    # Only clients that share a token with the title can score above zero.
    token_clients = index.get("token_clients")
    if token_clients is not None:
        plausible = set()
        for tok in title_tokens:
            plausible.update(token_clients.get(tok, ()))
    else:
        plausible = client_names.keys()      # index predates token_clients

    rivals = []
    for cid in plausible:
        if cid == booked_cid or cid not in client_names:
            continue
        cov, topw, abs_hit = score_title_against_client(title_tokens, cid, index)
        if abs_hit >= MIN_ABS_HIT and topw >= MIN_TOP_TOKEN and _corroborated(
            title_tokens, cid, index
        ):
            rivals.append((cov, abs_hit, cid))
    if not rivals:
        return None

    # Ranked by COVERAGE, not absolute mass. The rest of this module ranks by
    # mass because it is picking a winner, and mass is what separates a full
    # name from a lucky generic token. Here the question is only "is somebody
    # else's whole name sitting in this title", and a longer client name can
    # carry more mass at partial coverage than a shorter one at 100%:
    # "St. Mary's of the Assumption" (cov 0.615, abs 5.412) outranks
    # "Assumption Church" (cov 1.000, abs 5.262) on mass and would have hidden
    # the fully-named rival behind the gate.
    rivals.sort(reverse=True)

    best_cov, best_abs, _ = rivals[0]
    if best_cov < ABSENT_RIVAL_COVERAGE or best_abs <= booked_abs:
        return None                      # nobody else is clearly named either

    # Always its own bucket, never folded into "internal" even when the booked
    # client is an admin bucket: these rows carry ranked `candidates` where a
    # mismatch row carries one named target, and the two shapes must not share
    # a list the UI renders. `booked_is_internal` lets the UI filter instead.
    booked_name = client_names[booked_cid]
    return {
        "booked_coverage": round(booked_cov, 3),
        "booked_abs_hit": round(booked_abs, 3),
        "bucket": "unsure",
        "booked_is_internal": is_internal_client(booked_name, firm_name),
        "candidates": [
            {
                "client_id": cid,
                "client_name": client_names[cid],
                "coverage": round(cov, 3),
                "abs_hit": round(abs_hit, 3),
            }
            for cov, abs_hit, cid in rivals[:max_candidates]
        ],
    }


def detect_title_client(
    title: str,
    index: dict,
    client_names: dict[int, str],
    firm_name: str | None = None,
    skip_internal: bool = True,
) -> dict | None:
    """
    Pure client detection from a title — NOT compared to any booked client.

    Used by the reconcile path: "does this title distinctively name a business
    client, and which one?" Unlike detect_mismatch (which only fires when the
    title names a DIFFERENT client than booked), this just returns the single
    distinctive business client the title points at, or None.

    Same strict distinctive-token discipline: strong coverage, real absolute
    mass, a genuinely distinctive top token, and no ambiguity between two
    clients. Internal/admin/firm clients are skipped by default (a title that
    only fingerprints "Internal - Tax" is not a reroute target).

    Returns {client_id, client_name, coverage, abs_hit, top_token_weight} or None.
    """
    # Same chrome strip as detect_mismatch: the row the UI shows and the target
    # reconcile writes must be derived from identical text, or the "fix" button
    # sends the block somewhere other than the name on screen.
    title_tokens = set(_tokenize(strip_app_chrome(title)))
    if not title_tokens:
        return None

    best_cid = None
    best_cov = best_topw = best_abs = 0.0
    second_abs = 0.0
    for cid, name in client_names.items():
        if skip_internal and is_internal_client(name, firm_name):
            continue
        cov, topw, abs_hit = score_title_against_client(title_tokens, cid, index)
        if abs_hit > best_abs:
            second_abs = best_abs
            best_abs, best_cid, best_cov, best_topw = abs_hit, cid, cov, topw
        elif abs_hit > second_abs:
            second_abs = abs_hit

    if best_cid is None or best_abs <= 0:
        return None

    # Ambiguity gate — must fingerprint ONE client clearly.
    if second_abs >= AMBIGUITY_RATIO * best_abs:
        return None

    # Strength gates (same bar as detect_mismatch, minus the booked comparison).
    if (
        best_cov >= STRONG_COVERAGE
        and best_abs >= MIN_ABS_HIT
        and best_topw >= MIN_TOP_TOKEN
    ):
        return {
            "client_id": best_cid,
            "client_name": client_names[best_cid],
            "coverage": round(best_cov, 3),
            "abs_hit": round(best_abs, 3),
            "top_token_weight": round(best_topw, 3),
        }
    return None