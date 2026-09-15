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

# Generic words that nonetheless say WHAT KIND of organisation this is. A
# cemetery and a church of the same saint are different clients with different
# bills, and this word is the only thing in either name that separates them.
#
# Deliberately a subset of _STOPish, not the whole of it. The rest of _STOPish
# is connectors and legal noise — "st", "the", "of", "inc" — and "st" appears in
# nearly every title in this book of business. Letting a connector stand in for
# a head noun (see _corroborated) is what rubber-stamped every "St. X" client
# that happened to share a first name with the title.
_HEAD_NOUNS = {
    "church", "parish", "cemetery", "cemeteries", "school", "chapel",
    "cathedral", "basilica", "academy", "rectory", "shrine", "seminary",
    "diocese", "ministry", "ministries", "center", "centre", "association",
    "foundation", "society", "council", "hall", "home", "clinic", "hospital",
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


# ── Plural / possessive normalisation ───────────────────────────────────────
#
# _tokenize did no normalisation at all: regex, lowercase, drop single chars.
# So a roster reading "St. Peters Church" tokenizes to `peters` while its own
# documents say "St. Peter's" -> `peter`, the two never meet, and the parish
# scores 0.09 coverage against its own file. Org 21 block 66704: the title said
# "St. Mary - St. Peter's Church", the booked parish was invisible, and
# "St Peter's Cemetery" won by default at abs 3.19 to 0.30.
#
# Renaming the client is NOT the fix — it is worse. That stray "s" was the only
# token separating the Church from the Cemetery, so spelling it "St. Peter's
# Church" makes the two collide at 94% of each other and the ambiguity gate
# abstains on everything. Measured: 2 of 4 real title spellings match today,
# 0 of 4 after such a rename.
#
# Which is why this ships with ENTITY_CLASS_SEPARATES. Collapsing the plural
# without restoring a real differentiator just trades a wrong answer for no
# answer.
#
# The stem is deliberately timid. It only ever removes ONE trailing "s", never
# from a word ending "ss" (Cross, Mass) or "us" (Jesus, Campus), and never from
# anything that would leave fewer than three characters. Applied to client
# names and titles through the same function, so both sides always agree.
NORMALIZE_PLURALS = False


def _stem(tok: str) -> str:
    if not NORMALIZE_PLURALS:
        return tok
    if len(tok) <= 3 or not tok.endswith("s") or tok.endswith(("ss", "us", "is")):
        return tok
    stem = tok[:-1]
    # NEVER stem a distinctive word into a generic one. "saints" is a real
    # fingerprint; "saint" is in _STOPish and capped at 0.15, explicitly unable
    # to identify anybody. Folding one into the other stopped "All Saints
    # Church" matching its own name — 54 detections lost on org 21 in 30 days,
    # an own-goal by exactly the mechanism this was meant to fix.
    if stem in _STOPish:
        return tok
    return stem


def _tokenize(name: str, stem: bool = True) -> list[str]:
    """Tokens for `name`. `stem=False` gives the UNSTEMMED reading, which is
    what tells us whether a match depended on stemming at all."""
    raw = [t for t in _TOKEN_RE.findall((name or "").lower()) if len(t) > 1]
    return [_stem(t) for t in raw] if stem else raw


# ── Fix 2: a bent word must carry the whole name ────────────────────────────
#
# Stemming does not only rescue "St. Peters" -> "St. Peter's". It also lets a
# generic English plural in a window title reach a client's distinctive word:
# org 21's title "Client Communications" started accusing the union local
# "Communication Workers", 314 times in 30 days, off one folded "s".
#
# Both are single-token, stem-dependent matches, so no rule about how MANY
# tokens matched can separate them. Coverage can: the rescue names the client
# in full (1.00), the false positive names half of it (0.50). So a match that
# exists only because a word was bent has to clear a much higher bar — if we
# had to change the spelling to make it fit, we want the whole name present.
STEM_COVERAGE = 0.90


def _stem_dependent(title_raw: set, cid: int, index: dict) -> bool:
    """True when this client matches only after stemming, not as written."""
    if not NORMALIZE_PLURALS:
        return False
    weights = index["client_weights"].get(cid, {})
    raw = index.get("client_tokens_raw", {}).get(cid, set())
    distinctive = {t for t, w in weights.items() if w > CORROBORATION_FLOOR}
    # What it matched as written, against what it matched once both sides were
    # folded. A difference means the fold is load-bearing.
    return bool(distinctive) and not (distinctive & raw & title_raw)


# ── Entity class ────────────────────────────────────────────────────────────
#
# A church and its cemetery share every distinctive word they have. The head
# noun is the ONLY thing separating them, and in this scorer it cannot: every
# one of these words is in _STOPish and capped at 0.15, i.e. explicitly ruled
# unable to fingerprint anybody.
#
# That cap is right for scoring — "church" must never be evidence FOR a client
# — but it is wrong for exclusion. "Cemetery" appearing in a candidate's name
# and nowhere in the title is not weak evidence, it is a contradiction.
#
# Owned here rather than in classification_service because this module is pure
# and that one needs Django; the Stage-3 classifier now imports these from here
# so both halves of the system read the same list.
EXCLUSIVE_ENTITY_CLASSES = [
    # Religious entity types
    {'church', 'cemetery', 'fund', 'foundation', 'school'},
    # Business entity types
    {'inc', 'llc', 'cemetery', 'fund'},
]

# Different words for the SAME entity class, folded before the class comparison.
# A parish school is a separate client from its church (org 21 has 790
# "St. Mary's Church Baldwinsville" and 791 "St. Mary's School Baldwinsville"),
# but its files are named "St Mary Academy JUN26 P&L" — never "School". Folding
# academy->school lets the school claim its own files AND excludes the church
# from them.
ENTITY_CLASS_SYNONYMS = {
    'academy': 'school',
    'preschool': 'school',
}

ENTITY_CLASS_SEPARATES = False


def _entity_classes(tokens) -> set:
    """The exclusive-class words present, folded through the synonyms."""
    folded = {ENTITY_CLASS_SYNONYMS.get(t, t) for t in tokens}
    out = set()
    for group in EXCLUSIVE_ENTITY_CLASSES:
        out |= (folded & group)
    return out


def _class_contradicts(title_tokens, cid: int, index: dict) -> bool:
    """True when this candidate claims an entity class the title denies.

    Only fires when BOTH sides name a class and they do not overlap — "St
    Peter's Cemetery" against a title that says Church. A title naming no class
    at all contradicts nothing, and a candidate with no class in its name (most
    businesses) is never excluded.
    """
    if not ENTITY_CLASS_SEPARATES:
        return False
    theirs = _entity_classes(index["client_tokens"].get(cid, set()))
    if not theirs:
        return False
    mine = _entity_classes(title_tokens)
    if not mine:
        return False
    return not (theirs & mine)


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
    client_tokens_raw: dict[int, set[str]] = {}

    for cid, name in client_names.items():
        toks = set(_tokenize(name))
        client_tokens[cid] = toks
        client_tokens_raw[cid] = set(_tokenize(name, stem=False))
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
        # As written, before any fold — see _stem_dependent.
        "client_tokens_raw": client_tokens_raw,
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

# Browser banners. These were NOT stripped before, and the omission cost real
# detections: a web PDF captured in Edge arrives as
#
#     "9-8-2026 St. Mary's Cemetery bills etc_.pdf and 1 more page - Work - Microsoft Edge"
#
# and the surviving word "edge" scored 5.8 distinctive mass against a client
# actually named "Cutting Edge Decks, Inc". That is not enough to WIN, but it is
# enough to look like a second opinion — so the ambiguity gate concluded the
# title fingerprinted two clients and suppressed a correct, high-confidence
# match on "St. Mary's Cemetery Bville" (7.4 mass, booked to St. Joseph's
# Church). Browser chrome cannot arbitrate between clients; it is noise, and it
# has to be gone before scoring.
#
# The optional middle group is Edge's profile segment ("- Work -", "- Personal -",
# "- Profile 1 -"). It is bounded and may not itself contain a dash, so it eats
# the profile name and never document text.
#
# Only the unambiguous multi-word banners are listed. Bare "Safari" / "Opera" /
# "Brave" are ordinary words that can legitimately end a document name, and a
# wrong strip here silently deletes evidence.
_BROWSER_CHROME_RE = re.compile(
    r"\s*[-–—]\s*(?:[^-–—]{0,40}\s*[-–—]\s*)?"
    r"(?:Microsoft\s*Edge|Google\s+Chrome|Mozilla\s+Firefox)"
    r"\s*$",
    re.I,
)

# Zero-width and other invisible characters, stripped before anything is matched
# or tokenised. Edge injects U+200B into its own banner — the real title above is
# "Microsoft\u200b Edge" — so a literal "Microsoft Edge" pattern misses it, and
# a name split by one of these tokenises as two words that match nothing. 86 of
# org 21's 4,232 committed blocks in a 30-day window carry one.
_ZERO_WIDTH = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None
)


