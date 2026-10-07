"""Gmail compose duration — how long the user spent writing a SENT message.

Gmail records when a message was sent, not how long it took to write. What we
do know is when the user was in Gmail: their own captured blocks, whose URL is
mail.google.com or whose window title ends in "Gmail". So:

    compose time of a send at T = the contiguous run of Gmail time that ends at
    T, starting no earlier than the previous send in that same run.

"Contiguous" joins Gmail blocks separated by <= CHAIN_GAP (the agent splits a
long session at idle blips). A send is owned by the Gmail block it happened in,
or — because the SENT timestamp can land a moment after the agent closed the
block — by the last Gmail block that ended within SEND_GRACE before it.

Every function here is pure over the rows it is given, so Stage 7, the
evidence panel and the post-sync annotator all compute the same answer.

A send with no Gmail block around it (sent from a phone, from another client,
or before the agent flushed) has no compose time: None, not zero.
"""
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

GMAIL_HOST = 'mail.google.com'
SEND_GRACE = timedelta(minutes=3)
CHAIN_GAP = timedelta(minutes=2)
# How far back a Gmail run may reach when loading blocks for one send.
LOOKBACK = timedelta(hours=3)


def is_gmail_block(block) -> bool:
    """Is this block the user in Gmail (web)?"""
    url = (getattr(block, 'url', '') or '').strip()
    if url:
        try:
            host = (urlparse(url if '://' in url else f'https://{url}').hostname or '').lower()
        except ValueError:
            host = ''
        if host == GMAIL_HOST:
            return True
    for attr in ('window_title', 'title'):
        t = (getattr(block, attr, '') or '').strip().lower()
        if not t:
            continue
        # Browser titles: "Inbox (3) - jane@acme.com - Gmail", sometimes with
        # the browser name appended ("... - Gmail - Google Chrome").
        if t.endswith('gmail') or ' - gmail - ' in t or GMAIL_HOST in t:
            return True
        # A Workspace can rename Gmail ("MavOps Mail"), and the agent only has
        # the URL when it may script the browser. Recognise the mailbox
        # segment instead: after the owner's address, or just before the
        # browser banner / Chrome's memory label.
        if _BROWSER_RE.search(t) and not _OTHER_WEBMAIL_RE.search(t) and (
                _BRANDED_AFTER_ADDRESS_RE.search(t) or _BRANDED_BEFORE_BANNER_RE.search(t)):
            return True
    return False


_BROWSER_RE = re.compile(r'google chrome|microsoft\s*edge|mozilla firefox|safari|brave|arc\b')
_OTHER_WEBMAIL_RE = re.compile(r'\b(?:yahoo|outlook|hotmail|proton|aol|icloud|zoho|fastmail)\b')
_BRANDED_AFTER_ADDRESS_RE = re.compile(r'[^\s@]+@[^\s@]+\s*[-–—]\s*[^-–—@]{0,40}?\bmail\s*(?:[-–—]|$)')
_BRANDED_BEFORE_BANNER_RE = re.compile(
    r'[-–—]\s*[^-–—@]{0,40}?\bmail\s*[-–—]\s*'
    r'(?:high memory usage|google chrome|microsoft\s*edge|mozilla firefox)')


@dataclass
class _Chain:
    start: object
    end: object
    blocks: list = field(default_factory=list)


def _chains(gmail_blocks) -> List[_Chain]:
    chains: List[_Chain] = []
    for b in sorted(gmail_blocks, key=lambda x: x.start):
        if not b.start or not b.end:
            continue
        if chains and b.start - chains[-1].end <= CHAIN_GAP:
            chains[-1].end = max(chains[-1].end, b.end)
            chains[-1].blocks.append(b)
        else:
            chains.append(_Chain(start=b.start, end=b.end, blocks=[b]))
    return chains


@dataclass
class SendAttribution:
    signal: object
    block: object
    compose_seconds: int
    # When composing began (chain start or previous send). With the send time
    # this is the compose WINDOW, which may start in an earlier Gmail block.
    compose_start: object = None

    def seconds_within(self, block) -> int:
        """Compose seconds that fall inside `block` itself."""
        if self.compose_start is None or not block.start or not block.end:
            return 0
        lo = max(self.compose_start, block.start)
        hi = min(self.signal.occurred_at, block.end)
        return max(0, int((hi - lo).total_seconds()))


def attribute_sends(gmail_blocks, sends) -> Dict[int, SendAttribution]:
    """Assign each outbound send to its owning Gmail block + compose time.

    gmail_blocks: the user's Gmail blocks (anything else is filtered out).
    sends: outbound MailSignal rows (any order).
    Returns {signal.id: SendAttribution}; sends with no Gmail block are absent.
    """
    chains = _chains([b for b in gmail_blocks if is_gmail_block(b)])
    out: Dict[int, SendAttribution] = {}
    last_send_in_chain: Dict[int, object] = {}
    for sig in sorted(sends, key=lambda s: s.occurred_at):
        t = sig.occurred_at
        candidates = [
            (ci, ch) for ci, ch in enumerate(chains)
            if ch.start <= t <= ch.end + SEND_GRACE
        ]
        if not candidates:
            continue
        # A chain the send is actually inside beats one it trails by grace.
        inside = [c for c in candidates if c[1].start <= t <= c[1].end]
        ci, ch = (inside or candidates)[-1]
        # Owning block: the one containing t, else the last one before t.
        owner = next((b for b in ch.blocks if b.start <= t <= b.end), None)
        if owner is None:
            before = [b for b in ch.blocks if b.start <= t]
            owner = before[-1] if before else ch.blocks[0]
        begin = max(ch.start, last_send_in_chain.get(ci, ch.start))
        end = min(t, ch.end)
        secs = max(0, int((end - begin).total_seconds()))
        out[sig.id] = SendAttribution(
            signal=sig, block=owner, compose_seconds=secs, compose_start=begin,
        )
        last_send_in_chain[ci] = t
    return out


