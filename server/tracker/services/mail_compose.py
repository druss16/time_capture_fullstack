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
    return False


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
        out[sig.id] = SendAttribution(signal=sig, block=owner, compose_seconds=secs)
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
        ).only('id', 'start', 'end', 'url', 'title', 'window_title', 'user_id')
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