# The QuickBooks Vendor/Customer Center segment — "[Vendor Center: Acme Supply]".
#
# This is NOT chrome and is deliberately never stripped: Stage 4.6 reads the
# vendor as a FINGERPRINT, looking it up in a vendor→client map to tell
# same-named parishes apart, and it corroborates the booked client besides.
#
# But a fingerprint and a name are different things, and scoring this segment
# as if it were the client's own name is how a VENDOR of St. Mary's Church —
# "Integrated Marketing Services, Inc." — got matched against the firm's
# client "H & B Marketing" and accused a correctly-booked block.
#
# The bracket can never name the client of a QuickBooks block, because the
# company file already does. Whatever screen is open inside St. Mary's books,
# the work is in St. Mary's books. So the segment stays in the text for every
# other purpose and is refused only as a mismatch TARGET.
#
# Measured before changing it: across every org over 180 days there is exactly
# ONE client-bucket detection on a bracket-carrying title, and it is that false
# positive. The rule costs nothing and removes it.
_CENTER_BRACKET_RE = re.compile(
    r"\[[^\]]*(?:Vendor|Customer)\s+Center\s*:[^\]]*\]", re.I
)


def _tokens_outside_center(title: str) -> set:
    """Title tokens with the QB Vendor/Customer Center segment removed."""
    return set(_tokenize(strip_app_chrome(_CENTER_BRACKET_RE.sub(" ", title or ""))))


