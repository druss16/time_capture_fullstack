"""
Clio Manage sync orchestration.

Pulls contacts, matters, and users from Clio and mirrors them into:
  - Client               (one row per Clio company/person that is a client)
  - Project              (one row per Clio matter) + ExternalMatterMapping
  - ExternalStaffMapping (Clio user ↔ internal User, needed to attribute pushed time)

IDEMPOTENT — safe to re-run. Everything is keyed on (integration, external_id),
so a second run updates in place rather than duplicating.

WHY MATTERS BECOME PROJECTS
---------------------------
Clio rejects a TimeEntry with no matter id, so client-level attribution is not
enough to push legal time. Every Clio matter mirrors to exactly one Project.
This is a structural reflection of Clio — not a per-firm setting — so there is
no branch here and no configuration to get wrong.

REQUEST BUDGET
--------------
Clio allows ~50 requests/minute per firm. This sync is deliberately built from
whole-collection scans (3 endpoints, ~200 records per request) rather than
per-record lookups: a firm with 2,000 matters costs ~10 requests, not 2,000.
Every existing mapping is preloaded into a dict up front so the inner loops do
no per-record queries either.

⚠️ FIELD NAMES: verified against Clio's API v4 docs but NOT yet exercised
against a live account. Reads go through `_pick()` with fallbacks so an
unexpected key degrades to a blank value instead of raising, and the raw
payload is logged at DEBUG for the first record of each collection.
"""

import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from tracker.integrations.clio.client import ClioClient, ClioError
from tracker.models import Client, Integration, OrganizationMembership, Project
from tracker.models_task_type_sets import (
    ExternalClientMapping,
    ExternalMatterMapping,
    ExternalStaffMapping,
)

logger = logging.getLogger(__name__)
User = get_user_model()

# ── Field lists ─────────────────────────────────────────────────────────
# Clio returns only id+etag when `fields` is omitted, so these are load-bearing.
# Nesting is one level deep only.
CONTACT_FIELDS = 'id,name,first_name,last_name,type,primary_email_address'
MATTER_FIELDS = (
    'id,display_number,description,status,billable,billing_method,'
    'require_utbms_codes,client{id,name},open_date,'
    'responsible_attorney{id,name},practice_area{id,name}'
)
USER_FIELDS = 'id,name,first_name,last_name,email,enabled'

# Clio matter statuses that can still receive time.
OPEN_MATTER_STATUSES = {'open', 'pending'}


def _pick(record, *keys, default=''):
    """First present, non-empty value among `keys`. Tolerates field renames."""
    for key in keys:
        value = record.get(key)
        if value not in (None, '', []):
            return value
    return default


def _contact_display_name(record):
    """Clio companies carry `name`; people may only carry first/last."""
    name = _pick(record, 'name')
    if name:
        return str(name)[:255]
    parts = [str(_pick(record, 'first_name')), str(_pick(record, 'last_name'))]
    return ' '.join(p for p in parts if p).strip()[:255]


def _matter_project_name(record):
    """
    Build a Project name that is unique within the firm.

    Project is unique on (org, client, name), and two matters for the same
    client can easily share a description ("Estate Planning"). The Clio
    display number is unique per firm, so leading with it guarantees no
    collision while staying readable.
    """
    number = str(_pick(record, 'display_number')).strip()
    description = str(_pick(record, 'description')).strip()
    if number and description:
        name = f'{number} — {description}'
    else:
        name = number or description or f'Matter {record.get("id")}'
    return name[:200]


def _log_first(collection, record, logged):
    """Log one raw record per collection so field-name drift is diagnosable."""
    if collection not in logged:
        logged.add(collection)
        logger.debug('Clio %s sample payload: %s', collection, record)


# ============================================================================
# Top-level orchestrator
# ============================================================================

