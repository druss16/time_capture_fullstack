"""
Which TimeTracker project — or at least which client — an Asana project is.

An agency's project list lives in QuickBooks Time AND in Asana, typed twice by
hand. More Than Cars' two lists are "identical" the way people mean it, not
the way a string compare does (real pairs, 2026-10-08):

    QuickBooks Time / TimeTracker              Asana
    CarNow Showroom Deal Maker UX Video        CarNow: Showroom Dealmaker UX Video
    DeNooyer 250th Email                       DeNooyer: 250 Email
    DeNooyer Website & Asset Color Revisions   DeNooyer: Website and Asset Color Revision
    MTCM NY Auto Forum Event Coverage          MTC Media - NY Auto Forum Event Coverage
    Easterns Nissan White Marsh Website Updates
                                Easterns Auto Group: Nissan of White Marsh Website Update

and the client is written in whatever short form the agency says out loud —
"DeNooyer" for Robert DeNooyer Chevrolet, "Fredy Chevy" for Fredericktown
Chevrolet — the same short form its own QuickBooks Time project names use.

So, in order:

  1. the whole name is a project's name, once both are canonical (case, "&",
     plurals, "250th", bracketed asides, spacing);
  2. the part before ":" / " - " names candidate clients: by full name (legal
     suffix aside), alias, abbreviation, the first words of the name, or a
     short form LEARNED from that client's own project names ("DeNooyer
     250th Email" teaches "denooyer"). "Tom Gill" can be two clients;
  3. the rest is scored against those clients' projects, the client part of
     each project's name set aside. The best must be close (CLOSE) and clearly
     ahead of the next (MARGIN), and any numbers must agree — "Q3 Production"
     is never "Q4 Production". The project decides the client, so an
     ambiguous "Tom Gill" resolves when exactly one of its projects fits;
  4. one candidate client and no project fits: the client alone. Asana time
     then lands on the right client and asks only for the project;
  5. no client part, or no candidate: the whole name against every project,
     stricter (GLOBAL_CLOSE).

A wrong project bills the wrong work, so every step abstains rather than
guesses: ties, near-ties and number mismatches link nothing.

Two things outrank the name's own client part, when present:

  * a choice an operator made in the onboarding link report (AsanaNameMap:
    "DeNooyer" -> Robert DeNooyer Chevrolet, or "not a client");
  * what Asana says: a project custom field named Client / Customer /
    Account, else the project's team, when it names one client.
"""
import re
from difflib import SequenceMatcher

_SPLIT = re.compile(r'\s*:\s*|\s+-\s+|(?<=\w)-\s+')
_PARENS = re.compile(r'\([^)]*\)')
_ORDINAL = re.compile(r'\b(\d+)(?:st|nd|rd|th)\b')
_LEGAL = {'inc', 'llc', 'co', 'corp', 'corporation', 'ltd', 'the', 'company'}

CLOSE = 0.88          # a candidate client's project
GLOBAL_CLOSE = 0.93   # any project, no client to narrow it
MARGIN = 0.06         # the best must beat the runner-up by this much
MIN_SHORT_FORM = 3    # letters in a learned client short form


def _norm(text: str) -> str:
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).split())


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith('s') and not word.endswith('ss') else word


def canon(text: str) -> str:
    """'DeNooyer Website & Asset Color Revisions (v2)' -> 'denooyer website and
    asset color revision'."""
    t = (text or '').lower().replace('&', ' and ')
    t = _PARENS.sub(' ', t)
    t = _ORDINAL.sub(r'\1', t)
    return ' '.join(_stem(w) for w in _norm(t).split())


def _compact(text: str) -> str:
    return canon(text).replace(' ', '')


def _numbers(text: str) -> frozenset:
    return frozenset(w for w in canon(text).split() if any(ch.isdigit() for ch in w))


