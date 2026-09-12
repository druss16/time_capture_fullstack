# tracker/services/mismatch_agent.py
"""
Mismatch resolution agent — drafts a verdict for every flagged block.

The detector (services/mismatch_scan) answers one question: "does this block's
window title name a different client than it's booked to?" That question has a
yes/no answer and no opinion about what to DO, so every flag it raises lands on
a person. The review tab is therefore a queue you WORK: read the title, guess
what happened, pick a client, move on. At a handful of rows a month that is
fine. It stops being fine the moment a firm turns the detector on historical
data, or a second detector bucket (`unsure`) starts contributing rows that by
construction have no single answer.

This module reads the flag AND the evidence around the block — the file that
was actually open, the QuickBooks company file, what the same person was
booked to on either side of it, what a human decided about this same title
before — and drafts a resolution with that evidence attached. Above a
confidence bar it applies the draft itself. Below it, the draft rides along
with the row so the tab becomes a queue you APPROVE.

Three rules the agent never breaks, each one paid for:

  1. It never adjudicates a same-family pair. `are_lookalikes(booked, target)`
     is a hard veto. 27% of org 21's booked time is committed with no
     distinguishing word in the text; an agent that "resolves" St. Mary's
     Church vs St. Mary's Cemetery is not resolving anything, it is picking.

  2. Corroboration must be INDEPENDENT of the title. The title is what raised
     the flag; scoring it twice is not a second opinion. Auto-apply needs at
     least one signal that does not read the window title at all — the file on
     disk, the company file, the neighbours, a human's prior ruling.

  3. Any independent signal pointing back at the BOOKED client vetoes the
     auto-apply outright, however strong the title looks. A browser banner once
     leaked the word "edge" into a title and matched a real client; the decoy
     never had to win, it only had to look like a second opinion. That cuts
     both ways: a contradicting signal here does not lower the score, it stops
     the machine and calls a human.

No model call anywhere in this file. Every signal is derived from data the
system already holds, which is what makes the evidence line readable and the
verdict reproducible.
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

# Stamped on blocks the agent moves. NOT 'correction'/'manual': those mean a
# person decided, and the accuracy sampler, the heal commands and this very
# detector all key off that distinction. The agent is the system filing time,
# so its work stays inside the population we measure ourselves on.
AGENT_ACTOR = 'mismatch_agent'


@dataclass
class Signal:
    """One piece of evidence, and who it points at."""
    kind: str                 # 'title' | 'file_path' | 'qb_company' | ...
    supports: int | None      # client id this evidence points at
    weight: float             # 0..1
    text: str                 # the line a human reads on the row
    independent: bool = False # does it count toward the corroboration rule?

    def as_dict(self):
        return {'kind': self.kind, 'supports': self.supports,
                'weight': round(self.weight, 3), 'text': self.text,
                'independent': self.independent}


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
    auto: bool = False                      # clears the bar AND has no veto
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
            'evidence': [s.as_dict() for s in self.signals],
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

def _title_signal(block, ctx):
    """The flag's own evidence: the window title names somebody.

    NOT independent — this is the claim under review, not a witness to it.
    """
    from tracker.utils.client_name_match import detect_title_client

    det = detect_title_client(block.window_title or '', ctx.index, ctx.names,
                              firm_name=ctx.firm_name)
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


def _neighbour_signal(block, ctx):
    """What this person was booked to immediately before and after.

    Weakest of the independent signals and the one most likely to be circular:
    if the neighbours were filed by the same classifier that filed this block,
    agreement between them is one opinion repeated. So neighbours only speak
    when a HUMAN set them, or when they carry a client name in their own title.
    """
    from tracker.models import Block

    if not (block.start and block.end):
        return None

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

    top_cid, top_sigs = max(rivals.items(),
                            key=lambda kv: sum(s.weight for s in kv[1]))
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
# Applying a draft
# ─────────────────────────────────────────────────────────────────────────────

def apply_draft(draft, block, ctx, approved_by=None):
    """Carry out one draft. Returns the resolved_reason, or None if nothing done.

    Re-checks the vetoes against the live row rather than trusting the draft:
    a draft written at 3am and applied after somebody edited the block at 9 is
    a draft about a block that no longer exists.

    `approved_by` is the person who read the draft and agreed with it, when
    there was one. The RESOLUTION REASON does not change either way — a moved
    block is 'reconciled' and a cleared flag is 'confirmed_correct', the same
    two words the scan, the manual assign path and the Cleared list already
    speak. Inventing agent-only reasons would have split that vocabulary in
    four and quietly broken the skip logic that makes "I checked, it's right"
    stick. Who did it lives in `resolved_by`, which is where it belongs.
    """
    from tracker.models import ClassificationAudit
    from tracker.services.classification_service import ClassificationService

    # resolved_by is 32 chars; a username here is an email address, so this
    # can and does run over.
    actor = (f'approved:{approved_by}'[:32] if approved_by else AGENT_ACTOR)

    if draft.verdict == VERDICT_STALE:
        # Bookkeeping, not judgement — 'reconciled' is the same reason and the
        # same basis the nightly scan closes in-window flags on.
        _resolve_flag(block, reason='reconciled', draft=draft, by=actor)
        return 'reconciled'

    if draft.verdict == VERDICT_CONFIRM:
        if not approved_by and not AGENT_MAY_CLOSE_FLAGS:
            return None
        _resolve_flag(block, reason='confirmed_correct', draft=draft, by=actor)
        return 'confirmed_correct'

    if draft.verdict != VERDICT_REASSIGN or not draft.target_client_id:
        return None
    if _vetoes(block, ctx, draft.target_client_id):
        return None
    if not approved_by and not draft.auto:
        return None
    if block.client_id == draft.target_client_id:
        return None

    old_client = block.client_id
    cat_before = ClassificationService._extract_dominant_category(block)

    block.client_id = draft.target_client_id
    fields = ['client_id']
    # The agent is the system filing time, not a person correcting it — see
    # AGENT_ACTOR. Stamping it as a human correction would quietly remove the
    # block from the random accuracy sample, which is the one measurement that
    # would catch this agent being wrong.
    block.state_changed_by = AGENT_ACTOR
    block.state_changed_at = timezone.now()
    block.categorized_by = AGENT_ACTOR
    if block.classification_state != 'committed':
        # Same trap the manual assign path hit: a block stranded in
        # proposed-limbo stays invisible to billing AND review unless the fix
        # also commits it, and then nothing anyone can see has changed.
        block.classification_state = 'committed'
        block.is_categorized = True
    fields += ['state_changed_by', 'state_changed_at', 'categorized_by',
               'classification_state', 'is_categorized']
    block.save(update_fields=fields, force_classifier=True)

    ClassificationAudit.objects.create(
        block=block, source='auto',
        client_before_id=old_client, client_after_id=draft.target_client_id,
        category_before=cat_before,
        category_after=ClassificationService._extract_dominant_category(block),
        confidence_client=draft.confidence,
        confidence_category=0.0,
        overall_confidence=draft.confidence,
        matched_signals=[{
            'type': 'mismatch_agent',
            'strength': round(s.weight, 3),
            'evidence': s.text,
            'detail': s.kind,
        } for s in draft.signals],
        # False even when a person clicked Approve: the CONTENT of the decision
        # is the agent's, and this flag is what the accuracy sampler reads to
        # decide whether a block is our filing or someone's judgement. Marking
        # approvals as human corrections would quietly excuse the agent from
        # the one measurement that can catch it being wrong.
        corrected_by_user=False,
    )
    _resolve_flag(block, reason='reconciled', draft=draft, by=actor,
                  title_client_id=draft.target_client_id,
                  title_client_name=draft.target_client_name)
    return 'reconciled'


def _resolve_flag(block, reason, draft, by=AGENT_ACTOR,
                  title_client_id=None, title_client_name=None):
    """Close the open flag (or record one) with the agent's reasoning attached."""
    from tracker.models import MismatchFlag

    now = timezone.now()
    payload = {
        'resolved_at': now,
        'resolved_reason': reason,
        'resolved_by': by,
        'agent_verdict': draft.verdict,
        'agent_confidence': draft.confidence,
        'agent_evidence': _evidence_payload(draft),
        'agent_summary': draft.summary,
        'agent_drafted_at': now,
    }
    if title_client_id:
        payload['agent_target_client_id'] = title_client_id

    f = MismatchFlag.objects.filter(block=block, resolved_at__isnull=True).first()
    if f:
        for k, v in payload.items():
            setattr(f, k, v)
        f.save(update_fields=list(payload.keys()))
        return f
    return MismatchFlag.objects.create(
        org_id=block.org_id, block=block,
        booked_client_id=block.client_id,
        title_client_id=title_client_id,
        title_client_name=title_client_name or '',
        bucket='client', match_score=draft.confidence,
        window_title=(block.window_title or '')[:512],
        **payload,
    )