def full_sync(integration: Integration) -> dict:
    """
    Pull contacts, matters, and staff. Returns a stats dict for the sync log.

    Order matters: matters carry a nested client, so contacts run first and
    populate the id → Client map that matters then reuse.
    """
    started_at = timezone.now()

    stats = {
        'started_at': started_at.isoformat(),
        'integration_id': integration.id,
        'org_id': integration.organization_id,
        'contacts': {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0},
        'matters': {'fetched': 0, 'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0},
        'staff': {'fetched': 0, 'matched': 0, 'unmatched': 0, 'errors': 0},
        'errors': [],
    }

    try:
        # Constructed INSIDE the try on purpose. It raises when the process is
        # missing CLIO_CLIENT_ID/SECRET — which is what happens when the Celery
        # worker is deployed without the same environment as the web service.
        # Built outside, that exception escaped before anything recorded a
        # status, so the UI showed a connected integration with a blank sync
        # state and no way to tell "misconfigured" from "never ran".
        api = ClioClient(integration)

        stats['contacts'], client_by_external_id = sync_contacts(api, integration)
        stats['matters'] = sync_matters(api, integration, client_by_external_id)
        stats['staff'] = sync_staff(api, integration)

        # Derive aliases for the clients we just pulled. Without this a firm has
        # to name folders with the full legal entity — "Ridgeline Holdings LLC"
        # rather than "Ridgeline" — because the matcher only ever saw the exact
        # Clio name. QuickBooks and Xero imports have always done this; Clio was
        # missing it, which made every synced client invisible to file and window
        # matching.
        if stats['contacts'].get('created') or stats['contacts'].get('updated'):
            try:
                from tracker.views_integrations import run_post_import_alias_derivation
                run_post_import_alias_derivation(integration.organization)
            except Exception as e:
                logger.warning('Clio alias derivation failed: %s', e, exc_info=True)

        # Matters have just landed; use them. Best-effort — an attribution
        # problem must never fail the sync that succeeded.
        try:
            from tracker.services.matter_attribution import attribute_matters_for_org
            stats['attribution'] = attribute_matters_for_org(integration.organization)
        except Exception as e:
            logger.warning('Matter attribution after Clio sync failed: %s', e, exc_info=True)
            stats['attribution'] = {'error': str(e)[:200]}

        # Subscribe to live changes now that a token is known-good and the
        # roster exists. Idempotent and best-effort: a healthy subscription
        # short-circuits, and a failure here costs the firm latency (they fall
        # back to this hourly sweep), never data.
        try:
            from tracker.integrations.clio.webhooks import register_webhooks
            stats['webhooks'] = register_webhooks(integration)
        except Exception as e:
            logger.warning('Clio webhook registration failed: %s', e, exc_info=True)
            stats['webhooks'] = {'errors': [str(e)[:200]]}

        integration.last_synced_at = timezone.now()
        integration.last_sync_status = 'success' if not stats['errors'] else 'partial'
        integration.last_sync_error = ''
        integration.save(update_fields=[
            'last_synced_at', 'last_sync_status', 'last_sync_error', 'updated_at',
        ])

    except Exception as e:
        # Deliberately broad. This runs on a worker, so an unrecorded exception
        # is invisible to the person who pressed Sync — they get a success toast
        # and a counter that never moves. Whatever went wrong, it gets written
        # somewhere the UI can show it.
        integration.last_sync_status = 'failed'
        integration.last_sync_error = f'{type(e).__name__}: {e}'[:500]
        integration.save(update_fields=[
            'last_sync_status', 'last_sync_error', 'updated_at',
        ])
        stats['errors'].append(str(e))
        logger.exception('Clio sync failed for integration %s', integration.id)

    stats['completed_at'] = timezone.now().isoformat()
    return stats


# ============================================================================
# Contacts → Client
# ============================================================================

class ContactCache:
    """
    Preloaded lookups for the contact pass.

    Built once and mutated as records land, so the inner loop does no
    per-record queries — a 2,000-contact firm costs two queries, not 4,000.

    The webhook path builds one of these for a single record. That trades two
    cheap queries for ONE shared code path, which is the whole point: a second
    implementation of "which Client is this Clio contact" is exactly where the
    two would drift and start creating duplicate clients.
    """

    def __init__(self, integration: Integration):
        self.mappings = {
            m.external_id: m
            for m in ExternalClientMapping.objects.filter(
                integration=integration
            ).select_related('client')
        }
        self.clients_by_name = {
            c.name.strip().lower(): c
            for c in Client.objects.filter(org=integration.organization)
        }


def _contact_email(record) -> str:
    """Clio's email field is sometimes an object rather than a string."""
    raw = _pick(record, 'primary_email_address')
    if isinstance(raw, dict):
        return str(_pick(raw, 'address'))[:254]
    return str(raw)[:254]


def upsert_contact(integration: Integration, record: dict, *, cache=None, now=None):
    """
    Mirror ONE Clio contact into a Client row. Returns (client, outcome).

    `outcome` is 'created', 'updated', or 'skipped'. Database failures are
    raised, not swallowed — the caller decides whether one bad record should
    stop a batch.

    Note what this deliberately does NOT do: rename an existing Client when
    the Clio contact is renamed. The mapping is the identity; the local name
    may have been set by the firm, and clobbering it would silently rewrite
    what every alias and matcher rule was built against. The new name is
    recorded on the mapping instead.
    """
    org = integration.organization
    cache = cache if cache is not None else ContactCache(integration)
    now = now or timezone.now()

    external_id = str(record.get('id') or '')
    if not external_id:
        return None, 'skipped'

    name = _contact_display_name(record)
    if not name:
        return None, 'skipped'

    email = _contact_email(record)

    with transaction.atomic():
        mapping = cache.mappings.get(external_id)
        if mapping:
            client = mapping.client
            outcome = 'updated'
        else:
            client = cache.clients_by_name.get(name.strip().lower())
            if client is None:
                if not integration.auto_create_internal_records:
                    return None, 'skipped'
                client = Client.objects.create(
                    org=org, name=name, is_active=True,
                    imported_from='clio', email=email,
                )
                cache.clients_by_name[name.strip().lower()] = client
                outcome = 'created'
            else:
                outcome = 'updated'

            mapping = ExternalClientMapping.objects.create(
                integration=integration, client=client,
                external_id=external_id,
            )
            cache.mappings[external_id] = mapping

        # Email feeds domain-alias derivation; never clobber a value the firm
        # set by hand.
        if email and not client.email:
            client.email = email
            client.save(update_fields=['email'])

        mapping.external_name = name
        mapping.external_status = str(_pick(record, 'type'))
        mapping.last_synced_at = now
        mapping.last_seen_in_source = now
        mapping.save(update_fields=[
            'external_name', 'external_status',
            'last_synced_at', 'last_seen_in_source', 'updated_at',
        ])

    return client, outcome


def sync_contacts(api: ClioClient, integration: Integration):
    """
    Mirror Clio contacts into Client rows.

    Returns (stats, {clio_contact_id: Client}) — the map is handed to the
    matter pass so it never has to re-query per matter.

    Name-matches against existing Clients before creating, the same way the
    Xero import does, so a firm that already had clients in TimeTracker gets
    them linked rather than duplicated.
    """
    org = integration.organization
    stats = {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0}
    logged = set()

    cache = ContactCache(integration)
    client_by_external_id = {}
    now = timezone.now()

    for record in api.paginated_get('/contacts', fields=CONTACT_FIELDS):
        stats['fetched'] += 1
        _log_first('contacts', record, logged)

        try:
            client, outcome = upsert_contact(
                integration, record, cache=cache, now=now,
            )
        except Exception as e:
            stats['errors'] += 1
            logger.warning('Clio contact %s failed: %s',
                           record.get('id'), e, exc_info=True)
            continue

        if outcome == 'skipped':
            # Unusable record (no id, no name) or auto-create disabled. Not an
            # error — and not silently dropped either: a record with an id but
            # no name means the field list drifted, which is worth a count.
            if not record.get('id') or not _contact_display_name(record):
                stats['errors'] += 1
            continue

        stats[outcome] += 1
        if client is not None:
            client_by_external_id[str(record.get('id'))] = client

    logger.info('Clio contacts synced for org %s: %s', org.id, stats)
    return stats, client_by_external_id


# ============================================================================
# Matters → Project
# ============================================================================

class MatterCache:
    """
    Preloaded matter mappings, plus the contact→Client map from the contact
    pass. Same bargain as ContactCache: one build, no per-record queries.
    """

    def __init__(self, integration: Integration, client_by_external_id=None):
        self.mappings = {
            m.external_id: m
            for m in ExternalMatterMapping.objects.filter(
                integration=integration
            ).select_related('project')
        }
        self.client_by_external_id = dict(client_by_external_id or {})


def resolve_matter_client(integration: Integration, record: dict, cache: 'MatterCache',
                          api: ClioClient = None):
    """
    Find the Client a matter belongs to, fetching the contact if we must.

    In a full sync this is a dict hit: the contact pass already ran, so every
    client is in the cache and this costs nothing.

    In the webhook path it is the whole problem. A firm signing a new client
    creates the contact and the matter seconds apart, and the two callbacks
    can arrive in either order. If the matter lands first and we only looked
    in the cache, we would skip it — and nothing would ever revisit it,
    because the next sweep sees a matter that already has a mapping... except
    it does not, so it would be retried. It would be retried an hour later,
    which is precisely the delay this whole feature exists to remove.

    So when the contact is unknown and we have an API handle, we go get it.
    That is one extra request, on the rare path, to make the common "new
    client, new matter" case land complete and immediately.
    """
    nested = record.get('client') or {}
    clio_client_id = str(nested.get('id') or '')
    if not clio_client_id:
        return None, ''

    client = cache.client_by_external_id.get(clio_client_id)
    if client is not None:
        return client, clio_client_id

    # Not in this pass's map — check for a mapping from an earlier sync.
    mapping = (
        ExternalClientMapping.objects
        .filter(integration=integration, external_id=clio_client_id)
        .select_related('client')
        .first()
    )
    if mapping:
        cache.client_by_external_id[clio_client_id] = mapping.client
        return mapping.client, clio_client_id

    if api is None:
        return None, clio_client_id

    try:
        payload = api.get(f'/contacts/{clio_client_id}', fields=CONTACT_FIELDS)
        contact = payload.get('data') or {}
        if contact:
            client, _ = upsert_contact(integration, contact)
            if client is not None:
                cache.client_by_external_id[clio_client_id] = client
                return client, clio_client_id
    except Exception as e:
        logger.warning('Clio contact %s fetch for matter %s failed: %s',
                       clio_client_id, record.get('id'), e)

    return None, clio_client_id


def upsert_matter(integration: Integration, record: dict, client, *,
                  cache=None, now=None):
    """
    Mirror ONE Clio matter into a Project row + mapping. Returns (project, outcome).

    `billing_method` and `require_utbms_codes` are cached on the mapping here
    precisely so the push path never has to re-fetch a matter to learn its
    preconditions — that would double push's request count against a 50/min
    ceiling.
    """
    org = integration.organization
    cache = cache if cache is not None else MatterCache(integration)
    now = now or timezone.now()

    external_id = str(record.get('id') or '')
    if not external_id or client is None:
        return None, 'skipped'

    project_name = _matter_project_name(record)
    status = str(_pick(record, 'status')).lower()

    with transaction.atomic():
        mapping = cache.mappings.get(external_id)
        if mapping:
            project = mapping.project
            # A matter can be reassigned or renamed in Clio.
            changed = []
            if project.name != project_name:
                project.name = project_name
                changed.append('name')
            if project.client_id != client.id:
                project.client = client
                changed.append('client')
            is_active = status in OPEN_MATTER_STATUSES
            if project.is_active != is_active:
                project.is_active = is_active
                changed.append('is_active')
            if changed:
                project.save(update_fields=changed)
            outcome = 'updated'
        else:
            if not integration.auto_create_internal_records:
                return None, 'skipped'
            project, created = Project.objects.get_or_create(
                org=org, client=client, name=project_name,
                defaults={'is_active': status in OPEN_MATTER_STATUSES},
            )
            mapping = ExternalMatterMapping.objects.create(
                integration=integration, project=project,
                external_id=external_id,
            )
            cache.mappings[external_id] = mapping
            outcome = 'created' if created else 'updated'

        mapping.display_number = str(_pick(record, 'display_number'))[:128]
        mapping.external_name = str(_pick(record, 'description'))[:500]
        mapping.external_status = status[:32]
        mapping.billing_method = str(_pick(record, 'billing_method'))[:32]
        mapping.requires_utbms = bool(record.get('require_utbms_codes'))

        # What lets a person tell two same-named matters apart.
        raw_open = str(_pick(record, 'open_date'))[:10]
        mapping.open_date = None
        if raw_open:
            try:
                mapping.open_date = datetime.strptime(raw_open, '%Y-%m-%d').date()
            except ValueError:
                pass
        attorney = record.get('responsible_attorney') or {}
        mapping.responsible_attorney = str(attorney.get('name') or '')[:255]
        area = record.get('practice_area') or {}
        mapping.practice_area = str(area.get('name') or '')[:128]
        mapping.last_synced_at = now
        mapping.last_seen_in_source = now
        mapping.save(update_fields=[
            'display_number', 'external_name', 'external_status',
            'billing_method', 'requires_utbms',
            'open_date', 'responsible_attorney', 'practice_area',
            'last_synced_at', 'last_seen_in_source', 'updated_at',
        ])

    return project, outcome


def sync_matters(api: ClioClient, integration: Integration, client_by_external_id):
    """Mirror Clio matters into Project rows + ExternalMatterMapping."""
    org = integration.organization
    stats = {'fetched': 0, 'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
    logged = set()

    cache = MatterCache(integration, client_by_external_id)
    now = timezone.now()

    for record in api.paginated_get('/matters', fields=MATTER_FIELDS):
        stats['fetched'] += 1
        _log_first('matters', record, logged)

        external_id = str(record.get('id') or '')
        if not external_id:
            stats['errors'] += 1
            continue

        # No `api` here on purpose. The contact pass has already run, so an
        # unknown client means the contact was filtered, archived, or hidden
        # by permissions — not a race. Fetching it per matter would cost one
        # request each against a 50/min ceiling to re-learn the same answer.
        client, clio_client_id = resolve_matter_client(integration, record, cache)

        if client is None:
            # Skipped rather than guessed at — a matter attached to the wrong
            # client mis-bills.
            stats['skipped'] += 1
            logger.info(
                'Clio matter %s skipped: client %s not in contact sync',
                external_id, clio_client_id or '(none)',
            )
            continue

        try:
            _project, outcome = upsert_matter(
                integration, record, client, cache=cache, now=now,
            )
        except Exception as e:
            stats['errors'] += 1
            logger.warning('Clio matter %s failed: %s', external_id, e, exc_info=True)
            continue

        stats[outcome] += 1

    logger.info('Clio matters synced for org %s: %s', org.id, stats)
    return stats


# ============================================================================
# Users → ExternalStaffMapping
# ============================================================================

def sync_staff(api: ClioClient, integration: Integration):
    """
    Map Clio users to internal Users by email.

    Push needs this: a Clio TimeEntry records who did the work, and that has
    to be the Clio user id, not ours. Matching is by email only — guessing by
    name would attribute one attorney's time to another.

    Unmatched Clio users are counted, not created. A Clio seat is not
    necessarily a TimeTracker seat, and auto-creating users would inflate
    the org's billable seat count.
    """
    org = integration.organization
    stats = {'fetched': 0, 'matched': 0, 'unmatched': 0, 'errors': 0}
    logged = set()

    members = (
        OrganizationMembership.objects
        .filter(organization=org)
        .select_related('user')
    )
    users_by_email = {
        m.user.email.strip().lower(): m.user
        for m in members if m.user.email
    }
    existing_mappings = {
        m.external_id: m
        for m in ExternalStaffMapping.objects.filter(integration=integration)
    }
    now = timezone.now()

    for record in api.paginated_get('/users', fields=USER_FIELDS):
        stats['fetched'] += 1
        _log_first('users', record, logged)

        external_id = str(record.get('id') or '')
        email = str(_pick(record, 'email')).strip().lower()
        if not external_id:
            stats['errors'] += 1
            continue

        user = users_by_email.get(email) if email else None
        if user is None:
            stats['unmatched'] += 1
            logger.info(
                'Clio user %s (%s) has no TimeTracker account in org %s',
                external_id, email or '(no email)', org.id,
            )
            continue

        try:
            mapping = existing_mappings.get(external_id)
            if mapping is None:
                mapping, _ = ExternalStaffMapping.objects.get_or_create(
                    integration=integration, external_id=external_id,
                    defaults={'user': user},
                )
                existing_mappings[external_id] = mapping

            mapping.user = user
            mapping.external_name = _contact_display_name(record)
            mapping.external_email = email[:254]
            mapping.last_synced_at = now
            mapping.last_seen_in_source = now
            mapping.save(update_fields=[
                'user', 'external_name', 'external_email',
                'last_synced_at', 'last_seen_in_source', 'updated_at',
            ])
            stats['matched'] += 1

        except Exception as e:
            stats['errors'] += 1
            logger.warning('Clio user %s failed: %s', external_id, e, exc_info=True)

    logger.info('Clio staff synced for org %s: %s', org.id, stats)
    return stats


# ============================================================================
# Celery entry point
# ============================================================================

@shared_task(name='tracker.sync_clio_full')
def sync_clio_full(integration_id: int) -> dict:
    """
    Background full sync. Runs out-of-band because a large firm's sync can sit
    behind rate-limit pauses for minutes — far too long for a request cycle.
    """
    try:
        integration = Integration.objects.select_related('organization').get(
            id=integration_id, provider='clio',
        )
    except Integration.DoesNotExist:
        logger.error('Clio sync: integration %s not found', integration_id)
        return {'error': 'integration_not_found'}

    return full_sync(integration)


@shared_task(name='tracker.sync_all_clio_orgs')
def sync_all_clio_orgs(min_age_minutes: int = 45) -> dict:
    """
    Hourly sweep: queue a full sync for every connected Clio firm.

    THIS IS THE BACKSTOP, AND IT STAYS EVEN WITH WEBHOOKS LIVE.
    Clio webhook subscriptions expire — 31 days at the very most — and Clio
    neither warns nor retries when one lapses; deliveries just stop. A
    renewal task can itself fail. This sweep is what turns every one of those
    failures into an hour of staleness instead of a client list that quietly
    stopped updating in March.

    Fans out one task per firm rather than looping inline: Clio's rate limit
    is per access token, so firms do not contend with each other, and a
    single firm's rate-limit pause must not eat the 300s task time limit for
    everyone behind it.

    `min_age_minutes` skips firms synced very recently — someone who pressed
    Sync at 10:58 should not have it re-run at 11:00.
    """
    cutoff = timezone.now() - timedelta(minutes=min_age_minutes)

    integrations = Integration.objects.filter(
        provider='clio', is_connected=True,
    ).only('id', 'organization_id', 'last_synced_at')

    queued = skipped = 0
    for integration in integrations:
        if integration.last_synced_at and integration.last_synced_at > cutoff:
            skipped += 1
            continue
        sync_clio_full.delay(integration.id)
        queued += 1

    logger.info('Clio sweep: queued %s, skipped %s (synced within %sm)',
                queued, skipped, min_age_minutes)
    return {'queued': queued, 'skipped': skipped}