def _named_only_in_center(title: str, cid: int, index: dict) -> bool:
    """True when this client is fingerprinted ONLY by the Center bracket.

    Re-scores the candidate against the text outside the bracket. If it can no
    longer clear the same strength gates it just cleared, the whole of its
    evidence was the vendor/customer name — which identifies somebody the
    client does business with, not the client.
    """
    if not _CENTER_BRACKET_RE.search(title or ""):
        return False
    outside = _tokens_outside_center(title)
    if not outside:
        return True
    cov, topw, abs_hit = score_title_against_client(outside, cid, index)
    return not (cov >= STRONG_COVERAGE and abs_hit >= MIN_ABS_HIT
                and topw >= MIN_TOP_TOKEN)


def strip_app_chrome(title: str) -> str:
    """Remove application-banner noise so only document text is scored."""
    text = (title or "").translate(_ZERO_WIDTH)
    # Loop: a title may carry a banner behind a profile segment behind another
    # dash. Each pass must match a browser name, so this cannot run away.
    previous = None
    while previous != text:
        previous = text
        text = _BROWSER_CHROME_RE.sub("", text)
    return _APP_CHROME_RE.sub(" ", text)


# ── Tunables (strict defaults) ──────────────────────────────────────────────
STRONG_COVERAGE = 0.55   # winner must cover >=55% of its OWN distinctive mass
MIN_ABS_HIT = 1.6        # …and carry real absolute distinctive mass (a full
                         # name like "St Anne Mother of Mary" clears this; a
                         # thin "St. Mary" does not)
