# tracker/services/misfile_evidence.py
"""
Why is this block on this client? Six witnesses, and what each one says.

This began as an autonomous agent that drafted resolutions and, above a
confidence bar, applied them. That part is gone, and the reason is worth
keeping: on a real book of business it had nothing to do. Org 21 produces
roughly ONE client-name mismatch a quarter across 7,724 settled billable
blocks, and the errors that matter — 436 hours a quarter booked to a look-alike
parish — carry no evidence to act on at all, because the QuickBooks company
file reaches the server on 0.1% of events. An agent that acts on that would be
guessing, and the whole design refused to guess. So it sat there recommending
one row every ninety days.

What survived is what it was built out of: an evidence reader. Given a block it
asks six independent questions and reports what each one said, including the
silences — "the folder doesn't say so, no QuickBooks company file was open,
nobody has filed this title before". That is the sentence the Misfiled-time
sweep puts on a row, and the tally behind services/attribution_evidence.

It decides nothing and writes nothing. Every caller is read-only.

The three rules it was built with still hold, because they are what make the
sentence trustworthy rather than merely confident:

  1. Corroboration must be INDEPENDENT of the window title. The title is what
     raised the flag; scoring it twice is one opinion counted twice.

  2. Same-family pairs are never adjudicated. 27% of org 21's booked time
     carries no distinguishing word at all; "resolving" St. Mary's Church vs
     St. Mary's Cemetery would be picking, not resolving.

  3. Evidence pointing back at where the block already sits is reported as
     loudly as evidence pointing away. A one-sided reading invents certainty
     the data does not contain — see _same_day_signals, which fires for BOTH
     clients when a person worked both that day, and says so.

No model call anywhere. Every signal is data the system already holds, which is
what makes the sentence reproducible and free.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

log = logging.getLogger(__name__)

# ── Bars ────────────────────────────────────────────────────────────────────
#
# Deliberately high. The cost of a wrong auto-apply is not "a wrong row" — it
# is a firm that stops believing the tab, and there is no recovering that with
# a better threshold later.

AUTO_BAR = 0.80              # confidence needed to MOVE a block without a human
PRIOR = 0.35                 # shrinkage: a lone signal can never reach 1.0

# The agent never closes a flag unattended, at any confidence. Moving a block
# is visible — it lands in an audit row, it shows up in the random accuracy
# sample, somebody's hours change and they notice. Closing an alarm is
# invisible by construction: the row simply stops appearing, and the number
# that says "no mismatches" starts including the ones the machine waved away.
# A false zero on that tab is worse than a miss, because it is read as proof
# the book is clean. So "leave it where it is" is always a draft for a person,
# never an action.
AGENT_MAY_CLOSE_FLAGS = False

# How far to look for a neighbouring attributed block, either side.
NEIGHBOUR_WINDOW = timedelta(minutes=30)

# How many prior human rulings we need before "they keep deciding X" counts.
PRECEDENT_MIN = 1

# Every signal gather_signals attempts, in the order it tries them. Sent with
# each draft so a reader can see what was CHECKED, not only what was found.
#
# That asymmetry is most of the trust problem. "67% confident" invites you to
# either swallow the number or dismiss it. "The folder doesn't say so, the work
# either side doesn't say so, nobody has filed this file before" is the same
# finding stated so you can argue with it — and it is the half that says how
# hard the agent actually looked.
SIGNAL_KINDS = ('title', 'file_path', 'qb_company_file', 'neighbours',
                'same_day', 'human_precedent', 'prior_dismissal')

VERDICT_REASSIGN = 'reassign'
VERDICT_CONFIRM = 'confirm_correct'
VERDICT_HUMAN = 'needs_human'
# The detector does not flag this block at all any more — the flag is left over
# from before someone fixed it. Closing that is bookkeeping, not a judgement:
# the detector itself agrees there is nothing here, which is the same basis the
# nightly scan already closes in-window flags on, unattended, today. It is the
# one closure that is NOT the invisible-suppression hazard AGENT_MAY_CLOSE_FLAGS
# guards against, so it is the one closure the agent may do alone.
VERDICT_STALE = 'stale'

# Historical. Blocks the agent moved while it ran carry this in
# state_changed_by / categorized_by, and Block's choices still list it, so the
# value has to stay legible. Nothing writes it any more.
AGENT_ACTOR = 'mismatch_agent'


@dataclass
class Signal:
    """One piece of evidence, and who it points at."""
    kind: str                 # 'title' | 'file_path' | 'qb_company' | ...
    supports: int | None      # client id this evidence points at
    weight: float             # 0..1
    text: str                 # the line a human reads on the row
    independent: bool = False # does it count toward the corroboration rule?
    # A few words naming THIS witness's specific finding, for a one-line row
    # where the full `text` will not fit. Optional: falls back to the generic
    # label for the signal kind.
    short: str = ''

    def as_dict(self):
        return {'kind': self.kind, 'supports': self.supports,
                'weight': round(self.weight, 3), 'text': self.text,
                'short': self.short, 'independent': self.independent}


@dataclass
class Draft:
    """What the agent thinks should happen to one flagged block."""
    block_id: int
    org_id: int
    booked_client_id: int | None
    booked_client_name: str
    verdict: str = VERDICT_HUMAN
    target_client_id: int | None = None
    target_client_name: str = ''
    confidence: float = 0.0
    # Kept as "this would have cleared the bar", because the sweep sorts by it
    # and because a row with independent corroboration deserves to read
    # differently from one without. It no longer authorises anything.
    auto: bool = False
    signals: list = field(default_factory=list)
    # Hard stops. These block the agent AND a human clicking Approve, because
    # what they guard is not "thin evidence" but irreversibility (already
    # billed), a decision that was never ours (a person set it), and the one
    # question the text genuinely cannot answer (same-family names). A person
    # who wants to do any of those anyway has the manual assign path, which is
    # honest about being a human's pick.
    vetoes: list = field(default_factory=list)
    # Soft stops: reasons the agent will not act unattended, but that a person
    # reading the row is entitled to overrule. Approving IS the second opinion
    # these are asking for.
    caveats: list = field(default_factory=list)
    summary: str = ''

    # What each witness is called in a one-line row.
    _SHORT = {
        'file_path': 'the folder it sits in',
        'qb_company_file': 'the QuickBooks company file',
        'neighbours': 'the work either side of it',
        'same_day': 'their other work that day',
        'human_precedent': 'how this title was filed before',
        'prior_dismissal': 'an earlier review of this row',
    }

    def row_reason(self):
        """The reason as ONE short line, for a row that already shows the arrow.

        `summary` is written for a card with room, and it leads with "Looks like
        X" — which a row showing `Filed [A] -> [B]` has already said. Repeating
        it costs the only line this row has. So this says the part the arrow
        cannot: what agreed, and what stayed silent.
        """
        ind = [s for s in self.signals if s.independent]
        for_t = [s for s in ind if s.supports == self.target_client_id]
        against = [s for s in ind if s.supports == self.booked_client_id]

        if self.vetoes:
            return self.vetoes[0]

        if for_t and against:
            # The honest case, and the one a single nudge would misrepresent:
            # there is real evidence on BOTH sides.
            #
            # When both witnesses are the same KIND, naming the kind twice says
            # nothing — "their other work that day points one way and their
            # other work that day the other". What the reader needs is the two
            # findings, which is what `short` carries.
            a, b = for_t[0], against[0]
            if a.short and b.short:
                return (f"They worked both today — {a.short} and {b.short}. "
                        f"Only the title separates them.")
            return ("Both are in play — " + self._SHORT.get(a.kind, a.kind)
                    + " points one way and " + self._SHORT.get(b.kind, b.kind)
                    + " the other. Only the title separates them.")
        if for_t:
            names = [self._SHORT.get(s.kind, s.kind) for s in for_t[:2]]
            lead = names[0][0].upper() + names[0][1:]
            return (f"{lead} agrees." if len(names) == 1
                    else f"{lead} and {names[1]} both agree.")
        if against:
            return (self._SHORT.get(against[0].kind, against[0].kind)[0].upper()
                    + self._SHORT.get(against[0].kind, against[0].kind)[1:]
                    + " points back at where it already is.")
        silent = [self._SHORT[k] for k in SIGNAL_KINDS
                  if k in self._SHORT and not any(s.kind == k for s in self.signals)]
        return ("Only the title says so — "
                + ", ".join(silent[:3]) + " are all silent.")

    def as_dict(self):
        return {
            'block_id': self.block_id,
            'org_id': self.org_id,
            'booked_client_id': self.booked_client_id,
            'booked_client_name': self.booked_client_name,
            'verdict': self.verdict,
            'target_client_id': self.target_client_id,
            'target_client_name': self.target_client_name,
            'confidence': round(self.confidence, 3),
            'auto': self.auto,
            'summary': self.summary,
            'row_reason': self.row_reason(),
            'evidence': [s.as_dict() for s in self.signals],
            # What was looked for. The reader derives "checked and found
            # nothing" from (checked - evidence) rather than the UI hardcoding
            # a list that goes quietly stale the day a seventh signal lands.
            'checked': list(SIGNAL_KINDS),
            'vetoes': self.vetoes,
            'caveats': self.caveats,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Per-org context — built once per run, never per block.
# ─────────────────────────────────────────────────────────────────────────────

class OrgContext:
    """Everything the agent needs to reason about one org, loaded once."""

    def __init__(self, org_id):
        from tracker.models import Client, Organization
        from tracker.services import client_families
        from tracker.utils.client_name_match import build_token_index

        self.org_id = org_id
        self.names = {
            c.id: c.name
            for c in Client.objects.filter(org_id=org_id).only('id', 'name')
        }
        self.index = build_token_index(self.names)
        o = Organization.objects.filter(id=org_id).only('name').first()
        self.firm_name = o.name if o else None
        self.lookalikes = client_families.for_org(org_id)

        # Pairs a human has already waved away, and how many times. Read once:
        # "I checked, it's right" is a ruling, and an agent that re-raises it
        # every night is the queue this feature exists to empty.
        self._dismissed_titles = None
        self._human_rulings = None
        # Optional prebuilt neighbour index (see attribution_evidence). When
        # present, _neighbour_signal reads it instead of issuing two queries
        # per block. One flagged row at a time does not care; a report over
        # every billable block in a quarter cares a great deal — 7,724 blocks
        # is 15,448 queries the other way.
        self.neighbour_index = None

    # -- lazy, because most runs never need it -------------------------------

    @property
    def human_rulings(self):
        """{normalized title: {client_id: times a person filed it there}}.

        ONE query for the whole org, not one per row. The obvious shape —
        `Block.objects.filter(window_title__iexact=...)` per block — is a
        sequential scan of the block table per flagged row (no index survives
        the lower() that iexact applies), and the caller can hand us 500 rows.

        It fits in one query because there are so few of these: org 21 has
        roughly 344 human picks in its entire history. The scarcity is the
        point — this is the system's whole record of what a person actually
        decided, and it is small enough to hold in memory and precious enough
        to consult on every row.
        """
        from tracker.models import Block

        if self._human_rulings is None:
            out = {}
            rows = (Block.objects
                    .filter(org_id=self.org_id, client_id__isnull=False,
                            deleted_at__isnull=True)
                    # 'manual'/'correction' only — which pointedly excludes
                    # the agent's own AGENT_ACTOR stamp. An agent that counted
                    # its past moves as precedent would be citing itself, and
                    # the second identical title would look twice as settled
                    # as the first purely because it went second.
                    .filter(categorized_by__in=('manual', 'correction'))
                    .exclude(window_title__isnull=True)
                    .exclude(window_title='')
                    .values_list('window_title', 'client_id', 'id')[:20000])
            for title, cid, bid in rows:
                key = _norm_text(title)
                if len(key) < 8:
                    continue
                out.setdefault(key, {}).setdefault(cid, []).append(bid)
            self._human_rulings = out
        return self._human_rulings

    @property
    def dismissed_titles(self):
        """{normalized title: times a human called it correctly booked}."""
        from tracker.models import MismatchFlag

        if self._dismissed_titles is None:
            counts = {}
            rows = (MismatchFlag.objects
                    .filter(org_id=self.org_id, resolved_reason='confirmed_correct')
                    .values_list('window_title', 'booked_client_id'))
            for title, cid in rows:
                key = (_norm_text(title), cid)
                if key[0]:
                    counts[key] = counts.get(key, 0) + 1
            self._dismissed_titles = counts
        return self._dismissed_titles

    def name(self, cid):
        return self.names.get(cid) or ''


_CTX_CACHE = {}

# Short, because the thing being cached is a client ROSTER. Someone adds a
# client or fixes an alias precisely when they are trying to make the matcher
# behave, and a process-lifetime cache would keep serving them the old roster
# with no way to tell. Building one is a couple of queries; an hour of stale
# answers is not worth saving them.
_CTX_TTL_SECONDS = 300


def context_for(org_id, fresh=False):
    """Cached OrgContext. `fresh=True` after a run that moved blocks."""
    import time

    now = time.monotonic()
    if fresh:
        _CTX_CACHE.pop(org_id, None)
    hit = _CTX_CACHE.get(org_id)
    if hit and (now - hit[1]) < _CTX_TTL_SECONDS:
        return hit[0]
    ctx = OrgContext(org_id)
    _CTX_CACHE[org_id] = (ctx, now)
    return ctx


def _norm_text(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


# ─────────────────────────────────────────────────────────────────────────────
# The signals
# ─────────────────────────────────────────────────────────────────────────────

# Default OFF pending `manage.py shadow_needs_human --org 21`. See _title_signal.
TITLE_SIGNAL_TRUSTS_THE_FLAG = False


def _title_signal(block, ctx):
    """The flag's own evidence: the window title names somebody.

    NOT independent — this is the claim under review, not a witness to it.

    WHICH DETECTOR GETS ASKED MATTERS. A row only reaches here because
    `_stale_flag_draft` found `detect_mismatch` or `detect_booked_absent` still
    firing on it — so by construction something DID name a client. But this
    asked `detect_title_client`, a different question:

        detect_mismatch      ranks the OTHER clients, excluding the booked one,
                             then compares the winner against the booking.
        detect_title_client  ranks EVERY client including the booked one, and
                             abstains when two come out close.

    So a title that names the booked client AND a rival gives detect_mismatch a
    clean winner (the booked client was never in its ranking) and gives
    detect_title_client a tie (it was). The row gets flagged, and then the
    evidence layer reports nothing supporting any rival — `rivals` comes back
    empty, no branch sets a verdict, and the Draft keeps its default of
    needs_human. Org 21: 76 of 145 flagged rows, over half the queue, arriving
    as "there is no recommendation to make" on rows the detector had a specific
    accusation about.

    The flag's own claim is what this signal is FOR, so it now asks the
    detector that raised the row first, and only falls back to
    detect_title_client for callers whose block was never flagged.
    """
    from tracker.utils.client_name_match import (detect_mismatch,
                                                 detect_title_client)

    det = None
    if TITLE_SIGNAL_TRUSTS_THE_FLAG and block.client_id:
        m = detect_mismatch(block.window_title or '', block.client_id,
                            ctx.index, ctx.names, firm_name=ctx.firm_name)
        if m:
            # An acronym match ("SFA P&L 2025" -> St Francis of Assisi) reports
            # coverage 1.0 and zero mass by construction, because no word
            # matched at all — three uppercase letters did. Passing that
            # coverage through would award the full-fingerprint bonus to the
            # thinnest evidence the detector has, so it is pinned to the base
            # weight instead. This is also the clearest case of the two
            # detectors diverging: detect_mismatch has an acronym path and
            # detect_title_client has none, so every row raised that way
            # produced no title signal at all.
            acronym = m.get('match_kind') == 'acronym'
            det = {
                'client_id': m['looks_like_client_id'],
                'client_name': m['looks_like_client_name'],
                'coverage': 0.0 if acronym else m['looks_like_coverage'],
                'abs_hit': 0.0 if acronym else (m.get('looks_like_abs_hit') or 0.0),
            }
    if det is None:
        det = detect_title_client(block.window_title or '', ctx.index,
                                  ctx.names, firm_name=ctx.firm_name)
    if not det:
        return None
    # Coverage says "how much of that client's name is here"; abs_hit says "how
    # much distinctive mass". A full distinctive name scores both; a single
    # shared word scores neither, and stays near the floor.
    w = 0.55
    if det['coverage'] >= 0.80:
        w += 0.15
    if det['abs_hit'] >= 3.0:
        w += 0.15
    return Signal(
        kind='title',
        supports=det['client_id'],
        weight=min(w, 0.85),
        text=(f"The window title distinctively names {det['client_name']} "
              f"({det['coverage']:.0%} of its name, strength {det['abs_hit']:.1f})."),
    )


def _path_text(block):
    """Filename stem plus its immediate folder — the two parts that name a client.

    The full path is mostly shared scaffolding (a drive letter, "Clients",
    "2025", "Tax") that every client's work sits under, and feeding it whole
    dilutes every distinctive token in it.
    """
    fp = (block.file_path or '').strip()
    if not fp:
        return ''
    fp = fp.replace('\\', '/')
    stem = os.path.splitext(os.path.basename(fp))[0]
    parent = os.path.basename(os.path.dirname(fp))
    return f"{parent} {stem}".strip()


def _file_signal(block, ctx):
    """What the file on disk says — the strongest witness we have.

    A window title is whatever the app decided to render, and apps render
    plenty that is not the work: browser banners, QuickBooks chrome, the
    company you had open in the other tab. A file path is where the bytes
    actually are. When the two disagree, that disagreement is the finding.
    """
    from tracker.utils.client_name_match import detect_title_client
    from tracker.services.qb_company_file import company_file_key

    text = _path_text(block)
    if not text:
        return None
    det = detect_title_client(text, ctx.index, ctx.names, firm_name=ctx.firm_name)
    if not det:
        return None

    is_company_file = bool(company_file_key(block.app_name or '', block.file_path or ''))
    if is_company_file:
        # A .qbw is not a document about a client, it IS that client's books.
        # Nothing else in the system is this unambiguous about identity.
        return Signal(
            kind='qb_company_file',
            supports=det['client_id'],
            weight=0.95,
            text=(f"The QuickBooks company file open in this block is "
                  f"{det['client_name']}'s ({os.path.basename(block.file_path)})."),
            independent=True,
        )
    return Signal(
        kind='file_path',
        supports=det['client_id'],
        weight=0.85,
        text=(f"The file being worked in sits in {det['client_name']}'s path "
              f"({text})."),
        independent=True,
    )


def neighbours_of(block, ctx):
    """(before, after) nearest attributed blocks — from the index, or queried.

    Split out so a batch caller can supply the whole period's answer up front.
    The semantics must not drift between the two paths, which is why there is
    exactly one place that decides what "nearest attributed neighbour" means.
    """
    from tracker.models import Block

    if ctx.neighbour_index is not None:
        return ctx.neighbour_index.get(block.id, (None, None))

    before = (Block.objects
              .filter(user_id=block.user_id, org_id=block.org_id,
                      client_id__isnull=False, deleted_at__isnull=True,
                      end__lte=block.start, end__gte=block.start - NEIGHBOUR_WINDOW)
              .exclude(id=block.id)
              .order_by('-end')
              .only('id', 'client_id', 'app_name', 'state_changed_by',
                    'categorized_by', 'window_title')
              .first())
    after = (Block.objects
             .filter(user_id=block.user_id, org_id=block.org_id,
                     client_id__isnull=False, deleted_at__isnull=True,
                     start__gte=block.end, start__lte=block.end + NEIGHBOUR_WINDOW)
             .exclude(id=block.id)
             .order_by('start')
             .only('id', 'client_id', 'app_name', 'state_changed_by',
                   'categorized_by', 'window_title')
             .first())
    return before, after


def _neighbour_signal(block, ctx):
    """What this person was booked to immediately before and after.

    Weakest of the independent signals and the one most likely to be circular:
    if the neighbours were filed by the same classifier that filed this block,
    agreement between them is one opinion repeated. So neighbours only speak
    when a HUMAN set them, or when they carry a client name in their own title.
    """
    if not (block.start and block.end):
        return None
    before, after = neighbours_of(block, ctx)

    sides = [s for s in (before, after) if s is not None]
    if not sides:
        return None

    def trustworthy(n):
        if n.state_changed_by in ('user', 'user_edit', 'correction'):
            return True
        if n.categorized_by in ('manual', 'correction'):
            return True
        return False

    trusted = [n for n in sides if trustworthy(n)]
    if not trusted:
        return None

    cids = {n.client_id for n in trusted}
    if len(cids) != 1:
        return None                       # the two sides disagree — say nothing
    cid = cids.pop()

    both = len(trusted) == 2
    same_app = any((n.app_name or '').lower() == (block.app_name or '').lower()
                   and (block.app_name or '') for n in trusted)
    w = 0.70 if both else (0.55 if same_app else 0.40)
    where = 'either side of' if both else 'next to'
    return Signal(
        kind='neighbours',
        supports=cid,
        weight=w,
        text=(f"A person booked the work {where} this block to "
              f"{ctx.name(cid)}, within half an hour"
              f"{', same app' if same_app else ''}."),
        independent=True,
    )


def _same_day_signals(block, ctx, interested):
    """Did this person actually work these clients today, on work that named them?

    CORROBORATION, never nomination. The first version of this picked the
    person's biggest block of the day and pointed at whoever it belonged to,
    which on the case that motivated it named St. John the BAPTIST Church —
    a client with nothing to do with the question. Same-day presence cannot
    propose an answer; it can only agree with one already on the table.

    The case that motivated it. Eileen, 31 August: at 10:16 she is in St John
    Cemetery-Rome's QuickBooks, on a block whose own title reads "St. John's
    Cemetery". At 10:26 she opens "8-30-2026 St. John's Cemetery bills
    etc_.pdf" and it lands on St. Mary's Cemetery Bville, because that is what
    she was on at 10:21 and again at 10:28. Session stickiness swallowed it,
    and `neighbours` said nothing because it only trusts a neighbour a HUMAN
    set, while every block that morning was classifier-filed.

    It answers for BOTH sides, which is the point. On that block she worked St
    John Cemetery-Rome at 10:16 AND St. Mary's Cemetery Bville at 10:21 — so
    the signal fires twice, the two cancel, and the row says honestly that she
    was on both. A one-sided nudge would have invented a certainty the day does
    not contain.

    Requires the other block's OWN title to name where it sits, so a whole day
    of sticky mis-filing cannot vouch for itself.
    """
    from tracker.models import Block
    from tracker.utils.client_name_match import detect_title_client

    if not block.start or not block.user_id or not interested:
        return []

    day = timezone.localtime(block.start).date()
    rows = (Block.objects
            .filter(org_id=block.org_id, user_id=block.user_id, day=day,
                    client_id__in=list(interested), deleted_at__isnull=True)
            .exclude(id=block.id)
            .exclude(window_title__isnull=True).exclude(window_title='')
            .only('id', 'client_id', 'minutes', 'start', 'window_title')[:200])

    # Nearest in time, not longest. For a block at 10:26, "they were on St John
    # Cemetery-Rome at 10:16" is the sentence that decides it; "at 14:37" is
    # four hours later and settles nothing. Both prove the client is in play,
    # but only one of them is about THIS block.
    best = {}
    for r in rows:
        det = detect_title_client(r.window_title, ctx.index, ctx.names,
                                  firm_name=ctx.firm_name)
        if not det or det['client_id'] != r.client_id or not r.start:
            continue
        gap = abs((r.start - block.start).total_seconds())
        cur = best.get(r.client_id)
        if cur is None or gap < cur[0]:
            best[r.client_id] = (gap, r)
    best = {cid: r for cid, (_gap, r) in best.items()}

    out = []
    for cid, r in best.items():
        when = timezone.localtime(r.start).strftime('%H:%M')
        out.append(Signal(
            kind='same_day',
            supports=cid,
            weight=0.55,
            text=(f"The same person worked {ctx.name(cid)} for "
                  f"{r.minutes or 0} minute{'' if (r.minutes or 0) == 1 else 's'} "
                  f"at {when} the same day, on work whose own title named it."),
            short=f"{ctx.name(cid)} at {when}",
            independent=True,
        ))
    return out


def _precedent_signal(block, ctx):
    """How a human resolved this exact title before.

    The single most valuable thing the system knows and the one it currently
    throws away: someone already sat in this tab, looked at this filename, and
    decided. Asking them the same question next month is the whole complaint
    about the queue.
    """
    title = _norm_text(block.window_title)
    if not title or len(title) < 8:
        return None

    by_client = ctx.human_rulings.get(title)
    if not by_client:
        return None

    # Exclude this block's own row, so a block a person set does not stand as
    # its own precedent for staying where it is.
    counts = {cid: len([b for b in ids if b != block.id])
              for cid, ids in by_client.items()}
    counts = {cid: n for cid, n in counts.items() if n}
    total = sum(counts.values())
    if total < PRECEDENT_MIN:
        return None

    top_cid, top_n = max(counts.items(), key=lambda kv: kv[1])
    if len(counts) > 1 and top_n <= total / 2:
        return None                       # people disagree — not a precedent

    return Signal(
        kind='human_precedent',
        supports=top_cid,
        weight=0.90 if top_n > 1 else 0.75,
        text=(f"A person filed this same title to {ctx.name(top_cid)} "
              f"{top_n} time{'s' if top_n > 1 else ''} before."),
        independent=True,
    )


def _dismissal_signal(block, ctx):
    """Someone has already called this exact row a false alarm."""
    key = (_norm_text(block.window_title), block.client_id)
    n = ctx.dismissed_titles.get(key, 0)
    if not n:
        return None
    return Signal(
        kind='prior_dismissal',
        supports=block.client_id,
        weight=0.85 if n > 1 else 0.70,
        text=(f"This title on {ctx.name(block.client_id)} was reviewed and "
              f"called correct {n} time{'s' if n > 1 else ''} already."),
        independent=True,
    )


def gather_signals(block, ctx):
    """Every piece of evidence about who this block belongs to."""
    out = []
    for fn in (_title_signal, _file_signal, _neighbour_signal,
               _precedent_signal, _dismissal_signal):
        try:
            s = fn(block, ctx)
        except Exception:                  # one blind signal must not blind the rest
            log.exception('[MISMATCH-AGENT] signal %s failed on block %s',
                          fn.__name__, block.id)
            continue
        if s:
            out.append(s)

    # Same-day presence runs LAST and only for clients already on the table —
    # the booked one and whoever the signals above named. It corroborates; it
    # never nominates. See _same_day_signals.
    interested = {block.client_id} | {s.supports for s in out if s.supports}
    try:
        out.extend(_same_day_signals(block, ctx, {c for c in interested if c}))
    except Exception:
        log.exception('[MISMATCH-AGENT] same_day failed on block %s', block.id)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# The draft
# ─────────────────────────────────────────────────────────────────────────────

def _vetoes(block, ctx, target_id):
    """Reasons this block may not be auto-resolved, whatever the score says."""
    out = []

    if block.invoiced or getattr(block, 'qb_time_activity_id', None) \
            or getattr(block, 'xero_invoice_id', None):
        out.append('Already invoiced or pushed to billing — moving it here '
                   'would disagree with what the client was billed.')

    if block.state_changed_by in ('user', 'user_edit', 'correction') \
            or block.categorized_by in ('manual', 'correction'):
        out.append('A person put this block on this client. That is a '
                   'judgement, not a classifier error.')

    if target_id and block.client_id and ctx.lookalikes.are_lookalikes(
            block.client_id, target_id):
        out.append(f'{ctx.name(block.client_id)} and {ctx.name(target_id)} are '
                   f'same-family names. Nothing in the text separates them, so '
                   f'a machine choosing between them is guessing.')

    return out


def draft_for_block(block, ctx):
    """Read the block and everything around it; say what should happen."""
    stale = _stale_flag_draft(block, ctx)
    if stale:
        return stale
    return draft_from_signals(
        block_id=block.id,
        org_id=block.org_id,
        booked_id=block.client_id,
        signals=gather_signals(block, ctx),
        name_of=ctx.name,
        veto_fn=lambda target_id: _vetoes(block, ctx, target_id),
    )


def _stale_flag_draft(block, ctx):
    """A Draft saying "this was already fixed", or None if it really is flagged.

    Worth asking FIRST, because a queue fills up with these. The nightly scan
    only ever re-examined flags whose block was still inside its 7-day
    detection window, so a flag raised on day 1 and fixed on day 9 stayed open
    forever. Org 21 had 19 open flags and 18 of them were already correct.

    The scan now closes those itself (see tasks.scan_org_mismatches), which is
    where the fix belongs. This stays as the agent's own honest reading, so a
    row that slips through is labelled "already fixed" instead of being dressed
    up as a judgement call the agent made.
    """
    from tracker.utils.client_name_match import detect_booked_absent, detect_mismatch

    if not block.window_title or not block.client_id:
        return None
    if block.client_id not in ctx.names:
        return None

    if detect_mismatch(block.window_title, block.client_id, ctx.index, ctx.names,
                       firm_name=ctx.firm_name):
        return None
    if detect_booked_absent(block.window_title, block.client_id, ctx.index,
                            ctx.names, firm_name=ctx.firm_name):
        return None

    return Draft(
        block_id=block.id, org_id=block.org_id,
        booked_client_id=block.client_id,
        booked_client_name=ctx.name(block.client_id),
        verdict=VERDICT_STALE,
        confidence=1.0,
        auto=True,
        summary=(f"Already fixed — the detector no longer flags this block, "
                 f"and {ctx.name(block.client_id)} is what its title names. "
                 f"The flag is left over."),
    )


def draft_from_signals(block_id, org_id, booked_id, signals, name_of, veto_fn):
    """Turn evidence into a verdict.

    Separated from the gathering on purpose: this is the part that decides, so
    it is the part worth being able to test against a hand-written pile of
    signals with no database anywhere near it. `name_of(cid) -> str` and
    `veto_fn(target_id) -> [str]` are the only things it needs from the world.
    """
    booked = booked_id

    # Tally support per client.
    by_client = {}
    for s in signals:
        if s.supports is None:
            continue
        by_client.setdefault(s.supports, []).append(s)

    d = Draft(
        block_id=block_id,
        org_id=org_id,
        booked_client_id=booked,
        booked_client_name=name_of(booked),
        signals=signals,
    )

    booked_sigs = by_client.get(booked, [])
    rivals = {cid: ss for cid, ss in by_client.items() if cid != booked}

    if not rivals:
        # Nothing points anywhere else. If a human already cleared this exact
        # row, close it; otherwise the flag stands and a person looks.
        if any(s.independent for s in booked_sigs):
            d.verdict = VERDICT_CONFIRM
            d.confidence = _score(booked_sigs, [])
            d.auto = AGENT_MAY_CLOSE_FLAGS
            d.caveats.append('Closing a flag is always a person\'s call — the '
                             'agent only ever proposes it.')
            d.summary = (f"Leave it on {d.booked_client_name} — "
                         f"{booked_sigs[0].text.rstrip('.').lower()}.")
        elif booked_sigs:
            # There IS evidence — it just all reads the window title, which is
            # the text that raised the flag. Saying "no evidence" here was a
            # lie the row could be checked against in one glance.
            d.summary = (f"Only the title speaks, and it names "
                         f"{d.booked_client_name} — the client it is already "
                         f"on. Nothing independent either way.")
        else:
            d.summary = 'No evidence points anywhere. Needs a person.'
        return d

    top_cid, top_sigs = _pick_target(rivals, signals)
    if top_cid is None:
        # The title named somebody, and the only thing arguing for anywhere
        # else is the clock. Under the firm's standing rule that is not a
        # recommendation — see _pick_target.
        d.verdict = VERDICT_HUMAN
        named = next((s for s in signals if s.kind == 'title'), None)
        d.confidence = 0.0
        d.summary = (
            f"The title names {name_of(named.supports)}"
            f"{' — the client it is already on' if named.supports == booked else ''}"
            f". The work around it was booked elsewhere, but nothing in this "
            f"block's own text agrees, so there is no recommendation to make."
            if named else 'No evidence points anywhere. Needs a person.')
        return d
    d.target_client_id = top_cid
    d.target_client_name = name_of(top_cid)

    # A second rival with its own independent backing means the evidence is
    # split, not strong. Never auto-apply into a three-way argument.
    contested = [cid for cid, ss in rivals.items()
                 if cid != top_cid and any(s.independent for s in ss)]

    against = booked_sigs + [s for cid, ss in rivals.items() if cid != top_cid
                             for s in ss]
    d.confidence = _score(top_sigs, against)

    booked_independent = [s for s in booked_sigs if s.independent]
    if booked_independent and _score(booked_sigs, top_sigs) > d.confidence:
        # The evidence actually favours where it already is. That is a verdict,
        # not a failure — the flag is the thing that was wrong.
        d.verdict = VERDICT_CONFIRM
        d.target_client_id = None
        d.target_client_name = ''
        d.confidence = _score(booked_sigs, top_sigs)
        d.auto = AGENT_MAY_CLOSE_FLAGS
        d.caveats.append('Closing a flag is always a person\'s call — the '
                         'agent only ever proposes it.')
        d.summary = (f"Leave it on {d.booked_client_name} — "
                     f"{booked_independent[0].text.rstrip('.').lower()}.")
        return d

    d.vetoes = list(veto_fn(top_cid))
    if booked_independent:
        d.caveats.append(
            f'Evidence also points back at {d.booked_client_name}: '
            f'{booked_independent[0].text}')
    if contested:
        d.caveats.append(
            'More than one other client has independent evidence behind it.')

    corroborated = any(s.independent for s in top_sigs)
    if not corroborated:
        d.caveats.append('Only the window title says so — nothing independent '
                         'of the title agrees.')
    if d.confidence < AUTO_BAR:
        d.caveats.append(f'Confidence {d.confidence:.0%} is below the '
                         f'{AUTO_BAR:.0%} bar for acting unattended.')

    d.verdict = VERDICT_REASSIGN
    d.auto = (d.confidence >= AUTO_BAR and corroborated
              and not d.vetoes and not booked_independent and not contested)
    lead = max(top_sigs, key=lambda s: (s.independent, s.weight))
    blocker = (d.vetoes + d.caveats)
    d.summary = (f"Move to {d.target_client_name} — {lead.text.rstrip('.').lower()}."
                 if d.auto else
                 f"Looks like {d.target_client_name}, but a person should say: "
                 + (blocker[0] if blocker else 'evidence is thin.'))
    return d


# Evidence that is about WHEN the work happened, not what it was. Both witness
# the same thing — a person filed neighbouring work to some client — and neither
# reads this block's own text.
TEMPORAL_KINDS = frozenset({'neighbours', 'same_day'})

# Default ON: this encodes a rule the firm already holds, not a hypothesis about
# the data. It is switchable so the shadow harness can run old against new, and
# so it can be turned off in place if the measured effect is not what we want:
#   manage.py shadow_title_temporal --org 21 --days 120
TITLE_OUTRANKS_TEMPORAL = True


def _pick_target(rivals, signals):
    """Which rival client the evidence points at, or None to make no claim.

    THE STANDING RULE: read the block's OWN title for a company name FIRST; the
    work before and after it may only speak when the title names nobody.

    The target used to be `max(rivals, key=sum of weight)`, a straight popularity
    contest, and the title always lost it. A title signal is capped at 0.85; a
    neighbour (0.70) plus a same-day sighting (0.55) sums to 1.25. So on a block
    whose title said one parish, two clock-based witnesses for a different one
    carried the verdict — the exact inversion the rule exists to prevent, and
    visible in the live card that read "the work either side of it names X"
    while the title said Y.

    Temporal evidence is not discarded. Once a target is chosen it still
    corroborates, still feeds confidence, and still shows in the card. What it
    may no longer do is CHOOSE. Everything that reads the block itself — the
    file path, the QuickBooks company file, how a person filed this same title
    before — keeps its full say, including the right to outrank the title, which
    is why a .qbw at 0.95 still beats a title at 0.85. The file on disk is
    evidence about this block; a neighbour is evidence about a different one.
    """
    if not rivals:
        return None, []

    title_named = next((s.supports for s in signals
                        if s.kind == 'title' and s.supports is not None), None)
    if not TITLE_OUTRANKS_TEMPORAL:
        title_named = None          # straight popularity contest, as before

    def weight(sigs):
        return sum(s.weight for s in sigs
                   if title_named is None or s.kind not in TEMPORAL_KINDS)

    eligible = {cid: ss for cid, ss in rivals.items() if weight(ss) > 0}
    if not eligible:
        # Every rival's whole case is the clock, and the title named somebody
        # (possibly the booked client). Refuse rather than promote a guess.
        return None, []

    top_cid = max(eligible, key=lambda cid: (weight(eligible[cid]), -cid))
    # The chosen client keeps ALL of its signals — the restriction was about
    # who gets picked, not about what counts once they have been.
    return top_cid, rivals[top_cid]


def _score(for_sigs, against_sigs):
    """Shrunk share of evidence — never 1.0, never certain on one witness.

    Straight `for / (for + against)` reads 1.00 off a single mediocre signal,
    which is exactly the number that gets a bad auto-apply through. The prior
    makes a lone witness argue its way up instead.
    """
    f = sum(s.weight for s in for_sigs)
    a = sum(s.weight for s in against_sigs)
    if f <= 0:
        return 0.0
    return f / (f + a + PRIOR)


# ─────────────────────────────────────────────────────────────────────────────
# What used to live here
# ─────────────────────────────────────────────────────────────────────────────
#
# apply_draft / _resolve_flag / save_draft / run() — the acting half. Removed
# with the nightly task, the approve endpoint and the per-org autoresolve
# switch. Nothing reads a stored draft any more: every caller asks the question
# fresh and gets an answer that describes the block as it is now, which is the
# only kind of answer worth putting in front of somebody.
#
# The MismatchFlag.agent_* columns it wrote are left in place. Dropping them
# needs a migration to buy nothing, and they are a record of what the agent
# proposed while it ran.


def flagged_blocks_for_org(org_id, days, limit=500):
    """The rows the Mismatches tab actually shows, as Block objects.

    THE QUEUE IS DERIVED, NOT STORED. `MismatchFlag` is a detection record, not
    the queue: the tab re-derives every row live through
    `mismatch_scan.scan_buckets` over committed blocks and only then asks for
    drafts. Anything that reads MismatchFlag to find "the flagged rows" is
    measuring a different population — resolved flags, or (org 21, 120 days) an
    empty set while the tab was plainly showing rows.

    That mistake cost three round trips against production, so the derivation
    lives here once and the shadow commands share it rather than each
    re-implementing the endpoint's query and drifting from it.

    Returns (blocks_queryset, scanned_count).
    """
    from datetime import timedelta

    from django.utils import timezone

    from tracker.models import Block
    from tracker.services.mismatch_scan import scan_buckets
    from tracker.utils.db_iter import keyset_iter
    from tracker.views_mavops import _confirmed_correct_block_ids

    ctx = context_for(org_id)
    cutoff = timezone.now() - timedelta(days=days)
    # Mirrors the mavops mismatches endpoint, including keyset_iter: Neon's
    # transaction pooler can hand a named cursor's next FETCH to a different
    # backend session, so .iterator() truncates silently.
    scan_qs = (Block.objects
               .filter(org_id=org_id, deleted_at__isnull=True,
                       client_id__isnull=False,
                       classification_state='committed',
                       start__gte=cutoff)
               .exclude(window_title__isnull=True)
               .exclude(window_title=''))
    result = scan_buckets(
        keyset_iter(scan_qs, 1000, descending=True),
        {org_id: ctx.names}, {org_id: ctx.index}, {org_id: ctx.firm_name},
        limit=limit,
        skip_block_ids=_confirmed_correct_block_ids(org_id),
    )
    ids = [row['block_id']
           for bucket in ('client', 'internal', 'unsure')
           for row in result['flagged'].get(bucket, [])]
    # No .only(): draft_for_block reaches for invoiced, qb_time_activity_id,
    # xero_invoice_id, state_changed_by and categorized_by inside the veto
    # check, and a deferred field there is one refresh_from_db per row (the
    # N+1 that SIGKILLed a worker in PR #439).
    blocks = (Block.objects
              .filter(id__in=ids, org_id=org_id, deleted_at__isnull=True,
                      client_id__isnull=False)
              .order_by('id'))
    return blocks, result['scanned']


def drafts_for_blocks(org_id, block_ids):
    """Live drafts for an arbitrary set of blocks — what the review tab reads.

    Works for rows that have no flag at all (the `unsure` bucket never gets
    one), so the tab can show the agent's reading of every row it displays.
    """
    from tracker.models import Block

    if not block_ids:
        return {}
    ctx = context_for(org_id)
    out = {}
    for b in (Block.objects
              .filter(id__in=list(block_ids)[:500], org_id=org_id,
                      deleted_at__isnull=True, client_id__isnull=False)
              .select_related('client')):
        try:
            out[b.id] = draft_for_block(b, ctx).as_dict()
        except Exception:
            log.exception('[MISMATCH-AGENT] draft failed on block %s', b.id)
    return out