def load_context(user, start, end):
    """Gmail blocks + outbound Gmail sends for [start, end] (with margins)."""
    from tracker.models import Block, MailSignal

    blocks = [
        b for b in Block.objects.filter(
            user=user,
            deleted_at__isnull=True,
            end__gte=start - LOOKBACK,
            start__lte=end + SEND_GRACE,
        ).only('id', 'start', 'end', 'minutes', 'url', 'title', 'window_title', 'user_id', 'client_id')
        if is_gmail_block(b)
    ]
    sends = list(
        MailSignal.objects.filter(
            user=user,
            provider='google',
            direction='out',
            occurred_at__gte=start - LOOKBACK,
            occurred_at__lte=end + SEND_GRACE,
        ).select_related('extracted_client').order_by('occurred_at')
    )
    return blocks, sends


def sends_for_block(block) -> List[SendAttribution]:
    """The Gmail sends that happened in `block` (empty unless it is Gmail)."""
    if not is_gmail_block(block) or not block.start or not block.end:
        return []
    blocks, sends = load_context(block.user, block.start, block.end)
    if not any(b.id == block.id for b in blocks):
        blocks.append(block)
    attributed = attribute_sends(blocks, sends)
    return sorted(
        (a for a in attributed.values() if a.block.id == block.id),
        key=lambda a: a.signal.occurred_at,
    )


def annotate_compose_seconds(user, since, until=None) -> int:
    """Fill MailSignal.compose_seconds for this user's Gmail sends since `since`.

    Runs after every Gmail sync. Blocks for recent work may not exist yet when
    the sync lands (the agent uploads and compaction runs on their own clock),
    so rows stay NULL and are retried by the next sync until they age past the
    caller's window. Returns the number of rows updated.
    """
    from django.utils import timezone
    from tracker.models import MailSignal

    until = until or timezone.now()
    blocks, sends = load_context(user, since, until)
    sends = [s for s in sends if s.occurred_at >= since]
    if not sends or not blocks:
        return 0
    updated = 0
    for sid, att in attribute_sends(blocks, sends).items():
        if att.signal.compose_seconds != att.compose_seconds:
            MailSignal.objects.filter(id=sid).update(compose_seconds=att.compose_seconds)
            updated += 1
    return updated


def fmt_minutes(seconds: Optional[int]) -> str:
    """'~6 min', '<1 min', '' for None."""
    if seconds is None:
        return ''
    if seconds < 60:
        return '<1 min'
    return f'~{round(seconds / 60)} min'


def block_active_seconds(block) -> int:
    """The block's measured (active) duration: Block.minutes when recorded,
    else wall-clock end - start. Denominator of the compose-coverage test."""
    if getattr(block, 'minutes', None):
        return int(block.minutes) * 60
    if block.start and block.end:
        return max(0, int((block.end - block.start).total_seconds()))
    return 0


# ─── Reading time ─────────────────────────────────────────────────────────────
#
# With a message open, Gmail's tab title IS its subject: "Re: Q3 engagement
# letter - dan@mavops.ai - MavOps Mail". Strip the mailbox and browser chrome
# and what is left names the thread. If the user's synced mail has that
# subject with exactly one client, the time spent reading it is that client's.
# A list view ("Inbox (3)", "Sent Mail", a search) names no thread.

READING_LOOKBACK = timedelta(days=30)
_SUBJECT_PREFIX_RE = re.compile(r'^\s*(?:(?:re|fwd?|aw|sv|wg)\s*(?:\[\d+\])?\s*:\s*)+', re.I)
_GMAIL_VIEWS = {
    'inbox', 'sent', 'sent mail', 'drafts', 'starred', 'snoozed', 'important',
    'all mail', 'spam', 'trash', 'bin', 'scheduled', 'outbox', 'chats',
    'search results', 'compose', 'new message', 'gmail', 'mail', 'primary',
    'promotions', 'social', 'updates', 'forums',
}
MIN_SUBJECT_LEN = 8


def normalize_subject(subject) -> str:
    """Thread key: no Re:/Fwd: prefixes, case or spacing differences."""
    s = _SUBJECT_PREFIX_RE.sub('', subject or '')
    return ' '.join(s.lower().split())


def open_message_subject(block) -> str:
    """Normalized subject of the message open in this Gmail block, or ''."""
    if not is_gmail_block(block):
        return ''
    from tracker.utils.client_name_match import strip_app_chrome
    title = strip_app_chrome(getattr(block, 'window_title', '') or getattr(block, 'title', '') or '')
    title = re.sub(r'\s*\(\d[\d,]*\)\s*', ' ', title)     # unread counts
    title = re.sub(r'\s*[-–—]\s*gmail\s*$', '', title, flags=re.I)
    subject = normalize_subject(title)
    if len(subject) < MIN_SUBJECT_LEN or subject in _GMAIL_VIEWS:
        return ''
    # A search page: "Search results - from:acme.com"
    if subject.startswith('search results') or subject.startswith('label:'):
        return ''
    return subject


def thread_signals(block, subject):
    """The user's synced Gmail messages on this thread, up to the block's end."""
    from tracker.models import MailSignal
    if not subject or not block.end:
        return []
    core = _SUBJECT_PREFIX_RE.sub('', subject).strip()
    rows = MailSignal.objects.filter(
        user_id=block.user_id,
        provider='google',
        occurred_at__gte=block.end - READING_LOOKBACK,
        occurred_at__lte=block.end,
        subject__icontains=core[:200],
    ).select_related('extracted_client')
    return [r for r in rows if normalize_subject(r.subject) == subject]
