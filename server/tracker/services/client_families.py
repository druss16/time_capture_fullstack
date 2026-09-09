"""
Look-alike clients — who could this text plausibly mean, and can we tell?

A CPA firm serving 30+ parishes has a roster where "St. Mary's Church-Clinton",
"St. Mary's Church-Hamilton", "St. Mary's Church-Minoa" and "St. Mary's Church
Baldwinsville" are four different clients, and QuickBooks Desktop puts the
COMPANY NAME in the window title — which for a dozen of those files reads just
"St. Mary's Church". The matcher correctly abstains on such a title. What it
cannot do on its own is notice that the abstention MATTERS: the text named a
group, and whatever fills the gap afterwards (agent stickiness, AI inference, a
temporal bracket) is choosing between siblings with no evidence at all.

The unit here is deliberately **the candidate set for a piece of text**, not a
precomputed "family". Families sound tidier but chain: "Sacred Heart & St.
Mary's Church" shares "mary" with the St. Marys and "sacred heart" with the
Sacred Hearts, so transitive grouping collapses 19 unrelated parishes into one
blob and a picker built on it would offer 19 buttons. Asking "who is consistent
with THIS title?" instead yields the handful of clients a human would actually
choose between.

  candidates_for(text)     clients whose name is consistent with this text
  resolve(text)            the ONE client it names, or None if it can't tell
  short_name(cid, cands)   what to put on a picker button — just the deciding
                           word ("Hamilton"), since the shared part is already
                           on screen in the title above

Org-agnostic and derived purely from the client roster — no per-firm config, no
hardcoded parish names. A firm gets the benefit on day one, before a single
block is captured.
"""
import re
from collections import defaultdict

from django.core.cache import cache

from tracker.services.classification_service import (
    ALIAS_GENERIC_SUFFIXES,
    ALIAS_STOP_WORDS,
    DOMAIN_COMMON_WORDS,
    EXCLUSIVE_ENTITY_CLASSES,
    META_CLIENT_NAMES,
    ClassificationService,
    _canonical_entity_tokens,
)

_CACHE_TTL = 600  # roster changes are rare; a stale map for 10 min is fine


def _name_words(name):
    """Matchable words of a name — long enough and not structural filler."""
    return {
        t for t in ClassificationService._normalize_name(name or '').split()
        if len(t) >= 4
        and t not in ALIAS_STOP_WORDS
        and t not in ALIAS_GENERIC_SUFFIXES
    }


def _identifying(words):
    """Words that name somebody. "church" and "saint" name the whole roster."""
    return {w for w in words if w not in DOMAIN_COMMON_WORDS}


# Application chrome that trails a real title. Left in, it is not merely noise:
# "QuickBooks Accountant Desktop Plus 2024" contains "plus", which makes the
# client "Inventory Plus, Inc" a candidate for EVERY QuickBooks window in the
# firm — and, being the only candidate carrying a word unique to itself, the one
# the resolver picks.
_APP_CHROME = re.compile(
    r'\s*[-–]\s*(?:'
    r'quickbooks\b.*'
    r'|adobe acrobat.*'
    r'|microsoft.*'
    r'|work\s*[-–]\s*microsoft.*'
    r'|excel|word|outlook|powerpoint|onenote|edge|chrome|file explorer'
    r'|message \(html\)|read-only|protected view|compatibility mode'
    r')\s*$',
    re.IGNORECASE,
)


def strip_app_chrome(title):
    """Drop trailing application chrome, repeatedly (" .xlsx - Read-Only - Excel")."""
    out = ClassificationService._strip_qb_screen_bracket(title or '')
    for _ in range(4):
        stripped = _APP_CHROME.sub('', out)
        if stripped == out:
            break
        out = stripped
    return out


def text_words(*parts):
    """Normalize block text into the word set every query here expects."""
    joined = ' '.join(strip_app_chrome(p) for p in parts if p)
    words = set(ClassificationService._normalize_name(joined).split())
    # Fold entity synonyms so a file named "…Academy" can identify a client
    # named "…School", while keeping the literal words for everything else.
    return words | _canonical_entity_tokens(words)


def _entity_classes(words):
    """Which mutually-exclusive entity class(es) this word set claims."""
    folded = _canonical_entity_tokens(words)
    return [group & folded for group in EXCLUSIVE_ENTITY_CLASSES]


