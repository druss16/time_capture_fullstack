"""
The email outbox — MavOps' hold on every transactional email.

email_service.send_email() hands every email to dispatch(). It is recorded as an
OutboundEmail first, then — depending on the global EmailSendSettings — held for
review in MavOps Admin, sent to a test inbox instead of its recipient, or sent.

Fails CLOSED: if the settings cannot be read (a deploy that landed before its
migration, a database blip) nothing is sent. A held email can be released later;
an email that went out by accident cannot be recalled.
"""
import hashlib
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

HOLD, REDIRECT, LIVE = 'hold', 'redirect', 'live'
MODES = (HOLD, REDIRECT, LIVE)

# Every email type email_service sends, most specific first: a type is the
# first key here that appears in the email's SendGrid categories (the intake
# link carries "onboarding" too, so it must be checked before onboarding).
EMAIL_TYPES = [
    ('password_reset',      'Password reset',                 'A user asked to reset their password'),
    ('intake',              'Onboarding intake link',         'The firm questionnaire sent from the Onboarding Console'),
    ('connect_link',        'QuickBooks connect link',        'Asks a firm\u2019s QuickBooks admin to approve the connection'),
    ('onboarding',          'Invitation to join',             'A new user is invited to set up TimeTracker'),
    ('org_added',           'Added to a firm',                'An existing user is added to another firm'),
    ('timesheet_reminder',  'Daily review reminder',          'Daily nudge to review yesterday’s time'),
    ('submission_reminder', 'Submit your timesheet',          'Monday reminder to submit last week'),
    ('auto_submit',         'Timesheet auto-submitted',       'Tuesday notice that a draft week was submitted for them'),
    ('manager_approval',    'Approvals waiting (managers)',   'Managers told how many timesheets wait for approval'),
    ('timesheet_approved',  'Timesheet approved',             'A manager approved the user’s week'),
    ('timesheet_rejected',  'Timesheet sent back',            'A manager rejected the user’s week'),
    ('weekly_summary',      'Weekly summary',                 'Monday summary of last week’s time'),
    ('rule_suggestion',     'Rule suggestion',                'A suggested routing rule for an admin'),
    ('seat_overage',        'Seat overage notice',            'Billing notice that a firm is over its seats'),
    ('error_alert',         'Critical agent error (to MavOps)', 'Internal alert to dan@mavops.ai'),
]
TYPE_KEYS = [k for k, _, _ in EMAIL_TYPES]

# Window inside which the same email to the same person is one email. Beat
# fires on round minutes; offsetting the buckets by half a window keeps their
# edges away from those minutes, so two fires 30ms apart share a bucket.
DEDUPE_WINDOW = timedelta(minutes=15)


def email_type_for(categories) -> str:
    cats = list(categories or [])
    for key in TYPE_KEYS:
        if key in cats:
            return key
    return cats[0][:40] if cats else 'other'


def read_settings():
    """
    {'mode', 'redirect_to', 'live_types'} — a missing row means hold.
    Raises when the table cannot be read; dispatch() turns that into "send nothing".
    """
    from tracker.models import EmailSendSettings
    row = EmailSendSettings.objects.filter(pk=1).first()
    if row is None:
        return {'mode': HOLD, 'redirect_to': '', 'live_types': []}
    return {
        'mode': row.mode if row.mode in MODES else HOLD,
        'redirect_to': row.redirect_to or '',
        'live_types': [t for t in (row.live_types or []) if isinstance(t, str)],
    }


def save_settings(*, mode=None, redirect_to=None, live_types=None, user=None):
    from tracker.models import EmailSendSettings
    row, _ = EmailSendSettings.objects.get_or_create(pk=1)
    if mode is not None:
        if mode not in MODES:
            raise ValueError(f'Unknown mode {mode!r}')
        row.mode = mode
    if redirect_to is not None:
        row.redirect_to = redirect_to.strip()
    if live_types is not None:
        row.live_types = sorted({t for t in live_types if isinstance(t, str)})
    row.updated_by_id = getattr(user, 'id', None)
    row.save()
    return read_settings()


def _redirect_address(cfg) -> str:
    from django.conf import settings
    return cfg.get('redirect_to') or getattr(settings, 'DEFAULT_REPLY_TO_EMAIL', '') or ''