def split_name(name: str):
    """('Tom Gill', 'CDP Email Journeys') for 'Tom Gill: CDP Email Journeys',
    or (None, name) when it has no client part."""
    parts = _SPLIT.split(name or '', maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return None, (name or '').strip()


def _word_prefix(part_words, client_words) -> bool:
    """'easterns auto' starts 'easterns automotive group': same first word,
    each later word a prefix of the client's word in the same place."""
    if not part_words or len(part_words) > len(client_words) or part_words[0] != client_words[0]:
        return False
    return all(cw.startswith(pw) for pw, cw in zip(part_words[1:], client_words[1:]))


def _score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a.replace(' ', '') == b.replace(' ', ''):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


class Matcher:
    """Built once per sync from the firm's clients and projects."""

    def __init__(self, clients, projects, name_map=None):
        """clients: objects with id, name, aliases (+ email, alias_sources);
        projects: objects with id, name, client_id, is_active;
        name_map: {canonical prefix: client, or None for "not a client"}."""
        self.name_map = dict(name_map or {})
        from tracker.services.alias_derivation import usable_aliases
        from tracker.services.matter_attribution import client_abbreviations
        self.projects = list(projects)
        self.by_client = {}
        for p in self.projects:
            self.by_client.setdefault(p.client_id, []).append(p)

        # Every way a client is written, canonical, longest first so a
        # project name loses its longest client prefix.
        self.keys = {}
        for c in clients:
            full = canon(c.name)
            bare = ' '.join(w for w in full.split() if w not in _LEGAL)
            keys = {full, bare} | {canon(a) for a in usable_aliases(c)} \
                | {canon(a) for a in client_abbreviations(c.name)}
            self.keys[c.id] = (c, {k for k in keys if k})
        self._learn_short_forms()
        # Canonical forms computed once. Recomputing them inside every match
        # made a 3,655-project sync score 478 projects x millions of times.
        self._canon = {p.id: canon(p.name) for p in self.projects}
        self._by_canon = {}
        for p in self.projects:
            self._by_canon.setdefault(self._canon[p.id], []).append(p)
        self._rest = {p.id: self._strip_client(p) for p in self.projects}
        self._nums = {pid: _numbers(r) for pid, r in self._rest.items()}

    def _learn_short_forms(self):
        """A client's own project names start with its spoken short form:
        'DeNooyer 250th Email', 'Fredy Chevy Q4 Production'. A 1–3 word
        prefix that starts two or more of ONE client's projects, and no other
        client's, is a short form of that client."""
        seen = {}
        for p in self.projects:
            words = canon(p.name).split()
            for n in (1, 2, 3):
                if len(words) > n:
                    seen.setdefault(' '.join(words[:n]), {}).setdefault(p.client_id, set()).add(p.id)
        for prefix, by_client in seen.items():
            if len(by_client) != 1 or len(prefix.replace(' ', '')) < MIN_SHORT_FORM:
                continue
            (cid, ids), = by_client.items()
            if len(ids) >= 2 and cid in self.keys:
                self.keys[cid][1].add(prefix)

    # ── clients ─────────────────────────────────────────────────────────
    def mapped(self, part: str):
        """(True, client-or-None) when an operator decided this name."""
        key = canon(part)
        if key in self.name_map:
            return True, self.name_map[key]
        return False, None

    def client_candidates(self, part: str) -> list:
        key = canon(part)
        if not key:
            return []
        if key in self.name_map:
            return [self.name_map[key]] if self.name_map[key] is not None else []
        compact = key.replace(' ', '')
        exact = [c for c, keys in self.keys.values()
                 if key in keys or compact in {k.replace(' ', '') for k in keys}]
        if exact:
            return exact
        words = key.split()
        out = []
        for c, keys in self.keys.values():
            flat = {k.replace(' ', '') for k in keys}
            if any(_word_prefix(words, k.split()) for k in keys) \
                    or any(len(k) >= MIN_SHORT_FORM and words[0] == k for k in keys) \
                    or any(len(k) >= MIN_SHORT_FORM and compact.startswith(k) for k in flat):
                # 'mtc media' starts 'mtcm' (More Than Cars Media) as well as
                # being 'mtc' (More Than Cars): both are candidates, and the
                # project name picks between them.
                out.append(c)
        return out

    def client_for(self, part: str):
        found = self.client_candidates(part)
        return found[0] if len(found) == 1 else None

    def _project_rest(self, p) -> str:
        return self._rest.get(p.id) if p.id in getattr(self, '_rest', {}) else self._strip_client(p)

    def _strip_client(self, p) -> str:
        """The project's name with its client's name or short form set aside."""
        name = canon(p.name)
        entry = self.keys.get(p.client_id)
        for k in sorted(entry[1] if entry else (), key=len, reverse=True):
            if name.startswith(k + ' '):
                return name[len(k) + 1:]
        return name

    # ── projects ────────────────────────────────────────────────────────
    def _best(self, pool, text_rest: str, text_full: str, close: float):
        rest, full = canon(text_rest), canon(text_full)
        want = _numbers(text_rest)
        scored = []
        for p in pool:
            p_rest = self._project_rest(p)
            nums = self._nums[p.id] if p.id in self._nums else _numbers(p_rest)
            if nums != want:                  # Q3 is never Q4, 2024 never 2025
                continue
            s = max(_score(rest, p_rest), _score(full, self._canon.get(p.id) or canon(p.name)))
            scored.append((s, p))
        if not scored:
            return None
        scored.sort(key=lambda sp: -sp[0])
        best_s, best = scored[0]
        runner = next((s for s, p in scored[1:] if p.id != best.id), 0.0)
        if best_s >= close and best_s - runner >= MARGIN:
            return best
        return None

    def _by_phrase(self, client, rest: str):
        """The attribution sweep's own name rules, for a rest that CONTAINS a
        project's name ('Q1 Production shot list')."""
        from tracker.services.matter_attribution import (
            match_project_name, match_project_name_partial, name_phrase,
        )
        mine = self.by_client.get(client.id, [])
        seen = {}
        for p in mine:
            phrase = name_phrase(p.name, client.name)
            if phrase:
                seen.setdefault(phrase, set()).add(p.id)
        phrases = {ph: next(iter(ids)) for ph, ids in seen.items() if len(ids) == 1}
        pid = match_project_name(rest, phrases) or match_project_name_partial(rest, phrases)
        return next((p for p in mine if p.id == pid), None) if pid else None

    @staticmethod
    def _one(projects):
        live = [p for p in projects if p.is_active] or list(projects)
        return live[0] if len(live) == 1 else None

    def match(self, asana_name: str, team: str = '', client_hint: str = ''):
        """(project or None, client or None, how). how: 'name' / 'client' /
        'ignored' (an operator marked the name "not a client") / ''."""
        whole = self._one(self._by_canon.get(canon(asana_name), []))
        if whole is not None:
            return whole, None, 'name'
        part, rest = split_name(asana_name)
        flat = f'{part} {rest}' if part else rest
        if part:
            decided, client = self.mapped(part)
            if decided and client is None:
                return None, None, 'ignored'
        clients = []
        for source in (client_hint, part, team):       # most to least specific
            if source:
                clients = self.client_candidates(source)
                if clients:
                    break
        if not part and clients:
            rest = asana_name                          # the whole name is the project part
        if clients:
            pool = [p for c in clients for p in self.by_client.get(c.id, [])]
            project = self._best(pool, rest, flat, CLOSE)
            if project is None and len(clients) == 1:
                project = self._by_phrase(clients[0], rest)
            if project is not None:
                return project, None, 'name'
            if len(clients) == 1:
                return None, clients[0], 'client'
            return None, None, ''
        project = self._best(self.projects, rest, flat, GLOBAL_CLOSE)
        return (project, None, 'name') if project is not None else (None, None, '')