# Words that carry no identity on a picker button. "St." and "Saint" are the
# family, not the member; leaving them in renders "St. Baldwinsville".
_NAME_FILLER = {'saint', 'the', 'and', 'for', 'our', 'of'}


class ClientLookalikes:
    """Immutable view of one org's roster. Build via `for_org`."""

    def __init__(self, clients):
        self.by_id = {c.id: c for c in clients}
        self._words = {}
        self._ident = {}
        for c in clients:
            words = set()
            for raw in [c.name] + list(c.aliases or []):
                words |= _name_words(raw)
            self._words[c.id] = words
            self._ident[c.id] = _identifying(words)
        self._lookalike_cache = {}

    # -- the core question ---------------------------------------------------

    def candidates_for(self, words):
        """
        Every client whose name is CONSISTENT with this text.

        Consistent means: the text carries at least one of the client's
        identifying words, and nothing in the text contradicts it. The
        contradiction test is the entity class — a title whose head noun is
        "Cemetery" is not consistent with a client called "…Church", because a
        parish keeps those as two different clients.

        Returns client ids, no particular order.
        """
        words = set(words)
        text_classes = _entity_classes(words)
        out = []
        for cid, ident in self._ident.items():
            if not (ident & words):
                continue
            if self._class_conflict(cid, text_classes):
                continue
            out.append(cid)
        return out

    def _class_conflict(self, client_id, text_classes):
        """True when the text's entity class rules this client out."""
        client_classes = _entity_classes(self._words[client_id])
        for theirs, ours in zip(text_classes, client_classes):
            if theirs and ours and not (theirs & ours):
                return True
        return False

    def are_lookalikes(self, a, b):
        """Could these two specific clients be confused with each other?

        Pairwise and deliberately NOT transitive: they must share an identifying
        word and enough of the rest of their names to collide in a window title.
        "St. Patrick's Church" and "St Patrick's Taberg" qualify; "Assumption
        Church" and "Revive Hope and Healing Ministries" do not, even when one
        title happens to contain a word from each.
        """
        ident_a, ident_b = self._ident.get(a, set()), self._ident.get(b, set())
        words_a, words_b = self._words.get(a, set()), self._words.get(b, set())
        return bool(ident_a & ident_b) and len(words_a & words_b) >= 2

    def has_lookalikes(self, client_id):
        """Is there anyone on this roster this client could be confused with?

        Asked of the client's OWN name: if its name alone already fits more than
        one client, it lives in a look-alike group. Used to tell "inherited with
        no text, but nobody else it could be" (harmless) from "inherited with no
        text, and eleven parishes it could be" (the trust hole).
        """
        if client_id not in self._lookalike_cache:
            client = self.by_id.get(client_id)
            own = text_words(client.name) if client else set()
            self._lookalike_cache[client_id] = len(self.candidates_for(own)) > 1
        return self._lookalike_cache[client_id]

    def identifying_words(self, client_id):
        """The words of this client's name that name SOMEBODY — its own name and
        aliases minus the ones every client shares ("church", "saint", "llc").
        Exposed so callers can ask how much of a name a piece of text carries."""
        return set(self._ident.get(client_id, set()))

    def distinguishing_words(self, client_id, candidates):
        """Words this client owns that no OTHER candidate shares."""
        others = set().union(
            *[self._words[c] for c in candidates if c != client_id]
        ) if len(candidates) > 1 else set()
        return self._words.get(client_id, set()) - others

    def resolve(self, words):
        """The one client this text names, or None when it can't tell.

        None is the whole point: it is the difference between "this is Taberg"
        and "this is one of five St. Patrick's and the title doesn't say".
        """
        words = set(words)
        candidates = self.candidates_for(words)
        if len(candidates) == 1:
            return candidates[0]
        named = [
            c for c in candidates
            if self.distinguishing_words(c, candidates) & words
        ]
        if len(named) == 1:
            return named[0]
        if not named:
            return None
        # More than one candidate has a word to itself in this text. Usually
        # that is one real subject plus an incidental collision: "The Church of
        # the Annunciation - Clark Mills, NY" names Annunciation outright, and
        # only brushes "Sacred Heart NY Mills" through the shared word "mills".
        # Prefer whoever the text names most COMPLETELY — every word of
        # Annunciation's name is present, one of Sacred Heart's is — and abstain
        # when that is a tie, which is the genuine two-subjects case.
        def coverage(cid):
            ident = self._ident.get(cid, set())
            return len(ident & words) / len(ident) if ident else 0.0

        ranked = sorted(named, key=coverage, reverse=True)
        if len(ranked) > 1 and coverage(ranked[0]) > coverage(ranked[1]):
            return ranked[0]
        return None

    # -- presentation --------------------------------------------------------

    def rank(self, candidates, words, recent=()):
        """Order candidates so the right button is usually the first one.

        Two signals, both cheap: how much of the client's name the text actually
        covers (a title saying "St. Mary's Church" covers half of "St. Mary's
        Church-Clinton" but only a third of "Mary Driscoll-Ingraham", so people
        sort below parishes on their own), and whether this user has worked the
        client recently. Recency leads — the picker should feel like it already
        knows the answer.
        """
        words = set(words)
        recent_rank = {cid: i for i, cid in enumerate(recent)}
        text_classes = _entity_classes(words)

        def shares_class(cid):
            """Does this client call itself what the title calls the subject?

            A title saying "Church" should not lead with "Mary Rodman". The
            person is a legitimate candidate — "mary" is genuinely in the text —
            but a client that also calls itself a church is the better guess,
            and the first button is the one people press.
            """
            mine = _entity_classes(self._words.get(cid, set()))
            return any(t and m and (t & m) for t, m in zip(text_classes, mine))

        def key(cid):
            ident = self._ident.get(cid, set())
            coverage = len(ident & words) / len(ident) if ident else 0.0
            return (
                recent_rank.get(cid, len(recent_rank)),
                not shares_class(cid),
                -coverage,
                self.by_id[cid].name if cid in self.by_id else '',
            )

        return sorted(candidates, key=key)

    def short_name(self, client_id, words):
        """What to put on a picker button — just the deciding part of the name.

        The shared part is already on screen in the title above the buttons, so
        a button reading "St. Mary's Church-Hamilton" spends all its width on
        words the user is not choosing between. Drop everything the TITLE
        already said and "Hamilton" is what's left — the whole decision, in one
        word. Falls back to the full name when the title covers all of it.
        """
        client = self.by_id.get(client_id)
        if not client:
            return ''
        words = set(words)
        kept = []
        # Split on hyphens and underscores as well as spaces: this roster names
        # siblings "St Patrick's Church-Jordan" and "St Patricks_St
        # Anthony_Chadwicks", where the deciding word is glued to a word the
        # title already said.
        for raw_word in re.split(r'[\s_]+|(?<=[a-z])-(?=[A-Za-z])', client.name):
            raw_word = raw_word.strip(' -,&')
            if not raw_word:
                continue
            tokens = ClassificationService._normalize_name(raw_word).split()
            tokens = [t for t in tokens if len(t) >= 3 and t not in _NAME_FILLER]
            if tokens and not (set(tokens) & words):
                kept.append(raw_word)
        tail = ' '.join(kept).strip(' -,&')
        return tail or client.name

    # -- roster hygiene ------------------------------------------------------

    def ambiguous_name_forms(self):
        """
        Name/alias forms that cannot exclude another client.

        A form whose identifying words are a subset of (or identical to)
        another client's proves the group but never the member. These are the
        roster entries worth renaming — one rename settles a whole group.
        Returns ``{client_id: [(form, [(other_id, other_form, kind), ...])]}``.
        """
        forms = []
        for client in self.by_id.values():
            for raw in [client.name] + list(client.aliases or []):
                words = _identifying(_name_words(raw))
                if words:
                    forms.append((client.id, raw, words))

        out = defaultdict(list)
        for cid, raw, words in forms:
            clashes = [
                (other_id, other_raw, 'identical' if words == other else 'subset')
                for other_id, other_raw, other in forms
                if other_id != cid and (words == other or words < other)
            ]
            if clashes:
                out[cid].append((raw, clashes))
        return dict(out)


def for_org(org_id, use_cache=True):
    """Build (or reuse) the look-alike map for an org.

    Cached briefly because Stage 3 asks per block and the roster barely moves.
    Callers that just changed the roster should pass use_cache=False.
    """
    key = f'client_lookalikes:{org_id}'
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            return cached

    from tracker.models import Client
    clients = [
        c for c in Client.objects.filter(org_id=org_id, is_active=True)
        if c.name.lower().strip() not in META_CLIENT_NAMES
    ]
    lookalikes = ClientLookalikes(clients)
    if use_cache:
        cache.set(key, lookalikes, timeout=_CACHE_TTL)
    return lookalikes
