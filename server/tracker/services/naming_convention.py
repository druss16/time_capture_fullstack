"""
Read an agency's file-naming convention: CLIENTCODE_[date_]ClientName_ProjectName_...

More Than Cars names every file the same way —

    ACM_AcmeMotors_SpringLaunch_Storyboard_v3.psd
    ACM_Acme Motors_Spring Launch_hero.ai
    acm_acme-motors_website-refresh_sitemap – Figma

— so the name of the file in front of someone states the client AND the
project outright. That is not a guess from fuzzy text; it is the firm's own
filing system, as deliberate as a law firm's matter number. So it outranks
every inference tier, and it may correct a client the classifier only guessed.

MATCHING
--------
Underscores separate segments. Inside a segment, spelling of the same name
varies (CamelCase, hyphens, spaces), so names are compared COMPACT: lowercase
letters and digits only — "SpringLaunch", "Spring-Launch" and "spring launch"
are the same name.

  client  — segment 1 equal to a client's code (or its QuickBooks Time short
            code), and/or the first NAME segment after it equal to a client's
            name or alias. Dates and versions ("2026-09", "2026", "v3") are
            skipped wherever they sit, so CODE_2026-09_Name_Project reads the
            same as CODE_Name_Project.
  short   — when segment 1 is shaped like a client number (a known code, or
            2-6 digits), the name may be shortened word by word: "Easterns-Auto"
            and "Easterns-Auto-Group" both name "Easterns Automotive Group".
            The first word must match whole, and a short name that fits two
            clients names neither.
  project — a LATER segment equal to one of THAT client's live projects. Never
            another client's: two clients both have a "Website Refresh".

A two-segment folder (CODE_Name, e.g. "0074_Easterns-Auto-Group") names a
client only when it is unmistakable: the code and the name agree, or a
client-number code sits in front of a name of two or more words.

Nothing here is per-firm configuration. Real layouts seen so far:

    ACM_AcmeMotors_SpringLaunch_Storyboard_v3.psd
    Client-Work_2026/0074_Easterns-Auto-Group/0074_2026-09_Easterns-Auto_Collision-Flyer/hero.psd

Anything that does not resolve to exactly one answer abstains. A code shared by
two clients identifies neither; a file naming two of a client's projects names
neither. Abstaining costs a Daily Review pick; guessing bills the wrong client.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

_COMPACT = re.compile(r'[^a-z0-9]+')
# A token is a run of non-space characters containing underscores. Path
# separators split tokens too, so a folder and a file are read independently.
_TOKEN = re.compile(r'[^\s/\\]+')
# Trailing extension or app decoration that is not part of the name.
_EXTENSION = re.compile(r'\.[A-Za-z0-9]{1,5}$')

MIN_SEGMENTS = 3        # client code, client name, project — at least
MIN_COMPACT = 2         # "a" is not a client code

# Segments that are never a name: dates and versions. A bare 4-digit client
# number ("0074") is not a year, so years are 19xx/20xx only.
_NOISE = re.compile(
    r'^(?:(?:19|20)\d{2}(?:[-.]?\d{1,2}){0,2}|\d{1,2}[-.](?:19|20)\d{2}'
    r'|v\d+|rev\d+|r\d+|final|draft|copy)$', re.I)
# A client-number code: the shape that makes a shortened name trustworthy.
_NUMBER_CODE = re.compile(r'^\d{2,6}$')
_WORD_SPLIT = re.compile(r'[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])')


def compact(text: str) -> str:
    return _COMPACT.sub('', (text or '').lower())


def words(text: str) -> list[str]:
    """'Easterns-Auto', 'EasternsAuto' and 'Easterns Auto' -> ['easterns', 'auto']."""
    return [w.lower() for w in _WORD_SPLIT.split(text or '') if w]


def is_noise(seg: str) -> bool:
    return bool(_NOISE.match((seg or '').strip()))


def tokens(text: str, min_segments: int = MIN_SEGMENTS) -> list[list[str]]:
    """Every underscore-separated name in `text`, as its segments."""
    out = []
    for raw in _TOKEN.findall(text or ''):
        raw = _EXTENSION.sub('', raw)
        if raw.count('_') < min_segments - 1:
            continue
        segs = [s for s in raw.split('_') if s]
        if len(segs) >= min_segments:
            out.append(segs)
    # Window titles keep spaces inside a name ("ACM_Acme Motors_Spring
    # Launch_hero.ai"), which the token split breaks apart. Read the whole
    # title as one name too, cut at the usual app decorations.
    whole = re.split(r'\s+[@–—-]\s+|\s+\(', text or '')[0]
    whole = _EXTENSION.sub('', whole.replace('\\', '/').rsplit('/', 1)[-1].strip())
    if whole.count('_') >= min_segments - 1:
        segs = [s.strip() for s in whole.split('_') if s.strip()]
        if len(segs) >= min_segments and segs not in out:
            out.append(segs)
    return out


@dataclass
class ConventionIndex:
    client_by_code: dict           # compact code -> client_id (unambiguous only)
    client_by_name: dict           # compact name/alias -> client_id (unambiguous only)
    project_by_client: dict        # client_id -> {compact project name: project_id}
    # first word -> [(words, client_id)], for shortened names. Bucketed so a
    # lookup reads one first word's names, not every client the firm has.
    names_by_first_word: dict = None

    def __bool__(self):
        return bool(self.client_by_code or self.client_by_name)


def build_index(clients, codes_extra=(), projects=()) -> ConventionIndex:
    """
    clients      — iterable of (client_id, name, code, aliases)
    codes_extra  — iterable of (client_id, code) from integrations (QB Time short codes)
    projects     — iterable of (project_id, client_id, name), live projects only
    """
    codes, names = defaultdict(set), defaultdict(set)
    by_first = defaultdict(list)
    for cid, name, code, aliases in clients:
        if len(compact(code)) >= MIN_COMPACT:
            codes[compact(code)].add(cid)
        for n in [name, *(aliases or [])]:
            if len(compact(n)) >= 3:
                names[compact(n)].add(cid)
                w = words(n)
                if w:
                    by_first[w[0]].append((tuple(w), cid))
    for cid, code in codes_extra:
        if len(compact(code)) >= MIN_COMPACT:
            codes[compact(code)].add(cid)

    per_client = defaultdict(lambda: defaultdict(set))
    for pid, cid, name in projects:
        if len(compact(name)) >= 3:
            per_client[cid][compact(name)].add(pid)

    return ConventionIndex(
        client_by_code={k: next(iter(v)) for k, v in codes.items() if len(v) == 1},
        client_by_name={k: next(iter(v)) for k, v in names.items() if len(v) == 1},
        project_by_client={
            cid: {k: next(iter(v)) for k, v in m.items() if len(v) == 1}
            for cid, m in per_client.items()
        },
        names_by_first_word=dict(by_first),
    )


def _short_name_client(seg: str, index: ConventionIndex):
    """
    The one client whose name `seg` shortens word by word, or None.

    'Easterns-Auto' -> 'Easterns Automotive Group': the first word whole, each
    later word a prefix of the name's word in the same place. Returns
    (client_id, words matched).
    """
    w = words(seg)
    if not w or len(compact(seg)) < 5:
        return None
    hits = set()
    for name_words, cid in (index.names_by_first_word or {}).get(w[0], ()):
        if len(w) <= len(name_words) and all(
                nw.startswith(sw) for sw, nw in zip(w[1:], name_words[1:])):
            hits.add(cid)
    return (next(iter(hits)), len(w)) if len(hits) == 1 else None


def resolve_segments(segs: list[str], index: ConventionIndex):
    """(client_id, project_id|None) for one name, or None."""
    by_code = index.client_by_code.get(compact(segs[0]))
    code_shaped = bool(by_code) or bool(
        _NUMBER_CODE.match(segs[0].strip()) and not is_noise(segs[0]))
    # Dates and versions can sit anywhere ("0074_2026-09_Easterns-Auto_...").
    rest = [s for s in segs[1:] if not is_noise(s)]
    if not rest:
        return None
    name_seg = rest[0]
    by_name = index.client_by_name.get(compact(name_seg))
    short = None
    if not by_name and code_shaped:
        short = _short_name_client(name_seg, index)
        by_name = short[0] if short else None
    if len(segs) == 2:
        # CODE_Name alone (a client folder) — only when it is unmistakable.
        unmistakable = code_shaped and (
            (by_code and by_code == by_name)
            or (not by_code and by_name and (short is None or short[1] >= 2)))
        if not unmistakable:
            return None
    if by_code and by_name and by_code != by_name:
        return None                      # the code and the name disagree
    client_id = by_code or by_name
    if not client_id:
        return None
    projects = index.project_by_client.get(client_id, {})
    later_segs = rest[1:]
    later = [compact(s) for s in later_segs]
    # A project name can itself contain an underscore-free run of words, but
    # some people split it ("Spring_Launch"); try adjacent pairs too.
    later += [compact(a + b) for a, b in zip(later_segs, later_segs[1:])]
    hits = {projects[c] for c in later if c in projects}
    if len(hits) > 1:
        return client_id, None           # names two projects — client only
    return client_id, (next(iter(hits)) if hits else None)


def resolve_text(texts, index: ConventionIndex):
    """
    (client_id, project_id|None, which) from the first field that names a
    client by convention, or None. `texts` is [(field, text), ...] in priority
    order. Fields that disagree about the client abstain entirely.
    """
    found = []
    for field, text in texts:
        for segs in tokens(text, min_segments=2):
            r = resolve_segments(segs, index)
            if r:
                found.append((r[0], r[1], field))
    if not found:
        return None
    if len({c for c, _p, _f in found}) > 1:
        return None
    with_project = [f for f in found if f[1]]
    if len({p for _c, p, _f in with_project}) > 1:
        return found[0][0], None, found[0][2]
    return with_project[0] if with_project else found[0]
