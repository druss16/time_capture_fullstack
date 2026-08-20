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
    'require_utbms_codes,client{id,name}'
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
    api = ClioClient(integration)

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
        stats['contacts'], client_by_external_id = sync_contacts(api, integration)
        stats['matters'] = sync_matters(api, integration, client_by_external_id)
        stats['staff'] = sync_staff(api, integration)

        integration.last_synced_at = timezone.now()
        integration.last_sync_status = 'success' if not stats['errors'] else 'partial'
        integration.last_sync_error = ''
        integration.save(update_fields=[
            'last_synced_at', 'last_sync_status', 'last_sync_error', 'updated_at',
        ])

    except ClioError as e:
        integration.last_sync_status = 'failed'
        integration.last_sync_error = str(e)[:500]
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

    existing_mappings = {
        m.external_id: m
        for m in ExternalClientMapping.objects.filter(
            integration=integration
        ).select_related('client')
    }
    clients_by_name = {
        c.name.strip().lower(): c
        for c in Client.objects.filter(org=org)
    }

    client_by_external_id = {}
    now = timezone.now()

    for record in api.paginated_get('/contacts', fields=CONTACT_FIELDS):
        stats['fetched'] += 1
        _log_first('contacts', record, logged)

        external_id = str(record.get('id') or '')
        if not external_id:
            stats['errors'] += 1
            continue

        name = _contact_display_name(record)
        if not name:
            stats['errors'] += 1
            continue

        email = str(_pick(record, 'primary_email_address'))[:254]
        # Clio's email field is sometimes an object rather than a string.
        if isinstance(_pick(record, 'primary_email_address'), dict):
            email = str(_pick(record['primary_email_address'], 'address'))[:254]

        try:
            with transaction.atomic():
                mapping = existing_mappings.get(external_id)
                if mapping:
                    client = mapping.client
                    stats['updated'] += 1
                else:
                    client = clients_by_name.get(name.strip().lower())
                    if client is None:
                        if not integration.auto_create_internal_records:
                            continue
                        client = Client.objects.create(
                            org=org, name=name, is_active=True,
                            imported_from='clio', email=email,
                        )
                        clients_by_name[name.strip().lower()] = client
                        stats['created'] += 1
                    else:
                        stats['updated'] += 1

                    mapping = ExternalClientMapping.objects.create(
                        integration=integration, client=client,
                        external_id=external_id,
                    )
                    existing_mappings[external_id] = mapping

                # Email feeds domain-alias derivation; never clobber a value
                # the firm set by hand.
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

                client_by_external_id[external_id] = client

        except Exception as e:
            stats['errors'] += 1
            logger.warning('Clio contact %s failed: %s', external_id, e, exc_info=True)

    logger.info('Clio contacts synced for org %s: %s', org.id, stats)
    return stats, client_by_external_id


# ============================================================================
# Matters → Project
# ============================================================================

def sync_matters(api: ClioClient, integration: Integration, client_by_external_id):
    """
    Mirror Clio matters into Project rows + ExternalMatterMapping.

    `billing_method` and `require_utbms_codes` are cached on the mapping here
    precisely so the push path never has to re-fetch a matter to learn its
    preconditions — that would double push's request count against a 50/min
    ceiling.
    """
    org = integration.organization
    stats = {'fetched': 0, 'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
    logged = set()

    existing_mappings = {
        m.external_id: m
        for m in ExternalMatterMapping.objects.filter(
            integration=integration
        ).select_related('project')
    }
    now = timezone.now()

    for record in api.paginated_get('/matters', fields=MATTER_FIELDS):
        stats['fetched'] += 1
        _log_first('matters', record, logged)

        external_id = str(record.get('id') or '')
        if not external_id:
            stats['errors'] += 1
            continue

        nested_client = record.get('client') or {}
        clio_client_id = str(nested_client.get('id') or '')
        client = client_by_external_id.get(clio_client_id)

        if client is None:
            # A matter whose contact was not returned by the contacts pass
            # (filtered, archived, or a permissions gap). Skipped rather than
            # guessed at — a matter attached to the wrong client mis-bills.
            stats['skipped'] += 1
            logger.info(
                'Clio matter %s skipped: client %s not in contact sync',
                external_id, clio_client_id or '(none)',
            )
            continue

        project_name = _matter_project_name(record)
        status = str(_pick(record, 'status')).lower()

        try:
            with transaction.atomic():
                mapping = existing_mappings.get(external_id)
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
                    stats['updated'] += 1
                else:
                    if not integration.auto_create_internal_records:
                        stats['skipped'] += 1
                        continue
                    project, created = Project.objects.get_or_create(
                        org=org, client=client, name=project_name,
                        defaults={'is_active': status in OPEN_MATTER_STATUSES},
                    )
                    mapping = ExternalMatterMapping.objects.create(
                        integration=integration, project=project,
                        external_id=external_id,
                    )
                    existing_mappings[external_id] = mapping
                    stats['created' if created else 'updated'] += 1

                mapping.display_number = str(_pick(record, 'display_number'))[:128]
                mapping.external_name = str(_pick(record, 'description'))[:500]
                mapping.external_status = status[:32]
                mapping.billing_method = str(_pick(record, 'billing_method'))[:32]
                mapping.requires_utbms = bool(record.get('require_utbms_codes'))
                mapping.last_synced_at = now
                mapping.last_seen_in_source = now
                mapping.save(update_fields=[
                    'display_number', 'external_name', 'external_status',
                    'billing_method', 'requires_utbms',
                    'last_synced_at', 'last_seen_in_source', 'updated_at',
                ])

        except Exception as e:
            stats['errors'] += 1
            logger.warning('Clio matter %s failed: %s', external_id, e, exc_info=True)

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
