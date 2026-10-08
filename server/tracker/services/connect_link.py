"""
Connect link — a firm's QuickBooks admin connects QuickBooks Online and/or
QuickBooks Time from one emailed link, with no TimeTracker login.

Why: Intuit only lets a company admin approve a connection, and that is
usually a bookkeeper who will never use TimeTracker. Before this, connecting
meant giving them an owner/admin account and a call. Now the operator sends a
link from the Onboarding Console (or re-sends it when a connection lapses).

The flow reuses the existing OAuth plumbing end to end — same Intuit apps,
same redirect URIs, same callbacks. The only differences:

  * /start/ mints the state the Settings button would, and also records it
    on the ConnectLink, so the callback can recognise a link-started grant;
  * the callback then calls finish(), which stamps the link and, for
    QuickBooks Online, imports every active customer straight away (the
    playbook's "remove vendors/partners" step reviews what came in);
  * success and failure return to the link's page instead of Settings.

QuickBooks Time needs one connection per FIRM, not per person: that one
token writes every member's timesheets, matched to QuickBooks Time users by
email (qb_time/sync._sync_staff). So the page lists members with no match —
the one thing that stops a person's time from arriving.
"""
import logging
import secrets

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from tracker.models import Integration
from tracker.models_onboarding_console import CONNECT_PROVIDERS, ConnectLink

logger = logging.getLogger(__name__)

LABELS = {'quickbooks': 'QuickBooks Online', 'qb_time': 'QuickBooks Time', 'asana': 'Asana'}
_STATE_FIELD = {'quickbooks': 'qbo_state', 'qb_time': 'qbt_state', 'asana': 'asana_state'}
_DONE_FIELD = {'quickbooks': 'qbo_connected_at', 'qb_time': 'qbt_connected_at',
               'asana': 'asana_connected_at'}


class ConnectLinkError(Exception):
    pass


def frontend_base():
    return getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai').rstrip('/')


def link_url(raw):
    return f'{frontend_base()}/connect/{raw}'


def return_url(provider, ok, reason=''):
    """Where a callback sends the browser. The page holds the raw token in
    sessionStorage (only its hash is stored here) and reloads itself."""
    from urllib.parse import urlencode
    q = {'provider': provider, 'status': 'connected' if ok else 'error'}
    if reason:
        q['reason'] = reason
    return f'{frontend_base()}/connect/return?{urlencode(q)}'


def get_open(raw):
    link = (ConnectLink.objects.select_related('organization')
            .filter(token_hash=ConnectLink.hash_token(raw or '')).first())
    return link


def is_configured(provider):
    if provider == 'quickbooks':
        return bool(getattr(settings, 'QUICKBOOKS_CLIENT_ID', ''))
    if provider == 'asana':
        from tracker.integrations.asana.client import is_configured as asana_configured
        return bool(asana_configured())
    from tracker.integrations.qb_time.client import is_configured as qbt_configured
    return bool(qbt_configured())


def link_for_state(provider, state):
    """The ConnectLink that started this grant, or None.

    Never raises: the shared callbacks call this on every connect, including
    from Settings, and must keep working on a database where the ConnectLink
    migration has not run yet (Render deploys code before migrations).
    """
    if not state or provider not in _STATE_FIELD:
        return None
    try:
        return (ConnectLink.objects.select_related('organization')
                .filter(**{_STATE_FIELD[provider]: state}).first())
    except DatabaseError as e:
        logger.warning('connect link lookup skipped (%s): %s', provider, e)
        return None


def start(link, provider):
    """Mint the OAuth state and return Intuit's consent URL."""
    if not link.is_open:
        raise ConnectLinkError('This link has expired. Ask Mavops for a new one.')
    if provider not in link.providers:
        raise ConnectLinkError('This link is not for that connection.')
    if not is_configured(provider):
        raise ConnectLinkError(f'{LABELS[provider]} is not available yet. Please let Mavops know.')

    state = secrets.token_urlsafe(32)
    Integration.objects.update_or_create(
        organization=link.organization, provider=provider, defaults={'oauth_state': state})
    setattr(link, _STATE_FIELD[provider], state)
    link.save(update_fields=[_STATE_FIELD[provider]])

    if provider == 'quickbooks':
        from tracker.views_integrations import quickbooks_auth_url
        return quickbooks_auth_url(state)
    if provider == 'asana':
        from tracker.integrations.asana.client import authorize_url as asana_authorize_url
        return asana_authorize_url(state)
    from tracker.integrations.qb_time.client import authorize_url
    return authorize_url(settings.QBTIME_CLIENT_ID, settings.QBTIME_REDIRECT_URI, state)


