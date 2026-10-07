"""Re-file Gmail blocks once the mail they were written or read for has synced.

Stage 7a files a Gmail block to the client the user was writing to — but only
if the SENT message is already in MailSignal when the block is classified.
The agent usually uploads the block a minute or two after the user leaves
Gmail; Gmail sync runs every 5 minutes. So the block mostly wins the race, is
filed on its window title ("Inbox - MavOps Mail" → MAVOPS) with no mail to
see, and nothing ever looked at it again. Compose time never reached a client.

After every Gmail sync this looks at the user's recent Gmail blocks and, where
Stage 7a's STRONG rule now holds — the sends in the block go to exactly one
client and writing them covers >= 50% of the block — re-runs the classifier on
that block. The same goes for READING: a block whose open thread (its tab
title) is on one client's mail once that mail has synced (Stage 7b). The
classifier decides; this only supplies the second chance.

Never touched: blocks a person confirmed, edited or corrected, locked blocks,
suppressed blocks, and blocks already on that client. If the full classifier
does not land on the compose client (another strong signal disagrees), the
block is left exactly as it was.
"""
import logging

logger = logging.getLogger(__name__)

# state_changed_by / categorized_by values that mean a person decided.
PERSON_SOURCES = {'user', 'user_edit', 'correction', 'admin_bulk'}
PERSON_CATEGORIZED = {'manual', 'correction'}


def strong_compose_client(block, attributions):
    """Client id Stage 7a would file `block` to on its STRONG rule, else None.

    attributions: the SendAttributions owned by this block.
    """
    from tracker.services.classification_service import ClassificationService
    from tracker.services.mail_compose import block_active_seconds

    by_client = {}
    for att in attributions:
        cid = att.signal.extracted_client_id
        if cid:
            by_client[cid] = by_client.get(cid, 0) + att.seconds_within(block)
    if len(by_client) != 1:
        return None
    (cid, in_block), = by_client.items()
    active = block_active_seconds(block)
    if not active or in_block / active < ClassificationService.GMAIL_COMPOSE_MIN_COVERAGE:
        return None
    return cid


def strong_reading_client(block):
    """Client id Stage 7b would file `block` to: its open thread has one client."""
    from tracker.services.mail_compose import open_message_subject, thread_signals
    subject = open_message_subject(block)
    if not subject:
        return None
    clients = {r.extracted_client_id for r in thread_signals(block, subject) if r.extracted_client_id}
    return clients.pop() if len(clients) == 1 else None


def refile_composed_gmail_blocks(user, org, since, until=None) -> int:
    """Re-classify Gmail blocks whose compose or reading client is now known.
    Returns the count re-filed."""
    from django.utils import timezone
    from tracker.models import Block
    from tracker.services.classification_service import ClassificationService
    from tracker.services.mail_compose import attribute_sends, load_context

    if getattr(org, 'disable_mail_integration', False):
        return 0
    until = until or timezone.now()
    blocks, sends = load_context(user, since, until)
    if not blocks:
        return 0

    owned = {}
    for att in attribute_sends(blocks, sends).values():
        owned.setdefault(att.block.id, []).append(att)

    targets = {}
    for b in blocks:
        if b.end < since:
            continue
        # Composing to a client beats reading: it is what Stage 7a/7b do too.
        cid = strong_compose_client(b, owned[b.id]) if b.id in owned else None
        if cid is None:
            cid = strong_reading_client(b)
        if cid and cid != b.client_id:
            targets[b.id] = cid
    if not targets:
        return 0

    service = ClassificationService(org=org, user=user)
    refiled = 0
    for block in Block.objects.filter(id__in=targets, deleted_at__isnull=True).select_related('project'):
        cid = targets[block.id]
        if (block.locked or block.classification_state == 'suppressed'
                or (block.state_changed_by or '') in PERSON_SOURCES
                or (block.categorized_by or '') in PERSON_CATEGORIZED):
            continue
        decision = service.classify(block, skip_ai=True)
        if decision.client_id != cid:
            logger.info(f"[GMAIL-REFILE] block {block.pk}: classifier chose {decision.client_id}, "
                        f"not compose client {cid}; left as is")
            continue
        before = block.client_id
        # apply() keeps an existing client when the classifier disagrees
        # (agent attribution); that client is exactly what the late mail
        # overturns, so clear it first. A project belongs to its client.
        block.client_id = None
        if block.project_id and getattr(block.project, 'client_id', None) != cid:
            block.project = None
        service.apply(block, decision, source='classifier', propagate_current_client=False)
        _fix_audit_before(block, before)
        refiled += 1
        logger.info(f"[GMAIL-REFILE] block {block.pk}: client {before} → {cid} from Gmail compose")
    return refiled


def _fix_audit_before(block, before):
    """apply() audited the cleared client as 'before'; record the real one."""
    from tracker.models import ClassificationAudit
    audit = ClassificationAudit.objects.filter(block=block).order_by('-id').first()
    if audit and audit.client_before_id != before:
        audit.client_before_id = before
        audit.save(update_fields=['client_before_id'])