def _dedupe_key(to_email, subject, html_content, now) -> str:
    digest = hashlib.sha256(
        f'{to_email.strip().lower()}\x00{subject}\x00{html_content}'.encode('utf-8', 'replace')
    ).hexdigest()[:48]
    window = DEDUPE_WINDOW.total_seconds()
    bucket = int((now.timestamp() + window / 2) // window)
    return f'{digest}:{bucket}'


def _org_for_recipient(to_email):
    """(org_id, org_name) of the recipient's firm, for display only."""
    try:
        from django.contrib.auth import get_user_model
        from tracker.models import OrganizationMembership
        user = get_user_model().objects.filter(email__iexact=to_email.strip()).first()
        if user is None:
            return None, ''
        m = (OrganizationMembership.objects.select_related('organization')
             .filter(user=user).first())
        if m is None:
            return None, ''
        return m.organization_id, m.organization.name or ''
    except Exception:
        return None, ''


def dispatch(*, to_email, subject, html_content, plain_content, from_email,
             from_name, reply_to, categories) -> bool:
    """Record one email and route it per the current settings. See module doc."""
    email_type = email_type_for(categories)
    try:
        cfg = read_settings()
    except Exception as e:
        logger.error('[EMAIL] outbox settings unreadable — NOT sending %s to %s: %s',
                     email_type, to_email, e)
        return False

    from tracker.models import OutboundEmail
    org_id, org_name = _org_for_recipient(to_email)
    try:
        with transaction.atomic():
            email = OutboundEmail.objects.create(
                email_type=email_type,
                to_email=to_email,
                from_email=from_email,
                from_name=from_name or '',
                reply_to=reply_to or '',
                subject=subject[:500],
                html_content=html_content,
                plain_content=plain_content or '',
                categories=list(categories or []),
                org_id=org_id,
                org_name=org_name[:255],
                dedupe_key=_dedupe_key(to_email, subject, html_content, timezone.now()),
            )
    except IntegrityError:
        logger.warning('[EMAIL] duplicate %s to %s within %s — dropped',
                       email_type, to_email, DEDUPE_WINDOW)
        return True
    except Exception as e:
        logger.error('[EMAIL] outbox unwritable — NOT sending %s to %s: %s',
                     email_type, to_email, e)
        return False

    if cfg['mode'] == LIVE or email_type in cfg['live_types']:
        return deliver(email)
    if cfg['mode'] == REDIRECT:
        target = _redirect_address(cfg)
        if target:
            ok = deliver(email, redirect_to=target)
            if ok:
                email.status = 'redirected'
                email.save(update_fields=['status'])
            return ok
        logger.warning('[EMAIL] redirect mode with no test inbox — holding %s', email.id)
    logger.info('[EMAIL] held %s #%s to %s for review', email_type, email.id, to_email)
    return True


def deliver(email, *, redirect_to=None, user=None) -> bool:
    """
    Send one outbox email. With redirect_to it goes to that inbox instead, the
    real recipient named in the subject, and the email stays releasable.
    """
    from tracker.email_service import post_to_sendgrid

    if redirect_to:
        to, subject = redirect_to, f'[TEST → {email.to_email}] {email.subject}'
    else:
        to, subject = email.to_email, email.subject

    ok, http_status, err = post_to_sendgrid(
        to_email=to,
        subject=subject,
        html_content=email.html_content,
        plain_content=email.plain_content,
        from_email=email.from_email,
        from_name=email.from_name,
        reply_to=email.reply_to or None,
        categories=email.categories or None,
    )
    email.sendgrid_status = http_status
    email.acted_by_id = getattr(user, 'id', None) or email.acted_by_id
    if ok:
        email.sent_to = to
        email.sent_at = timezone.now()
        email.error = ''
        # A real send is final; a test copy leaves the email where it was.
        if not redirect_to:
            email.status = 'sent'
    else:
        email.error = err or 'SendGrid refused the email'
        if not redirect_to:
            email.status = 'failed'
    email.save(update_fields=['status', 'sent_to', 'sent_at', 'sendgrid_status',
                              'error', 'acted_by_id'])
    return ok


RELEASABLE = ('held', 'redirected', 'failed')


def release(email, user=None) -> bool:
    """Send a held email to its real recipient."""
    if email.status not in RELEASABLE:
        raise ValueError(f'Email {email.id} is {email.status}')
    return deliver(email, user=user)


def send_test(email, to_address, user=None) -> bool:
    """Send a copy to `to_address`; the email itself stays where it was."""
    if not to_address:
        raise ValueError('No address to send the test to')
    return deliver(email, redirect_to=to_address, user=user)


def discard(email, user=None):
    if email.status not in RELEASABLE:
        raise ValueError(f'Email {email.id} is {email.status}')
    email.status = 'discarded'
    email.acted_by_id = getattr(user, 'id', None)
    email.save(update_fields=['status', 'acted_by_id'])