def finish(link, provider, integration):
    """Called by the callback after the tokens are saved. Never raises —
    the connection itself already succeeded."""
    now = timezone.now()
    setattr(link, _DONE_FIELD[provider], now)
    setattr(link, _STATE_FIELD[provider], '')
    link.save(update_fields=[_DONE_FIELD[provider], _STATE_FIELD[provider]])
    _audit(link, f'connect.{provider}', realm=integration.realm_id)

    if provider == 'quickbooks':
        try:
            from tracker.views_integrations import import_qb_customers
            result, err = import_qb_customers(link.organization, integration)
            if err is not None:
                logger.warning('connect link: QuickBooks customer import failed for org %s: %s',
                               link.organization_id, getattr(err, 'data', err))
            else:
                _audit(link, 'connect.quickbooks.import', **result['summary'])
        except Exception:                                          # noqa: BLE001
            logger.exception('connect link: QuickBooks customer import crashed for org %s',
                             link.organization_id)


def _audit(link, action, **detail):
    if not link.project_id:
        return
    try:
        from tracker.services.onboarding_console import audit
        audit(link.project, None, action, **detail)
    except Exception:                                              # noqa: BLE001
        logger.exception('connect link audit failed')


def unmatched_members(org, integration):
    """Members with no QuickBooks Time user of the same email — their time
    is skipped on push until the emails agree."""
    from tracker.models import OrganizationMembership
    from tracker.models_task_type_sets import ExternalStaffMapping
    mapped = set(ExternalStaffMapping.objects.filter(integration=integration)
                 .values_list('user_id', flat=True))
    rows = (OrganizationMembership.objects.filter(organization=org, user__is_active=True)
            .exclude(user_id__in=mapped).select_related('user').order_by('user__first_name'))
    return [{'name': m.user.get_full_name() or m.user.email, 'email': m.user.email} for m in rows]


def status(link):
    """What the firm's page shows."""
    org = link.organization
    out = []
    for p in link.providers:
        integration = Integration.objects.filter(organization=org, provider=p).first()
        connected = bool(integration and integration.is_connected)
        row = {'key': p, 'label': LABELS[p], 'connected': connected,
               'configured': is_configured(p)}
        if p == 'qb_time' and connected:
            row['sync_status'] = integration.last_sync_status or ''
            row['unmatched'] = unmatched_members(org, integration)
        if p == 'quickbooks' and connected:
            from tracker.models import Client
            row['clients'] = Client.objects.filter(org=org, imported_from='quickbooks').count()
        if p == 'asana' and connected:
            # Linked projects + who has no Asana account of the same email:
            # their Asana time cannot be filed until it matches.
            from tracker.integrations.asana.views import asana_status
            row['sync_status'] = integration.last_sync_status or ''
            row.update(asana_status(integration))
            row['unmatched'] = unmatched_members(org, integration)
        out.append(row)
    return {
        'firm': org.name,
        'providers': out,
        'expires_at': link.expires_at.isoformat(),
        'open': link.is_open,
    }


def send(link, raw, *, to_email, contact_name=''):
    """Email the link. Returns True if it went out."""
    from tracker.email_service import send_connect_link
    try:
        return bool(send_connect_link(
            to_email=to_email, firm_name=link.organization.name, connect_url=link_url(raw),
            providers=[LABELS[p] for p in link.providers],
            contact_name=(contact_name or '').strip() or None,
            expires_on=f'{link.expires_at:%B %-d}'))
    except Exception:                                              # noqa: BLE001
        logger.exception('connect link email failed')
        return False

