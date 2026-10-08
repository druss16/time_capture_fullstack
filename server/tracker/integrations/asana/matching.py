"""
Which TimeTracker project — or at least which client — an Asana project is.

Agencies name Asana projects "Client: Project" ("Tom Gill: CDP Email
Journeys", "Easterns Auto: Monthly Nissan New Cars Offer Ads"), with the client
in whatever short form they say out loud. Matching only the whole name linked
13 of More Than Cars' 803 live projects. So, in order:

  1. the whole name is a TimeTracker project's name (punctuation aside);
  2. the part before the colon (or " - ") names exactly one client — in full,
     by an alias, by its abbreviation, or as the first words of its name
     ("Tom Gill" → Tom Gill Buick GMC, "Easterns Auto" → Easterns Automotive
     Group) — and the rest names one of THAT client's projects, by the same
     name rules as the attribution sweep;
  3. the client alone, when no project of it fits. Asana time then lands on
     the right client and asks only for the project.

A client part that fits two clients ("Beaver" — Toyota or Mazda?) names
neither: a wrong client bills the wrong client, which is worse than asking.
"""
import re

_SPLIT = re.compile(r'\s*:\s*|\s+-\s+|(?<=\w)-\s+')


def _norm(text: str) -> str:
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).split())


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


class Matcher:
    """Built once per sync from the firm's clients and projects."""

    def __init__(self, clients, projects):
        """clients: objects with id, name, aliases (+ email, alias_sources);
        projects: objects with id, name, client_id, is_active."""
        from tracker.services.alias_derivation import usable_aliases
        from tracker.services.matter_attribution import client_abbreviations
        self.clients = []
        for c in clients:
            names = {_norm(c.name)} | {_norm(a) for a in usable_aliases(c)} \
                | set(client_abbreviations(c.name))
            self.clients.append((c, {n for n in names if n}))
        self.by_name = {}
        self.by_client = {}
        for p in projects:
            self.by_name.setdefault(_norm(p.name), []).append(p)
            self.by_client.setdefault(p.client_id, []).append(p)

    @staticmethod
    def _one(projects):
        live = [p for p in projects if p.is_active] or list(projects)
        return live[0] if len(live) == 1 else None

    def client_for(self, part: str):
        key = _norm(part)
        if not key:
            return None
        exact = [c for c, names in self.clients if key in names]
        if len(exact) == 1:
            return exact[0]
        if exact:
            return None
        words = key.split()
        prefix = [c for c, _ in self.clients if _word_prefix(words, _norm(c.name).split())]
        return prefix[0] if len(prefix) == 1 else None

    def project_for(self, client, rest: str):
        from tracker.services.matter_attribution import (
            match_project_name, match_project_name_partial, name_phrase,
        )
        mine = self.by_client.get(client.id, [])
        if not mine:
            return None
        same = [p for p in mine if _norm(p.name) == _norm(rest)
                or _norm(p.name) == _norm(f'{client.name} {rest}')]
        if same:
            return self._one(same)
        seen = {}
        for p in mine:
            phrase = name_phrase(p.name, client.name)
            if phrase:
                seen.setdefault(phrase, set()).add(p.id)
        phrases = {ph: next(iter(ids)) for ph, ids in seen.items() if len(ids) == 1}
        pid = match_project_name(rest, phrases) or match_project_name_partial(rest, phrases)
        return next((p for p in mine if p.id == pid), None) if pid else None

    def match(self, asana_name: str):
        """(project or None, client or None, how)."""
        whole = self._one(self.by_name.get(_norm(asana_name), []))
        if whole is not None:
            return whole, None, 'name'
        part, rest = split_name(asana_name)
        if not part:
            return None, None, ''
        client = self.client_for(part)
        if client is None:
            return None, None, ''
        project = self.project_for(client, rest)
        if project is not None:
            return project, client, 'name'
        return None, client, 'client'