MIN_TOP_TOKEN = 0.80     # …with at least one genuinely distinctive token
COVERAGE_MARGIN = 0.30   # winner must out-cover the booked client by this
AMBIGUITY_RATIO = 0.65   # runner-up other-client's ABSOLUTE hit must be < this
                         # fraction of the winner's, else >1 client fingerprinted

# ── Who counts as a second opinion ──────────────────────────────────────────
#
# The ambiguity gate above is the right instinct — a title that fingerprints two
# clients should name neither — but it was weighing a rival that is not a rival.
#
# `_named_only_in_center` already refuses a client whose entire case is the QB
# "[Vendor Center: X]" / "[Customer Center: X]" tag: that names somebody the
# client does business with, not the client. But it ran ONLY on the winner, and
# ONLY after the ambiguity gate. So a vendor could never be chosen, yet could
# still out-shout the client the document was about and veto it:
#
#   "ST. FRANCIS XAVIER (Secondary) - QuickBooks … - [Vendor Center: DIOCESE OF
#    SYRACUSE.]"
#     St. Francis Xavier Church  abs 6.42
#     Diocese of Syracuse        abs 6.42   <- entirely from inside the bracket
#     -> 100% of the winner, gate trips, detection discarded.
#
# Same shape as the Edge-banner bug (PR #405): noise never has to WIN to do
# damage, it only has to look like a second opinion. A suspicious silence means
# a suppressor, not an absence.
#
# So a center-only client is dropped from the ranking entirely — it can neither
# win nor suppress. Everything else about the gate is untouched: where two real
# clients are both named, the title still fingerprints neither.
#
# NOT DONE, deliberately: same-family specificity ("Sacred Heart Church" losing
# to "Sacred Heart & St. Mary's Church" the way Stage 3's `[STAGE-3-DOMINATION]`
# does it). It was built and dropped — on realistic rosters the IDF weighting
# already puts a strictly-shorter sibling under the 65% gate on its own, and
# where a sibling DOES tie it ties because it matched the identical token set,
# which is genuine ambiguity that should abstain. It changed no outcome worth
# having. classification_service.py's note about deferring it still stands.
#
# DEFAULT OFF: demonstrated on constructed rosters, not yet on org 21's real
# one. Measure first, then flip:
#   manage.py shadow_title_specificity --org 21 --explain <block_id>
#   manage.py shadow_title_specificity --org 21 --days 120
CENTER_ONLY_CANNOT_SUPPRESS = False  # a client named only inside [Vendor
                                     # Center: X] is not a second opinion

# ── A partial match is not a second opinion to a complete one ───────────────
#
# The ambiguity gate ranks on ABSOLUTE distinctive mass. That is right for
# picking a winner and wrong for deciding whether the title is ambiguous,
# because a long name sharing a common prefix carries a lot of mass while
# naming almost none of itself. Org 21 block 70787, from the real roster:
#
#   "Church of Sacred Heart and St. Mary (Secondary) - QuickBooks …"
#     abs  cov
#   12.38 1.00  Sacred Heart & St. Mary's Church        <- every word present
#    8.99 0.43  Basilica of The Sacred Heart of Jesus   = 73% -> gate trips
#    8.84 0.60  Sacred Heart- Cicero
#    8.84 0.65  Sacred Heart Parish-Rome
#
# "Basilica", "Jesus", "Cicero" and "Rome" appear nowhere in that title. Those
# three cannot win — they fail the coverage gate — yet they were enough to make
# the detector say the title names nobody, on a title that spells one client
# out in full. The firm reads "Church of Sacred Heart and St. Mary" and sees an
# obvious answer; the machine saw four Sacred Hearts and shrugged.
#
# So: when the title contains the WHOLE of one client's name, a client whose
# name is only partly there is a subset reading of the same words, not a rival
# interpretation. It stops being allowed to veto.
#
# Deliberately narrow. Both conditions must hold — the winner fully named AND
# the rival well short of it — so a genuine tie between two fully-named clients
# still abstains, and a bare "Sacred Heart" title (where nobody reaches full
# coverage) still abstains. Those are the two abstentions worth keeping and
# they are pinned as tests.
FULLY_NAMED = 0.95       # "the title contains this client's entire name"
FULL_NAME_BEATS_PARTIAL = False