def _evidence_payload(draft):
    """What gets stored on the flag — the reasoning, not just the witnesses.

    The vetoes and caveats travel WITH the signals because they are half the
    reasoning: "the file agrees" and "but this was already invoiced" are one
    thought, and a stored justification missing its second half reads as a
    confident recommendation the agent never made.
    """
    return {
        'signals': [s.as_dict() for s in draft.signals],
        'vetoes': list(draft.vetoes),
        'caveats': list(draft.caveats),
    }


def save_draft(flag, draft):
    """Attach a draft to an OPEN flag without resolving it — the queue-to-approve."""
    flag.agent_verdict = draft.verdict
    flag.agent_target_client_id = draft.target_client_id
    flag.agent_confidence = draft.confidence
    flag.agent_evidence = _evidence_payload(draft)
    flag.agent_summary = draft.summary
    flag.agent_drafted_at = timezone.now()
    flag.save(update_fields=['agent_verdict', 'agent_target_client',
                             'agent_confidence', 'agent_evidence',
                             'agent_summary', 'agent_drafted_at'])
    return flag


# ─────────────────────────────────────────────────────────────────────────────
# The run
# ─────────────────────────────────────────────────────────────────────────────

# The columns migration 0162 adds to MismatchFlag. Nothing in a dry run reads
# them, so nothing in a dry run should select them.
_DRAFT_FIELDS = ('resolved_by', 'agent_verdict', 'agent_target_client',
                 'agent_confidence', 'agent_evidence', 'agent_summary',
                 'agent_drafted_at')


