"""
Inline alias suggestion — mine one alias candidate from a block the user just
corrected, so the correction teaches future auto-classification instead of
having to be repeated.

Shared by:
  - recategorize_block (offers the candidate inline right after a single move)
  - the suggest_aliases management command (batch/CLI form of the same idea)

Human-in-the-loop and safe: a person made the correction and a person approves
the alias. Extraction reuses the classifier's normalize + safety gates; the
collision guard mirrors alias_derivation so an offered alias can never match a
sibling client (the multi-parish poisoning we guard against elsewhere).
"""
import re
from typing import Optional

# alias_derivation is pure (no Django) — safe to import at module load, which
# keeps alias_is_safe_to_add() importable without the app registry. The heavy
# classifier is imported lazily (see _C) only where its normalize gates are
# actually needed.
from tracker.services.alias_derivation import (
    MIN_ALIAS_LEN, _collapse_ws, _distinctive_token_sig, _entity_aware_token_sig,
)


def _C():
    """Lazy handle to the classifier (a 5.7k-line module that pulls in Django
    models). Deferred so importing this module — and running the collision
    guard — doesn't require the full app registry."""
    from tracker.services.classification_service import ClassificationService
    return ClassificationService

# strip app/window chrome from a title to get the work "subject" (client name)
_APP_TAIL = re.compile(
    r'\s*[-|]\s*(quickbooks|excel|adobe acrobat|acrobat|word|outlook|microsoft'
    r'|message \(html\)|google|work|search|yahoo|yelp|msn|file explorer|adobe'
    r'|reader|\d+ more).*$', re.I)
_DOC_EXT = re.compile(r'\.(pdf|xlsx?|xlsm|xlsb|docx?|csv|pptx?)\b.*$', re.I)
_PAREN = re.compile(r'\s*\((primary|secondary)\)\s*', re.I)
# Trailing year / quarter / fiscal-period noise ("Smith Combined 2023",
# "Acme Q1 2024", "Wexford FY2023"). Stripped so the alias is reusable across
# periods instead of matching only one year's file.
_TRAIL_PERIOD = re.compile(
    r'[\s_\-]+(?:q[1-4][\s_\-]*)?(?:fy[\s_\-]*)?(?:19|20)\d{2}$', re.I)
_GENERIC_SUBJ = {
    'home', 'documents', 'document', 'book1', 'untitled', 'downloads', 'desktop',
    'new tab', 'settings', 'all', 'office', 'inbox', 'save as', 'move or copy',
    'open', 'print', 'preview',
}


def _subject(title: str) -> str:
    t = _C()._strip_qb_screen_bracket(title or '')
    t = _APP_TAIL.sub('', t)
    t = _DOC_EXT.sub('', t)
    t = _PAREN.sub(' ', t)
    t = _TRAIL_PERIOD.sub('', t)
    return re.sub(r'\s+', ' ', t).strip()


def _is_distinctive(subj: str) -> bool:
    n = _C()._normalize_name(subj)
    if not n or n in _GENERIC_SUBJ or len(n) < 5:
        return False
    toks = n.split()
    return len(toks) >= 2 and any(len(t) >= 4 for t in toks)


def suggest_alias_for_block(block, client) -> Optional[str]:
    """The distinctive title "subject" worth remembering as an alias for
    `client`, or None if the title isn't distinctive, already matches the
    client, or is already one of its aliases.

    Does NOT run the sibling-collision gate — any caller that PERSISTS the
    result must also pass it through alias_is_safe_to_add().
    """
    C = _C()
    subj = _subject(getattr(block, 'window_title', '') or '')
    if not _is_distinctive(subj):
        return None
    names = [client.name] + list(client.aliases or [])
    if any(C._alias_matches_safely(n.lower(), subj.lower()) for n in names):
        return None  # already matches — no alias needed
    if C._normalize_name(subj) in {C._normalize_name(n) for n in names}:
        return None  # already an alias
    return subj


def alias_is_safe_to_add(candidate: str, client, siblings) -> bool:
    """True if `candidate` can be added to `client` without colliding with a
    sibling. `siblings` is an iterable of Client rows in the same org (it may
    include `client` itself — that row is skipped).

    Mirrors alias_derivation's guards: reject too-short aliases, aliases equal
    to another client's name, and aliases whose distinctive tokens are a subset
    of a sibling's name signature (the multi-parish case).

    Uses the ENTITY-AWARE signature so the entity head-noun (church/cemetery/
    school…) counts as a differentiator: 'St John Cemetery' is allowed even
    when 'St John's Church' exists, because the head-noun tells them apart.
    Two SAME-type siblings still collide (they share the head-noun), and a bare
    'St John' (no head-noun) still reads as an ambiguous subset of both.
    """
    cand = _collapse_ws(candidate or '')
    if len(cand) < MIN_ALIAS_LEN:
        return False
    cand_key = cand.lower()
    cand_sig = _entity_aware_token_sig(cand)
    for s in siblings:
        if s.id == client.id:
            continue
        if _collapse_ws(s.name).lower() == cand_key:
            return False  # equals another client's name → would match them
        if cand_sig and cand_sig <= _entity_aware_token_sig(s.name):
            return False  # can't tell this alias apart from the sibling
    return True