def _is_magnet(winner: int, rival: int, index: dict) -> bool:
    """Is "fully named" meaningless for this winner against this rival?

    Two ways it can be, both found in org 21's first run of this rule, where
    35 of 35 new accusations were one or the other:

    1. THE WINNER IS THE RIVAL'S GENERIC FORM. Every distinctive word the
       winner has, the rival also has — "Christ our Hope Church" inside
       "Christ our Hope Church-Boonville", "St. Patrick's Church" inside
       "St Patrick's Jordan Cemetery". A title saying only the shared part
       fully names the short one by construction, so the short one wins every
       time and becomes a magnet for its whole family's work. That is not a
       complete match beating a partial one, it is the ambiguity the gate
       exists for.

    2. THE WINNER HAS ONE DISTINCTIVE WORD. Coverage is a fraction of a
       client's OWN distinctive mass, so a client whose mass is a single token
       is "fully named" by any title mentioning it. 21% of org 21's roster is
       in this position (see the attribution audit). "St. Patrick's Church"
       reduces to {patrick}, and every Patrick in the firm fully names it.

    The case this rule is actually for survives both: "Sacred Heart & St.
    Mary's Church" carries {sacred, heart, mary}, and "mary" appears in
    neither "Sacred Heart- Cicero" nor "Basilica of The Sacred Heart of
    Jesus", so it is nobody's generic form.
    """
    weights = index["client_weights"]
    w_dist = {t for t, x in weights.get(winner, {}).items()
              if x > CORROBORATION_FLOOR}
    if len(w_dist) < 2:
        return True
    r_dist = {t for t, x in weights.get(rival, {}).items()
              if x > CORROBORATION_FLOOR}
    return w_dist <= r_dist


