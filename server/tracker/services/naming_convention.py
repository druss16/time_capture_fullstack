"""
Read an agency's file-naming convention: CLIENTCODE_ClientName_ProjectName_...

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
            code), else segment 2 equal to a client's name or an alias.
  project — a LATER segment equal to one of THAT client's live projects. Never
            another client's: two clients both have a "Website Refresh".

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


def compact(text: str) -> str:
    return _COMPACT.sub('', (text or '').lower())


def tokens(text: str) -> list[list[str]]:
    """Every underscore-separated name in `text`, as its segments."""
    out = []
    for raw in _TOKEN.findall(text or ''):
        raw = _EXTENSION.sub('', raw)
        if raw.count('_') < MIN_SEGMENTS - 1:
            continue
        segs = [s for s in raw.split('_') if s]
        if len(segs) >= MIN_SEGMENTS:
            out.append(segs)
    # Window titles keep spaces inside a name ("ACM_Acme Motors_Spring
    # Launch_hero.ai"), which the token split breaks apart. Read the whole
    # title as one name too, cut at the usual app decorations.
    whole = re.split(r'\s+[@–—-]\s+|\s+\(', text or '')[0]
    whole = _EXTENSION.sub('', whole.replace('\\', '/').rsplit('/', 1)[-1].strip())
    if whole.count('_') >= MIN_SEGMENTS - 1:
        segs = [s.strip() for s in whole.split('_') if s.strip()]
        if len(segs) >= MIN_SEGMENTS and segs not in out:
            out.append(segs)
    return out


@dataclass
class ConventionIndex:
    client_by_code: dict           # compact code -> client_id (unambiguous only)
    client_by_name: dict           # compact name/alias -> client_id (unambiguous only)
    project_by_client: dict        # client_id -> {compact project name: project_id}

    def __bool__(self):
        return bool(self.client_by_code or self.client_by_name)


def build_index(clients, codes_extra=(), projects=()) -> ConventionIndex:
    """
    clients      — iterable of (client_id, name, code, aliases)
    codes_extra  — iterable of (client_id, code) from integrations (QB Time short codes)
    projects     — iterable of (project_id, client_id, name), live projects only
    """
    codes, names = defaultdict(set), defaultdict(set)
    for cid, name, code, aliases in clients:
        if len(compact(code)) >= MIN_COMPACT:
            codes[compact(code)].add(cid)
        for n in [name, *(aliases or [])]:
            if len(compact(n)) >= 3:
                names[compact(n)].add(cid)
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
    )


def resolve_segments(segs: list[str], index: ConventionIndex):
    """(client_id, project_id|None) for one name, or None."""
    by_code = index.client_by_code.get(compact(segs[0]))
    by_name = index.client_by_name.get(compact(segs[1]))
    if by_code and by_name and by_code != by_name:
        return None                      # the code and the name disagree
    client_id = by_code or by_name
    if not client_id:
        return None
    projects = index.project_by_client.get(client_id, {})
    later = [compact(s) for s in segs[2:]]
    # A project name can itself contain an underscore-free run of words, but
    # some people split it ("Spring_Launch"); try adjacent pairs too.
    later += [compact(a + b) for a, b in zip(segs[2:], segs[3:])]
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
        for segs in tokens(text):
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