def _draft_fields_on_model():
    """Which of those the running MODEL actually declares.

    Two different kinds of "not there yet" have to be survived and they fail at
    different layers. Between merge and the hand-applied migrate, the model has
    the fields and the database has no columns — deferring fixes that. Running
    this service against an older models.py (copying it into a checkout to try
    it before merging anything) has neither, and `.defer()` on a name the model
    does not declare raises FieldDoesNotExist before a single query is built.

    Asking the model what it has covers both, and costs one cached lookup.
    """
    from tracker.models import MismatchFlag

    have = {f.name for f in MismatchFlag._meta.get_fields()}
    return tuple(f for f in _DRAFT_FIELDS if f in have)


def run(org_ids=None, days=90, apply=False, limit=500, respect_optin=True):
    """Draft a resolution for every OPEN flag; apply the ones above the bar.

    Read-only unless `apply=True`, and even then only for orgs that have
    switched `mismatch_agent_autoresolve` on. The dry run is the useful mode:
    it is how you find out what the agent WOULD have done before letting it.

    `respect_optin=False` is for a deliberate operator-run sweep on one org
    (the management command's `--force`), never for the scheduled task.
    """
    from tracker.models import MismatchFlag, Organization

    if not org_ids:
        org_ids = list(Organization.objects.values_list('id', flat=True))

    # Which orgs have said the agent may act. Everyone else still gets drafts.
    acting = set()
    if apply:
        acting = set(
            Organization.objects
            .filter(id__in=org_ids, mismatch_agent_autoresolve=True)
            .values_list('id', flat=True)
        ) if respect_optin else set(org_ids)

    cutoff = timezone.now() - timedelta(days=days)
    flags = (MismatchFlag.objects
             .filter(org_id__in=org_ids, resolved_at__isnull=True,
                     block__deleted_at__isnull=True,
                     block__start__gte=cutoff)
             .select_related('block', 'block__client', 'booked_client')
             # Nothing here READS a previous draft — every run re-derives from
             # the block as it is now — so don't select those columns. Not a
             # micro-optimisation: it is what lets a dry run survive a database
             # that migration 0162 has not reached yet, which is every database
             # between the merge and the hand-applied migrate.
             #
             # Deferred on the FLAG only. Deferring anything on `block` would
             # reintroduce the refresh_from_db-per-row trap that SIGKILLed a
             # worker in #439.
             .defer(*_draft_fields_on_model())
             .order_by('-detected_at')[:limit])

    summary = {'drafted': 0, 'auto_reassigned': 0, 'auto_confirmed': 0,
               'queued': 0, 'skipped': 0, 'drafts': [],
               'acting_orgs': sorted(acting)}

    for flag in flags:
        block = flag.block
        if not block or not block.client_id:
            summary['skipped'] += 1
            continue
        ctx = context_for(block.org_id)
        draft = draft_for_block(block, ctx)
        summary['drafted'] += 1
        summary['drafts'].append(draft)

        may_act = apply and block.org_id in acting
        if not may_act or not draft.auto:
            # Persisting the draft is the whole point of the non-acting path:
            # the flag stays open, but the row now carries a proposed answer
            # and the evidence behind it.
            if apply:
                save_draft(flag, draft)
            summary['queued'] += 1
            continue

        try:
            with transaction.atomic():
                reason = apply_draft(draft, block, ctx)
        except Exception:
            log.exception('[MISMATCH-AGENT] apply failed on block %s', block.id)
            summary['skipped'] += 1
            continue

        if reason == 'reconciled':
            summary['auto_reassigned'] += 1
        elif reason == 'confirmed_correct':
            summary['auto_confirmed'] += 1
        else:
            save_draft(flag, draft)
            summary['queued'] += 1

    log.info('[MISMATCH-AGENT] orgs=%s drafted=%s reassigned=%s confirmed=%s '
             'queued=%s apply=%s', len(org_ids), summary['drafted'],
             summary['auto_reassigned'], summary['auto_confirmed'],
             summary['queued'], apply)
    return summary


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