def rank_rivals(title, title_tokens, index, cids, booked_cid=None):
    """Score `cids` against the title; return (best, second_abs).

    best is (cid, coverage, top_token_weight, abs_hit), or None when the title
    must not be allowed to name anybody. `second_abs` is the strongest hit among
    candidates the ambiguity gate is entitled to weigh.

    A bracket-only client may never WIN — that has always been true and is not
    behind the flag. What the flag changes is whether it may SUPPRESS.
    """
    scored = []
    for cid in cids:
        cov, topw, abs_hit = score_title_against_client(title_tokens, cid, index)
        if abs_hit > 0:
            scored.append((abs_hit, cid, cov, topw))
    if not scored:
        return None, 0.0
    scored.sort(key=lambda r: (-r[0], r[1]))

    has_center = bool(_CENTER_BRACKET_RE.search(title or ""))

    def _center_only(cid):
        return has_center and _named_only_in_center(title, cid, index)

    title_raw = set(_tokenize(strip_app_chrome(title), stem=False))

    def _excluded(cid, cov=None):
        # Three independent reasons a candidate is not a rival: its whole case
        # is the QB Center bracket; it claims an entity class the title denies;
        # or it only fits after a word was bent and it does not name the client
        # in full.
        if _center_only(cid) or _class_contradicts(title_tokens, cid, index):
            return True
        if cov is not None and cov < STEM_COVERAGE \
                and _stem_dependent(title_raw, cid, index):
            return True
        return False

    if not (CENTER_ONLY_CANNOT_SUPPRESS or ENTITY_CLASS_SEPARATES
            or FULL_NAME_BEATS_PARTIAL):
        # Today's behaviour, preserved exactly: rank everything, refuse only if
        # the WINNER turns out to be bracket-only. (The old code ran that check
        # after the ambiguity gate; both paths refuse identically, so moving it
        # earlier changes nothing but the number of re-scores.)
        best = scored[0]
        second_abs = scored[1][0] if len(scored) > 1 else 0.0
        if _center_only(best[1]):
            return None, 0.0
        return (best[1], best[2], best[3], best[0]), second_abs

    # Flag on. A bracket-only client is not a candidate at all, so it can
    # neither win nor stand in front of the client the document is about.
    # Filtering is lazy — `_named_only_in_center` re-scores, and only the top
    # few candidates can ever matter.
    best, rest = None, []
    for i, row in enumerate(scored):
        if _excluded(row[1], row[2]):
            continue
        best, rest = row, scored[i + 1:]
        break
    if best is None:
        return None, 0.0

    best_abs = best[0]

    # THE COMPARISON THE RIVAL LOOP CANNOT MAKE. detect_mismatch excludes the
    # booked client from the candidates by design, so if the winner is the
    # BOOKED client's own generic form — "Christ our Hope Church" winning on a
    # block booked to "Christ our Hope Church-Boonville" — no rival comparison
    # will ever reveal it, and the short name accuses its own longer sibling.
    # Twelve of eighteen new accusations in org 21's second run of this rule
    # were that one pair. Checked once, against the booking, before the loop.
    allow_full_name = (
        FULL_NAME_BEATS_PARTIAL
        and best[2] >= FULLY_NAMED
        and not (booked_cid and _is_magnet(best[1], booked_cid, index))
    )

    second_abs = 0.0
    for abs_hit, cid, _cov, _topw in rest:
        # Below the gate's threshold a candidate cannot change the verdict, so
        # it is taken as the runner-up without paying for the filter. That keeps
        # the reported `runner_up_abs_hit` honest rather than collapsing it to
        # zero whenever the strongest rival happened to be filtered out.
        if abs_hit >= AMBIGUITY_RATIO * best_abs:
            if _excluded(cid, _cov):
                continue
            # The winner's whole name is in this title and this rival's is not,
            # by a wide margin. Same words, less of them — a subset reading,
            # not a competing one.
            if (allow_full_name
                    and _cov <= best[2] - COVERAGE_MARGIN
                    and not _is_magnet(best[1], cid, index)):
                continue
        second_abs = abs_hit
        break                # sorted: the first survivor is the strongest

    return (best[1], best[2], best[3], best_abs), second_abs


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

    # Rank OTHER clients by absolute hit mass. `rank_rivals` drops the two
    # kinds of candidate that are not second opinions (a client's own shorter
    # self, and a name that exists only inside the QB Center bracket) before
    # the ambiguity gate weighs them — see the note above it.
    best, second_abs = rank_rivals(
        title, title_tokens, index,
        [cid for cid in client_names if cid != booked_cid],
        booked_cid=booked_cid)

    if best is None:
        return _acronym_match()
    best_cid, best_cov, best_topw, best_abs = best

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
    # A lone distinctive word needs its HEAD NOUN alongside — the word that says
    # what kind of organisation this is. Any generic token used to count, and
    # "st" is generic: "St. John's Church" is {john, church, st}, so a title
    # reading "St. John's CEMETERY bills" corroborated the CHURCH off the shared
    # "st" and won at 97% coverage, while the real St John Cemetery never
    # surfaced. A connector cannot stand in for the head noun.
    return bool(generic & _HEAD_NOUNS & title_tokens)


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

    # Same ranking discipline as detect_mismatch, through the same helper, so
    # the row the UI shows and the target the reconcile button re-derives can
    # never disagree about who the runner-up was.
    best, second_abs = rank_rivals(
        title, title_tokens, index,
        [cid for cid, name in client_names.items()
         if not (skip_internal and is_internal_client(name, firm_name))])

    if best is None:
        return None
    best_cid, best_cov, best_topw, best_abs = best

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