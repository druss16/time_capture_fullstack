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

    return {
        "df": dict(df),
        "n": n,
        "client_tokens": client_tokens,
        "client_weights": client_weights,
        "client_mass": client_mass,
        "distinctiveness": distinctiveness,
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
    title_tokens = set(_tokenize(title))
    if not title_tokens:
        return None

    booked_cov, _, _ = score_title_against_client(title_tokens, booked_cid, index)

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
        return None

    # Ambiguity gate (mass-based): if another client's absolute fingerprint is
    # nearly as strong, the title doesn't point at ONE client → suppress.
    if second_abs >= AMBIGUITY_RATIO * best_abs:
        return None

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
    return None

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
    title_tokens = set(_tokenize(title))
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